from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, replace
from time import perf_counter
from typing import Any

import httpx
from ragstudio.schemas.chunks import ChunkOut
from ragstudio.services.arabic_text import arabic_tokens
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.context_assembly_service import ContextAssemblyService
from ragstudio.services.domain_metadata_quality_gate import DomainMetadataQualityGate
from ragstudio.services.domain_query_expansion_service import DomainQueryExpansionService
from ragstudio.services.evidence_first_answer_service import EvidenceFirstAnswerService
from ragstudio.services.graph_expansion_service import GraphExpansionService
from ragstudio.services.grounding_validator import GroundingValidator
from ragstudio.services.metadata_retrieval_service import MetadataRetrievalService
from ragstudio.services.query_hypothesis_service import (
    QueryHypothesis,
    QueryHypothesisService,
)
from ragstudio.services.query_hypothesis_verifier import (
    QueryHypothesisVerification,
    QueryHypothesisVerifier,
)
from ragstudio.services.reranker_service import RerankerService
from ragstudio.services.retrieval_evidence import (
    EvidenceCandidate,
    OrchestratedAnswer,
    apply_query_aware_ordering,
    fuse_candidates,
    plan_for_query,
)
from ragstudio.services.retrieval_fusion import RetrievalFusion
from ragstudio.services.retrieval_observability import RetrievalObservability
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


class _ProfileWithLlmTimeout:
    def __init__(self, profile: Any, llm_timeout_ms: int):
        self._profile = profile
        self.llm_timeout_ms = llm_timeout_ms

    def __getattr__(self, name: str) -> Any:
        return getattr(self._profile, name)


