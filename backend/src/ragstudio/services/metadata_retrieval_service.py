from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn, HybridSearchWeights
from ragstudio.services.query_hypothesis_service import normalize_reference_hypothesis
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


MetadataSearch = Callable[[ChunkSearchIn], Awaitable[Any]]


@dataclass(frozen=True)
class MetadataPassResult:
    retrieval_pass: RetrievalPass
    pass_query: str
    started_at: float
    search: Any


class MetadataRetrievalService:
    def __init__(
        self,
        chunk_service: Any,
        *,
        parallel_search: MetadataSearch | None = None,
        max_parallel_passes: int = 4,
    ):
        self.chunk_service = chunk_service
        self.parallel_search = parallel_search
        self.max_parallel_passes = max(1, max_parallel_passes)

    async def retrieve(
        self,
        query: str,
        *,
        understanding: QueryUnderstanding,
        document_ids: list[str],
        variant_id: str,
        limit: int,
        search_weights: dict[str, Any] | HybridSearchWeights | None = None,
    ) -> tuple[list[EvidenceCandidate], dict[str, Any]]:
        candidates: list[EvidenceCandidate] = []
        pass_traces: list[dict[str, Any]] = []
        seen_chunk_ids: set[str] = set()
        effective_search_weights = (
            HybridSearchWeights.model_validate(search_weights)
            if search_weights is not None
            else None
        )

        metadata_passes = self._metadata_passes(understanding)
        if self.parallel_search is None or len(metadata_passes) <= 1:
            for retrieval_pass in metadata_passes:
                pass_result = await self._run_one_pass(
                    query,
                    retrieval_pass=retrieval_pass,
                    document_ids=document_ids,
                    variant_id=variant_id,
                    limit=limit,
                    search=self.chunk_service.search,
                    search_weights=effective_search_weights,
                )
                if self._append_pass_result(
                    pass_result,
                    candidates=candidates,
                    pass_traces=pass_traces,
                    seen_chunk_ids=seen_chunk_ids,
                ):
                    break
            return candidates, {"stage": "metadata_retrieval", "passes": pass_traces}

        pass_results = await self._run_metadata_passes(
            query,
            retrieval_passes=metadata_passes,
            document_ids=document_ids,
            variant_id=variant_id,
            limit=limit,
            search_weights=effective_search_weights,
        )
        for pass_result in pass_results:
            if self._append_pass_result(
                pass_result,
                candidates=candidates,
                pass_traces=pass_traces,
                seen_chunk_ids=seen_chunk_ids,
            ):
                break

        return candidates, {"stage": "metadata_retrieval", "passes": pass_traces}

    async def _run_metadata_passes(
        self,
        query: str,
        *,
        retrieval_passes: list[RetrievalPass],
        document_ids: list[str],
        variant_id: str,
        limit: int,
        search_weights: HybridSearchWeights | None,
    ) -> list[MetadataPassResult]:
        semaphore = asyncio.Semaphore(self.max_parallel_passes)

        async def run_limited(retrieval_pass: RetrievalPass) -> MetadataPassResult:
            async with semaphore:
                return await self._run_one_pass(
                    query,
                    retrieval_pass=retrieval_pass,
                    document_ids=document_ids,
                    variant_id=variant_id,
                    limit=limit,
                    search=self.parallel_search,
                    search_weights=search_weights,
                )

        return list(await asyncio.gather(*(run_limited(item) for item in retrieval_passes)))

    def _append_pass_result(
        self,
        pass_result: MetadataPassResult,
        *,
        candidates: list[EvidenceCandidate],
        pass_traces: list[dict[str, Any]],
        seen_chunk_ids: set[str],
    ) -> bool:
        retrieval_pass = pass_result.retrieval_pass
        pass_candidates: list[EvidenceCandidate] = []
        for index, chunk in enumerate(pass_result.search.items, start=1):
            chunk_id = _chunk_id(chunk)
            if chunk_id in seen_chunk_ids:
                continue
            candidate = self._candidate_from_chunk(chunk, index, retrieval_pass)
            if candidate.retrieval_pass != "reference_hypothesis":
                seen_chunk_ids.add(chunk_id)
            pass_candidates.append(candidate)

        candidates.extend(pass_candidates)
        pass_traces.append(
            {
                "name": retrieval_pass.name,
                "query": pass_result.pass_query,
                "candidate_count": len(pass_candidates),
                "latency_ms": _elapsed_ms(pass_result.started_at),
                "top_candidate_ids": [
                    candidate.candidate_id for candidate in pass_candidates[:5]
                ],
            }
        )
        return _has_direct_evidence_candidates(retrieval_pass, pass_candidates)

    async def _run_one_pass(
        self,
        query: str,
        *,
        retrieval_pass: RetrievalPass,
        document_ids: list[str],
        variant_id: str,
        limit: int,
        search: MetadataSearch,
        search_weights: HybridSearchWeights | None = None,
    ) -> MetadataPassResult:
        pass_started = perf_counter()
        pass_query = retrieval_pass.query or query
        result = await search(
            ChunkSearchIn(
                query=pass_query,
                document_ids=document_ids,
                variant_id=variant_id,
                limit=max(limit * retrieval_pass.limit_multiplier, limit),
                explain=True,
                include_neighbors=True,
                search_weights=search_weights,
            )
        )
        return MetadataPassResult(
            retrieval_pass=retrieval_pass,
            pass_query=pass_query,
            started_at=pass_started,
            search=result,
        )

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
        if effective_pass == "reference_hypothesis":
            base_score = min(base_score, 1.0)
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
        if retrieval_pass.match_type == "hypothesis_reference":
            return "reference_hypothesis"
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
                "match_type": getattr(retrieval_pass, "match_type", None) or "transliteration",
            }
        if effective_pass == "reference_exact":
            return {"reference_exact": True, "reference": retrieval_pass.query}
        if effective_pass == "reference_hypothesis":
            return {
                "reference_hypothesis": True,
                "reference": retrieval_pass.query,
                "match_type": "hypothesis_reference",
            }
        if effective_pass == "phrase_exact":
            return {"target_phrase": retrieval_pass.query}
        if effective_pass == "title_count":
            return {"title_count": True}
        return {}

    def _first_reference(self, chunk: ChunkOut) -> str | None:
        source_reference = _chunk_source_location(chunk).get("reference")
        if isinstance(source_reference, str) and source_reference:
            return normalize_reference_hypothesis(source_reference) or source_reference
        reference_metadata = _chunk_metadata(chunk).get("reference_metadata")
        if not isinstance(reference_metadata, dict):
            return None
        references = reference_metadata.get("references")
        if isinstance(references, list) and references:
            reference = str(references[0])
            return normalize_reference_hypothesis(reference) or reference
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


def _has_direct_evidence_candidates(
    retrieval_pass: RetrievalPass,
    candidates: list[EvidenceCandidate],
) -> bool:
    if getattr(retrieval_pass, "match_type", None) == "hypothesis_reference":
        return False
    return (
        bool(getattr(retrieval_pass, "direct_evidence", False))
        and retrieval_pass.name in _METADATA_PASS_NAMES
        and any(candidate.retrieval_pass == retrieval_pass.name for candidate in candidates)
    )


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 3)
