from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any

from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.graph_expansion_service import GraphExpansionService
from ragstudio.services.reranker_service import RerankerService
from ragstudio.services.retrieval_evidence import (
    EvidenceCandidate,
    OrchestratedAnswer,
    fuse_candidates,
    plan_for_query,
)
from ragstudio.services.runtime_answer_service import RuntimeAnswerService


class NativeScopedQueryUnsupported(RuntimeError):
    pass


class NativeRuntimeQueryFailed(RuntimeError):
    def __init__(self, error: str, error_type: str | None, timings: dict[str, Any]):
        self.error = error
        self.error_type = error_type or "runtime_query_error"
        self.timings = timings
        super().__init__(error)


class RetrievalOrchestrator:
    def __init__(
        self,
        *,
        chunk_service: ChunkService,
        answer_service: RuntimeAnswerService | None = None,
        reranker_service: RerankerService | None = None,
        graph_expansion_service: GraphExpansionService | None = None,
    ):
        self.chunk_service = chunk_service
        self.answer_service = answer_service or RuntimeAnswerService()
        self.reranker_service = reranker_service or RerankerService()
        self.graph_expansion_service = graph_expansion_service or GraphExpansionService()

    async def query(
        self,
        query: str,
        *,
        runtime: Any,
        profile: Any,
        document_ids: list[str],
        variant_id: str,
        query_config: dict[str, Any],
    ) -> OrchestratedAnswer:
        started = perf_counter()
        limit = int(query_config.get("limit") or 8)
        plan = plan_for_query(query, document_ids=document_ids, limit=limit)
        traces: list[dict[str, Any]] = [
            {
                "stage": "planner",
                "intent": plan.intent,
                "tools": ["native", "metadata", "graph"],
                "candidate_limit": plan.candidate_limit,
            }
        ]

        native_task = self._native_candidates(query, runtime, document_ids, query_config)
        metadata_task = self._metadata_candidates(
            query,
            document_ids,
            variant_id,
            plan.candidate_limit,
        )
        try:
            native_candidates, metadata_candidates = await asyncio.gather(
                native_task,
                metadata_task,
            )
        except NativeRuntimeQueryFailed as exc:
            return OrchestratedAnswer(
                answer="",
                sources=[],
                chunk_traces=[],
                reranker_traces=[],
                timings={**exc.timings, "total_ms": _elapsed_ms(started)},
                error=exc.error,
                error_type=exc.error_type,
            )

        traces.append(
            {
                "stage": "retrieval",
                "native_candidates": len(native_candidates),
                "metadata_candidates": len(metadata_candidates),
            }
        )

        seed_candidates = fuse_candidates(plan, [*native_candidates, *metadata_candidates])
        graph_candidates, graph_traces = await self.graph_expansion_service.expand(
            query,
            seeds=seed_candidates[:limit],
            profile=profile,
            document_ids=document_ids,
            limit=limit,
        )
        traces.extend(graph_traces)

        fused = fuse_candidates(plan, [*native_candidates, *metadata_candidates, *graph_candidates])
        reranker_traces: list[dict[str, Any]] = []
        reranked = fused
        if getattr(profile, "enable_rerank", False):
            reranked, reranker_traces = await self._rerank(query, fused, profile)

        final_evidence = reranked[:limit]
        traces.extend(candidate.to_trace() for candidate in final_evidence)
        answer_started = perf_counter()
        answer, token_metadata = await self.answer_service.answer(query, final_evidence, profile)
        return OrchestratedAnswer(
            answer=answer,
            sources=[candidate.to_source() for candidate in final_evidence],
            chunk_traces=traces,
            reranker_traces=reranker_traces,
            timings={
                "orchestrated_query": True,
                "answer_ms": _elapsed_ms(answer_started),
                "total_ms": _elapsed_ms(started),
            },
            token_metadata=token_metadata,
        )

    async def _native_candidates(
        self,
        query: str,
        runtime: Any,
        document_ids: list[str],
        query_config: dict[str, Any],
    ) -> list[EvidenceCandidate]:
        result = await runtime.query(query, document_ids=document_ids, query_config=query_config)
        if getattr(result, "error_type", None) == "native_document_scope_unsupported":
            raise NativeScopedQueryUnsupported(getattr(result, "error", None) or "")
        if getattr(result, "error", None):
            raise NativeRuntimeQueryFailed(
                str(result.error),
                getattr(result, "error_type", None),
                getattr(result, "timings", None) or {},
            )
        candidates = []
        for index, source in enumerate(result.sources or [], start=1):
            if not isinstance(source, dict):
                continue
            candidates.append(
                EvidenceCandidate(
                    candidate_id=f"native:{source.get('chunk_id') or index}",
                    text=str(source.get("text") or ""),
                    document_id=_str_or_none(source.get("document_id")),
                    chunk_id=_str_or_none(source.get("chunk_id")),
                    source_location=_dict_or_empty(source.get("source_location")),
                    metadata=_dict_or_empty(source.get("metadata")),
                    tool="native",
                    tool_rank=index,
                    base_score=max(1.0, 20.0 - index),
                )
            )
        return [candidate for candidate in candidates if candidate.text.strip()]

    async def _metadata_candidates(
        self,
        query: str,
        document_ids: list[str],
        variant_id: str,
        limit: int,
    ) -> list[EvidenceCandidate]:
        search = await self.chunk_service.search(
            ChunkSearchIn(
                query=query,
                document_ids=document_ids,
                variant_id=variant_id,
                limit=limit,
                explain=True,
                include_neighbors=True,
            )
        )
        return [
            self._candidate_from_chunk(chunk, index)
            for index, chunk in enumerate(search.items, start=1)
        ]

    def _candidate_from_chunk(self, chunk: ChunkOut, rank: int) -> EvidenceCandidate:
        score = chunk.metadata.get("score")
        base_score = float(score) if isinstance(score, (int, float)) else max(1.0, 20.0 - rank)
        return EvidenceCandidate(
            candidate_id=f"metadata:{chunk.id}",
            text=chunk.text,
            document_id=chunk.document_id,
            chunk_id=chunk.id,
            source_location=chunk.source_location,
            metadata=chunk.metadata,
            tool="metadata",
            tool_rank=rank,
            base_score=base_score,
        )

    async def _rerank(
        self,
        query: str,
        candidates: list[EvidenceCandidate],
        profile: Any,
    ) -> tuple[list[EvidenceCandidate], list[dict[str, Any]]]:
        chunks = [
            ChunkOut(
                id=candidate.chunk_id or candidate.candidate_id,
                document_id=candidate.document_id or "",
                text=candidate.text,
                source_location=candidate.source_location,
                metadata=candidate.metadata,
            )
            for candidate in candidates
        ]
        reranked_chunks, traces = await self.reranker_service.rerank(query, chunks, profile)
        by_id = {chunk.id: index for index, chunk in enumerate(reranked_chunks)}
        return (
            sorted(
                candidates,
                key=lambda candidate: by_id.get(
                    candidate.chunk_id or candidate.candidate_id,
                    10_000,
                ),
            ),
            traces,
        )


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 3)
