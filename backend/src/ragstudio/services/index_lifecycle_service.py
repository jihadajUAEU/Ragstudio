import logging
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from inspect import signature
from typing import Any

from ragstudio.config import AppSettings
from ragstudio.db.models import Document, GraphProjectionRecord, IndexRecord
from ragstudio.schemas.chunks import ChunkOut
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_persistence_service import ChunkPersistenceService
from ragstudio.services.chunk_splitter import ChunkSplitter
from ragstudio.services.document_parser_service import DocumentParserService
from ragstudio.services.graph_workspace import workspace_label
from ragstudio.services.index_artifact_cleanup import cleanup_document_index_artifacts
from ragstudio.services.index_progress import IndexStage
from ragstudio.services.index_quality_gate import IndexQualityGate
from ragstudio.services.index_stage_scheduler import IndexStageBranch, IndexStageScheduler
from ragstudio.services.mineru_relationship_builder import MinerURelationshipBuilder
from ragstudio.services.parser_normalization import VisionRecoveryConfig
from ragstudio.services.runtime_factory import RAGAnythingRuntimeFactory
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_profile_service import RuntimeProfileService
from ragstudio.services.trace_normalizer import TraceNormalizer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class RuntimeHealthBlockedError(RuntimeError):
    pass


MinerUStatusCallback = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class IndexLifecycleResult:
    chunks: list[ChunkOut]
    graph_projection_record_id: str | None
    graph_materialization: dict[str, Any]

    def __iter__(self) -> Iterator[ChunkOut]:
        return iter(self.chunks)

    def __len__(self) -> int:
        return len(self.chunks)

    def __getitem__(self, index: int) -> ChunkOut:
        return self.chunks[index]


