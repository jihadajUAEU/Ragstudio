from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ragstudio.services.lexical_language_adapters import (
    ArabicLexicalAdapter,
    LexicalExpansion,
)
from ragstudio.services.query_hypothesis_service import QueryHypothesis
from ragstudio.services.query_understanding import RetrievalPass


@dataclass(frozen=True)
class DomainQueryExpansion:
    original_query: str
    domain_family: str
    expansions: list[LexicalExpansion] = field(default_factory=list)
    retrieval_passes: list[RetrievalPass] = field(default_factory=list)
    trace: dict[str, object] = field(default_factory=dict)


class DomainQueryExpansionService:
    def __init__(self, arabic_adapter: ArabicLexicalAdapter | None = None):
        self.arabic_adapter = arabic_adapter or ArabicLexicalAdapter()

    def expand(
        self,
        query: str,
        *,
        domain_metadata: list[dict[str, Any]],
        query_hypothesis: QueryHypothesis | None = None,
    ) -> DomainQueryExpansion:
        domain_family = _domain_family(domain_metadata)
        expansions: list[LexicalExpansion] = []
        retrieval_passes: list[RetrievalPass] = []
        expansion_source = "original_query"
        expansion_inputs = [query]

        if (
            domain_family == "arabic_religious"
            and query_hypothesis is not None
            and query_hypothesis.valid
            and query_hypothesis.target_terms
        ):
            hypothesis_inputs = [
                term.surface
                for term in query_hypothesis.target_terms
                if term.surface.strip()
            ]
            hypothesis_expansions = [
                self.arabic_adapter.expand_query(term)
                for term in hypothesis_inputs
                if self.arabic_adapter.supports_query(term)
            ]
            expansions.extend(
                expansion
                for expansion in hypothesis_expansions
                if expansion.terms and expansion.match_type in {"exact_script", "transliteration"}
            )
            if expansions:
                expansion_source = "query_hypothesis"
                expansion_inputs = hypothesis_inputs

        if (
            not expansions
            and domain_family == "arabic_religious"
            and self.arabic_adapter.supports_query(query)
        ):
            expansion = self.arabic_adapter.expand_query(query)
            if expansion.terms and expansion.match_type in {"exact_script", "transliteration"}:
                expansions.append(expansion)

        for expansion in expansions:
            retrieval_passes.extend(
                RetrievalPass(
                    "lexical_expanded_token",
                    term,
                    direct_evidence=True,
                    match_type=expansion.match_type,
                )
                for term in expansion.terms
            )

        expanded_terms = [term for expansion in expansions for term in expansion.terms]
        return DomainQueryExpansion(
            original_query=query,
            domain_family=domain_family,
            expansions=expansions,
            retrieval_passes=retrieval_passes,
            trace={
                "stage": "domain_query_expansion",
                "original_query": query,
                "domain_family": domain_family,
                "expansion_source": expansion_source,
                "expansion_input_terms": expansion_inputs,
                "expanded_terms": expanded_terms,
                "query_hypothesis": (
                    _hypothesis_summary(query_hypothesis)
                    if query_hypothesis is not None
                    else None
                ),
                "expansions": [
                    {
                        "language": expansion.language,
                        "script": expansion.script,
                        "match_type": expansion.match_type,
                        "confidence": expansion.confidence,
                        "source": expansion.source,
                        "terms": list(expansion.terms),
                    }
                    for expansion in expansions
                ],
            },
        )


def _domain_family(domain_metadata: list[dict[str, Any]]) -> str:
    religious_signals: set[str] = set()
    for metadata in domain_metadata:
        if not isinstance(metadata, dict):
            continue
        raw_tags = metadata.get("tags")
        tags = raw_tags if isinstance(raw_tags, list | tuple | set) else []
        religious_signals.update(
            normalized_value
            for value in [
                metadata.get("domain"),
                metadata.get("document_type"),
                metadata.get("content_role"),
                *tags,
            ]
            if isinstance(value, str)
            if (normalized_value := value.strip().casefold())
        )

    if religious_signals & {
        "quran",
        "tafseer",
        "quran_tafseer",
        "hadith",
        "islamic_text",
        "religious_text",
        "fiqh",
        "fatwa",
        "islamic_law",
    }:
        return "arabic_religious"
    return "generic"


def _hypothesis_summary(hypothesis: QueryHypothesis) -> dict[str, object]:
    return {
        "status": "valid" if hypothesis.valid else "skipped",
        "source": hypothesis.source,
        "reason": hypothesis.reason,
        "intent": hypothesis.intent,
        "domain_hint": hypothesis.domain_hint,
        "answer_shape": hypothesis.answer_shape,
        "confidence": hypothesis.confidence,
        "target_terms": [term.to_trace() for term in hypothesis.target_terms],
        "probable_answer": (
            hypothesis.probable_answer.to_trace()
            if hypothesis.probable_answer is not None
            else None
        ),
    }
