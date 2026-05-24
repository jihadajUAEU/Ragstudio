from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.arabic_text import (
    arabic_query_variants,
    arabic_tokens,
    normalize_arabic_text,
)
from ragstudio.services.domain_search_policy import DomainSearchPolicy
from ragstudio.services.reference_metadata import ReferenceSemantics
from ragstudio.services.retrieval_explainer import build_retrieval_explain
from ragstudio.services.retrieval_policy import DEFAULT_RETRIEVAL_POLICY, HybridScorePolicy

if TYPE_CHECKING:
    from ragstudio.db.models import Chunk

_ENGLISH_STOPWORDS = {
    "a",
    "an",
    "about",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "saying",
    "says",
    "say",
    "the",
    "this",
    "to",
    "was",
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "with",
}

_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
_COUNT_QUERY_RE = re.compile(r"\b(how many|count|number of|total)\b")
_NUMBER_RE = re.compile(r"\b\d{2,}\b")
_GUIDE_US_RE = re.compile(r"\bguide\s+us\b")
_QUOTED_PHRASE_RE = re.compile(r'"([^"]{8,160})"')
_ANSWER_BEARING_PATTERNS = (
    re.compile(r"\b(?:that|which)\s+says?\s+(.+?)(?:[.?!]|$)"),
    re.compile(r"\bsays?\s+(.+?)(?:[.?!]|$)"),
    re.compile(r"\btranslated\s+as\s+(.+?)(?:[.?!]|$)"),
)
_LEADING_PHRASE_NOISE_RE = re.compile(r"^(?:that|which|the verse)\s+")
_SPACE_RE = re.compile(r"\s+")
_TERM_RE = re.compile(r"[\w\u0600-\u06FF]+", flags=re.UNICODE)


@dataclass(frozen=True)
class ChunkScore:
    score: float
    breakdown: dict[str, Any]


