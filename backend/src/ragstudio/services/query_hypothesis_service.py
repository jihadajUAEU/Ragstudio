from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from string import Formatter
from typing import Any

import httpx
from ragstudio.services.http_client_provider import HttpClientProviderProtocol
from ragstudio.services.http_retry import raise_for_transient_status, retry_async_http
from ragstudio.services.reference_contracts import (
    build_executable_reference_contract,
    canonical_reference_from_groups,
    metadata_list_declared_scripts,
)
from ragstudio.services.reference_query_parser import (
    parse_legacy_reference_query,
    parse_query_references,
)

QUERY_HYPOTHESIS_PROTOCOL_VERSION = "2026-05-24"

_ALLOWED_INTENTS = {
    "find_word_occurrence",
    "reference_lookup",
    "explain_reference",
    "semantic_question",
    "unknown",
}
_ALLOWED_SCRIPTS = {"arabic", "latin", "mixed", "unknown"}
_ALLOWED_TERM_TYPES = {"exact_text", "transliteration", "reference", "unknown"}
_ALLOWED_ANSWER_SHAPES = {
    "reference",
    "short_answer",
    "explanation",
    "unknown",
}
_INTENT_ALIASES = {
    "retrieval": "semantic_question",
    "search": "semantic_question",
    "citation_lookup": "reference_lookup",
}
_ANSWER_SHAPE_ALIASES = {
    "citation": "reference",
    "citation_reference": "reference",
    "source_citation": "reference",
}
_CONFIDENCE_LABELS = {
    "low": 0.33,
    "medium": 0.66,
    "high": 0.9,
}
_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+")
_WORD_TARGET_RE = re.compile(
    r"\b(?:word|term|arabic word|arabic term)\s+['\"]?(?P<term>[A-Za-z][A-Za-z'-]{1,79})['\"]?",
    re.IGNORECASE,
)
_ARABIC_TARGET_RE = re.compile(
    r"(?:كلمة|لفظ)\s+(?P<term>[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+)"
)
_PATH_LIKE_RE = re.compile(r"(?:^|/)(?:Users|home|var|tmp|etc|private)(?:/|$)", re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_DOMAIN_HINT_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")


@dataclass(frozen=True)
class QueryTargetTerm:
    surface: str
    script: str = "unknown"
    language_hint: str | None = None
    term_type: str = "unknown"

    def to_trace(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProbableAnswer:
    matched_term: str | None = None
    reference: str | None = None
    reference_groups: dict[str, str] | None = None
    display_label: str | None = None

    def to_trace(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if value is not None
        }


@dataclass(frozen=True)
class QueryHypothesis:
    original_query: str
    intent: str = "unknown"
    target_terms: list[QueryTargetTerm] = field(default_factory=list)
    possible_references: list[str] = field(default_factory=list)
    domain_hint: str = "unknown"
    answer_shape: str = "unknown"
    probable_answer: ProbableAnswer | None = None
    confidence: float = 0.0
    needs_clarification: bool = False
    valid: bool = False
    source: str = "none"
    reason: str | None = None

    @classmethod
    def empty(cls, original_query: str, *, reason: str) -> QueryHypothesis:
        return cls(original_query=original_query, reason=reason)

    def to_trace(self) -> dict[str, Any]:
        return {
            "stage": "query_hypothesis",
            "status": "valid" if self.valid else "skipped",
            "source": self.source,
            "reason": self.reason,
            "intent": self.intent,
            "domain_hint": self.domain_hint,
            "answer_shape": self.answer_shape,
            "confidence": self.confidence,
            "needs_clarification": self.needs_clarification,
            "target_terms": [term.to_trace() for term in self.target_terms],
            "possible_references": list(self.possible_references),
            "probable_answer": (
                self.probable_answer.to_trace() if self.probable_answer is not None else None
            ),
        }


@dataclass(frozen=True)
class _ReferenceGroupMatch:
    groups: dict[str, str]
    template: str | None


class QueryHypothesisService:
    def __init__(self, http_client_provider: HttpClientProviderProtocol | None = None) -> None:
        self.http_client_provider = http_client_provider

    async def hypothesize(
        self,
        query: str,
        *,
        profile: Any,
        domain_metadata: list[dict[str, Any]],
        timeout_ms: int = 650,
    ) -> QueryHypothesis:
        deterministic = self.deterministic_hypothesis(query, domain_metadata=domain_metadata)
        if deterministic.valid:
            return deterministic

        if not getattr(profile, "llm_base_url", None):
            return deterministic

        payload = self._payload(query, domain_metadata=domain_metadata, profile=profile)
        headers = {"content-type": "application/json"}
        api_key = getattr(profile, "llm_api_key", None)
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"

        try:
            timeout = max(timeout_ms, 1) / 1000
            if self.http_client_provider is not None:
                client = self.http_client_provider.client("query-hypothesis", timeout=timeout)
                response = await retry_async_http(
                    lambda: self._post_for_retry(
                        client,
                        _chat_url(str(profile.llm_base_url)),
                        headers=headers,
                        json=payload,
                    ),
                    attempts=2,
                )
            else:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await retry_async_http(
                        lambda: self._post_for_retry(
                            client,
                            _chat_url(str(profile.llm_base_url)),
                            headers=headers,
                            json=payload,
                        ),
                        attempts=2,
                    )
            response.raise_for_status()
            raw = _json_content(response.json())
        except Exception as exc:
            return QueryHypothesis.empty(
                query,
                reason=f"llm_{exc.__class__.__name__}",
            )

        hypothesis = self.parse_hypothesis(
            raw,
            original_query=query,
            reference_contracts=_reference_contracts_from_metadata(domain_metadata),
        )
        if hypothesis.valid:
            return replace(hypothesis, source="llm", reason=None)
        return hypothesis

    async def _post_for_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> httpx.Response:
        response = await client.post(url, headers=headers, json=json)
        raise_for_transient_status(response)
        return response

    def deterministic_hypothesis(
        self,
        query: str,
        *,
        domain_metadata: list[dict[str, Any]],
    ) -> QueryHypothesis:
        if not _domain_supports_arabic_terms(domain_metadata):
            return QueryHypothesis.empty(query, reason="domain_not_supported")

        terms: list[QueryTargetTerm] = []
        for token in _arabic_target_terms(query):
            terms.append(
                QueryTargetTerm(
                    surface=token,
                    script="arabic",
                    language_hint="arabic",
                    term_type="exact_text",
                )
            )
        for token in _latin_word_targets(query):
            terms.append(
                QueryTargetTerm(
                    surface=token,
                    script="latin",
                    language_hint="arabic",
                    term_type="transliteration",
                )
            )

        terms = _dedupe_terms([term for term in terms if _safe_term(term.surface)])
        if not terms:
            return QueryHypothesis.empty(query, reason="no_target_terms")

        return QueryHypothesis(
            original_query=query,
            intent="find_word_occurrence",
            target_terms=terms[:5],
            domain_hint="reference",
            answer_shape="reference",
            confidence=0.74,
            valid=True,
            source="deterministic",
        )

    @staticmethod
    def parse_hypothesis(
        raw: Any,
        *,
        original_query: str,
        reference_contracts: list[dict[str, Any]] | None = None,
    ) -> QueryHypothesis:
        if not isinstance(raw, dict):
            return QueryHypothesis.empty(original_query, reason="invalid_hypothesis_shape")

        active_contracts = reference_contracts or []
        target_terms = _target_terms(raw.get("target_terms"))
        possible_references = _possible_references(
            raw.get("possible_references"),
            reference_contracts=active_contracts,
        )
        probable_answer = _probable_answer(
            raw.get("probable_answer"),
            reference_contracts=active_contracts,
        )
        intent = _allowed_alias(
            raw.get("intent"),
            _ALLOWED_INTENTS,
            default="unknown",
            aliases=_INTENT_ALIASES,
        )
        domain_hint = _domain_hint(raw.get("domain_hint"))
        answer_shape = _allowed_alias(
            raw.get("answer_shape"),
            _ALLOWED_ANSWER_SHAPES,
            default="unknown",
            aliases=_ANSWER_SHAPE_ALIASES,
        )
        confidence = _confidence(raw.get("confidence"))
        has_search_plan = bool(target_terms or possible_references)
        needs_clarification = bool(raw.get("needs_clarification", False)) and not has_search_plan

        valid = has_search_plan and not needs_clarification
        return QueryHypothesis(
            original_query=original_query,
            intent=intent,
            target_terms=target_terms,
            possible_references=possible_references,
            domain_hint=domain_hint,
            answer_shape=answer_shape,
            probable_answer=probable_answer,
            confidence=confidence,
            needs_clarification=needs_clarification,
            valid=valid,
            source="parsed",
            reason=None if valid else "no_valid_search_plan",
        )

    def _payload(
        self,
        query: str,
        *,
        domain_metadata: list[dict[str, Any]],
        profile: Any,
    ) -> dict[str, Any]:
        reference_contracts = _reference_contracts_from_metadata(domain_metadata)
        domain_tokens = sorted(
            {
                str(value).strip().casefold()
                for metadata in domain_metadata[:5]
                for value in _metadata_values(metadata)
                if str(value).strip()
            }
        )[:20]
        return {
            "model": getattr(profile, "llm_model", None),
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only JSON. Extract a mandatory search plan for a RAG "
                        "retrieval system. Do not answer authoritatively. For semantic "
                        "or content lookup questions, target_terms must contain 2-5 "
                        "answer-bearing terms from the query after removing wrapper words "
                        "and source names. You may also include up to 3 possible_references "
                        "when the query suggests a concrete citation, but those references "
                        "are untrusted hypotheses that retrieval must verify. Set "
                        "needs_clarification true only when no usable retrieval terms or "
                        "reference hypotheses can be extracted. Probable answers are "
                        "hypotheses and must include only compact references."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Schema keys: intent, target_terms, possible_references, "
                        "domain_hint, answer_shape, "
                        "probable_answer, confidence, needs_clarification.\n"
                        "Use canonical values when possible: intent semantic_question, "
                        "reference_lookup, find_word_occurrence, or explain_reference; "
                        "answer_shape reference, short_answer, explanation, or unknown.\n"
                        "Use supplied reference contracts as the only source for structured "
                        "possible_references. For example, if the contract says Article "
                        "and Clause identify units, a query about Article 12.7 may include "
                        "those fields or the matching canonical reference only when the "
                        "contract supports it.\n"
                        f"Domain tokens: {domain_tokens}\n"
                        "Reference contracts: "
                        f"{_reference_contract_summaries(reference_contracts)}\n"
                        f"Query: {query.strip()}"
                    ),
                },
            ],
        }


