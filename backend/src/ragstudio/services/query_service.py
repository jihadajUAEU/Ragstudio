from pathlib import Path
from time import perf_counter
from typing import Any

from ragstudio.config import AppSettings
from ragstudio.db.models import Document, IndexRecord, Run, Variant
from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.query import QueryIn, QueryOut
from ragstudio.schemas.runs import RunOut
from ragstudio.schemas.runtime import RuntimeHealthCheck
from ragstudio.services.adapter import AdapterChunk, RAGAnythingAdapter
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.runtime_factory import RAGAnythingRuntimeFactory
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_profile_service import RuntimeProfileService
from ragstudio.services.trace_normalizer import TraceNormalizer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class QueryResourceNotFoundError(LookupError):
    def __init__(self, resource: str, missing_ids: list[str]):
        self.resource = resource
        self.missing_ids = missing_ids
        super().__init__(f"{resource} not found: {', '.join(missing_ids)}")


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
        normalizer: TraceNormalizer | None = None,
    ):
        self.session = session
        self.data_dir = data_dir
        self.adapter = adapter or RAGAnythingAdapter()
        self.settings = settings
        self.runtime_factory = runtime_factory or RAGAnythingRuntimeFactory()
        self.health_service = health_service or RuntimeHealthService()
        self.normalizer = normalizer or TraceNormalizer()

    async def run_query(self, payload: QueryIn) -> QueryOut:
        await self._validate_query_inputs(payload)
        if self.settings is not None:
            return await self._run_runtime_query(payload)

        runs: list[Run] = []
        for variant_id in payload.variant_ids:
            started_at = perf_counter()
            search_started_at = perf_counter()
            search = await ChunkService(self.session, self.data_dir, self.adapter).search(
                ChunkSearchIn(
                    query=payload.query,
                    document_ids=payload.document_ids,
                    variant_id=variant_id,
                    limit=payload.limit,
                )
            )
            search_ms = self._elapsed_ms(search_started_at)

            run = Run(variant_id=variant_id, query=payload.query, status=StageStatus.RUNNING.value)
            self.session.add(run)
            try:
                adapter_chunks = [self._adapter_chunk(chunk) for chunk in search.items]
                query_started_at = perf_counter()
                result = await self.adapter.query(
                    payload.query, adapter_chunks, limit=payload.limit
                )
                query_ms = self._elapsed_ms(query_started_at)

                result_timings = result.get("timings", {})
                if not isinstance(result_timings, dict):
                    result_timings = {}
                run.status = StageStatus.SUCCEEDED.value
                run.answer = str(result.get("answer", ""))
                run.sources = self._result_list(result.get("sources")) or [
                    self._source(chunk) for chunk in search.items
                ]
                run.chunk_traces = self._result_list(result.get("chunk_traces"))
                run.timings = {
                    **result_timings,
                    "search_ms": search_ms,
                    "query_ms": query_ms,
                    "total_ms": self._elapsed_ms(started_at),
                }
            except Exception as exc:
                run.status = StageStatus.FAILED.value
                run.error = str(exc)
                run.timings = {
                    "search_ms": search_ms,
                    "total_ms": self._elapsed_ms(started_at),
                }

            runs.append(run)

        await self.session.commit()
        for run in runs:
            await self.session.refresh(run)
        return QueryOut(runs=[RunOut.model_validate(run) for run in runs])

    async def list_runs(self) -> list[RunOut]:
        result = await self.session.execute(select(Run).order_by(Run.created_at.desc()))
        return [RunOut.model_validate(item) for item in result.scalars().all()]

    async def _run_runtime_query(self, payload: QueryIn) -> QueryOut:
        assert self.settings is not None
        profile = await RuntimeProfileService(self.session, self.settings).get_active_profile()
        checks = await self.health_service.check(profile)
        blocking = self.health_service.blocking_failures(checks)
        if profile.runtime_mode != "fallback" and blocking:
            return await self._failed_runtime_runs(payload, profile.id, blocking)
        if profile.runtime_mode != "fallback":
            await self._validate_index_readiness(payload.document_ids, profile.id)

        runtime = self.runtime_factory.build(profile)
        variants = await self._variants_by_id(payload.variant_ids)
        runs: list[Run] = []
        for variant_id in payload.variant_ids:
            variant = variants[variant_id]
            started_at = perf_counter()
            query_config = self._query_config(profile, variant, payload.limit)
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
                runtime_result = await runtime.query(
                    payload.query,
                    document_ids=payload.document_ids,
                    query_config=query_config,
                )
                normalized = self.normalizer.query_result(runtime_result)
                run.status = (
                    StageStatus.FAILED.value
                    if normalized.get("error")
                    else StageStatus.SUCCEEDED.value
                )
                run.answer = str(normalized.get("answer") or "")
                run.sources = self._result_list(normalized.get("sources"))
                run.chunk_traces = self._result_list(normalized.get("chunk_traces"))
                run.reranker_traces = self._result_list(normalized.get("reranker_traces"))
                run.token_metadata = normalized.get("token_metadata") or {}
                run.error = normalized.get("error")
                run.error_type = normalized.get("error_type")
                timings = normalized.get("timings") or {}
                run.timings = {**timings, "total_ms": self._elapsed_ms(started_at)}
            except Exception as exc:
                run.status = StageStatus.FAILED.value
                run.error = str(exc)
                run.error_type = exc.__class__.__name__
                run.timings = {"total_ms": self._elapsed_ms(started_at)}
            runs.append(run)

        await self.session.commit()
        for run in runs:
            await self.session.refresh(run)
        return QueryOut(runs=[RunOut.model_validate(run) for run in runs])

    async def _validate_query_inputs(self, payload: QueryIn) -> None:
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

    def _query_config(self, profile: Any, variant: Variant, limit: int) -> dict[str, Any]:
        parameters = variant.parameters or {}
        return {
            "mode": parameters.get("mode", profile.query_mode),
            "top_k": int(parameters.get("top_k", profile.top_k)),
            "chunk_top_k": int(parameters.get("chunk_top_k", profile.chunk_top_k)),
            "enable_rerank": bool(parameters.get("enable_rerank", profile.enable_rerank)),
            "max_total_tokens": int(
                parameters.get("max_total_tokens", profile.max_total_tokens)
            ),
            "max_context_tokens": int(
                parameters.get("max_context_tokens", profile.max_context_tokens)
            ),
            "cosine_better_than_threshold": float(
                parameters.get(
                    "cosine_better_than_threshold",
                    profile.cosine_better_than_threshold,
                )
            ),
            "limit": limit,
        }

    async def _validate_index_readiness(
        self, document_ids: list[str], runtime_profile_id: str
    ) -> None:
        if not document_ids:
            return
        result = await self.session.execute(
            select(IndexRecord.document_id).where(
                IndexRecord.document_id.in_(document_ids),
                IndexRecord.runtime_profile_id == runtime_profile_id,
                IndexRecord.status == StageStatus.SUCCEEDED.value,
            )
        )
        ready = set(result.scalars().all())
        missing = [document_id for document_id in document_ids if document_id not in ready]
        if missing:
            raise QueryResourceNotFoundError("Runtime index", missing)

    async def _variants_by_id(self, variant_ids: list[str]) -> dict[str, Variant]:
        result = await self.session.execute(select(Variant).where(Variant.id.in_(variant_ids)))
        return {variant.id: variant for variant in result.scalars().all()}

    async def _failed_runtime_runs(
        self,
        payload: QueryIn,
        runtime_profile_id: str,
        checks: list[RuntimeHealthCheck],
    ) -> QueryOut:
        detail = "; ".join(f"{item.name}: {item.detail}" for item in checks)
        runs = [
            Run(
                variant_id=variant_id,
                query=payload.query,
                status=StageStatus.FAILED.value,
                runtime_profile_id=runtime_profile_id,
                document_ids=payload.document_ids,
                error=detail,
                error_type="runtime_health_blocked",
            )
            for variant_id in payload.variant_ids
        ]
        self.session.add_all(runs)
        await self.session.commit()
        for run in runs:
            await self.session.refresh(run)
        return QueryOut(runs=[RunOut.model_validate(run) for run in runs])

    def _adapter_chunk(self, chunk: ChunkOut) -> AdapterChunk:
        metadata = {**chunk.metadata, "chunk_id": chunk.id, "document_id": chunk.document_id}
        return AdapterChunk(
            text=chunk.text, source_location=chunk.source_location, metadata=metadata
        )

    def _source(self, chunk: ChunkOut) -> dict[str, Any]:
        return {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "text": chunk.text,
            "source_location": chunk.source_location,
            "metadata": chunk.metadata,
        }

    def _result_list(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _elapsed_ms(self, started_at: float) -> float:
        return round((perf_counter() - started_at) * 1000, 3)
