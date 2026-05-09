from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExcelCase:
    case_id: str
    query: str
    expected_text: str
    required_rank: int


def summarize_excel_results(
    cases: list[ExcelCase],
    results_by_case: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []

    for case in cases:
        results = results_by_case.get(case.case_id, [])
        matched_rank = _matched_rank(case.expected_text, results)
        verdict = (
            "PASS"
            if matched_rank is not None and matched_rank <= case.required_rank
            else "FAIL"
        )

        summaries.append(
            {
                "case_id": case.case_id,
                "query": case.query,
                "expected_text": case.expected_text,
                "required_rank": case.required_rank,
                "matched_rank": matched_rank,
                "verdict": verdict,
                "top_debug": _top_debug(results),
            }
        )

    return summaries


def _matched_rank(expected_text: str, results: list[Any]) -> int | None:
    for index, result in enumerate(results, start=1):
        text = _get_field(result, "text")
        if isinstance(text, str) and expected_text in text:
            return index
    return None


def _top_debug(results: list[Any]) -> list[Any]:
    debug: list[Any] = []
    for result in results[:5]:
        metadata = _get_field(result, "metadata")
        if isinstance(metadata, dict):
            debug.append(metadata.get("retrieval_explain"))
        else:
            debug.append(None)
    return debug


def _get_field(item: Any, field: str) -> Any:
    if isinstance(item, dict):
        return item.get(field)
    return getattr(item, field, None)
