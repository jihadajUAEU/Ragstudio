from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ragstudio.services.domain_lexical_registry import DomainLexicalAdapter, DomainLexicalRegistry
from ragstudio.services.lexical_language_adapters import ArabicLexicalAdapter, LexicalExpansion
from ragstudio.services.query_hypothesis_service import QueryHypothesis
from ragstudio.services.query_understanding import RetrievalPass
from ragstudio.services.reference_contracts import metadata_list_declared_scripts


@dataclass(frozen=True)
class DomainQueryExpansion:
    original_query: str
    domain_family: str
    expansions: list[LexicalExpansion] = field(default_factory=list)
    retrieval_passes: list[RetrievalPass] = field(default_factory=list)
    trace: dict[str, object] = field(default_factory=dict)


class DomainQueryExpansionService:
    def __init__(
        self,
        registry: DomainLexicalRegistry | DomainLexicalAdapter | None = None,
        arabic_adapter: DomainLexicalAdapter | None = None,
    ) -> None:
        selected_registry: DomainLexicalRegistry
        selected_arabic_adapter = arabic_adapter

        if registry is None:
            selected_registry = DomainLexicalRegistry()
        elif isinstance(registry, DomainLexicalRegistry):
            selected_registry = registry
        else:
            selected_registry = DomainLexicalRegistry()
            selected_arabic_adapter = registry

        self.registry = selected_registry
        self.arabic_adapter = selected_arabic_adapter or ArabicLexicalAdapter()

    def expand(
        self,
        query: str,
        *,
        domain_metadata: list[dict[str, Any]],
        query_hypothesis: QueryHypothesis | None = None,
    ) -> DomainQueryExpansion:
        domain_family = self.registry.resolve_domain_family(domain_metadata)
        expansions: list[LexicalExpansion] = []
        retrieval_passes: list[RetrievalPass] = []
        expansion_source = "original_query"
        expansion_inputs = [query]
        possible_references = (
            list(query_hypothesis.possible_references)
            if query_hypothesis is not None and query_hypothesis.valid
            else []
        )
        adapters = self.registry.adapters_for(domain_family)
        if domain_family == "reference_heavy" and _declares_arabic_script(domain_metadata):
            adapters.append(self.arabic_adapter)

        retrieval_passes.extend(
            RetrievalPass(
                "reference_exact",
                reference,
                direct_evidence=True,
                match_type="hypothesis_reference",
            )
            for reference in possible_references
        )
        if possible_references:
            expansion_source = "query_hypothesis"

        if (
            adapters
            and query_hypothesis is not None
            and query_hypothesis.valid
            and query_hypothesis.target_terms
        ):
            hypothesis_inputs = [
                term.surface
                for term in query_hypothesis.target_terms
                if term.surface.strip()
            ]
            hypothesis_expansions = _expand_with_adapters(hypothesis_inputs, adapters)
            expansions.extend(
                expansion
                for expansion in hypothesis_expansions
                if _use_expansion(domain_family, expansion)
            )
            if expansions:
                expansion_source = "query_hypothesis"
                expansion_inputs = hypothesis_inputs

        if not expansions and adapters:
            expansions.extend(
                expansion
                for expansion in _expand_with_adapters([query], adapters)
                if _use_expansion(domain_family, expansion)
            )

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
        adapter_sources = _dedupe(expansion.source for expansion in expansions)
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
                "adapter_sources": adapter_sources,
                "possible_references": possible_references,
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



def _expand_with_adapters(
    queries: list[str], adapters: list[DomainLexicalAdapter]
) -> list[LexicalExpansion]:
    expansions: list[LexicalExpansion] = []
    for query in queries:
        for adapter in adapters:
            if adapter.supports_query(query):
                expansions.append(adapter.expand_query(query))
    return expansions


def _use_expansion(domain_family: str, expansion: LexicalExpansion) -> bool:
    if not expansion.terms:
        return False
    if domain_family == "reference_heavy":
        return expansion.match_type in {"exact_script", "transliteration"}
    return True


def _declares_arabic_script(domain_metadata: list[dict[str, Any]]) -> bool:
    scripts = metadata_list_declared_scripts(domain_metadata)
    return bool({"arabic", "ar", "arab"} & scripts)


def _dedupe(values: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if isinstance(value, str) and value not in deduped:
            deduped.append(value)
    return deduped


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
        "possible_references": list(hypothesis.possible_references),
        "probable_answer": (
            hypothesis.probable_answer.to_trace()
            if hypothesis.probable_answer is not None
            else None
        ),
    }