def parse_query_hypothesis_payload(
    payload: Any,
    *,
    reference_contracts: list[dict[str, Any]] | None = None,
    original_query: str = "",
) -> QueryHypothesis:
    return QueryHypothesisService.parse_hypothesis(
        payload,
        original_query=original_query,
        reference_contracts=reference_contracts,
    )


def _target_terms(raw: Any) -> list[QueryTargetTerm]:
    if not isinstance(raw, list):
        return []
    terms: list[QueryTargetTerm] = []
    for item in raw:
        if isinstance(item, str):
            surface = item.strip()
            if not _safe_term(surface):
                continue
            terms.append(
                QueryTargetTerm(
                    surface=surface,
                    script=_script_for_term(surface),
                )
            )
            continue
        if not isinstance(item, dict):
            continue
        surface = str(item.get("surface") or "").strip()
        if not _safe_term(surface):
            continue
        terms.append(
            QueryTargetTerm(
                surface=surface,
                script=_allowed(item.get("script"), _ALLOWED_SCRIPTS, default="unknown"),
                language_hint=_str_or_none(item.get("language_hint")),
                term_type=_allowed(
                    item.get("term_type"),
                    _ALLOWED_TERM_TYPES,
                    default="unknown",
                ),
            )
        )
    return _dedupe_terms(terms)[:5]


