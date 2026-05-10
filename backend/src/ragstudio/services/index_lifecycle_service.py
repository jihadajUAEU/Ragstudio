from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from inspect import signature
from typing import Any

from ragstudio.config import AppSettings
from ragstudio.db.models import Chunk, Document, GraphProjectionRecord, IndexRecord
from ragstudio.schemas.chunks import ChunkOut
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_sanitizer import sanitize_db_text, sanitize_db_value
from ragstudio.services.chunk_splitter import ChunkSplitter
from ragstudio.services.document_parser_service import DocumentParserService
from ragstudio.services.graph_workspace import workspace_label
from ragstudio.services.mineru_relationship_builder import MinerURelationshipBuilder
from ragstudio.services.runtime_factory import RAGAnythingRuntimeFactory
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_profile_service import RuntimeProfileService
from ragstudio.services.trace_normalizer import TraceNormalizer
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession


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
    ):
        self.session = session
        self.settings = settings
        self.runtime_factory = runtime_factory or RAGAnythingRuntimeFactory(settings)
        self.health_service = health_service or RuntimeHealthService(
            session,
            verify_storage=True,
        )
        self.normalizer = normalizer or TraceNormalizer()
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
        preparsed_chunks = await self._preparse_runtime_document(
            runtime,
            document,
            options,
            on_mineru_status=on_mineru_status,
        )
        await runtime.delete_document_index(document.id)
        runtime_chunks = await self._index_runtime_document(
            runtime,
            artifact_path,
            document.id,
            preparsed_chunks=preparsed_chunks,
        )

        await self.session.execute(delete(Chunk).where(Chunk.document_id == document.id))
        await self.session.execute(
            delete(IndexRecord).where(IndexRecord.document_id == document.id)
        )
        indexed_at = datetime.now(UTC)
        normalized_chunks: list[AdapterChunk] = [
            self.normalizer.chunk_to_adapter_chunk(
                runtime_chunk,
                document_id=document.id,
                runtime_profile_id=profile.id,
                index_shape=profile.index_shape,
            )
            for runtime_chunk in runtime_chunks
        ]
        adapter_chunks = ChunkSplitter().split(
            normalized_chunks,
            domain_metadata=options.domain_metadata,
            parser_mode=options.parser_mode,
        )
        adapter_chunks = MinerURelationshipBuilder().annotate(
            adapter_chunks,
            options.domain_metadata,
        )
        chunks: list[Chunk] = []
        for adapter_chunk in adapter_chunks:
            chunks.append(
                Chunk(
                    document_id=document.id,
                    text=sanitize_db_text(adapter_chunk.text),
                    source_location=sanitize_db_value(adapter_chunk.source_location),
                    metadata_json=sanitize_db_value(
                        self._merge_options_metadata(adapter_chunk.metadata, options)
                    ),
                    runtime_profile_id=profile.id,
                    runtime_source_id=sanitize_db_value(
                        adapter_chunk.metadata.get("runtime_source_id")
                    ),
                    content_type=sanitize_db_text(
                        str(adapter_chunk.metadata.get("content_type") or "text")
                    ),
                    preview_ref=sanitize_db_value(adapter_chunk.metadata.get("preview_ref")),
                    indexed_at=indexed_at,
                )
            )

        self.session.add_all(chunks)
        await self.session.flush()
        projection_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id=profile.id,
            status="pending",
            graph_workspace_label=workspace_label(profile),
            graph_storage_uri=profile.neo4j_uri,
            node_count=0,
            edge_count=0,
        )
        self.session.add(projection_record)
        self.session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id=profile.id,
                status=StageStatus.SUCCEEDED.value,
                index_shape=profile.index_shape,
                chunk_count=len(chunks),
            )
        )
        document.status = StageStatus.SUCCEEDED.value
        await self.session.flush()
        for chunk in chunks:
            await self.session.refresh(chunk)
        return IndexLifecycleResult(
            chunks=[ChunkOut.model_validate(chunk) for chunk in chunks],
            graph_projection_record_id=projection_record.id,
            graph_materialization={
                "status": "pending",
                "node_count": 0,
                "edge_count": 0,
                "reason": None,
            },
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

    def _merge_options_metadata(
        self,
        metadata: dict[str, Any],
        options: IndexDocumentIn,
    ) -> dict[str, Any]:
        merged = dict(metadata)
        merged["domain_metadata"] = options.domain_metadata.model_dump(exclude_none=True)
        if "parser_metadata" not in merged:
            merged["parser_metadata"] = {
                "backend": merged.get("backend", "fallback"),
                "parser_mode": options.parser_mode,
                "artifact_ref": merged.get("artifact_ref"),
                "chunk_index": merged.get("chunk_index"),
                "source_type": merged.get("source_type"),
            }
        merged.pop("backend", None)
        merged.pop("artifact_ref", None)
        merged.pop("chunk_index", None)
        merged.pop("source_type", None)
        return merged
