from __future__ import annotations

from time import perf_counter
from typing import Any

from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn
from ragstudio.services.query_understanding import QueryUnderstanding, RetrievalPass
from ragstudio.services.retrieval_evidence import EvidenceCandidate

_METADATA_PASS_NAMES = {
    "reference_exact",
    "arabic_exact_token",
    "phrase_exact",
    "title_count",
    "semantic_metadata",
}


class MetadataRetrievalService:
    def __init__(self, chunk_service: Any):
        self.chunk_service = chunk_service

    async def retrieve(
        self,
        query: str,
        *,
        understanding: QueryUnderstanding,
        document_ids: list[str],
        variant_id: str,
        limit: int,
    ) -> tuple[list[EvidenceCandidate], dict[str, Any]]:
        candidates: list[EvidenceCandidate] = []
        pass_traces: list[dict[str, Any]] = []
        seen_chunk_ids: set[str] = set()

        for retrieval_pass in self._metadata_passes(understanding):
            pass_started = perf_counter()
            pass_query = retrieval_pass.query or query
            search = await self.chunk_service.search(
                ChunkSearchIn(
                    query=pass_query,
                    document_ids=document_ids,
                    variant_id=variant_id,
                    limit=max(limit * retrieval_pass.limit_multiplier, limit),
                    explain=True,
                    include_neighbors=True,
                )
            )
            pass_candidates: list[EvidenceCandidate] = []
            for index, chunk in enumerate(search.items, start=1):
                if chunk.id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk.id)
                pass_candidates.append(
                    self._candidate_from_chunk(chunk, index, retrieval_pass)
                )

            candidates.extend(pass_candidates)
            pass_traces.append(
                {
                    "name": retrieval_pass.name,
                    "query": pass_query,
                    "candidate_count": len(pass_candidates),
                    "latency_ms": _elapsed_ms(pass_started),
                    "top_candidate_ids": [
                        candidate.candidate_id for candidate in pass_candidates[:5]
                    ],
                }
            )

        return candidates, {"stage": "metadata_retrieval", "passes": pass_traces}

    def _metadata_passes(self, understanding: QueryUnderstanding) -> list[RetrievalPass]:
        return [
            retrieval_pass
            for retrieval_pass in understanding.retrieval_passes
            if retrieval_pass.name in _METADATA_PASS_NAMES
        ]

    def _candidate_from_chunk(
        self,
        chunk: ChunkOut,
        rank: int,
        retrieval_pass: RetrievalPass,
    ) -> EvidenceCandidate:
        score = chunk.metadata.get("score")
        base_score = float(score) if isinstance(score, (int, float)) else max(1.0, 20.0 - rank)
        metadata = dict(chunk.metadata)
        if chunk.runtime_source_id:
            metadata.setdefault("runtime_source_id", chunk.runtime_source_id)
        metadata.setdefault("canonical_chunk_id", chunk.id)
        return EvidenceCandidate(
            candidate_id=f"metadata:{chunk.id}",
            text=chunk.text,
            document_id=chunk.document_id,
            chunk_id=chunk.id,
            source_location=chunk.source_location,
            metadata=metadata,
            tool="metadata",
            tool_rank=rank,
            base_score=base_score,
            retrieval_pass=retrieval_pass.name,
            match_features=self._match_features(retrieval_pass),
            canonical_reference=self._first_reference(chunk),
            scope_status="in_scope",
            source_quality=self._source_quality(chunk),
        )

    def _match_features(self, retrieval_pass: RetrievalPass) -> dict[str, Any]:
        if retrieval_pass.name == "arabic_exact_token":
            return {"arabic_exact": True, "arabic_token": retrieval_pass.query}
        if retrieval_pass.name == "reference_exact":
            return {"reference_exact": True, "reference": retrieval_pass.query}
        if retrieval_pass.name == "phrase_exact":
            return {"target_phrase": retrieval_pass.query}
        if retrieval_pass.name == "title_count":
            return {"title_count": True}
        return {}

    def _first_reference(self, chunk: ChunkOut) -> str | None:
        source_reference = chunk.source_location.get("reference")
        if isinstance(source_reference, str) and source_reference:
            return source_reference
        reference_metadata = chunk.metadata.get("reference_metadata")
        if not isinstance(reference_metadata, dict):
            return None
        references = reference_metadata.get("references")
        if isinstance(references, list) and references:
            return str(references[0])
        return None

    def _source_quality(self, chunk: ChunkOut) -> dict[str, Any]:
        extraction_quality = chunk.metadata.get("extraction_quality")
        parser_warnings: list[Any] = []
        if isinstance(extraction_quality, dict):
            warnings = extraction_quality.get("parser_warnings")
            parser_warnings = warnings if isinstance(warnings, list) else []
        parser_metadata = chunk.metadata.get("parser_metadata")
        parser_metadata = parser_metadata if isinstance(parser_metadata, dict) else {}
        return {
            "parser": chunk.metadata.get("backend") or parser_metadata.get("backend"),
            "warning_count": len(parser_warnings),
        }


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 3)
