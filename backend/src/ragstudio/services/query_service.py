from pathlib import Path
from time import perf_counter
from typing import Any

from ragstudio.config import AppSettings
from ragstudio.db.models import Document, GraphProjectionRecord, IndexRecord, Run, Variant
from ragstudio.schemas.chunks import ChunkSearchIn
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.query import QueryIn, QueryOut, SimulateRetrievalIn, SimulateRetrievalOut
from ragstudio.schemas.runs import RunOut
from ragstudio.schemas.runtime import RuntimeHealthCheck
from ragstudio.services.adapter import RAGAnythingAdapter
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.index_progress import index_shape_compatible
from ragstudio.services.query_pathway_diagnostics_service import (
    QueryPathwayDiagnosticsService,
)
from ragstudio.services.reranker_service import RerankerService
from ragstudio.services.retrieval_orchestrator import RetrievalOrchestrator
from ragstudio.services.runtime_factory import RAGAnythingRuntimeFactory
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_profile_service import (
    RuntimeProfileNotConfiguredError,
    RuntimeProfileService,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


class QueryResourceNotFoundError(LookupError):
    def __init__(self, resource: str, missing_ids: list[str]):
        self.resource = resource
        self.missing_ids = missing_ids
        super().__init__(f"{resource} not found: {', '.join(missing_ids)}")


class QueryRuntimeReadinessError(RuntimeError):
    def __init__(
        self,
        checks: list[RuntimeHealthCheck],
        *,
        error_type: str = "runtime_health_blocked",
        runtime_profile_id: str | None = None,
    ):
        self.checks = checks
        self.error_type = error_type
        self.runtime_profile_id = runtime_profile_id
        super().__init__(QueryService.runtime_failure_detail(checks))


class QueryService:
    def __init__(
        self,
        session: AsyncSession,
        data_dir: Path,
        adapter: RAGAnythingAdapter | None = None,
        *,
        settings: AppSettings | None = None,
        runtime_factory: Any | None = None,
        health_service: Any | None = None,
        reranker_service: RerankerService | None = None,
        retrieval_orchestrator: RetrievalOrchestrator | None = None,
    ):
        self.session = session
        self.data_dir = data_dir
        self.adapter = adapter or RAGAnythingAdapter()
        self.settings = settings
        self.runtime_factory = runtime_factory or RAGAnythingRuntimeFactory(settings)
        self.health_service = health_service or RuntimeHealthService(
            session,
            verify_storage=True,
        )
        self.reranker_service = reranker_service or RerankerService(
            allowed_hosts=settings.allowed_reranker_hosts if settings else None
        )
        self.retrieval_orchestrator = retrieval_orchestrator

    async def run_query(self, payload: QueryIn) -> QueryOut:
        await self._validate_query_inputs(payload)
        if self.settings is not None:
            try:
                profile = await RuntimeProfileService(
                    self.session,
                    self.settings,
                ).get_active_profile()
            except RuntimeProfileNotConfiguredError as exc:
                return await self._failed_runtime_runs(
                    payload,
                    None,
                    self._runtime_profile_missing_checks(str(exc)),
                    error_type="runtime_profile_missing",
                )
            if profile.runtime_mode != "runtime":
                return await self._failed_runtime_runs(
                    payload,
                    profile.id,
                    self._inactive_runtime_mode_checks(profile.runtime_mode),
                    error_type="runtime_mode_inactive",
                )
            return await self._run_runtime_query(payload, profile)

        return await self._failed_runtime_runs(
            payload,
            None,
            self._runtime_profile_settings_missing_checks(),
            error_type="runtime_profile_missing",
        )

    async def preflight_runtime_readiness(
        self,
        payload: QueryIn,
        *,
        validate_index_readiness: bool = True,
    ) -> None:
        await self._validate_query_inputs(payload)
        if self.settings is None:
            raise QueryRuntimeReadinessError(
                self._runtime_profile_settings_missing_checks(),
                error_type="runtime_profile_missing",
            )
        try:
            profile = await RuntimeProfileService(
                self.session,
                self.settings,
            ).get_active_profile()
        except RuntimeProfileNotConfiguredError as exc:
            raise QueryRuntimeReadinessError(
                self._runtime_profile_missing_checks(str(exc)),
                error_type="runtime_profile_missing",
            ) from exc
        if profile.runtime_mode != "runtime":
            raise QueryRuntimeReadinessError(
                self._inactive_runtime_mode_checks(profile.runtime_mode),
                error_type="runtime_mode_inactive",
                runtime_profile_id=profile.id,
            )
        checks = await self.health_service.check(profile)
        blocking = self.health_service.blocking_failures(checks)
        if blocking:
            raise QueryRuntimeReadinessError(
                blocking,
                runtime_profile_id=profile.id,
            )
        if validate_index_readiness:
            await self._validate_index_readiness(
                payload.document_ids,
                profile.id,
                profile.index_shape,
            )

    async def list_runs(self) -> list[RunOut]:
        result = await self.session.execute(select(Run).order_by(Run.created_at.desc()))
        return [self._run_out(item) for item in result.scalars().all()]

    async def simulate_retrieval(self, payload: SimulateRetrievalIn) -> SimulateRetrievalOut:
        await self._validate_simulation_inputs(payload)
        result = await ChunkService(self.session, self.data_dir, self.adapter).search(
            ChunkSearchIn(
                query=payload.query,
                document_ids=payload.document_ids,
                variant_id=payload.variant_ids[0] if payload.variant_ids else None,
                limit=payload.limit,
                explain=True,
                include_neighbors=True,
                search_weights=payload.search_weights,
            )
        )
        return SimulateRetrievalOut(items=result.items, total=result.total)

    async def _run_runtime_query(self, payload: QueryIn, profile: Any) -> QueryOut:
        checks = await self.health_service.check(profile)
        blocking = self.health_service.blocking_failures(checks)
        if blocking:
            return await self._failed_runtime_runs(payload, profile.id, blocking)
        index_degradation = await self._index_degradation(
            payload.document_ids,
            profile.id,
            profile.index_shape,
        )
        graph_degradation = await self._graph_degradation(payload.document_ids, profile.id)

        variants = await self._variants_by_id(payload.variant_ids)
        document_labels = await self._document_labels(payload.document_ids)
        runs: list[Run] = []
        for variant_id in payload.variant_ids:
            variant = variants[variant_id]
            started_at = perf_counter()
            query_config = self._query_config(profile, variant, payload)
            if index_degradation:
                query_config = {**query_config, "retrieval_mode": "metadata"}
            if graph_degradation:
                query_config = {**query_config, "graph_expansion_enabled": False}
            run = Run(
                variant_id=variant_id,
                query=payload.query,
                status=StageStatus.RUNNING.value,
                runtime_profile_id=profile.id,
                document_ids=payload.document_ids,
                query_config=query_config,
            )
            self.session.add(run)
            try:
                runtime = self.runtime_factory.build(profile)
                orchestrated = await self._retrieval_orchestrator().query(
                    payload.query,
                    runtime=runtime,
                    profile=profile,
                    document_ids=payload.document_ids,
                    variant_id=variant_id,
                    query_config=query_config,
                )
                has_orchestrated_error = bool(orchestrated.error or orchestrated.error_type)
                run.status = (
                    StageStatus.FAILED.value
                    if has_orchestrated_error
                    else StageStatus.SUCCEEDED.value
                )
                run.answer = orchestrated.answer
                run.sources = self._enriched_sources(
                    orchestrated.sources,
                    document_labels=document_labels,
                    runtime_profile_id=profile.id,
                )
                run.chunk_traces = orchestrated.chunk_traces
                run.reranker_traces = orchestrated.reranker_traces
                run.token_metadata = orchestrated.token_metadata
                run.error = orchestrated.error or orchestrated.error_type
                run.error_type = orchestrated.error_type
                run.timings = {
                    **orchestrated.timings,
                    **(index_degradation or {}),
                    **(graph_degradation or {}),
                    "total_ms": self._elapsed_ms(started_at),
                }
            except Exception as exc:
                run.status = StageStatus.FAILED.value
                run.error = str(exc)
                run.error_type = exc.__class__.__name__
                run.timings = {"total_ms": self._elapsed_ms(started_at)}

            runs.append(await self._commit_query_run(run))
        return QueryOut(runs=[self._run_out(run) for run in runs])

    async def _commit_query_run(self, run: Run) -> Run:
        snapshot = self._run_snapshot(run)
        try:
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            recovered = Run(**snapshot)
            self.session.add(recovered)
            await self.session.commit()
            run = recovered
        await self.session.refresh(run)
        return run

    def _run_snapshot(self, run: Run) -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "variant_id": run.variant_id,
            "experiment_id": run.experiment_id,
            "runtime_profile_id": run.runtime_profile_id,
            "query": run.query,
            "status": run.status,
            "answer": run.answer,
            "document_ids": list(run.document_ids or []),
            "query_config": dict(run.query_config or {}),
            "sources": list(run.sources or []),
            "chunk_traces": list(run.chunk_traces or []),
            "reranker_traces": list(run.reranker_traces or []),
            "timings": dict(run.timings or {}),
            "token_metadata": dict(run.token_metadata or {}),
            "error": run.error,
            "error_type": run.error_type,
        }
        if run.id:
            snapshot["id"] = run.id
        return snapshot

    def _run_out(self, run: Run) -> RunOut:
        sources = list(run.sources or [])
        chunk_traces = list(run.chunk_traces or [])
        timings = dict(run.timings or {})
        token_metadata = dict(run.token_metadata or {})
        query_config = dict(run.query_config or {})
        return RunOut.model_validate(
            {
                "id": run.id,
                "variant_id": run.variant_id,
                "experiment_id": run.experiment_id,
                "query": run.query,
                "status": run.status,
                "answer": run.answer,
                "sources": sources,
                "chunk_traces": chunk_traces,
                "timings": timings,
                "error": run.error,
                "runtime_profile_id": run.runtime_profile_id,
                "document_ids": list(run.document_ids or []),
                "query_config": query_config,
                "reranker_traces": list(run.reranker_traces or []),
                "token_metadata": token_metadata,
                "error_type": run.error_type,
                "pathway_diagnostics": QueryPathwayDiagnosticsService().build(
                    status=str(run.status or ""),
                    error=run.error,
                    error_type=run.error_type,
                    timings=timings,
                    chunk_traces=chunk_traces,
                    sources=sources,
                    token_metadata=token_metadata,
                    query_config=query_config,
                ),
            }
        )

    def _retrieval_orchestrator(self) -> RetrievalOrchestrator:
        if self.retrieval_orchestrator is not None:
            return self.retrieval_orchestrator
        return RetrievalOrchestrator(
            chunk_service=ChunkService(self.session, self.data_dir, self.adapter),
            reranker_service=self.reranker_service,
        )

    async def _validate_query_inputs(self, payload: QueryIn) -> None:
        missing_variants = await self._missing_ids(Variant, payload.variant_ids)
        if missing_variants:
            raise QueryResourceNotFoundError("Variant", missing_variants)

        missing_documents = await self._missing_ids(Document, payload.document_ids)
        if missing_documents:
            raise QueryResourceNotFoundError("Document", missing_documents)

    async def _validate_simulation_inputs(self, payload: SimulateRetrievalIn) -> None:
        missing_variants = await self._missing_ids(Variant, payload.variant_ids)
        if missing_variants:
            raise QueryResourceNotFoundError("Variant", missing_variants)

        missing_documents = await self._missing_ids(Document, payload.document_ids)
        if missing_documents:
            raise QueryResourceNotFoundError("Document", missing_documents)

    async def _missing_ids(
        self, model: type[Document] | type[Variant], ids: list[str]
    ) -> list[str]:
        if not ids:
            return []
        requested_ids = list(dict.fromkeys(ids))
        result = await self.session.execute(select(model.id).where(model.id.in_(requested_ids)))
        found_ids = set(result.scalars().all())
        return [item_id for item_id in requested_ids if item_id not in found_ids]

    async def _document_labels(self, document_ids: list[str]) -> dict[str, str]:
        if not document_ids:
            return {}
        requested_ids = list(dict.fromkeys(document_ids))
        result = await self.session.execute(
            select(Document.id, Document.filename).where(Document.id.in_(requested_ids))
        )
        return {document_id: filename for document_id, filename in result.all()}

    def _enriched_sources(
        self,
        sources: list[dict[str, Any]],
        *,
        document_labels: dict[str, str],
        runtime_profile_id: str,
    ) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for source in sources:
            item = dict(source)
            document_id = item.get("document_id")
            document_name = (
                document_labels.get(document_id) if isinstance(document_id, str) else None
            )
            if document_name:
                item.setdefault("document_name", document_name)
                item.setdefault("filename", document_name)
            item.setdefault("runtime_profile_id", runtime_profile_id)
            source_location = item.get("source_location")
            if isinstance(source_location, dict):
                item["source_location"] = self._source_location_summary(
                    source_location,
                    document_name=document_name,
                )
            metadata = dict(item.get("metadata") or {})
            if document_name:
                metadata.setdefault("document_name", document_name)
                metadata.setdefault("filename", document_name)
            metadata.setdefault("runtime_profile_id", runtime_profile_id)
            item["metadata"] = metadata
            enriched.append(item)
        return enriched

    def _source_location_summary(
        self,
        source_location: dict[str, Any],
        *,
        document_name: str | None,
    ) -> dict[str, Any]:
        location = dict(source_location)
        page = location.get("page")
        page_start = location.get("page_start")
        page_end = location.get("page_end")
        if page is None and page_start is not None and page_start == page_end:
            location["page"] = page_start
        label_parts = [document_name]
        if location.get("page") is not None:
            label_parts.append(f"page {location['page']}")
        elif page_start is not None and page_end is not None:
            label_parts.append(f"pages {page_start}-{page_end}")
        elif page_start is not None:
            label_parts.append(f"page {page_start}")
        line = location.get("line") or location.get("line_start")
        if line is not None:
            label_parts.append(f"line {line}")
        if any(label_parts):
            location.setdefault("label", " · ".join(str(part) for part in label_parts if part))
        return location

    def _query_config(self, profile: Any, variant: Variant, payload: QueryIn) -> dict[str, Any]:
        parameters = variant.parameters or {}
        query_config = {
            "mode": self._query_mode(parameters.get("mode"), profile.query_mode),
            "parser": self._text_param(parameters.get("parser"), profile.parser),
            "parse_method": self._text_param(parameters.get("parse_method"), profile.parse_method),
            "chunk_token_size": self._int_param(
                parameters.get("chunk_token_size"), profile.chunk_token_size
            ),
            "chunk_overlap_token_size": self._int_param(
                parameters.get("chunk_overlap_token_size"),
                profile.chunk_overlap_token_size,
            ),
            "enable_image_processing": self._bool_param(
                parameters.get("enable_image_processing"),
                profile.enable_image_processing,
            ),
            "enable_table_processing": self._bool_param(
                parameters.get("enable_table_processing"),
                profile.enable_table_processing,
            ),
            "enable_equation_processing": self._bool_param(
                parameters.get("enable_equation_processing"),
                profile.enable_equation_processing,
            ),
            "context_window": self._int_param(
                parameters.get("context_window"), profile.context_window
            ),
            "context_mode": self._text_param(parameters.get("context_mode"), profile.context_mode),
            "max_context_tokens": self._int_param(
                parameters.get("max_context_tokens"), profile.max_context_tokens
            ),
            "include_headers": self._bool_param(
                parameters.get("include_headers"), profile.include_headers
            ),
            "include_captions": self._bool_param(
                parameters.get("include_captions"), profile.include_captions
            ),
            "top_k": self._int_param(parameters.get("top_k"), profile.top_k),
            "chunk_top_k": self._int_param(parameters.get("chunk_top_k"), profile.chunk_top_k),
            "enable_rerank": self._bool_param(
                parameters.get("enable_rerank"), profile.enable_rerank
            ),
            "max_total_tokens": self._int_param(
                parameters.get("max_total_tokens"), profile.max_total_tokens
            ),
            "max_entity_tokens": self._int_param(
                parameters.get("max_entity_tokens"), profile.max_entity_tokens
            ),
            "max_relation_tokens": self._int_param(
                parameters.get("max_relation_tokens"), profile.max_relation_tokens
            ),
            "cosine_better_than_threshold": self._float_param(
                parameters.get("cosine_better_than_threshold"),
                profile.cosine_better_than_threshold,
            ),
            "enable_llm_cache": self._bool_param(
                parameters.get("enable_llm_cache"), profile.enable_llm_cache
            ),
            "enable_llm_cache_for_entity_extract": self._bool_param(
                parameters.get("enable_llm_cache_for_entity_extract"),
                profile.enable_llm_cache_for_entity_extract,
            ),
            "llm_model_max_async": self._int_param(
                parameters.get("llm_model_max_async"), profile.llm_model_max_async
            ),
            "embedding_func_max_async": self._int_param(
                parameters.get("embedding_func_max_async"),
                profile.embedding_func_max_async,
            ),
            "max_parallel_insert": self._int_param(
                parameters.get("max_parallel_insert"), profile.max_parallel_insert
            ),
            "vlm_enhanced": self._bool_param(
                parameters.get("vlm_enhanced"),
                profile.enable_image_processing or "vision" in profile.llm_capabilities,
            ),
            "retrieval_mode": self._text_param(parameters.get("retrieval_mode"), "hybrid"),
            "reference_query_mode": self._text_param(
                parameters.get("reference_query_mode"),
                "hybrid",
            ),
            "native_query_timeout_ms": self._int_param(
                parameters.get("native_query_timeout_ms"),
                15_000,
            ),
            "query_hypothesis_timeout_ms": self._int_param(
                parameters.get("query_hypothesis_timeout_ms"),
                5000,
            ),
            "query_hypothesis_required": self._query_hypothesis_required_param(
                parameters.get("query_hypothesis_required")
            ),
            "answer_style": self._text_param(parameters.get("answer_style"), ""),
            "limit": payload.limit,
            "response_mode": payload.response_mode,
            "answer_budget_ms": payload.answer_budget_ms,
            "response_budget_ms": payload.response_budget_ms,
        }
        if payload.response_mode == "fast":
            query_config["enable_rerank"] = False
            query_config["native_query_timeout_ms"] = min(
                int(query_config["native_query_timeout_ms"]),
                2500,
            )
            query_config["answer_budget_ms"] = payload.answer_budget_ms or 3000
            query_config["response_budget_ms"] = payload.response_budget_ms or 15000
        else:
            query_config["answer_budget_ms"] = payload.answer_budget_ms or profile.llm_timeout_ms
            query_config["response_budget_ms"] = payload.response_budget_ms
        if payload.search_weights is not None:
            query_config["hybrid_search_weights"] = payload.search_weights.model_dump(
                exclude_none=True
            )
        return query_config

    def _query_hypothesis_required_param(self, value: Any) -> bool | str:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"true", "required", "always"}:
                return True
            if normalized in {"false", "optional", "never"}:
                return False
            if normalized == "auto":
                return "auto"
        return "auto"

    def _query_mode(self, value: Any, fallback: str) -> str:
        mode = self._text_param(value, fallback)
        return mode if mode in {"mix", "hybrid", "local", "global", "naive"} else fallback

    def _text_param(self, value: Any, fallback: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return fallback

    def _int_param(self, value: Any, fallback: int) -> int:
        if isinstance(value, bool):
            return fallback
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    def _float_param(self, value: Any, fallback: float) -> float:
        if isinstance(value, bool):
            return fallback
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    def _bool_param(self, value: Any, fallback: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return fallback

    async def _validate_index_readiness(
        self,
        document_ids: list[str],
        runtime_profile_id: str,
        index_shape: dict[str, Any],
    ) -> None:
        if not document_ids:
            return
        result = await self.session.execute(
            select(IndexRecord).where(
                IndexRecord.document_id.in_(document_ids),
                IndexRecord.runtime_profile_id == runtime_profile_id,
                IndexRecord.status == StageStatus.SUCCEEDED.value,
            )
        )
        ready = {
            record.document_id
            for record in result.scalars().all()
            if index_shape_compatible(record.index_shape, index_shape)
        }
        missing = [document_id for document_id in document_ids if document_id not in ready]
        if missing:
            raise QueryResourceNotFoundError("Runtime index", missing)

    async def _index_degradation(
        self,
        document_ids: list[str],
        runtime_profile_id: str,
        index_shape: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not document_ids:
            return None
        result = await self.session.execute(
            select(IndexRecord).where(
                IndexRecord.document_id.in_(document_ids),
                IndexRecord.runtime_profile_id == runtime_profile_id,
            )
        )
        records = list(result.scalars().all())
        ready = {
            record.document_id
            for record in records
            if record.status == StageStatus.SUCCEEDED.value
            and index_shape_compatible(record.index_shape, index_shape)
        }
        missing = [document_id for document_id in document_ids if document_id not in ready]
        if not missing:
            return None
        reason_by_document = {
            record.document_id: record.error or record.status
            for record in records
            if record.document_id in missing
        }
        return {
            "index_degraded": True,
            "index_degraded_documents": missing,
            "index_degraded_reason": reason_by_document.get(missing[0], "runtime index pending"),
            "retrieval_mode": "metadata_fallback",
        }

    async def _graph_degradation(
        self,
        document_ids: list[str],
        runtime_profile_id: str,
    ) -> dict[str, Any] | None:
        if not document_ids:
            return None
        result = await self.session.execute(
            select(GraphProjectionRecord).where(
                GraphProjectionRecord.document_id.in_(document_ids),
                GraphProjectionRecord.runtime_profile_id == runtime_profile_id,
            )
        )
        records_by_document: dict[str, list[GraphProjectionRecord]] = {}
        for record in result.scalars().all():
            records_by_document.setdefault(record.document_id, []).append(record)

        degraded_documents: list[str] = []
        reason_by_document: dict[str, str] = {}
        for document_id in document_ids:
            records = records_by_document.get(document_id, [])
            latest = max(records, key=lambda record: record.created_at) if records else None
            if latest is None:
                degraded_documents.append(document_id)
                reason_by_document[document_id] = "graph projection pending"
            elif latest.status != StageStatus.SUCCEEDED.value:
                degraded_documents.append(document_id)
                reason_by_document[document_id] = latest.error or latest.status

        if not degraded_documents:
            return None
        return {
            "graph_degraded": True,
            "graph_degraded_documents": degraded_documents,
            "graph_degraded_reason": reason_by_document.get(
                degraded_documents[0],
                "graph projection pending",
            ),
            "graph_expansion_mode": "disabled",
        }

    async def _variants_by_id(self, variant_ids: list[str]) -> dict[str, Variant]:
        result = await self.session.execute(select(Variant).where(Variant.id.in_(variant_ids)))
        return {variant.id: variant for variant in result.scalars().all()}

    async def _failed_runtime_runs(
        self,
        payload: QueryIn,
        runtime_profile_id: str | None,
        checks: list[RuntimeHealthCheck],
        *,
        error_type: str = "runtime_health_blocked",
    ) -> QueryOut:
        detail = self.runtime_failure_detail(checks)
        runs = [
            Run(
                variant_id=variant_id,
                query=payload.query,
                status=StageStatus.FAILED.value,
                runtime_profile_id=runtime_profile_id,
                document_ids=payload.document_ids,
                error=detail,
                error_type=error_type,
            )
            for variant_id in payload.variant_ids
        ]
        self.session.add_all(runs)
        await self.session.commit()
        for run in runs:
            await self.session.refresh(run)
        return QueryOut(runs=[self._run_out(run) for run in runs])

    @staticmethod
    def runtime_failure_detail(checks: list[RuntimeHealthCheck]) -> str:
        return "; ".join(f"{item.name}: {item.detail}" for item in checks)

    def _runtime_profile_missing_checks(self, detail: str) -> list[RuntimeHealthCheck]:
        return [
            RuntimeHealthCheck(
                name="runtime_profile",
                status="failed",
                severity="blocking",
                detail=detail,
                error_type="runtime_profile_missing",
            )
        ]

    def _runtime_profile_settings_missing_checks(self) -> list[RuntimeHealthCheck]:
        return self._runtime_profile_missing_checks("Runtime profile settings are not available.")

    def _inactive_runtime_mode_checks(self, runtime_mode: str) -> list[RuntimeHealthCheck]:
        return [
            RuntimeHealthCheck(
                name="runtime_mode",
                status="failed",
                severity="blocking",
                detail=(
                    f"Runtime mode '{runtime_mode}' does not provide native RAG-Anything execution."
                ),
                error_type="runtime_mode_inactive",
            )
        ]

    def _elapsed_ms(self, started_at: float) -> float:
        return round((perf_counter() - started_at) * 1000, 3)
