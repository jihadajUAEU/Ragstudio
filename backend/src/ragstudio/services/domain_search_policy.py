from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchIntent:
    query_terms: frozenset[str]
    query_phrases: frozenset[str]
    requires_numeric_evidence: bool
    vocabulary: frozenset[str]
    boost: float


@dataclass(frozen=True)
class DomainSearchPolicy:
    intents: tuple[SearchIntent, ...] = ()
    term_aliases: dict[str, frozenset[str]] | None = None
    domain_vocabulary: dict[str, frozenset[str]] | None = None
    hybrid_search_weights: dict[str, float] | None = None

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any]) -> DomainSearchPolicy | None:
        domain_metadata = metadata.get("domain_metadata")
        if not isinstance(domain_metadata, dict):
            return None
        custom_json = domain_metadata.get("custom_json")
        if not isinstance(custom_json, dict):
            return None

        domain_vocabulary = _domain_vocabulary(custom_json.get("domain_vocabulary"))
        policy = cls(
            intents=_search_intents(
                custom_json.get("search_intents"),
                domain_vocabulary=domain_vocabulary,
            ),
            term_aliases=_term_aliases(custom_json.get("domain_vocabulary")),
            domain_vocabulary=domain_vocabulary,
            hybrid_search_weights=_weights(custom_json.get("hybrid_search_weights")),
        )
        if (
            not policy.intents
            and not policy.term_aliases
            and not policy.domain_vocabulary
            and not policy.hybrid_search_weights
        ):
            return None
        return policy

    def aliases_for(self, term: str) -> frozenset[str]:
        if not self.term_aliases:
            return frozenset()
        return self.term_aliases.get(term.casefold(), frozenset())

    def intent_boost(
        self,
        *,
        query_text: str,
        query_terms: set[str],
        chunk_terms: set[str],
        evidence_text: str,
    ) -> float:
        boost = 0.0
        normalized_query_text = _normalized_text(query_text)
        for intent in self.intents:
            has_query_match = (
                bool(query_terms & set(intent.query_terms))
                or any(phrase in normalized_query_text for phrase in intent.query_phrases)
            )
            if (intent.query_terms or intent.query_phrases) and not has_query_match:
                continue
            if intent.vocabulary and not (chunk_terms & set(intent.vocabulary)):
                continue
            if intent.requires_numeric_evidence and not re.search(
                r"\b\d+(?:[.,]\d+)?\b",
                evidence_text,
            ):
                continue
            boost += intent.boost
        return boost


def _search_intents(
    value: Any,
    *,
    domain_vocabulary: dict[str, frozenset[str]] | None,
) -> tuple[SearchIntent, ...]:
    if not isinstance(value, list):
        return ()
    intents: list[SearchIntent] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        boost = item.get("boost")
        if isinstance(boost, bool) or not isinstance(boost, int | float):
            continue
        query_terms, query_phrases = _normalized_query_matchers(item.get("query_terms"))
        intents.append(
            SearchIntent(
                query_terms=frozenset(query_terms),
                query_phrases=frozenset(query_phrases),
                requires_numeric_evidence=bool(item.get("requires_numeric_evidence", False)),
                vocabulary=frozenset(
                    _resolve_vocabulary_terms(
                        item.get("vocabulary"),
                        domain_vocabulary=domain_vocabulary,
                    )
                ),
                boost=float(boost),
            )
        )
    return tuple(intents)


def _domain_vocabulary(value: Any) -> dict[str, frozenset[str]] | None:
    if not isinstance(value, dict):
        return None
    vocabulary: dict[str, frozenset[str]] = {}
    for key, terms in value.items():
        if key == "term_aliases" or not isinstance(key, str):
            continue
        normalized = _normalized_terms(terms)
        if normalized:
            vocabulary[key.casefold()] = frozenset(normalized)
    return vocabulary or None


def _term_aliases(value: Any) -> dict[str, frozenset[str]] | None:
    if not isinstance(value, dict):
        return None
    aliases = value.get("term_aliases")
    if not isinstance(aliases, dict):
        return None

    expanded: dict[str, set[str]] = {}
    for term, term_aliases in aliases.items():
        if not isinstance(term, str) or not isinstance(term_aliases, list):
            continue
        normalized_term = term.casefold()
        normalized_aliases = {
            alias.casefold()
            for alias in term_aliases
            if isinstance(alias, str) and alias.strip()
        }
        if not normalized_aliases:
            continue
        expanded.setdefault(normalized_term, set()).update(normalized_aliases)
        for alias in normalized_aliases:
            expanded.setdefault(alias, set()).add(normalized_term)

    return {term: frozenset(values) for term, values in expanded.items()} or None


def _weights(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    weights: dict[str, float] = {}
    for key, weight in value.items():
        if not isinstance(key, str):
            continue
        if isinstance(weight, bool) or not isinstance(weight, int | float):
            continue
        weights[_weight_key(key)] = float(weight)
    return weights or None


def _normalized_terms(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    terms: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            continue
        for match in re.finditer(r"[\w\u0600-\u06FF]+", item, flags=re.UNICODE):
            terms.add(match.group(0).casefold())
    return terms


def _normalized_query_matchers(value: Any) -> tuple[set[str], set[str]]:
    if not isinstance(value, list):
        return set(), set()
    terms: set[str] = set()
    phrases: set[str] = set()
    for item in value:
        tokens = _normalized_tokens(item)
        if len(tokens) == 1:
            terms.add(tokens[0])
        elif len(tokens) > 1:
            phrases.add(" ".join(tokens))
    return terms, phrases


def _normalized_tokens(value: Any) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return []
    return [
        match.group(0).casefold()
        for match in re.finditer(r"[\w\u0600-\u06FF]+", value, flags=re.UNICODE)
    ]


def _normalized_text(value: str) -> str:
    return " ".join(_normalized_tokens(value))


def _resolve_vocabulary_terms(
    value: Any,
    *,
    domain_vocabulary: dict[str, frozenset[str]] | None,
) -> set[str]:
    terms = _normalized_terms(value)
    if not domain_vocabulary:
        return terms
    resolved = set(terms)
    for term in terms:
        resolved.update(domain_vocabulary.get(term, frozenset()))
    return resolved


def _weight_key(key: str) -> str:
    return key.casefold()