def _possible_references(
    raw: Any,
    *,
    reference_contracts: list[dict[str, Any]],
) -> list[str]:
    if isinstance(raw, str | dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    references: list[str] = []
    for item in raw:
        reference = _reference_from_item(item, reference_contracts=reference_contracts)
        if reference is not None:
            references.append(reference)
    return list(dict.fromkeys(references))[:3]


def _reference_from_item(
    item: Any,
    *,
    reference_contracts: list[dict[str, Any]],
) -> str | None:
    if isinstance(item, str):
        return normalize_reference_hypothesis(item, reference_contracts=reference_contracts)
    if not isinstance(item, dict):
        return None
    for key in ("reference", "ref", "citation"):
        reference = normalize_reference_hypothesis(
            item.get(key),
            reference_contracts=reference_contracts,
        )
        if reference is not None:
            return reference
    contract_reference = _reference_from_contract_groups(
        item,
        reference_contracts=reference_contracts,
    )
    if contract_reference is not None:
        return contract_reference
    return None


def _probable_answer(
    raw: Any,
    *,
    reference_contracts: list[dict[str, Any]],
) -> ProbableAnswer | None:
    if not isinstance(raw, dict):
        return None
    reference_group_match = _reference_groups_from_contracts(raw, reference_contracts)
    reference_groups = reference_group_match.groups if reference_group_match else None
    contract_reference = (
        canonical_reference_from_groups(
            reference_groups,
            reference_group_match.template,
        )
        if reference_group_match is not None
        else None
    )
    reference = contract_reference or _safe_reference(
        raw.get("reference"),
        reference_contracts=reference_contracts,
    )
    return ProbableAnswer(
        matched_term=_safe_short_text(raw.get("matched_term"), max_length=80),
        reference=reference,
        reference_groups=reference_groups,
        display_label=_safe_short_text(
            raw.get("display_label", raw.get("reference_label")),
            max_length=120,
        ),
    )


def _json_content(body: Any) -> Any:
    content = _content(body)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {}


def _content(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    text = first.get("text")
    return text if isinstance(text, str) else ""


def _chat_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _safe_term(value: str) -> bool:
    stripped = value.strip()
    if not stripped or len(stripped) > 80:
        return False
    if "://" in stripped or _PATH_LIKE_RE.search(stripped):
        return False
    return True


def _safe_short_text(value: Any, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = _CONTROL_RE.sub(" ", value)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized or len(normalized) > max_length:
        return None
    if not _safe_term(normalized):
        return None
    return normalized


def _safe_reference(
    value: Any,
    *,
    reference_contracts: list[dict[str, Any]],
) -> str | None:
    return normalize_reference_hypothesis(value, reference_contracts=reference_contracts)


def normalize_reference_hypothesis(
    value: Any,
    *,
    reference_contracts: list[dict[str, Any]] | None = None,
) -> str | None:
    reference = _safe_short_text(value, max_length=80)
    if reference is None:
        return None
    active_contracts = reference_contracts or []
    if active_contracts:
        references = parse_query_references(reference, active_contracts)
        if references:
            return references[0]
        canonical_reference = _canonical_reference_from_string(reference, active_contracts)
        if canonical_reference is not None:
            return canonical_reference
    references = parse_legacy_reference_query(
        reference,
        enabled_profiles=_legacy_reference_profiles(active_contracts),
    )
    return references[0] if references else None


def _reference_contracts_from_metadata(
    domain_metadata: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for metadata in domain_metadata:
        if not isinstance(metadata, dict):
            continue
        for contract in _metadata_reference_contracts(metadata):
            key = json.dumps(contract, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            contracts.append(contract)
    return contracts


def _metadata_reference_contracts(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    index_contract = _dict_value(metadata.get("index_contract"))
    index_reference_contract = _dict_value(index_contract.get("reference_contract"))
    if index_reference_contract:
        contracts.append({"reference_contract": index_reference_contract})

    reference_contract = _dict_value(metadata.get("reference_contract"))
    if reference_contract:
        contracts.append({"reference_contract": reference_contract})

    custom_json = _dict_value(metadata.get("custom_json"))
    if isinstance(custom_json.get("reference_schema"), dict):
        executable = build_executable_reference_contract(custom_json)
        contracts.append(
            {
                "reference_contract": {
                    "schema_type": executable.schema_type,
                    "canonical_ref_template": executable.canonical_ref_template,
                    "required_groups": sorted(executable.required_groups),
                    "verified": executable.verified,
                    "anchors": [
                        {
                            "kind": anchor.kind,
                            "regex": anchor.regex,
                            "verified": anchor.verified,
                        }
                        for anchor in executable.anchors
                    ],
                }
            }
        )
    return contracts


def _reference_contract_summaries(contracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for contract in contracts[:5]:
        reference_contract = _reference_contract_payload(contract)
        if not reference_contract:
            continue
        summaries.append(
            {
                "schema_type": reference_contract.get("schema_type"),
                "canonical_ref_template": reference_contract.get("canonical_ref_template"),
                "required_groups": _string_list(reference_contract.get("required_groups")),
                "anchor_kinds": [
                    anchor.get("kind")
                    for anchor in _anchor_list(reference_contract)
                    if isinstance(anchor.get("kind"), str)
                ],
            }
        )
    return summaries


def _reference_from_contract_groups(
    item: dict[str, Any],
    *,
    reference_contracts: list[dict[str, Any]],
) -> str | None:
    for contract in reference_contracts:
        reference_contract = _reference_contract_payload(contract)
        if reference_contract.get("verified") is not True:
            continue
        template = _string_value(reference_contract.get("canonical_ref_template"))
        if not template:
            continue
        fields = _template_fields(template) or set(
            _string_list(reference_contract.get("required_groups"))
        )
        if not fields:
            continue
        groups: dict[str, str] = {}
        for group_name in fields:
            group_value = _safe_reference_group(item.get(group_name))
            if group_value is None:
                break
            groups[group_name] = group_value
        if len(groups) != len(fields):
            continue
        reference = canonical_reference_from_groups(groups, template)
        if reference is not None:
            return reference
    return None


def _reference_groups_from_contracts(
    raw: dict[str, Any],
    reference_contracts: list[dict[str, Any]],
) -> _ReferenceGroupMatch | None:
    raw_groups = raw.get("reference_groups")
    group_sources = [raw_groups, raw] if isinstance(raw_groups, dict) else [raw]
    for contract in reference_contracts:
        reference_contract = _reference_contract_payload(contract)
        if reference_contract.get("verified") is not True:
            continue
        template = _string_value(reference_contract.get("canonical_ref_template"))
        fields = _string_list(reference_contract.get("required_groups"))
        if not fields:
            fields = sorted(_template_fields(template) or set()) if template else []
        for source in group_sources:
            groups: dict[str, str] = {}
            for field_name in fields:
                value = _safe_reference_group(source.get(field_name))
                if value is None:
                    break
                groups[field_name] = value
            if len(groups) == len(fields) and groups:
                return _ReferenceGroupMatch(groups=groups, template=template)
    return None


def _canonical_reference_from_string(
    reference: str,
    reference_contracts: list[dict[str, Any]],
) -> str | None:
    for contract in reference_contracts:
        reference_contract = _reference_contract_payload(contract)
        if reference_contract.get("verified") is not True:
            continue
        template = _string_value(reference_contract.get("canonical_ref_template"))
        if not template:
            continue
        pattern = _canonical_template_pattern(template)
        if pattern is None:
            continue
        match = pattern.fullmatch(reference)
        if not match:
            continue
        canonical = canonical_reference_from_groups(
            {key: value for key, value in match.groupdict().items() if value},
            template,
        )
        if canonical is not None:
            return canonical
    return None


def _canonical_template_pattern(template: str) -> re.Pattern[str] | None:
    parts: list[str] = [r"\s*"]
    try:
        parsed = list(Formatter().parse(template))
    except ValueError:
        return None
    for literal, field_name, _format_spec, _conversion in parsed:
        parts.append(re.escape(literal))
        if not field_name:
            continue
        group_name = field_name.split(".", 1)[0].split("[", 1)[0]
        if not re.fullmatch(r"[A-Za-z]\w*", group_name):
            return None
        parts.append(rf"(?P<{group_name}>[\w.-]+)")
    parts.append(r"\s*")
    try:
        return re.compile("".join(parts), flags=re.IGNORECASE)
    except re.error:
        return None


def _reference_contract_payload(contract: dict[str, Any]) -> dict[str, Any]:
    reference_contract = _dict_value(contract.get("reference_contract"))
    return reference_contract or contract


def _legacy_reference_profiles(reference_contracts: list[dict[str, Any]]) -> set[str]:
    profiles: set[str] = set()
    for contract in reference_contracts:
        reference_contract = _reference_contract_payload(contract)
        if reference_contract.get("verified") is not True:
            continue
        schema_type = _string_value(reference_contract.get("schema_type"))
        if schema_type:
            profiles.add(schema_type)
    return profiles


def _anchor_list(reference_contract: dict[str, Any]) -> list[dict[str, Any]]:
    anchors = reference_contract.get("anchors")
    if isinstance(anchors, list):
        return [anchor for anchor in anchors if isinstance(anchor, dict)]
    return []


def _safe_reference_group(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str):
        return None
    normalized = _CONTROL_RE.sub(" ", value)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized or len(normalized) > 40:
        return None
    if "://" in normalized or _PATH_LIKE_RE.search(normalized):
        return None
    return normalized


def _domain_hint(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in {"", "unknown"}:
        return "unknown"
    return normalized if _DOMAIN_HINT_RE.fullmatch(normalized) else "unknown"


def _allowed(value: Any, allowed: set[str], *, default: str) -> str:
    normalized = str(value or "").strip().casefold()
    return normalized if normalized in allowed else default


def _allowed_alias(
    value: Any,
    allowed: set[str],
    *,
    default: str,
    aliases: dict[str, str],
) -> str:
    normalized = str(value or "").strip().casefold()
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in allowed else default


def _confidence(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, str):
        label = value.strip().casefold()
        if label in _CONFIDENCE_LABELS:
            return _CONFIDENCE_LABELS[label]
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(parsed, 0.0), 1.0)


def _positive_int(value: Any, *, max_value: int | None = None) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        return None
    if parsed > 0 and (max_value is None or parsed <= max_value):
        return parsed
    return None


def _str_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _string_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _template_fields(template: str) -> set[str]:
    try:
        return {
            field_name.split(".", 1)[0].split("[", 1)[0]
            for _, field_name, _, _ in Formatter().parse(template)
            if field_name
        }
    except ValueError:
        return set()


def _script_for_term(value: str) -> str:
    if _ARABIC_RE.search(value):
        return "arabic"
    if re.search(r"[A-Za-z]", value):
        return "latin"
    return "unknown"


def _arabic_target_terms(query: str) -> list[str]:
    pattern_terms = [
        match.group("term")
        for match in _ARABIC_TARGET_RE.finditer(query)
        if match.group("term")
    ]
    if pattern_terms:
        return list(dict.fromkeys(pattern_terms))
    tokens = list(dict.fromkeys(match.group(0) for match in _ARABIC_RE.finditer(query)))
    return tokens if len(tokens) == 1 else []


def _latin_word_targets(query: str) -> list[str]:
    terms = [match.group("term").strip("'\"") for match in _WORD_TARGET_RE.finditer(query)]
    if terms:
        return terms
    stripped = query.strip()
    if re.fullmatch(r"[A-Za-z][A-Za-z'-]{1,79}", stripped):
        return [stripped]
    return []


def _dedupe_terms(terms: list[QueryTargetTerm]) -> list[QueryTargetTerm]:
    deduped: list[QueryTargetTerm] = []
    seen: set[tuple[str, str, str]] = set()
    for term in terms:
        key = (term.surface.casefold(), term.script, term.term_type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(term)
    return deduped


def _domain_supports_arabic_terms(domain_metadata: list[dict[str, Any]]) -> bool:
    scripts = metadata_list_declared_scripts(domain_metadata)
    return bool({"arabic", "ar", "arab"} & scripts)


def _metadata_values(metadata: dict[str, Any]) -> list[Any]:
    values: list[Any] = [
        metadata.get("domain"),
        metadata.get("document_type"),
        metadata.get("content_role"),
        metadata.get("language"),
        metadata.get("script"),
    ]
    tags = metadata.get("tags")
    if isinstance(tags, list | tuple | set):
        values.extend(tags)
    return values
