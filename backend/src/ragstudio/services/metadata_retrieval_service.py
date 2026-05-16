from __future__ import annotations

from time import perf_counter
from typing import Any

from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn
from ragstudio.services.query_understanding import QueryUnderstanding, RetrievalPass
from ragstudio.services.retrieval_evidence import EvidenceCandidate

_METADATA_PASS_NAMES = {
    "reference_exact",
    "arabic_exact_token",
    "lexical_expanded_token",
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
                chunk_id = _chunk_id(chunk)
                if chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk_id)
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
        metadata = _chunk_metadata(chunk)
        score = metadata.get("score")
        base_score = float(score) if isinstance(score, (int, float)) else max(1.0, 20.0 - rank)
        runtime_source_id = getattr(chunk, "runtime_source_id", None)
        if runtime_source_id:
            metadata.setdefault("runtime_source_id", runtime_source_id)
        chunk_id = _chunk_id(chunk)
        effective_pass = self._effective_retrieval_pass(chunk, retrieval_pass, metadata)
        metadata.setdefault("canonical_chunk_id", chunk_id)
        return EvidenceCandidate(
            candidate_id=f"metadata:{chunk_id}",
            text=str(getattr(chunk, "text", "")),
            document_id=getattr(chunk, "document_id", None),
            chunk_id=chunk_id,
            source_location=_chunk_source_location(chunk),
            metadata=metadata,
            tool="metadata",
            tool_rank=rank,
            base_score=base_score,
            retrieval_pass=effective_pass,
            match_features=self._match_features(retrieval_pass, effective_pass),
            canonical_reference=self._first_reference(chunk),
            scope_status="in_scope",
            source_quality=self._source_quality(chunk),
        )

    def _effective_retrieval_pass(
        self,
        chunk: ChunkOut,
        retrieval_pass: RetrievalPass,
        metadata: dict[str, Any],
    ) -> str:
        if retrieval_pass.name != "reference_exact":
            return retrieval_pass.name
        if _reference_exact_score(metadata) > 0:
            return "reference_exact"
        if _normalize_reference(self._first_reference(chunk)) == _normalize_reference(
            retrieval_pass.query
        ):
            return "reference_exact"
        return "semantic_metadata"

    def _match_features(
        self,
        retrieval_pass: RetrievalPass,
        effective_pass: str,
    ) -> dict[str, Any]:
        if effective_pass == "arabic_exact_token":
            return {"arabic_exact": True, "arabic_token": retrieval_pass.query}
        if effective_pass == "lexical_expanded_token":
            return {
                "lexical_expanded": True,
                "expanded_token": retrieval_pass.query,
                "match_type": retrieval_pass.match_type or "transliteration",
            }
        if effective_pass == "reference_exact":
            return {"reference_exact": True, "reference": retrieval_pass.query}
        if effective_pass == "phrase_exact":
            return {"target_phrase": retrieval_pass.query}
        if effective_pass == "title_count":
            return {"title_count": True}
        return {}

    def _first_reference(self, chunk: ChunkOut) -> str | None:
        source_reference = _chunk_source_location(chunk).get("reference")
        if isinstance(source_reference, str) and source_reference:
            return source_reference
        reference_metadata = _chunk_metadata(chunk).get("reference_metadata")
        if not isinstance(reference_metadata, dict):
            return None
        references = reference_metadata.get("references")
        if isinstance(references, list) and references:
            return str(references[0])
        return None

    def _source_quality(self, chunk: ChunkOut) -> dict[str, Any]:
        metadata = _chunk_metadata(chunk)
        extraction_quality = metadata.get("extraction_quality")
        parser_warnings: list[Any] = []
        if isinstance(extraction_quality, dict):
            warnings = extraction_quality.get("parser_warnings")
            parser_warnings = warnings if isinstance(warnings, list) else []
        counted_parser_warnings = [
            warning
            for warning in parser_warnings
            if not (
                isinstance(warning, dict)
                and bool(warning.get("suppressed_from_counts"))
            )
        ]
        parser_metadata = metadata.get("parser_metadata")
        parser_metadata = parser_metadata if isinstance(parser_metadata, dict) else {}
        return {
            "parser": metadata.get("backend") or parser_metadata.get("backend"),
            "warning_count": len(counted_parser_warnings),
        }


def _chunk_id(chunk: Any) -> str:
    return str(chunk.id)


def _chunk_metadata(chunk: Any) -> dict[str, Any]:
    metadata = getattr(chunk, "metadata", None)
    return dict(metadata) if isinstance(metadata, dict) else {}


def _chunk_source_location(chunk: Any) -> dict[str, Any]:
    source_location = getattr(chunk, "source_location", None)
    return dict(source_location) if isinstance(source_location, dict) else {}


def _reference_exact_score(metadata: dict[str, Any]) -> float:
    breakdown = metadata.get("score_breakdown")
    if not isinstance(breakdown, dict):
        return 0.0
    score = breakdown.get("reference_exact")
    return float(score) if isinstance(score, (int, float)) else 0.0


def _normalize_reference(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().casefold()


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 3)
