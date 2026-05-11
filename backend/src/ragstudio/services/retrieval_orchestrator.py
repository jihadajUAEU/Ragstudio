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


class NativeRuntimeQueryFailed(RuntimeError):
    def __init__(self, error: str, error_type: str | None, timings: dict[str, Any]):
        self.error = error
        self.error_type = error_type or "runtime_query_error"
        self.timings = timings
        super().__init__(error)


class MetadataRetrievalFailed(RuntimeError):
    def __init__(self, error: str, timings: dict[str, Any]):
        self.error = error
        self.error_type = "metadata_retrieval_error"
        self.timings = timings
        super().__init__(error)


class ParallelRetrievalFailed(RuntimeError):
    def __init__(
        self,
        *,
        error: str,
        error_type: str,
        timings: dict[str, Any],
    ):
        self.error = error
        self.error_type = error_type
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
        timings: dict[str, Any] = {"orchestrated_query": True}
        plan = plan_for_query(query, document_ids=document_ids, limit=limit)
        traces: list[dict[str, Any]] = [
            {
                "stage": "planner",
                "intent": plan.intent,
                "tools": ["native", "metadata", "graph"],
                "candidate_limit": plan.candidate_limit,
            }
        ]
        timings["planner_ms"] = _elapsed_ms(started)

        try:
            native_candidates, metadata_candidates, retrieval_trace = await (
                self._parallel_retrieval(
                query,
                runtime,
                document_ids,
                variant_id,
                query_config,
                plan,
                timings,
                )
            )
        except (NativeRuntimeQueryFailed, MetadataRetrievalFailed, ParallelRetrievalFailed) as exc:
            return self._failed_orchestrated_answer(exc, started, {**timings, **exc.timings})
        except Exception as exc:
            return self._failed_orchestrated_answer(exc, started, timings)

        traces.append(retrieval_trace)

        try:
            fuse_started = perf_counter()
            seed_candidates = fuse_candidates(plan, [*native_candidates, *metadata_candidates])
            timings["initial_fusion_ms"] = _elapsed_ms(fuse_started)

            graph_candidates, graph_traces = await self._safe_graph_expansion(
                query,
                seeds=seed_candidates[:limit],
                profile=profile,
                document_ids=document_ids,
                limit=limit,
                timings=timings,
            )
            traces.extend(graph_traces)
            graph_candidates, graph_hydration_traces = await self._hydrate_graph_candidates(
                graph_candidates,
                document_ids=document_ids,
                timings=timings,
            )
            traces.extend(graph_hydration_traces)

            refusion_started = perf_counter()
            fused = fuse_candidates(
                plan,
                [*native_candidates, *metadata_candidates, *graph_candidates],
            )
            timings["final_fusion_ms"] = _elapsed_ms(refusion_started)
            reranker_traces: list[dict[str, Any]] = []
            reranked = fused
            timings["rerank_ms"] = 0.0
            if getattr(profile, "enable_rerank", False):
                rerank_started = perf_counter()
                reranked, reranker_traces = await self._rerank(query, fused, profile)
                timings["rerank_ms"] = _elapsed_ms(rerank_started)

            final_evidence = reranked[:limit]
            traces.extend(candidate.to_trace() for candidate in final_evidence)
            answer_started = perf_counter()
            answer, token_metadata = await self.answer_service.answer(
                query,
                final_evidence,
                profile,
            )
            timings["answer_ms"] = _elapsed_ms(answer_started)
            timings["total_ms"] = _elapsed_ms(started)
            return OrchestratedAnswer(
                answer=answer,
                sources=[candidate.to_source() for candidate in final_evidence],
                chunk_traces=traces,
                reranker_traces=reranker_traces,
                timings=timings,
                token_metadata=token_metadata,
            )
        except Exception as exc:
            return self._failed_orchestrated_answer(exc, started, timings)

    async def _parallel_retrieval(
        self,
        query: str,
        runtime: Any,
        document_ids: list[str],
        variant_id: str,
        query_config: dict[str, Any],
        plan: Any,
        timings: dict[str, Any],
    ) -> tuple[list[EvidenceCandidate], list[EvidenceCandidate], dict[str, Any]]:
        parallel_started = perf_counter()
        if document_ids:
            if _metadata_only(query_config):
                metadata_candidates, metadata_ms = await self._timed_metadata_candidates(
                    query,
                    document_ids,
                    variant_id,
                    plan.candidate_limit,
                )
                timings["metadata_ms"] = metadata_ms
                timings["parallel_retrieval_ms"] = _elapsed_ms(parallel_started)
                return (
                    [],
                    metadata_candidates,
                    {
                        "stage": "retrieval",
                        "native_status": "skipped",
                        "native_candidates": 0,
                        "metadata_candidates": len(metadata_candidates),
                    },
                )
            native_task = self._timed_native_candidates(query, runtime, document_ids, query_config)
            try:
                native_result = await native_task
            except Exception as exc:
                native_result = exc
            if (
                isinstance(native_result, NativeRuntimeQueryFailed)
                and native_result.error_type == "native_document_scope_unsupported"
            ):
                native_timings = getattr(native_result, "timings", None)
                if isinstance(native_timings, dict):
                    timings.update(native_timings)
                timings["parallel_retrieval_ms"] = _elapsed_ms(parallel_started)
                raise native_result
            return await self._metadata_after_native_result(
                query,
                document_ids,
                variant_id,
                plan,
                timings,
                parallel_started,
                native_result,
            )

        native_task = self._timed_native_candidates(query, runtime, document_ids, query_config)
        metadata_task = self._timed_metadata_candidates(
            query,
            document_ids,
            variant_id,
            plan.candidate_limit,
        )
        native_result, metadata_result = await asyncio.gather(
            native_task,
            metadata_task,
            return_exceptions=True,
        )
        return self._resolve_retrieval_results(
            native_result=native_result,
            metadata_result=metadata_result,
            timings=timings,
            parallel_started=parallel_started,
        )

    async def _metadata_after_native_result(
        self,
        query: str,
        document_ids: list[str],
        variant_id: str,
        plan: Any,
        timings: dict[str, Any],
        parallel_started: float,
        native_result: Any,
    ) -> tuple[list[EvidenceCandidate], list[EvidenceCandidate], dict[str, Any]]:
        try:
            metadata_result = await self._timed_metadata_candidates(
                query,
                document_ids,
                variant_id,
                plan.candidate_limit,
            )
        except Exception as exc:
            metadata_result = exc
        return self._resolve_retrieval_results(
            native_result=native_result,
            metadata_result=metadata_result,
            timings=timings,
            parallel_started=parallel_started,
        )

    def _resolve_retrieval_results(
        self,
        *,
        native_result: Any,
        metadata_result: Any,
        timings: dict[str, Any],
        parallel_started: float,
    ) -> tuple[list[EvidenceCandidate], list[EvidenceCandidate], dict[str, Any]]:

        if not isinstance(native_result, Exception):
            _, native_timings = native_result
            timings.update(native_timings)

        metadata_candidates: list[EvidenceCandidate] = []
        if isinstance(metadata_result, Exception):
            if not isinstance(metadata_result, asyncio.CancelledError):
                timings["parallel_retrieval_ms"] = _elapsed_ms(parallel_started)
            if isinstance(native_result, Exception):
                raise self._parallel_retrieval_failed(
                    native_result=native_result,
                    metadata_result=metadata_result,
                    timings=timings,
                ) from metadata_result
            raise MetadataRetrievalFailed(str(metadata_result), dict(timings)) from metadata_result
        metadata_candidates, metadata_ms = metadata_result
        timings["metadata_ms"] = metadata_ms
        timings["parallel_retrieval_ms"] = _elapsed_ms(parallel_started)

        native_candidates: list[EvidenceCandidate] = []
        native_status = "ok"
        if isinstance(native_result, Exception):
            native_status = "degraded"
            if isinstance(native_result, NativeRuntimeQueryFailed):
                timings.update(native_result.timings)
                timings["native_error_type"] = native_result.error_type
                timings["native_error"] = native_result.error
            else:
                timings["native_error_type"] = native_result.__class__.__name__
                timings["native_error"] = str(native_result)
            timings["native_degraded"] = True
            native_candidates = []
        else:
            native_candidates, _native_timings = native_result

        return (
            native_candidates,
            metadata_candidates,
            {
                "stage": "retrieval",
                "native_status": native_status,
                "native_candidates": len(native_candidates),
                "metadata_candidates": len(metadata_candidates),
            },
        )

    async def _safe_graph_expansion(
        self,
        query: str,
        *,
        seeds: list[EvidenceCandidate],
        profile: Any,
        document_ids: list[str],
        limit: int,
        timings: dict[str, Any],
    ) -> tuple[list[EvidenceCandidate], list[dict[str, Any]]]:
        graph_started = perf_counter()
        try:
            graph_candidates, graph_traces = await self.graph_expansion_service.expand(
                query,
                seeds=seeds,
                profile=profile,
                document_ids=document_ids,
                limit=limit,
            )
            timings["graph_ms"] = _elapsed_ms(graph_started)
            if _graph_degraded(graph_traces):
                timings["graph_degraded"] = True
                timings["graph_error_type"] = _graph_degradation_reason(graph_traces)
            return graph_candidates, graph_traces
        except Exception as exc:
            timings["graph_ms"] = _elapsed_ms(graph_started)
            timings["graph_degraded"] = True
            timings["graph_error_type"] = exc.__class__.__name__
            return [], [
                {
                    "stage": "graph_expansion",
                    "status": "failed",
                    "reason": exc.__class__.__name__,
                    "detail": str(exc),
                }
            ]

    def _parallel_retrieval_failed(
        self,
        *,
        native_result: Exception,
        metadata_result: Exception,
        timings: dict[str, Any],
    ) -> ParallelRetrievalFailed:
        native_timings = getattr(native_result, "timings", None)
        timing_details = native_timings if isinstance(native_timings, dict) else {}
        combined_timings = {**timings, **timing_details}
        native_error = getattr(native_result, "error", None)
        native_error_type = (
            getattr(native_result, "error_type", None)
            or native_result.__class__.__name__
        )
        return ParallelRetrievalFailed(
            error=(
                "Parallel retrieval failed: "
                f"native={native_error or str(native_result)}; "
                f"metadata={metadata_result}"
            ),
            error_type="parallel_retrieval_failed",
            timings={
                **combined_timings,
                "native_error_type": native_error_type,
                "metadata_error_type": metadata_result.__class__.__name__,
            },
        )

    def _failed_orchestrated_answer(
        self,
        exc: Exception,
        started: float,
        timings: dict[str, Any],
    ) -> OrchestratedAnswer:
        failure_timings = {**timings, "total_ms": _elapsed_ms(started)}
        error = str(exc)
        error_type = getattr(exc, "error_type", None) or exc.__class__.__name__
        return OrchestratedAnswer(
            answer="",
            sources=[],
            chunk_traces=[],
            reranker_traces=[],
            timings=failure_timings,
            error=error,
            error_type=error_type,
        )

    async def _timed_native_candidates(
        self,
        query: str,
        runtime: Any,
        document_ids: list[str],
        query_config: dict[str, Any],
    ) -> tuple[list[EvidenceCandidate], dict[str, Any]]:
        started = perf_counter()
        timeout_ms = int(query_config.get("native_query_timeout_ms") or 15_000)
        native_timings = {"native_stage_ms": _elapsed_ms(started)}
        try:
            result = await asyncio.wait_for(
                runtime.query(query, document_ids=document_ids, query_config=query_config),
                timeout=max(timeout_ms, 1) / 1000,
            )
        except TimeoutError as exc:
            native_timings["native_stage_ms"] = _elapsed_ms(started)
            raise NativeRuntimeQueryFailed(
                f"Native query timed out after {timeout_ms} ms.",
                "native_query_timeout",
                native_timings,
            ) from exc
        result_timings = getattr(result, "timings", None)
        if isinstance(result_timings, dict):
            native_timings.update(result_timings)
        error_type = getattr(result, "error_type", None)
        error = getattr(result, "error", None)
        if error or error_type == "native_document_scope_unsupported":
            raise NativeRuntimeQueryFailed(
                str(error or ""),
                error_type,
                native_timings,
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
        return [candidate for candidate in candidates if candidate.text.strip()], native_timings

    async def _timed_metadata_candidates(
        self,
        query: str,
        document_ids: list[str],
        variant_id: str,
        limit: int,
    ) -> tuple[list[EvidenceCandidate], float]:
        started = perf_counter()
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
        return (
            [
                self._candidate_from_chunk(chunk, index)
                for index, chunk in enumerate(search.items, start=1)
            ],
            _elapsed_ms(started),
        )

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

    async def _hydrate_graph_candidates(
        self,
        candidates: list[EvidenceCandidate],
        *,
        document_ids: list[str],
        timings: dict[str, Any],
    ) -> tuple[list[EvidenceCandidate], list[dict[str, Any]]]:
        hydration_started = perf_counter()
        chunk_lookup = getattr(self.chunk_service, "chunks_by_id", None)
        if chunk_lookup is None:
            timings["graph_hydration_ms"] = _elapsed_ms(hydration_started)
            return [], [
                {
                    "stage": "graph_hydration",
                    "status": "skipped",
                    "reason": "chunk_lookup_unavailable",
                    "input_candidates": len(candidates),
                }
            ]

        chunk_ids = [
            chunk_id
            for candidate in candidates
            if (chunk_id := _graph_candidate_chunk_id(candidate)) is not None
        ]
        if not chunk_ids:
            timings["graph_hydration_ms"] = _elapsed_ms(hydration_started)
            return [], [
                {
                    "stage": "graph_hydration",
                    "status": "skipped",
                    "reason": "no_chunk_ids",
                    "input_candidates": len(candidates),
                }
            ]

        try:
            hydrated_chunks = await chunk_lookup(chunk_ids)
        except Exception as exc:
            timings["graph_hydration_ms"] = _elapsed_ms(hydration_started)
            timings["graph_hydration_degraded"] = True
            timings["graph_hydration_error_type"] = exc.__class__.__name__
            return [], [
                {
                    "stage": "graph_hydration",
                    "status": "failed",
                    "reason": exc.__class__.__name__,
                    "detail": str(exc),
                    "input_candidates": len(candidates),
                }
            ]

        chunks_by_id = {chunk.id: chunk for chunk in hydrated_chunks}
        allowed_document_ids = set(document_ids)
        hydrated: list[EvidenceCandidate] = []
        missing_count = 0
        dropped_preview_count = 0
        scope_mismatch_count = 0
        for candidate in candidates:
            chunk_id = _graph_candidate_chunk_id(candidate)
            chunk = chunks_by_id.get(chunk_id or "")
            if chunk is None:
                missing_count += 1 if chunk_id else 0
                dropped_preview_count += 1
                continue
            if allowed_document_ids and chunk.document_id not in allowed_document_ids:
                scope_mismatch_count += 1
                continue
            hydrated.append(_hydrated_graph_candidate(candidate, chunk))

        timings["graph_hydration_ms"] = _elapsed_ms(hydration_started)
        return hydrated, [
            {
                "stage": "graph_hydration",
                "status": "ok",
                "input_candidates": len(candidates),
                "hydrated_candidates": len(hydrated),
                "unique_hydrated_chunks": len(chunks_by_id),
                "missing_candidates": missing_count,
                "scope_mismatch_candidates": scope_mismatch_count,
                "dropped_preview_candidates": dropped_preview_count,
            }
        ]

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


def _metadata_only(query_config: dict[str, Any]) -> bool:
    retrieval_mode = str(query_config.get("retrieval_mode") or "").casefold()
    reference_mode = str(query_config.get("reference_query_mode") or "").casefold()
    return retrieval_mode == "metadata" or reference_mode in {"exact", "lexical"}


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _graph_candidate_chunk_id(candidate: EvidenceCandidate) -> str | None:
    chunk_id = candidate.chunk_id
    if not isinstance(chunk_id, str) or not chunk_id:
        return None
    if chunk_id.startswith("ref:"):
        return None
    if chunk_id.startswith("chunk:"):
        parts = chunk_id.split(":")
        if len(parts) >= 3 and parts[-1]:
            return parts[-1]
        return None
    return chunk_id


def _hydrated_graph_candidate(
    candidate: EvidenceCandidate,
    chunk: ChunkOut,
) -> EvidenceCandidate:
    return EvidenceCandidate(
        candidate_id=f"graph:{chunk.id}",
        text=chunk.text,
        document_id=chunk.document_id,
        chunk_id=chunk.id,
        source_location=chunk.source_location,
        metadata={
            **chunk.metadata,
            **candidate.metadata,
            "graph_hydration": {
                "status": "hydrated",
                "original_candidate_id": candidate.candidate_id,
            },
        },
        tool="graph",
        tool_rank=candidate.tool_rank,
        base_score=candidate.base_score,
        boost_score=candidate.boost_score + 1.0,
        final_score=candidate.final_score,
        reasons=[*candidate.reasons, "graph_hydrated_chunk"],
    )


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 3)


def _is_native_document_scope_unsupported(value: Any) -> bool:
    return (
        isinstance(value, NativeRuntimeQueryFailed)
        and value.error_type == "native_document_scope_unsupported"
    )


def _graph_degraded(graph_traces: list[dict[str, Any]]) -> bool:
    return any(
        trace.get("stage") == "graph_expansion"
        and trace.get("status") in {"failed", "skipped"}
        and trace.get("reason") not in {None, "", "no_seed_ids"}
        for trace in graph_traces
        if isinstance(trace, dict)
    )


def _graph_degradation_reason(graph_traces: list[dict[str, Any]]) -> str:
    for trace in graph_traces:
        if not isinstance(trace, dict):
            continue
        if (
            trace.get("stage") == "graph_expansion"
            and trace.get("status") in {"failed", "skipped"}
            and trace.get("reason") not in {None, "", "no_seed_ids"}
        ):
            reason = trace.get("reason")
            if isinstance(reason, str) and reason:
                return reason
    return "graph_degraded"
