from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ragstudio.db.models import Chunk
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.reference_metadata import ReferenceSemantics
from ragstudio.services.retrieval_explainer import build_retrieval_explain


@dataclass(frozen=True)
class ChunkScore:
    score: float
    breakdown: dict[str, Any]


class HybridChunkSearch:
    def score(self, query: str, chunk: Chunk) -> ChunkScore:
        query_text = query.strip().lower()
        if not query_text:
            return ChunkScore(score=1.0, breakdown={"empty_query": 1.0})

        chunk_text = chunk.text.lower()
        metadata = chunk.metadata_json or {}
        semantics = self._semantics(metadata)
        query_ref = semantics.extract_query_reference(query) if semantics else None
        reference_metadata = metadata.get("reference_metadata")

        reference_exact = 0.0
        same_chapter = 0.0
        neighbor_match = 0.0
        requested_ref = self._query_reference_label(query_ref)
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
                semantics
                and semantics.exact_reference_top1
                and requested_ref in explicit_refs
            ):
                reference_exact = 100.0
            elif (
                semantics
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
                reference_exact = 100.0
            elif (
                semantics
                and semantics.boost_same_chapter
                and isinstance(q_chapter, int)
                and isinstance(chapter_start, int)
                and isinstance(chapter_end, int)
                and chapter_start <= q_chapter <= chapter_end
            ):
                same_chapter = 60.0 if q_verse is None else 5.0

            if semantics and semantics.boost_neighbor_verses and requested_ref in {
                reference_metadata.get("previous_ref"),
                reference_metadata.get("next_ref"),
            }:
                neighbor_match = 30.0

        exact_phrase = 8.0 if query_text and query_text in chunk_text else 0.0
        query_terms = self._terms(query_text)
        chunk_terms = self._terms(chunk_text)
        if query_terms and chunk_terms:
            overlap = query_terms & chunk_terms
            coverage = len(overlap) / len(query_terms)
            density = len(overlap) / len(chunk_terms)
        else:
            coverage = 0.0
            density = 0.0

        metadata_boost = self._metadata_boost(query_text, metadata)
        breakdown: dict[str, float] = {
            "reference_exact": reference_exact,
            "neighbor_match": neighbor_match,
            "same_chapter": same_chapter,
            "exact_phrase": exact_phrase,
            "term_coverage": coverage * 10.0,
            "term_density": density * 2.0,
            "metadata_boost": metadata_boost,
        }
        explain = build_retrieval_explain(
            query_reference=self._query_reference_label(query_ref),
            metadata=metadata,
            score_breakdown=breakdown,
        )
        return ChunkScore(
            score=sum(breakdown.values()),
            breakdown={**breakdown, "retrieval_explain": explain.model_dump()},
        )

    def _semantics(self, metadata: dict[str, Any]) -> ReferenceSemantics | None:
        domain_metadata = metadata.get("domain_metadata")
        if not isinstance(domain_metadata, dict):
            return None
        return ReferenceSemantics.from_metadata(DomainMetadata.model_validate(domain_metadata))

    def _metadata_boost(self, query_text: str, metadata: dict[str, Any]) -> float:
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
                    boost += min(10.0, len(shared_title_terms) * 2.0)

        return min(boost, 12.0)

    def _terms(self, value: str) -> set[str]:
        return {
            match.group(0).lower()
            for match in re.finditer(r"[\w\u0600-\u06FF]+", value, flags=re.UNICODE)
        }

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
