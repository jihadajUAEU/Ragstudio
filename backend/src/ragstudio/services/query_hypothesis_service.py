from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from typing import Any

import httpx
from ragstudio.services.http_client_provider import HttpClientProviderProtocol
from ragstudio.services.http_retry import raise_for_transient_status, retry_async_http
from ragstudio.services.reference_contracts import metadata_list_declared_scripts
from ragstudio.services.reference_query_parser import parse_legacy_reference_query

_ALLOWED_INTENTS = {
    "find_word_occurrence",
    "reference_lookup",
    "explain_reference",
    "semantic_question",
    "unknown",
}
_ALLOWED_SCRIPTS = {"arabic", "latin", "mixed", "unknown"}
_ALLOWED_TERM_TYPES = {"exact_text", "transliteration", "reference", "unknown"}
_ALLOWED_DOMAIN_HINTS = {
    "quran",
    "tafseer",
    "hadith",
    "research",
    "legal",
    "generic",
    "unknown",
}
_ALLOWED_ANSWER_SHAPES = {
    "surah_and_verse",
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
    surah: str | None = None
    surah_number: int | None = None
    ayah: int | None = None
    matched_term: str | None = None
    reference: str | None = None

    def to_trace(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if value is not None and value != ""
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

        hypothesis = self.parse_hypothesis(raw, original_query=query)
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
            domain_hint="quran",
            answer_shape="surah_and_verse",
            confidence=0.74,
            valid=True,
            source="deterministic",
        )

    @staticmethod
    def parse_hypothesis(raw: Any, *, original_query: str) -> QueryHypothesis:
        if not isinstance(raw, dict):
            return QueryHypothesis.empty(original_query, reason="invalid_hypothesis_shape")

        target_terms = _target_terms(raw.get("target_terms"))
        possible_references = _possible_references(raw.get("possible_references"))
        probable_answer = _probable_answer(raw.get("probable_answer"))
        intent = _allowed_alias(
            raw.get("intent"),
            _ALLOWED_INTENTS,
            default="unknown",
            aliases=_INTENT_ALIASES,
        )
        domain_hint = _allowed(raw.get("domain_hint"), _ALLOWED_DOMAIN_HINTS, default="unknown")
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
                        "answer_shape reference, short_answer, explanation, or "
                        "surah_and_verse.\n"
                        "Example: query 'Which hadith says about offering sacrifice for "
                        "eid from hadith_bukhari' should include target_terms such as "
                        "offering, sacrifice, eid, may include possible_references such "
                        "as book:13:hadith:25 only if plausible, and must set "
                        "needs_clarification false.\n"
                        f"Domain tokens: {domain_tokens}\n"
                        f"Query: {query.strip()}"
                    ),
                },
            ],
        }


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


def _possible_references(raw: Any) -> list[str]:
    if isinstance(raw, str | dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    references: list[str] = []
    for item in raw:
        reference = _reference_from_item(item)
        if reference is not None:
            references.append(reference)
    return list(dict.fromkeys(references))[:3]


def _reference_from_item(item: Any) -> str | None:
    if isinstance(item, str):
        return normalize_reference_hypothesis(item)
    if not isinstance(item, dict):
        return None
    for key in ("reference", "ref", "citation"):
        reference = normalize_reference_hypothesis(item.get(key))
        if reference is not None:
            return reference
    book = _positive_int(item.get("book"), max_value=9999)
    hadith = _positive_int(item.get("hadith"), max_value=999999)
    if book is not None and hadith is not None:
        return f"book:{book}:hadith:{hadith}"
    return None


def _probable_answer(raw: Any) -> ProbableAnswer | None:
    if not isinstance(raw, dict):
        return None
    surah_number = _positive_int(raw.get("surah_number"))
    ayah = _positive_int(raw.get("ayah"))
    if raw.get("surah_number") is not None and surah_number is None:
        return None
    if raw.get("ayah") is not None and ayah is None:
        return None
    reference = _safe_reference(raw.get("reference"))
    return ProbableAnswer(
        surah=_safe_short_text(raw.get("surah"), max_length=80),
        surah_number=surah_number,
        ayah=ayah,
        matched_term=_safe_short_text(raw.get("matched_term"), max_length=80),
        reference=reference,
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


def _safe_reference(value: Any) -> str | None:
    return normalize_reference_hypothesis(value)


def normalize_reference_hypothesis(value: Any) -> str | None:
    reference = _safe_short_text(value, max_length=80)
    if reference is None:
        return None
    references = parse_legacy_reference_query(reference)
    return references[0] if references else None


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
