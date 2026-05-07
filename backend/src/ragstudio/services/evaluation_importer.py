import csv
import json
from collections.abc import Iterable
from io import StringIO
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import EvaluationSet
from ragstudio.schemas.evaluation import EvaluationCaseIn, EvaluationSetOut, EvaluationSetPage

LIST_FIELDS = {"documents", "expected_sources", "must_include", "must_avoid"}
DICT_FIELDS = {"expected_structure", "rubric", "objective"}
LIST_OF_DICT_FIELDS = {"expected_media"}
DICT_OF_LIST_FIELDS = {"variant_hints"}


class EvaluationImportError(ValueError):
    pass


class EvaluationImporter:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def import_file(self, name: str, filename: str, content: bytes) -> EvaluationSetOut:
        cases = parse_evaluation_cases(filename, content)
        evaluation_set = EvaluationSet(name=name, cases=[case.model_dump() for case in cases])
        self.session.add(evaluation_set)
        await self.session.commit()
        await self.session.refresh(evaluation_set)
        return EvaluationSetOut.model_validate(evaluation_set)

    async def list(self) -> EvaluationSetPage:
        result = await self.session.execute(
            select(EvaluationSet).order_by(EvaluationSet.created_at.desc())
        )
        items = [EvaluationSetOut.model_validate(item) for item in result.scalars().all()]
        return EvaluationSetPage(items=items, total=len(items))


def parse_evaluation_cases(filename: str, content: bytes) -> list[EvaluationCaseIn]:
    suffix = Path(filename).suffix.lower()
    text = content.decode("utf-8-sig")

    if suffix == ".csv":
        rows = list(csv.DictReader(StringIO(text)))
    elif suffix == ".json":
        rows = _extract_cases(json.loads(text))
    elif suffix in {".jsonl", ".ndjson"}:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    elif suffix in {".yaml", ".yml"}:
        rows = _extract_cases(_parse_simple_yaml(text))
    else:
        raise EvaluationImportError(f"Unsupported evaluation set file type: {suffix or 'unknown'}")

    cases = [_normalize_case(row, index) for index, row in enumerate(rows, start=1)]
    if not cases:
        raise EvaluationImportError("Evaluation import requires at least one case")
    return cases


def _extract_cases(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        rows = payload["cases"]
    elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
        rows = payload["items"]
    elif isinstance(payload, dict):
        rows = [payload]
    else:
        raise EvaluationImportError("Evaluation import must contain a list of cases")

    if not all(isinstance(row, dict) for row in rows):
        raise EvaluationImportError("Evaluation import cases must be objects")
    return rows


def _normalize_case(raw: dict[str, Any], index: int) -> EvaluationCaseIn:
    data = {str(key).strip(): value for key, value in raw.items() if key is not None}
    _apply_aliases(data)
    data.setdefault("id", f"case-{index}")

    for field in LIST_FIELDS:
        data[field] = _normalize_list(data.get(field))
    for field in DICT_FIELDS:
        data[field] = _normalize_dict(data.get(field))
    for field in LIST_OF_DICT_FIELDS:
        data[field] = _normalize_list_of_dicts(data.get(field))
    for field in DICT_OF_LIST_FIELDS:
        data[field] = _normalize_dict_of_lists(data.get(field))

    expected_answer = data.get("expected_answer")
    if expected_answer is not None:
        expected_answer = str(expected_answer).strip()
        data["expected_answer"] = expected_answer or None

    if not _has_expected_output_signal(data):
        raise EvaluationImportError(f"Case {data['id']} has no expected-output signal")

    try:
        return EvaluationCaseIn.model_validate(data)
    except ValidationError as exc:
        raise EvaluationImportError(f"Case {data['id']} is invalid: {exc.errors()[0]['msg']}") from exc


def _apply_aliases(data: dict[str, Any]) -> None:
    aliases = {
        "question": "query",
        "prompt": "query",
        "expected_output": "expected_answer",
        "expected": "expected_answer",
        "answer": "expected_answer",
        "sources": "expected_sources",
    }
    for alias, field in aliases.items():
        if field not in data and alias in data:
            data[field] = data.pop(alias)


def _has_expected_output_signal(data: dict[str, Any]) -> bool:
    expected_answer = data.get("expected_answer")
    return bool(
        expected_answer
        or data["expected_sources"]
        or data["must_include"]
        or data["must_avoid"]
        or data["expected_media"]
        or data["expected_structure"]
        or data["rubric"]
        or data["objective"]
    )


def _normalize_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split("|") if item.strip()]
    if isinstance(value, Iterable) and not isinstance(value, (bytes, dict)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _normalize_dict(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = _parse_json_cell(value)
        if isinstance(parsed, dict):
            return parsed
    raise EvaluationImportError("Dictionary fields must be objects")


def _normalize_list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        parsed = _parse_json_cell(value)
        value = parsed
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value
    raise EvaluationImportError("List-of-object fields must be arrays of objects")


def _normalize_dict_of_lists(value: Any) -> dict[str, list[str]]:
    if value is None or value == "":
        return {}
    if isinstance(value, str):
        parsed = _parse_json_cell(value)
        value = parsed
    if not isinstance(value, dict):
        raise EvaluationImportError("Dictionary-of-list fields must be objects")
    return {str(key): _normalize_list(item) for key, item in value.items()}


def _parse_json_cell(value: str) -> Any:
    value = value.strip()
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise EvaluationImportError("Structured fields must contain valid JSON") from exc


def _parse_simple_yaml(text: str) -> Any:
    lines = [
        line.rstrip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if lines and lines[0].strip() == "cases:":
        lines = lines[1:]
    if not lines:
        return []
    if lines[0].lstrip().startswith("- "):
        return _parse_yaml_list(lines)
    return _parse_yaml_mapping(lines)


def _parse_yaml_list(lines: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            current = {}
            rows.append(current)
            rest = stripped[2:].strip()
            if rest:
                key, value = _split_yaml_pair(rest)
                current[key] = _parse_yaml_scalar(value)
        elif current is not None:
            key, value = _split_yaml_pair(stripped)
            current[key] = _parse_yaml_scalar(value)
        else:
            raise EvaluationImportError("YAML import must contain a list of cases")
    return rows


def _parse_yaml_mapping(lines: list[str]) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for line in lines:
        key, value = _split_yaml_pair(line.strip())
        mapping[key] = _parse_yaml_scalar(value)
    return mapping


def _split_yaml_pair(line: str) -> tuple[str, str]:
    if ":" not in line:
        raise EvaluationImportError("YAML import supports key: value pairs")
    key, value = line.split(":", 1)
    return key.strip(), value.strip()


def _parse_yaml_scalar(value: str) -> Any:
    if value in {"", "null", "Null", "NULL", "~"}:
        return None
    if value in {"[]", "{}"}:
        return json.loads(value)
    if value.startswith(("[", "{")):
        return json.loads(value)
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value
