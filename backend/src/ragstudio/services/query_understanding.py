from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from ragstudio.services.arabic_text import arabic_query_variants

QueryUnderstandingIntent = Literal[
    "arabic_exact_token",
    "reference",
    "phrase_lookup",
    "count",
    "summary",
    "semantic",
]

_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
_REFERENCE_RE = re.compile(r"\b\d{1,3}:\d{1,3}\b")
_PHRASE_RE = re.compile(
    r"\b(?:says|say|phrase|quote)\b(?:\s+(?:that|is|was|as))?\s+(?P<phrase>.+)",
    re.IGNORECASE,
)
_NORMALIZED_PHRASE_RE = re.compile(r"[^0-9A-Za-z\u0600-\u06FF]+")


@dataclass(frozen=True)
class RetrievalPass:
    name: str
    query: str
    limit_multiplier: int = 1
    direct_evidence: bool = False


@dataclass(frozen=True)
class QueryUnderstanding:
    query: str
    intent: QueryUnderstandingIntent
    answer_type: str
    target_phrases: list[str] = field(default_factory=list)
    required_terms: list[str] = field(default_factory=list)
    reference_hints: list[str] = field(default_factory=list)
    arabic_query_variants: list[str] = field(default_factory=list)
    retrieval_passes: list[RetrievalPass] = field(default_factory=list)
    direct_evidence_required: bool = False


def understand_query(query: str) -> QueryUnderstanding:
    normalized = query.casefold()
    reference_hints = _reference_hints(query)
    if reference_hints:
        return QueryUnderstanding(
            query=query,
            intent="reference",
            answer_type="reference",
            reference_hints=reference_hints,
            retrieval_passes=_passes(query, "reference_exact", direct_first=True),
            direct_evidence_required=True,
        )

    if _is_compact_arabic_query(query):
        variants = arabic_query_variants(query)
        return QueryUnderstanding(
            query=query,
            intent="arabic_exact_token",
            answer_type="reference",
            required_terms=variants,
            arabic_query_variants=variants,
            retrieval_passes=_passes(
                variants[0] if variants else query,
                "arabic_exact_token",
                direct_first=True,
            ),
            direct_evidence_required=True,
        )

    target_phrases = _target_phrases(query)
    if target_phrases:
        return QueryUnderstanding(
            query=query,
            intent="phrase_lookup",
            answer_type="reference",
            target_phrases=target_phrases,
            required_terms=target_phrases,
            retrieval_passes=_passes(target_phrases[0], "phrase_exact", direct_first=True),
            direct_evidence_required=True,
        )

    if re.search(r"\b(how many|count|number of|total)\b", normalized):
        return QueryUnderstanding(
            query=query,
            intent="count",
            answer_type="count",
            retrieval_passes=_passes(query, "title_count"),
        )

    if re.search(r"\b(summary|summarize|overview)\b", normalized):
        return QueryUnderstanding(
            query=query,
            intent="summary",
            answer_type="summary",
            retrieval_passes=_semantic_passes(query),
        )

    return QueryUnderstanding(
        query=query,
        intent="semantic",
        answer_type="semantic",
        retrieval_passes=_semantic_passes(query),
    )


def _reference_hints(query: str) -> list[str]:
    return list(dict.fromkeys(_REFERENCE_RE.findall(query)))


def _is_compact_arabic_query(query: str) -> bool:
    return bool(_ARABIC_RE.search(query)) and len(query.split()) <= 3


def _target_phrases(query: str) -> list[str]:
    match = _PHRASE_RE.search(query)
    if not match:
        return []
    phrase = _normalize_phrase(match.group("phrase"))
    return [phrase] if phrase else []


def _normalize_phrase(value: str) -> str:
    normalized = _NORMALIZED_PHRASE_RE.sub(" ", value.casefold())
    return re.sub(r"\s+", " ", normalized).strip()


def _passes(query: str, first_pass: str, *, direct_first: bool = False) -> list[RetrievalPass]:
    return [
        RetrievalPass(first_pass, query, direct_evidence=direct_first),
        RetrievalPass("semantic_metadata", query),
        RetrievalPass("vector_db", query),
        RetrievalPass("native_vector", query),
    ]


def _semantic_passes(query: str) -> list[RetrievalPass]:
    return [
        RetrievalPass("semantic_metadata", query),
        RetrievalPass("vector_db", query),
        RetrievalPass("native_vector", query),
    ]
