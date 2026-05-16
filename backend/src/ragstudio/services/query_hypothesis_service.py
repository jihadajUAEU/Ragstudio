from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from typing import Any

import httpx

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
_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+")
_WORD_TARGET_RE = re.compile(
    r"\b(?:word|term|arabic word|arabic term)\s+['\"]?(?P<term>[A-Za-z][A-Za-z'-]{1,79})['\"]?",
    re.IGNORECASE,
)
_PATH_LIKE_RE = re.compile(r"(?:^|/)(?:Users|home|var|tmp|etc|private)(?:/|$)", re.IGNORECASE)


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
            "probable_answer": (
                self.probable_answer.to_trace() if self.probable_answer is not None else None
            ),
        }


class QueryHypothesisService:
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
            async with httpx.AsyncClient(timeout=max(timeout_ms, 1) / 1000) as client:
                response = await client.post(
                    _chat_url(str(profile.llm_base_url)),
                    headers=headers,
                    json=payload,
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

    def deterministic_hypothesis(
        self,
        query: str,
        *,
        domain_metadata: list[dict[str, Any]],
    ) -> QueryHypothesis:
        if _domain_family(domain_metadata) != "arabic_religious":
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
        probable_answer = _probable_answer(raw.get("probable_answer"))
        intent = _allowed(raw.get("intent"), _ALLOWED_INTENTS, default="unknown")
        domain_hint = _allowed(raw.get("domain_hint"), _ALLOWED_DOMAIN_HINTS, default="unknown")
        answer_shape = _allowed(
            raw.get("answer_shape"),
            _ALLOWED_ANSWER_SHAPES,
            default="unknown",
        )
        confidence = _confidence(raw.get("confidence"))
        needs_clarification = bool(raw.get("needs_clarification", False))

        valid = bool(target_terms) and not needs_clarification
        return QueryHypothesis(
            original_query=original_query,
            intent=intent,
            target_terms=target_terms,
            domain_hint=domain_hint,
            answer_shape=answer_shape,
            probable_answer=probable_answer,
            confidence=confidence,
            needs_clarification=needs_clarification,
            valid=valid,
            source="parsed",
            reason=None if valid else "no_valid_target_terms",
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
                        "Return only JSON. Extract search intent and exact target terms for "
                        "a RAG retrieval system. Do not answer authoritatively. Probable "
                        "answers are hypotheses and must include only compact references."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Schema keys: intent, target_terms, domain_hint, answer_shape, "
                        "probable_answer, confidence, needs_clarification.\n"
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


def _probable_answer(raw: Any) -> ProbableAnswer | None:
    if not isinstance(raw, dict):
        return None
    surah_number = _positive_int(raw.get("surah_number"))
    ayah = _positive_int(raw.get("ayah"))
    if raw.get("surah_number") is not None and surah_number is None:
        return None
    if raw.get("ayah") is not None and ayah is None:
        return None
    return ProbableAnswer(
        surah=_str_or_none(raw.get("surah")),
        surah_number=surah_number,
        ayah=ayah,
        matched_term=_str_or_none(raw.get("matched_term")),
        reference=_str_or_none(raw.get("reference")),
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


def _allowed(value: Any, allowed: set[str], *, default: str) -> str:
    normalized = str(value or "").strip().casefold()
    return normalized if normalized in allowed else default


def _confidence(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(parsed, 0.0), 1.0)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _str_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _arabic_target_terms(query: str) -> list[str]:
    return list(dict.fromkeys(match.group(0) for match in _ARABIC_RE.finditer(query)))


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


def _domain_family(domain_metadata: list[dict[str, Any]]) -> str:
    signals = {
        str(value).strip().casefold()
        for metadata in domain_metadata
        for value in _metadata_values(metadata)
        if str(value).strip()
    }
    if signals & {"quran", "tafseer", "quran_tafseer", "hadith", "islamic_text"}:
        return "arabic_religious"
    return "generic"


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