class IndexLifecycleService:
    def __init__(
        self,
        session: AsyncSession,
        settings: AppSettings,
        *,
        runtime_factory: Any | None = None,
        health_service: RuntimeHealthService | None = None,
        normalizer: TraceNormalizer | None = None,
        document_parser: DocumentParserService | None = None,
        quality_gate: IndexQualityGate | None = None,
    ):
        self.session = session
        self.settings = settings
        self.runtime_factory = runtime_factory or RAGAnythingRuntimeFactory(settings)
        self.health_service = health_service or RuntimeHealthService(
            session,
            verify_storage=True,
        )
        self.normalizer = normalizer or TraceNormalizer()
        self.quality_gate = quality_gate or IndexQualityGate()
        self.document_parser = document_parser or DocumentParserService(
            session,
            settings.data_dir,
            commit_before_remote_parse=True,
        )

    async def reindex_document(
        self,
        document_id: str,
        *,
        options: IndexDocumentIn | None = None,
        on_mineru_status: MinerUStatusCallback | None = None,
        on_stage: Callable[..., Awaitable[None]] | None = None,
    ) -> IndexLifecycleResult | None:
        document = await self.session.get(Document, document_id)
        if document is None:
            return None

        options = options or IndexDocumentIn()
        profile = await RuntimeProfileService(self.session, self.settings).get_active_profile()
        if profile.runtime_mode != "fallback":
            checks = await self.health_service.check(profile)
            blocking = self.health_service.blocking_failures(checks)
            if blocking:
                details = "; ".join(f"{item.name}: {item.detail}" for item in blocking)
                raise RuntimeHealthBlockedError(details)

        runtime = self.runtime_factory.build(profile)
        document.status = StageStatus.RUNNING.value
        await self.session.commit()

        # Native LightRAG storage may run schema DDL such as CREATE INDEX CONCURRENTLY.
        # Do not hold the Studio session's transaction open while runtime storage works,
        # or Postgres can block the runtime on our own idle transaction.
        artifact_path = document.artifact_path
        await cleanup_document_index_artifacts(self.session, document.id)
        await self.session.commit()

        preparsed_chunks = await self._preparse_runtime_document(
            runtime,
            document,
            options,
            on_mineru_status=on_mineru_status,
        )
        runtime_chunks: list[Any] | None = None
        if preparsed_chunks is None:
            await runtime.delete_document_index(document.id)
            runtime_chunks = await self._index_runtime_document(
                runtime,
                artifact_path,
                document.id,
                preparsed_chunks=None,
            )
            normalized_chunks = self._normalize_runtime_chunks(
                runtime_chunks,
                document_id=document.id,
                runtime_profile_id=profile.id,
                index_shape=profile.index_shape,
            )
        else:
            normalized_chunks = preparsed_chunks

        adapter_chunks = ChunkSplitter(
            vision_recovery_config=VisionRecoveryConfig.from_runtime_profile(
                options.domain_metadata,
                profile,
            )
        ).split(
            normalized_chunks,
            domain_metadata=options.domain_metadata,
            parser_mode=options.parser_mode,
        )
        adapter_chunks = MinerURelationshipBuilder().annotate(
            adapter_chunks,
            options.domain_metadata,
        )
        quality_report = self.quality_gate.validate_adapter_chunks(
            adapter_chunks,
            language=self._quality_language(options.domain_metadata),
            domain_metadata=options.domain_metadata,
        )
        index_quality_report = quality_report.get("index_quality_report")
        runtime_adapter_chunks = self._runtime_materializable_chunks(adapter_chunks)
        if on_stage is not None:
            await on_stage(
                IndexStage.MINERU_VALIDATED,
                detail=f"Validated {len(adapter_chunks)} chunks from MinerU.",
                chunk_count=len(adapter_chunks),
            )
        projection_record = await self._create_pending_graph_projection(document.id, profile)
        graph_materialization = {
            "status": "pending",
            "node_count": 0,
            "edge_count": 0,
            "reason": None,
        }

        async def persist_studio_chunks() -> list[ChunkOut]:
            chunks = await ChunkPersistenceService(self.session).persist(
                document,
                adapter_chunks,
                options,
                commit=False,
                runtime_profile_id=profile.id,
                index_shape=profile.index_shape,
            )
            self.session.add(
                IndexRecord(
                    document_id=document.id,
                    runtime_profile_id=profile.id,
                    status=StageStatus.RUNNING.value,
                    index_shape={
                        **profile.index_shape,
                        "embedding_model": profile.embedding_model,
                        "embedding_dimensions": profile.embedding_dimensions,
                        "parser_mode": options.parser_mode,
                        "index_quality_report": index_quality_report,
                        "quality_report_version": (
                            index_quality_report.get("quality_report_version")
                            if isinstance(index_quality_report, dict)
                            else None
                        ),
                    },
                    chunk_count=len(chunks),
                )
            )
            document.status = StageStatus.SUCCEEDED.value
            await self.session.commit()
            if on_stage is not None:
                await on_stage(
                    IndexStage.CHUNKS_PERSISTED,
                    detail=f"Persisted {len(chunks)} canonical chunks.",
                    chunk_count=len(chunks),
                )
                await on_stage(
                    IndexStage.SEARCH_READY,
                    detail="Lexical and metadata retrieval are ready.",
                    chunk_count=len(chunks),
                )
            return chunks

        async def enrich_runtime() -> list[Any] | None:
            if runtime_chunks is not None:
                return runtime_chunks
            await runtime.delete_document_index(document.id)
            if not runtime_adapter_chunks:
                return []
            return await self._index_runtime_document(
                runtime,
                artifact_path,
                document.id,
                preparsed_chunks=runtime_adapter_chunks,
            )

        studio_branch_name = IndexStage.CHUNKS_PERSISTED.value
        runtime_branch_name = IndexStage.RUNTIME_ENRICHING.value

        async def cleanup_runtime_index_best_effort() -> None:
            try:
                await runtime.delete_document_index(document.id)
            except Exception:
                logger.exception("Failed to clean runtime index for %s.", document.id)

        if on_stage is not None:
            await on_stage(
                IndexStage.RUNTIME_ENRICHING,
                detail="Runtime enrichment is running.",
                chunk_count=len(adapter_chunks),
            )
        try:
            branch_results = await IndexStageScheduler(max_parallel_branches=2).run(
                [
                    IndexStageBranch(
                        studio_branch_name,
                        persist_studio_chunks,
                        critical=True,
                    ),
                    IndexStageBranch(
                        runtime_branch_name,
                        enrich_runtime,
                        critical=False,
                    ),
                ]
            )
        except Exception as exc:
            reason = f"Canonical chunk persistence failed: {exc}"
            await cleanup_runtime_index_best_effort()
            await self._mark_graph_projection_skipped(projection_record.id, reason)
            raise
        chunks = branch_results[studio_branch_name].value

        runtime_result = branch_results[runtime_branch_name]
        if runtime_result.status == "skipped":
            reason = runtime_result.warning or "Runtime enrichment skipped."
            await cleanup_runtime_index_best_effort()
            await self._mark_runtime_index_failed(document.id, profile.id, reason)
            projection_record = await self._mark_graph_projection_skipped(
                projection_record.id,
                reason,
            )
            return IndexLifecycleResult(
                chunks=chunks,
                graph_projection_record_id=projection_record.id,
                graph_materialization={
                    "status": "skipped",
                    "node_count": 0,
                    "edge_count": 0,
                    "reason": reason,
                },
            )

        runtime_chunk_count = len(runtime_result.value or [])
        expected_runtime_chunk_count = len(runtime_adapter_chunks)
        if chunks and expected_runtime_chunk_count == 0:
            reason = "No chunks passed the runtime materialization quality gate."
            if runtime_chunks is not None or runtime_chunk_count > 0:
                await cleanup_runtime_index_best_effort()
            await self._mark_runtime_index_failed(document.id, profile.id, reason)
            projection_record = await self._mark_graph_projection_skipped(
                projection_record.id,
                reason,
            )
            return IndexLifecycleResult(
                chunks=chunks,
                graph_projection_record_id=projection_record.id,
                graph_materialization={
                    "status": "skipped",
                    "node_count": 0,
                    "edge_count": 0,
                    "reason": reason,
                },
            )
        if runtime_chunk_count != expected_runtime_chunk_count:
            reason = (
                f"Runtime enrichment produced {runtime_chunk_count} chunks for "
                f"{expected_runtime_chunk_count} quality-approved chunks."
            )
            await cleanup_runtime_index_best_effort()
            await self._mark_runtime_index_failed(document.id, profile.id, reason)
            projection_record = await self._mark_graph_projection_skipped(
                projection_record.id,
                reason,
            )
            return IndexLifecycleResult(
                chunks=chunks,
                graph_projection_record_id=projection_record.id,
                graph_materialization={
                    "status": "skipped",
                    "node_count": 0,
                    "edge_count": 0,
                    "reason": reason,
                },
            )

        await self._mark_runtime_index_succeeded(
            document.id,
            profile.id,
            expected_runtime_chunk_count,
        )
        if on_stage is not None:
            await on_stage(
                IndexStage.GRAPH_ENRICHING,
                detail="Graph enrichment is queued.",
                chunk_count=len(chunks),
            )
        return IndexLifecycleResult(
            chunks=chunks,
            graph_projection_record_id=projection_record.id,
            graph_materialization=graph_materialization,
        )

    async def _preparse_runtime_document(
        self,
        runtime: Any,
        document: Document,
        options: IndexDocumentIn,
        *,
        on_mineru_status: MinerUStatusCallback | None = None,
    ) -> list[AdapterChunk] | None:
        if options.parser_mode == "local_fallback":
            return None
        if not hasattr(runtime, "index_preparsed_chunks"):
            return None
        return await self.document_parser.parse(
            document,
            options,
            on_mineru_status=on_mineru_status,
        )

    async def _index_runtime_document(
        self,
        runtime: Any,
        artifact_path: str,
        document_id: str,
        *,
        preparsed_chunks: list[AdapterChunk] | None = None,
    ) -> list[Any]:
        if preparsed_chunks is not None:
            return await runtime.index_preparsed_chunks(
                artifact_path,
                preparsed_chunks,
                document_id=document_id,
            )
        parameters = signature(runtime.index_document).parameters
        if "document_id" in parameters:
            return await runtime.index_document(artifact_path, document_id=document_id)
        return await runtime.index_document(artifact_path)

    def _runtime_materializable_chunks(
        self,
        chunks: list[AdapterChunk],
    ) -> list[AdapterChunk]:
        return [
            chunk
            for chunk in chunks
            if self._quality_policy(chunk.metadata).get("index_vector", True)
        ]

    def _quality_policy(self, metadata: dict[str, Any]) -> dict[str, Any]:
        policy = metadata.get("quality_action_policy")
        return policy if isinstance(policy, dict) else {}

    def _normalize_runtime_chunks(
        self,
        runtime_chunks: list[Any],
        *,
        document_id: str,
        runtime_profile_id: str,
        index_shape: dict[str, Any],
    ) -> list[AdapterChunk]:
        adapter_chunks: list[AdapterChunk] = []
        for runtime_chunk in runtime_chunks:
            normalized = self.normalizer.chunk_to_adapter_chunk(
                runtime_chunk,
                document_id=document_id,
                runtime_profile_id=runtime_profile_id,
                index_shape=index_shape,
            )
            adapter_chunks.append(
                AdapterChunk(
                    text=normalized.text,
                    source_location=normalized.source_location,
                    metadata=normalized.metadata,
                    runtime_source_id=runtime_chunk.runtime_source_id,
                    content_type=runtime_chunk.content_type,
                    preview_ref=runtime_chunk.preview_ref,
                )
            )
        return adapter_chunks

    async def _mark_runtime_index_succeeded(
        self,
        document_id: str,
        runtime_profile_id: str,
        chunk_count: int,
    ) -> None:
        records = await self.session.execute(
            select(IndexRecord).where(
                IndexRecord.document_id == document_id,
                IndexRecord.runtime_profile_id == runtime_profile_id,
            )
        )
        for record in records.scalars().all():
            record.status = StageStatus.SUCCEEDED.value
            record.chunk_count = chunk_count
            record.error = None
        await self.session.commit()

    async def _mark_runtime_index_failed(
        self,
        document_id: str,
        runtime_profile_id: str,
        reason: str,
    ) -> None:
        records = await self.session.execute(
            select(IndexRecord).where(
                IndexRecord.document_id == document_id,
                IndexRecord.runtime_profile_id == runtime_profile_id,
            )
        )
        for record in records.scalars().all():
            record.status = StageStatus.FAILED.value
            record.error = reason
        await self.session.commit()

    async def _create_pending_graph_projection(
        self,
        document_id: str,
        profile: Any,
    ) -> GraphProjectionRecord:
        projection_record = GraphProjectionRecord(
            document_id=document_id,
            runtime_profile_id=profile.id,
            status="pending",
            graph_workspace_label=workspace_label(profile),
            graph_storage_uri=profile.neo4j_uri,
            graph_storage_username=profile.neo4j_username,
            graph_storage_password=None,
            node_count=0,
            edge_count=0,
        )
        self.session.add(projection_record)
        await self.session.flush()
        await self.session.commit()
        return projection_record

    async def _mark_graph_projection_skipped(
        self,
        projection_record_id: str,
        reason: str,
    ) -> GraphProjectionRecord:
        await self.session.rollback()
        projection_record = await self.session.get(GraphProjectionRecord, projection_record_id)
        if projection_record is None:
            raise RuntimeError("Graph projection record disappeared before skip update.")
        projection_record.status = "skipped"
        projection_record.node_count = 0
        projection_record.edge_count = 0
        projection_record.error = reason
        await self.session.commit()
        return projection_record

    def _quality_language(self, metadata: DomainMetadata) -> str:
        values = [
            metadata.domain,
            metadata.document_type,
            metadata.collection,
            metadata.content_role,
            *metadata.tags,
        ]
        combined = " ".join(value for value in values if value).casefold()
        if "quran" in combined or "arabic" in combined:
            return "quran"
        return "unknown"