class HybridChunkSearch:
    def __init__(self, policy: HybridScorePolicy | None = None) -> None:
        self.policy = policy or DEFAULT_RETRIEVAL_POLICY.hybrid

    def score(
        self,
        query: str,
        chunk: Chunk,
        search_weights: dict[str, float] | None = None,
    ) -> ChunkScore:
        query_text = query.strip().lower()
        if not query_text:
            return ChunkScore(score=1.0, breakdown={"empty_query": 1.0})

        chunk_text = chunk.text.lower()
        metadata = chunk.metadata_json or {}
        policy = DomainSearchPolicy.from_metadata(metadata)
        if _contains_arabic(query) and not self._quality_allows_exact_arabic(metadata):
            return ChunkScore(
                score=0.0,
                breakdown={
                    "quality_blocked_arabic": 1.0,
                    "retrieval_explain": build_retrieval_explain(
                        query_reference=None,
                        metadata=metadata,
                        score_breakdown={"quality_blocked_arabic": 1.0},
                    ).model_dump(),
                },
            )
        semantics = self._semantics(metadata)
        query_ref = semantics.extract_query_reference(query) if semantics else None
        reference_metadata = metadata.get("reference_metadata")

        reference_exact = 0.0
        same_chapter = 0.0
        neighbor_match = 0.0
        requested_ref = self._query_reference_label(query_ref)
        quality_allows_reference_boost = self._quality_allows_reference_boost(metadata)
        if isinstance(query_ref, dict) and isinstance(reference_metadata, dict):
            q_chapter = query_ref.get("chapter")
            q_verse = query_ref.get("verse")
            chapter_start = reference_metadata.get("chapter_start")
            chapter_end = reference_metadata.get("chapter_end")
            verse_start = reference_metadata.get("verse_start")
            verse_end = reference_metadata.get("verse_end")
            references = reference_metadata.get("references")
            explicit_refs = (
                {ref for ref in references if isinstance(ref, str)}
                if isinstance(references, list)
                else set()
            )
            if (
                quality_allows_reference_boost
                and semantics
                and semantics.exact_reference_top1
                and requested_ref in explicit_refs
            ):
                reference_exact = self.policy.reference_exact
            elif (
                quality_allows_reference_boost
                and semantics
                and semantics.exact_reference_top1
                and isinstance(q_chapter, int)
                and isinstance(q_verse, int)
                and isinstance(chapter_start, int)
                and isinstance(chapter_end, int)
                and isinstance(verse_start, int)
                and isinstance(verse_end, int)
                and chapter_start <= q_chapter <= chapter_end
                and verse_start <= q_verse <= verse_end
            ):
                reference_exact = self.policy.reference_exact
            elif (
                quality_allows_reference_boost
                and semantics
                and semantics.boost_same_chapter
                and isinstance(q_chapter, int)
                and isinstance(chapter_start, int)
                and isinstance(chapter_end, int)
                and chapter_start <= q_chapter <= chapter_end
            ):
                same_chapter = (
                    self.policy.same_chapter_reference_query
                    if q_verse is None
                    else self.policy.same_chapter_with_verse_query
                )

            if (
                quality_allows_reference_boost
                and semantics
                and semantics.boost_neighbor_verses
                and requested_ref
                in {
                    reference_metadata.get("previous_ref"),
                    reference_metadata.get("next_ref"),
                }
            ):
                neighbor_match = self.policy.neighbor_match

        exact_phrase = self._exact_phrase_score(query_text, chunk_text)
        query_terms = self._terms(query_text)
        aliased_query_terms = self._terms(query_text, policy)
        chunk_terms = self._terms(chunk_text)
        if aliased_query_terms and chunk_terms:
            coverage_overlap = aliased_query_terms & chunk_terms
            coverage = len(coverage_overlap) / len(aliased_query_terms)
        else:
            coverage = 0.0
        if query_terms and chunk_terms:
            raw_overlap = query_terms & chunk_terms
            density = len(raw_overlap) / len(chunk_terms)
        else:
            density = 0.0

        arabic_exact = self._arabic_exact_score(query, chunk)
        arabic_token = self._arabic_token_score(query, chunk)
        metadata_boost = self._metadata_boost(query_text, metadata)
        layout_context = self._layout_context_boost(query_text, metadata)
        answer_bearing_count = self._answer_bearing_count_boost(
            query_text,
            chunk.text,
            metadata,
        )
        guidance_request = self._guidance_request_boost(query_text, chunk_text)
        domain_intent = self._domain_intent_boost(
            policy,
            query_text=query_text,
            query_terms=query_terms,
            chunk_terms=chunk_terms,
            evidence_text=f"{chunk.text} {self._metadata_title(metadata)}",
        )
        breakdown: dict[str, float] = {
            "reference_exact": reference_exact,
            "neighbor_match": neighbor_match,
            "same_chapter": same_chapter,
            "exact_phrase": exact_phrase,
            "term_coverage": coverage * self.policy.term_coverage_multiplier,
            "semantic_density": density * self.policy.semantic_density_multiplier,
            "arabic_exact": arabic_exact,
            "arabic_token": arabic_token,
            "metadata_boost": metadata_boost,
            "layout_context": layout_context,
            "answer_bearing_count": answer_bearing_count,
            "guidance_request": guidance_request,
            "domain_intent": domain_intent,
        }
        weights = self._effective_weights(policy, search_weights)
        weighted_breakdown = {
            key: value * weights.get(key, 1.0)
            for key, value in breakdown.items()
        }
        explain = build_retrieval_explain(
            query_reference=self._query_reference_label(query_ref),
            metadata=metadata,
            score_breakdown=weighted_breakdown,
        )
        return ChunkScore(
            score=sum(weighted_breakdown.values()),
            breakdown={
                **breakdown,
                "weighted_score_breakdown": weighted_breakdown,
                "retrieval_explain": explain.model_dump(),
            },
        )

    def _semantics(self, metadata: dict[str, Any]) -> ReferenceSemantics | None:
        domain_metadata = metadata.get("domain_metadata")
        if not isinstance(domain_metadata, dict):
            return None
        return ReferenceSemantics.from_metadata(DomainMetadata.model_validate(domain_metadata))

    def _metadata_boost(
        self,
        query_text: str,
        metadata: dict[str, Any],
    ) -> float:
        boost = 0.0
        domain_metadata = metadata.get("domain_metadata")
        if isinstance(domain_metadata, dict):
            tags = domain_metadata.get("tags")
            if isinstance(tags, list):
                for tag in tags:
                    if isinstance(tag, str) and tag.casefold() in query_text:
                        boost += 1.0
            for field in ("domain", "document_type", "collection", "content_role"):
                value = domain_metadata.get(field)
                if isinstance(value, str) and value and value.casefold() in query_text:
                    boost += 1.0

        document_metadata = metadata.get("document_metadata")
        if isinstance(document_metadata, dict):
            title = document_metadata.get("title")
            if isinstance(title, str):
                title_terms = self._terms(title.lower())
                query_terms = self._terms(query_text)
                shared_title_terms = query_terms & title_terms
                if shared_title_terms:
                    boost += min(
                        self.policy.metadata_title_term_cap,
                        len(shared_title_terms)
                        * self.policy.metadata_title_term_multiplier,
                    )

        return min(boost, self.policy.metadata_boost_cap)

    def _layout_context_boost(self, query_text: str, metadata: dict[str, Any]) -> float:
        query_terms = self._terms(query_text)
        if not query_terms:
            return 0.0

        layout_terms: set[str] = set()
        for key in ("modality", "content_type"):
            value = metadata.get(key)
            if isinstance(value, str):
                layout_terms.update(self._terms(value))

        layout_context = metadata.get("layout_context")
        if isinstance(layout_context, dict):
            for value in layout_context.values():
                if isinstance(value, str):
                    layout_terms.update(self._terms(value))
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            layout_terms.update(self._terms(item))

        provenance = metadata.get("provenance")
        if isinstance(provenance, dict):
            blocks = provenance.get("blocks")
            if isinstance(blocks, list):
                for block in blocks[:8]:
                    if not isinstance(block, dict):
                        continue
                    for key in ("role", "block_type", "text_preview"):
                        value = block.get(key)
                        if isinstance(value, str):
                            layout_terms.update(self._terms(value))

        overlap = query_terms & layout_terms
        return min(
            self.policy.layout_context_cap,
            len(overlap) * self.policy.layout_context_term_multiplier,
        )

    def _domain_intent_boost(
        self,
        policy: DomainSearchPolicy | None,
        *,
        query_text: str,
        query_terms: set[str],
        chunk_terms: set[str],
        evidence_text: str,
    ) -> float:
        if policy is None:
            return 0.0
        return policy.intent_boost(
            query_text=query_text,
            query_terms=query_terms,
            chunk_terms=chunk_terms,
            evidence_text=evidence_text,
        )

    def _quality_allows_reference_boost(self, metadata: dict[str, Any]) -> bool:
        policy = metadata.get("quality_action_policy")
        if not isinstance(policy, dict):
            return True
        return self._quality_allows_exact_arabic(metadata) and policy.get(
            "graph_confidence"
        ) != "blocked"

    def _quality_allows_exact_arabic(self, metadata: dict[str, Any]) -> bool:
        policy = metadata.get("quality_action_policy")
        if not isinstance(policy, dict):
            return True
        return bool(policy.get("index_exact_arabic", True))

    def _arabic_exact_score(self, query: str, chunk: Chunk) -> float:
        variants = arabic_query_variants(query)
        if not variants:
            return 0.0
        metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
        if not self._quality_allows_exact_arabic(metadata):
            return 0.0
        stored_tokens = getattr(chunk, "tokens_ar", None)
        token_set = set(
            stored_tokens
            if isinstance(stored_tokens, list) and stored_tokens
            else arabic_tokens(chunk.text)
        )
        if variants and token_set and any(variant in token_set for variant in variants):
            return self.policy.arabic_exact
        searchable = str(getattr(chunk, "text_search_ar", "") or normalize_arabic_text(chunk.text))
        if any(
            variant and " " in variant and self._has_arabic_phrase_boundary(searchable, variant)
            for variant in variants
        ):
            return self.policy.arabic_exact
        return 0.0

    def _arabic_token_score(self, query: str, chunk: Chunk) -> float:
        variants = set(arabic_query_variants(query))
        if not variants:
            return 0.0
        metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
        if not self._quality_allows_exact_arabic(metadata):
            return 0.0
        stored_tokens = getattr(chunk, "tokens_ar", None)
        tokens = set(
            stored_tokens
            if isinstance(stored_tokens, list) and stored_tokens
            else arabic_tokens(chunk.text)
        )
        if variants & tokens:
            return self.policy.arabic_token
        return 0.0

    def _has_arabic_phrase_boundary(self, searchable: str, variant: str) -> bool:
        return _arabic_phrase_boundary_pattern(variant).search(searchable) is not None

    def _answer_bearing_count_boost(
        self,
        query_text: str,
        chunk_text: str,
        metadata: dict[str, Any],
    ) -> float:
        if not _COUNT_QUERY_RE.search(query_text):
            return 0.0
        combined = f"{chunk_text} {self._metadata_title(metadata)}".casefold()
        if not _NUMBER_RE.search(combined):
            return 0.0
        if not any(term in combined for term in ("hadith", "collection", "bukhari")):
            return 0.0
        return self.policy.answer_bearing_count

    def _guidance_request_boost(self, query_text: str, chunk_text: str) -> float:
        query_terms = self._terms(query_text)
        asks_for_guidance = (
            {"ask", "asks", "asking", "request", "requests", "prayer"} & query_terms
            and {"guidance", "guide", "guides", "guided"} & query_terms
        )
        if not asks_for_guidance:
            return 0.0

        if "straight path" not in query_text or "straight path" not in chunk_text:
            return 0.0
        if _GUIDE_US_RE.search(chunk_text):
            return self.policy.guidance_request
        return 0.0

    def _exact_phrase_score(self, query_text: str, chunk_text: str) -> float:
        if query_text and query_text in chunk_text:
            return self.policy.exact_query_phrase

        for phrase in self._answer_bearing_phrases(query_text):
            if phrase in chunk_text:
                return self.policy.answer_bearing_phrase
        return 0.0

    def _answer_bearing_phrases(self, query_text: str) -> list[str]:
        phrases: list[str] = []
        for match in _QUOTED_PHRASE_RE.finditer(query_text):
            phrases.append(match.group(1).strip())

        for pattern in _ANSWER_BEARING_PATTERNS:
            for match in pattern.finditer(query_text):
                phrase = match.group(1).strip()
                phrase = _LEADING_PHRASE_NOISE_RE.sub("", phrase)
                if phrase:
                    phrases.append(phrase)

        normalized: list[str] = []
        for phrase in phrases:
            phrase = _SPACE_RE.sub(" ", phrase).strip().casefold()
            if len(self._terms(phrase)) >= 4 and phrase not in normalized:
                normalized.append(phrase)
        return normalized

    def _metadata_title(self, metadata: dict[str, Any]) -> str:
        document_metadata = metadata.get("document_metadata")
        if isinstance(document_metadata, dict):
            title = document_metadata.get("title")
            if isinstance(title, str):
                return title
        return ""

    def _terms(self, value: str, policy: DomainSearchPolicy | None = None) -> set[str]:
        terms: set[str] = set()
        for match in _TERM_RE.finditer(value):
            term = match.group(0).lower()
            if term in _ENGLISH_STOPWORDS:
                continue
            terms.add(term)
            if policy is not None:
                terms.update(policy.aliases_for(term))
        return terms

    def _effective_weights(
        self,
        policy: DomainSearchPolicy | None,
        search_weights: dict[str, float] | None,
    ) -> dict[str, float]:
        weights: dict[str, float] = {}
        if policy is not None and policy.hybrid_search_weights:
            weights.update(policy.hybrid_search_weights)
        if search_weights:
            for key, value in search_weights.items():
                if isinstance(value, bool) or not isinstance(value, int | float):
                    continue
                weights[key] = float(value)
        return weights

    def _query_reference_label(self, query_ref: dict[str, Any] | None) -> str | None:
        if not isinstance(query_ref, dict):
            return None
        chapter = query_ref.get("chapter")
        verse = query_ref.get("verse")
        if isinstance(chapter, int) and isinstance(verse, int):
            return f"{chapter}:{verse}"
        if isinstance(chapter, int):
            return f"chapter:{chapter}"
        ref = query_ref.get("ref")
        if isinstance(ref, str) and ref:
            return ref
        return None


@lru_cache(maxsize=2048)
def _arabic_phrase_boundary_pattern(variant: str) -> re.Pattern[str]:
    escaped = re.escape(variant)
    return re.compile(rf"(?<![\u0600-\u06FF]){escaped}(?![\u0600-\u06FF])")


def _contains_arabic(value: str) -> bool:
    return _ARABIC_RE.search(value) is not None