class RetrievalOrchestrator:
    def __init__(
        self,
        *,
        chunk_service: ChunkService,
        answer_service: RuntimeAnswerService | None = None,
        reranker_service: RerankerService | None = None,
        graph_expansion_service: GraphExpansionService | None = None,
        context_assembly_service: ContextAssemblyService | None = None,
        retrieval_fusion: RetrievalFusion | None = None,
        metadata_retrieval_service: MetadataRetrievalService | None = None,
        grounding_validator: GroundingValidator | None = None,
        evidence_first_answer_service: EvidenceFirstAnswerService | None = None,
        domain_query_expansion_service: DomainQueryExpansionService | None = None,
        query_hypothesis_service: QueryHypothesisService | None = None,
        query_hypothesis_verifier: QueryHypothesisVerifier | None = None,
    ):
        self.chunk_service = chunk_service
        self.answer_service = answer_service or RuntimeAnswerService()
        self.reranker_service = reranker_service or RerankerService()
        self.graph_expansion_service = graph_expansion_service or GraphExpansionService()
        self.context_assembly_service = context_assembly_service or ContextAssemblyService()
        self.retrieval_fusion = retrieval_fusion or RetrievalFusion()
        self.metadata_retrieval_service = (
            metadata_retrieval_service or MetadataRetrievalService(chunk_service)
        )
        self.grounding_validator = grounding_validator or GroundingValidator()
        self.evidence_first_answer_service = (
            evidence_first_answer_service or EvidenceFirstAnswerService()
        )
        self.domain_query_expansion_service = (
            domain_query_expansion_service or DomainQueryExpansionService()
        )
        self.query_hypothesis_service = query_hypothesis_service or QueryHypothesisService()
        self.query_hypothesis_verifier = query_hypothesis_verifier or QueryHypothesisVerifier()

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
        deadline_at = _deadline_at(started, query_config)
        if deadline_at is not None:
            timings["response_budget_ms"] = _response_budget_ms(query_config)
        domain_metadata = await self._domain_metadata_for_documents(document_ids)
        query_hypothesis = await self._safe_query_hypothesis(
            query,
            profile=profile,
            domain_metadata=domain_metadata,
            query_config=query_config,
            timings=timings,
            deadline_at=deadline_at,
        )
        domain_expansion = self.domain_query_expansion_service.expand(
            query,
            domain_metadata=domain_metadata,
            query_hypothesis=query_hypothesis,
        )
        plan = plan_for_query(
            query,
            document_ids=document_ids,
            limit=limit,
            domain_expansion=domain_expansion,
        )
        observability = RetrievalObservability()
        cache_decision = observability.cache_decision(
            query=query,
            document_ids=document_ids,
            query_type=_cache_query_type(query, plan.intent),
        )
        traces: list[dict[str, Any]] = [
            {
                "stage": "planner",
                "intent": plan.intent,
                "understanding_intent": plan.understanding.intent,
                "retrieval_strategy": plan.retrieval_strategy,
                "expanded_terms": list(plan.understanding.expanded_terms),
                "retrieval_passes": [
                    item.name for item in plan.understanding.retrieval_passes
                ],
                "query_hypothesis_status": (
                    "valid" if query_hypothesis.valid else "skipped"
                ),
                "tools": ["native", "metadata", "graph"],
                "candidate_limit": plan.candidate_limit,
                "cache": cache_decision,
            }
        ]
        traces.append(query_hypothesis.to_trace())
        if domain_expansion.expansions or domain_expansion.retrieval_passes:
            traces.append(dict(domain_expansion.trace))
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
                    deadline_at,
                )
            )
        except (NativeRuntimeQueryFailed, MetadataRetrievalFailed, ParallelRetrievalFailed) as exc:
            return self._failed_orchestrated_answer(exc, started, {**timings, **exc.timings})
        except Exception as exc:
            return self._failed_orchestrated_answer(exc, started, timings)

        traces.append(retrieval_trace)
        observability.record_stage(
            "primary_retrieval",
            candidate_count=len(native_candidates) + len(metadata_candidates),
            latency_ms=timings.get("native_stage_ms", 0.0) + timings.get("metadata_ms", 0.0),
            detail={
                "native_candidates": len(native_candidates),
                "metadata_candidates": len(metadata_candidates),
                "vector_candidates": _vector_candidate_count(native_candidates),
            },
        )
        traces.append(
            {
                "stage": "primary_retrieval",
                "native_candidates": len(native_candidates),
                "metadata_candidates": len(metadata_candidates),
                "vector_candidates": _vector_candidate_count(native_candidates),
            }
        )

        try:
            fuse_started = perf_counter()
            seed_candidates = fuse_candidates(plan, [*native_candidates, *metadata_candidates])
            timings["initial_fusion_ms"] = _elapsed_ms(fuse_started)
            seed_candidate_ids = [
                candidate.candidate_id for candidate in seed_candidates[:limit]
            ]
            observability.record_stage(
                "seed_fusion",
                candidate_count=len(seed_candidates),
                latency_ms=timings["initial_fusion_ms"],
                detail={
                    "seed_candidates": len(seed_candidates),
                    "seed_candidate_ids": seed_candidate_ids,
                },
            )
            traces.append(
                {
                    "stage": "seed_fusion",
                    "seed_candidates": len(seed_candidates),
                    "seed_candidate_ids": seed_candidate_ids,
                }
            )

            graph_candidates, graph_traces = await self._safe_graph_expansion(
                query,
                seeds=seed_candidates[:limit],
                profile=profile,
                document_ids=document_ids,
                limit=limit,
                enabled=bool(query_config.get("graph_expansion_enabled", True)),
                timings=timings,
                deadline_at=deadline_at,
            )
            traces.extend(graph_traces)
            graph_candidates, graph_hydration_traces = await self._hydrate_graph_candidates(
                graph_candidates,
                document_ids=document_ids,
                timings=timings,
            )
            traces.extend(graph_hydration_traces)

            refusion_started = perf_counter()
            legacy_fused = fuse_candidates(
                plan,
                [*native_candidates, *metadata_candidates, *graph_candidates],
            )
            fused = apply_query_aware_ordering(
                plan,
                self.retrieval_fusion.fuse([legacy_fused], limit=plan.candidate_limit),
            )
            timings["final_fusion_ms"] = _elapsed_ms(refusion_started)
            final_fusion_detail = {
                "native_candidates": len(native_candidates),
                "metadata_candidates": len(metadata_candidates),
                "graph_candidates": len(graph_candidates),
                "fused_candidates": len(fused),
            }
            traces.extend(
                [
                    {
                        "stage": "final_fusion",
                        "compat_stage": "retrieval_fusion",
                        **final_fusion_detail,
                    },
                    {
                        "stage": "retrieval_fusion",
                        "canonical_stage": "final_fusion",
                        **final_fusion_detail,
                    },
                ]
            )
            quality_diagnostics_trace = await self._quality_diagnostics_trace(
                query,
                document_ids,
                fused,
            )
            if quality_diagnostics_trace is not None:
                traces.append(quality_diagnostics_trace)
            observability.record_stage(
                "final_fusion",
                candidate_count=len(fused),
                latency_ms=timings["final_fusion_ms"],
                detail={"compat_stage": "retrieval_fusion"},
            )
            reranker_traces: list[dict[str, Any]] = []
            reranked = fused
            timings["rerank_ms"] = 0.0
            if getattr(profile, "enable_rerank", False) and bool(
                query_config.get("enable_rerank", True)
            ):
                rerank_started = perf_counter()
                reranked, reranker_traces = await self._rerank(query, fused, profile)
                timings["rerank_ms"] = _elapsed_ms(rerank_started)
            reranked, parser_quality_trace = _annotate_parser_quality_warnings(reranked)
            if parser_quality_trace is not None:
                traces.append(parser_quality_trace)

            context_started = perf_counter()
            context_service = self._context_assembly_service(profile)
            assembled_context = context_service.assemble(reranked)
            timings["context_assembly_ms"] = _elapsed_ms(context_started)
            final_evidence = _evidence_from_context(reranked, assembled_context)[:limit]
            if not final_evidence:
                final_evidence = reranked[:limit]
            hypothesis_verification = self.query_hypothesis_verifier.verify(
                query_hypothesis,
                final_evidence,
                document_ids=document_ids,
            )
            traces.append(hypothesis_verification.to_trace())
            observability.record_stage(
                "context_assembly",
                candidate_count=len(final_evidence),
                latency_ms=timings["context_assembly_ms"],
            )
            observability.record_final_evidence(
                [candidate.candidate_id for candidate in final_evidence],
                grounding_status=assembled_context.grounding_status,
            )
            traces.append(
                {
                    "stage": "context_assembly",
                    "included_candidates": len(assembled_context.evidence),
                    "dropped_candidates": len(assembled_context.dropped),
                    "assembled_context": {
                        "evidence_ids": [
                            item.candidate_id for item in assembled_context.evidence
                        ],
                        "dropped": [asdict(item) for item in assembled_context.dropped],
                        "total_estimated_tokens": assembled_context.total_estimated_tokens,
                        "grounding_status": assembled_context.grounding_status,
                    },
                    "retrieval_observability": observability.trace,
                }
            )
            traces.extend(candidate.to_trace() for candidate in final_evidence)
            answer, token_metadata = await self._answer_with_budget(
                query,
                final_evidence,
                profile,
                query_config=query_config,
                timings=timings,
                deadline_at=deadline_at,
                hypothesis_verification=hypothesis_verification,
            )
            expected_references = _expected_references(plan, hypothesis_verification)
            validation = self.grounding_validator.validate(
                answer=answer,
                evidence=final_evidence,
                expected_references=expected_references,
            )
            validation_trace = validation.to_trace()
            traces.append(validation_trace)
            timings["total_ms"] = _elapsed_ms(started)
            return OrchestratedAnswer(
                answer=answer,
                sources=[candidate.to_source() for candidate in final_evidence],
                chunk_traces=traces,
                reranker_traces=reranker_traces,
                timings=timings,
                token_metadata=token_metadata,
                validation=validation_trace,
            )
        except Exception as exc:
            return self._failed_orchestrated_answer(exc, started, timings)

    async def _answer_with_budget(
        self,
        query: str,
        evidence: list[EvidenceCandidate],
        profile: Any,
        *,
        query_config: dict[str, Any],
        timings: dict[str, Any],
        deadline_at: float | None,
        hypothesis_verification: QueryHypothesisVerification | None = None,
    ) -> tuple[str, dict[str, Any]]:
        answer_started = perf_counter()
        if hypothesis_verification is not None and hypothesis_verification.confirmed:
            answer, token_metadata = (
                self.evidence_first_answer_service.answer_confirmed_hypothesis(
                    query,
                    evidence,
                    verification=hypothesis_verification,
                )
            )
            timings["answer_ms"] = _elapsed_ms(answer_started)
            return answer, token_metadata

        response_mode = _response_mode(query_config)
        timeout_ms = int(
            _remaining_timeout_seconds(
                deadline_at,
                fallback_ms=_answer_budget_ms(query_config),
            )
            * 1000
        )
        answer_profile = _profile_with_llm_timeout(profile, timeout_ms)
        try:
            if response_mode == "fast":
                answer, token_metadata = await asyncio.wait_for(
                    self.answer_service.answer(query, evidence, answer_profile),
                    timeout=max(timeout_ms, 1) / 1000,
                )
            else:
                answer, token_metadata = await self.answer_service.answer(
                    query,
                    evidence,
                    answer_profile,
                )
            timings["answer_ms"] = _elapsed_ms(answer_started)
            return answer, {
                **token_metadata,
                "answer_mode": response_mode,
                "generated_without_llm": False,
            }
        except (TimeoutError, httpx.TimeoutException) as exc:
            if response_mode != "fast":
                raise
            timings["answer_ms"] = _elapsed_ms(answer_started)
            timings["answer_timeout_ms"] = timeout_ms
            timings["answer_fallback"] = True
            answer, token_metadata = self.evidence_first_answer_service.answer(
                query,
                evidence,
                reason="llm_timeout",
                llm_timeout_ms=timeout_ms,
            )
            return answer, {
                **token_metadata,
                "llm_answer_status": "timeout",
                "llm_error_type": exc.__class__.__name__,
            }

    async def _quality_diagnostics_trace(
        self,
        query: str,
        document_ids: list[str],
        candidates: list[EvidenceCandidate],
    ) -> dict[str, Any] | None:
        if candidates or not document_ids:
            return None
        query_script = _query_script(query)
        if query_script is None:
            return None
        lookup = getattr(self.chunk_service, "quality_reports_for_documents", None)
        if not callable(lookup):
            return None
        try:
            reports = await lookup(document_ids)
        except Exception as exc:
            return {
                "stage": "quality_diagnostics",
                "status": "failed",
                "reason": exc.__class__.__name__,
                "detail": str(exc),
            }
        return _quality_diagnostics_from_reports(
            reports,
            query_script=query_script,
            query=query,
        )

    def _context_assembly_service(self, profile: Any) -> ContextAssemblyService:
        max_context_tokens = getattr(profile, "max_context_tokens", None)
        if isinstance(max_context_tokens, int) and max_context_tokens > 0:
            return ContextAssemblyService(max_context_tokens=max_context_tokens)
        return self.context_assembly_service

    async def _domain_metadata_for_documents(
        self,
        document_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not document_ids:
            return []
        lookup = getattr(self.chunk_service, "domain_metadata_for_documents", None)
        if not callable(lookup):
            return []
        try:
            metadata = await lookup(document_ids)
        except Exception:
            return []
        if not isinstance(metadata, list):
            return []
        return [item for item in metadata if isinstance(item, dict)]

    async def _safe_query_hypothesis(
        self,
        query: str,
        *,
        profile: Any,
        domain_metadata: list[dict[str, Any]],
        query_config: dict[str, Any],
        timings: dict[str, Any],
        deadline_at: float | None,
    ) -> QueryHypothesis:
        hypothesis_started = perf_counter()
        if query_config.get("enable_query_hypothesis") is False:
            timings["query_hypothesis_ms"] = _elapsed_ms(hypothesis_started)
            timings["query_hypothesis_status"] = "skipped"
            return QueryHypothesis.empty(query, reason="disabled")

        fallback_ms = int(query_config.get("query_hypothesis_timeout_ms") or 650)
        timeout_ms = int(
            _remaining_timeout_seconds(deadline_at, fallback_ms=fallback_ms) * 1000
        )
        try:
            hypothesis = await asyncio.wait_for(
                self.query_hypothesis_service.hypothesize(
                    query,
                    profile=profile,
                    domain_metadata=domain_metadata,
                    timeout_ms=timeout_ms,
                ),
                timeout=max(timeout_ms, 1) / 1000,
            )
        except Exception as exc:
            hypothesis = QueryHypothesis.empty(
                query,
                reason=f"failed_{exc.__class__.__name__}",
            )
        timings["query_hypothesis_ms"] = _elapsed_ms(hypothesis_started)
        timings["query_hypothesis_status"] = "valid" if hypothesis.valid else "skipped"
        return hypothesis

    async def _parallel_retrieval(
        self,
        query: str,
        runtime: Any,
        document_ids: list[str],
        variant_id: str,
        query_config: dict[str, Any],
        plan: Any,
        timings: dict[str, Any],
        deadline_at: float | None,
    ) -> tuple[list[EvidenceCandidate], list[EvidenceCandidate], dict[str, Any]]:
        parallel_started = perf_counter()
        if document_ids:
            if _metadata_only(query_config):
                metadata_result = await self._timed_metadata_candidates_with_deadline(
                    query,
                    document_ids,
                    variant_id,
                    plan.candidate_limit,
                    plan,
                    deadline_at=deadline_at,
                )
                metadata_candidates, metadata_ms, metadata_trace = metadata_result
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
                        "metadata_trace": metadata_trace,
                    },
                )
            if _fast_mode(query_config):
                return await self._fast_parallel_retrieval(
                    query,
                    runtime,
                    document_ids,
                    variant_id,
                    query_config,
                    plan,
                    timings,
                    parallel_started,
                    deadline_at,
                )
            native_task = self._timed_native_candidates(query, runtime, document_ids, query_config)
            try:
                native_result = await native_task
            except Exception as exc:
                native_result = exc
            return await self._metadata_after_native_result(
                query,
                document_ids,
                variant_id,
                plan,
                timings,
                parallel_started,
                native_result,
                deadline_at,
            )

        native_task = self._timed_native_candidates(query, runtime, document_ids, query_config)
        metadata_task = self._timed_metadata_candidates(
            query,
            document_ids,
            variant_id,
            plan.candidate_limit,
            plan,
        )
        native_result, metadata_result = await asyncio.gather(
            native_task,
            metadata_task,
            return_exceptions=True,
        )
        return self._resolve_retrieval_results(
            native_result=native_result,
            metadata_result=metadata_result,
            plan=plan,
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
        deadline_at: float | None = None,
    ) -> tuple[list[EvidenceCandidate], list[EvidenceCandidate], dict[str, Any]]:
        try:
            metadata_result = await self._timed_metadata_candidates_with_deadline(
                query,
                document_ids,
                variant_id,
                plan.candidate_limit,
                plan,
                deadline_at=deadline_at,
            )
        except Exception as exc:
            metadata_result = exc
        return self._resolve_retrieval_results(
            native_result=native_result,
            metadata_result=metadata_result,
            plan=plan,
            timings=timings,
            parallel_started=parallel_started,
        )

    async def _fast_parallel_retrieval(
        self,
        query: str,
        runtime: Any,
        document_ids: list[str],
        variant_id: str,
        query_config: dict[str, Any],
        plan: Any,
        timings: dict[str, Any],
        parallel_started: float,
        deadline_at: float | None,
    ) -> tuple[list[EvidenceCandidate], list[EvidenceCandidate], dict[str, Any]]:
        native_task = asyncio.create_task(
            self._timed_native_candidates(query, runtime, document_ids, query_config)
        )
        try:
            metadata_result = await self._timed_metadata_candidates_with_deadline(
                query,
                document_ids,
                variant_id,
                plan.candidate_limit,
                plan,
                deadline_at=deadline_at,
            )
        except Exception as exc:
            metadata_result = exc
        timeout_ms = int(
            _remaining_timeout_seconds(
                deadline_at,
                fallback_ms=int(query_config.get("native_query_timeout_ms") or 2500),
            )
            * 1000
        )
        try:
            native_result = await asyncio.wait_for(
                native_task,
                timeout=max(timeout_ms, 1) / 1000,
            )
        except TimeoutError as exc:
            native_task.cancel()
            native_result = NativeRuntimeQueryFailed(
                f"Native query timed out after {timeout_ms} ms.",
                "native_query_timeout",
                {"native_stage_ms": _elapsed_ms(parallel_started)},
            )
            native_result.__cause__ = exc
        except Exception as exc:
            native_result = exc
        return self._resolve_retrieval_results(
            native_result=native_result,
            metadata_result=metadata_result,
            plan=plan,
            timings=timings,
            parallel_started=parallel_started,
        )

    async def _timed_metadata_candidates_with_deadline(
        self,
        query: str,
        document_ids: list[str],
        variant_id: str,
        limit: int,
        plan: Any,
        *,
        deadline_at: float | None,
    ) -> tuple[list[EvidenceCandidate], float, dict[str, Any]]:
        if deadline_at is None:
            return await self._timed_metadata_candidates(
                query,
                document_ids,
                variant_id,
                limit,
                plan,
            )
        return await asyncio.wait_for(
            self._timed_metadata_candidates(
                query,
                document_ids,
                variant_id,
                limit,
                plan,
            ),
            timeout=_remaining_timeout_seconds(deadline_at, fallback_ms=8000),
        )

    def _resolve_retrieval_results(
        self,
        *,
        native_result: Any,
        metadata_result: Any,
        plan: Any,
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
        metadata_candidates, metadata_ms, metadata_trace = metadata_result
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
                "metadata_trace": metadata_trace,
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
        enabled: bool,
        timings: dict[str, Any],
        deadline_at: float | None,
    ) -> tuple[list[EvidenceCandidate], list[dict[str, Any]]]:
        graph_started = perf_counter()
        if not enabled:
            timings["graph_ms"] = _elapsed_ms(graph_started)
            timings["graph_degraded"] = True
            timings["graph_error_type"] = "graph_projection_not_ready"
            return [], [
                {
                    "stage": "graph_expansion",
                    "status": "skipped",
                    "reason": "graph_projection_not_ready",
                }
            ]
        try:
            graph_candidates, graph_traces = await asyncio.wait_for(
                self.graph_expansion_service.expand(
                    query,
                    seeds=seeds,
                    profile=profile,
                    document_ids=document_ids,
                    limit=limit,
                ),
                timeout=_remaining_timeout_seconds(deadline_at, fallback_ms=1200),
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
            validation={},
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

        async def run_native_query() -> Any:
            preflight_fn = getattr(runtime, "preflight_scoped_retrieval", None)
            if document_ids and callable(preflight_fn):
                preflight = await preflight_fn(document_ids)
                native_timings["native_preflight"] = preflight
                if preflight.get("status") == "degraded":
                    raise NativeRuntimeQueryFailed(
                        str(
                            preflight.get("detail")
                            or "Native scoped retrieval preflight failed."
                        ),
                        str(preflight.get("error_type") or "native_preflight_failed"),
                        native_timings,
                    )
            return await runtime.query(
                query,
                document_ids=document_ids,
                query_config=query_config,
            )

        try:
            result = await asyncio.wait_for(
                run_native_query(),
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
        plan: Any | None = None,
    ) -> tuple[list[EvidenceCandidate], float, dict[str, Any]]:
        started = perf_counter()
        understanding = getattr(plan, "understanding", None)
        if understanding is None:
            understanding = plan_for_query(
                query,
                document_ids=document_ids,
                limit=limit,
            ).understanding
        candidates, trace = await self.metadata_retrieval_service.retrieve(
            query,
            understanding=understanding,
            document_ids=document_ids,
            variant_id=variant_id,
            limit=limit,
        )
        return candidates, _elapsed_ms(started), trace

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


def _fast_mode(query_config: dict[str, Any]) -> bool:
    return _response_mode(query_config) == "fast"


def _response_mode(query_config: dict[str, Any]) -> str:
    mode = str(query_config.get("response_mode") or "full").casefold()
    return mode if mode in {"fast", "full"} else "full"


def _response_budget_ms(query_config: dict[str, Any]) -> int:
    value = query_config.get("response_budget_ms")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 8000
    return min(max(parsed, 1), 120_000)


def _deadline_at(started: float, query_config: dict[str, Any]) -> float | None:
    if not _fast_mode(query_config):
        return None
    return started + (_response_budget_ms(query_config) / 1000)


def _remaining_timeout_seconds(deadline_at: float | None, *, fallback_ms: int) -> float:
    if deadline_at is None:
        return max(fallback_ms, 1) / 1000
    remaining = deadline_at - perf_counter()
    return max(min(remaining, max(fallback_ms, 1) / 1000), 0.001)


def _answer_budget_ms(query_config: dict[str, Any]) -> int:
    value = query_config.get("answer_budget_ms")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 1000
    return min(max(parsed, 1), 120_000)


def _profile_with_llm_timeout(profile: Any, timeout_ms: int) -> Any:
    return _ProfileWithLlmTimeout(profile, max(int(timeout_ms), 1))


def _expected_references(
    plan: Any,
    hypothesis_verification: QueryHypothesisVerification | None = None,
) -> set[str]:
    references: set[str] = set()
    if (
        hypothesis_verification is not None
        and hypothesis_verification.confirmed
        and hypothesis_verification.reference
    ):
        references.add(hypothesis_verification.reference)
    understanding = getattr(plan, "understanding", None)
    hints = getattr(understanding, "reference_hints", None)
    if not isinstance(hints, list):
        return references
    references.update(str(hint) for hint in hints if hint)
    return references


def _vector_candidate_count(candidates: list[EvidenceCandidate]) -> int:
    return sum(
        1
        for candidate in candidates
        if candidate.retrieval_pass in {"vector_db", "native_vector"}
        or candidate.tool in {"pgvector", "native"}
    )


def _cache_query_type(query: str, intent: str) -> str:
    stripped = query.strip()
    if intent == "reference":
        return "exact_reference"
    if stripped and len(stripped.split()) == 1 and _contains_arabic(stripped):
        return "exact_arabic_token"
    return "semantic_query"


def _contains_arabic(value: str) -> bool:
    return any("\u0600" <= character <= "\u06FF" for character in value)


def _query_script(query: str) -> str | None:
    if arabic_tokens(query) or _contains_arabic(query):
        return "arabic"
    return None


def _quality_diagnostics_from_reports(
    reports: list[dict[str, Any]],
    *,
    query_script: str,
    query: str,
) -> dict[str, Any] | None:
    reference_hints = _reference_hints(query)
    affected: list[str] = []
    document_summaries: list[dict[str, Any]] = []
    unknown_documents: list[str] = []

    for report in reports:
        if not isinstance(report, dict):
            continue
        document_id = report.get("document_id")
        status = report.get("status")
        if status == "quality_unknown":
            if isinstance(document_id, str):
                unknown_documents.append(document_id)
            document_summaries.append(
                {
                    "document_id": document_id,
                    "quality_status": "quality_unknown",
                    "quality_report_version": report.get("quality_report_version"),
                }
            )
            continue
        references = report.get("references")
        if not isinstance(references, list):
            continue
        document_affected = []
        for item in references:
            if not isinstance(item, dict):
                continue
            reference = item.get("reference")
            if not isinstance(reference, str) or not reference:
                continue
            if reference_hints and reference not in reference_hints:
                continue
            if not _reference_affects_script(item, query_script):
                continue
            document_affected.append(reference)
        if document_affected:
            affected.extend(document_affected)
            document_summaries.append(
                {
                    "document_id": document_id,
                    "quality_status": status,
                    "affected_references": document_affected[:5],
                    "summary": report.get("summary"),
                }
            )

    affected = list(dict.fromkeys(affected))[:5]
    if affected:
        return {
            "stage": "quality_diagnostics",
            "status": "warning",
            "quality_status": "missing_expected_script",
            "query_script": query_script,
            "message": (
                "Arabic content is missing for one or more expected reference units "
                "in this document."
            ),
            "affected_references": affected,
            "documents": document_summaries,
        }
    if unknown_documents:
        return {
            "stage": "quality_diagnostics",
            "status": "unknown",
            "quality_status": "quality_unknown",
            "query_script": query_script,
            "message": (
                "No reference-level index quality report is available for one or more "
                "selected documents."
            ),
            "quality_unknown_documents": unknown_documents,
            "documents": document_summaries,
        }
    return None


def _reference_affects_script(reference: dict[str, Any], query_script: str) -> bool:
    expected = reference.get("expected_scripts")
    if isinstance(expected, list) and query_script not in expected:
        return False
    missing = reference.get("missing_scripts")
    if isinstance(missing, list) and query_script in missing:
        return True
    materialization = reference.get("materialization")
    if isinstance(materialization, dict) and query_script == "arabic":
        return not bool(materialization.get("index_exact_arabic", True))
    return False


def _reference_hints(query: str) -> set[str]:
    return {
        re.sub(r"\s+", "", match)
        for match in re.findall(r"\b\d{1,4}\s*:\s*\d{1,4}\b", query)
    }


def _evidence_from_context(
    candidates: list[EvidenceCandidate],
    assembled_context: Any,
) -> list[EvidenceCandidate]:
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    ordered: list[EvidenceCandidate] = []
    for item in assembled_context.evidence:
        candidate = by_id.get(item.candidate_id)
        if candidate is not None:
            ordered.append(candidate)
    return ordered


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


def _annotate_parser_quality_warnings(
    candidates: list[EvidenceCandidate],
) -> tuple[list[EvidenceCandidate], dict[str, Any] | None]:
    annotated: list[EvidenceCandidate] = []
    warning_counts: dict[str, int] = {}
    affected_candidate_ids: list[str] = []
    quality_gate = DomainMetadataQualityGate()
    for candidate in candidates:
        codes = quality_gate.parser_warning_codes(candidate.metadata)
        if not codes:
            annotated.append(candidate)
            continue
        affected_candidate_ids.append(candidate.candidate_id)
        unique_codes = sorted(set(codes))
        for code in codes:
            warning_counts[code] = warning_counts.get(code, 0) + 1
        metadata = {
            **candidate.metadata,
            "parser_quality_warning_codes": unique_codes,
        }
        reasons = [
            *candidate.reasons,
            *(f"parser_quality_warning:{code}" for code in unique_codes),
        ]
        annotated.append(replace(candidate, metadata=metadata, reasons=reasons))
    return annotated, quality_gate.retrieval_trace(warning_counts, affected_candidate_ids)


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
