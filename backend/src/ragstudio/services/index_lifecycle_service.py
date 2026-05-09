from datetime import UTC, datetime
from inspect import signature
from typing import Any

from ragstudio.config import AppSettings
from ragstudio.db.models import Chunk, Document, IndexRecord
from ragstudio.schemas.chunks import ChunkOut
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_sanitizer import sanitize_db_text, sanitize_db_value
from ragstudio.services.chunk_splitter import ChunkSplitter
from ragstudio.services.runtime_factory import RAGAnythingRuntimeFactory
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_profile_service import RuntimeProfileService
from ragstudio.services.trace_normalizer import TraceNormalizer
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession


class RuntimeHealthBlockedError(RuntimeError):
    pass


class IndexLifecycleService:
    def __init__(
        self,
        session: AsyncSession,
        settings: AppSettings,
        *,
        runtime_factory: Any | None = None,
        health_service: RuntimeHealthService | None = None,
        normalizer: TraceNormalizer | None = None,
    ):
        self.session = session
        self.settings = settings
        self.runtime_factory = runtime_factory or self._runtime_factory(settings)
        self.health_service = health_service or self._health_service(session)
        self.normalizer = normalizer or TraceNormalizer()

    async def reindex_document(
        self,
        document_id: str,
        *,
        options: IndexDocumentIn | None = None,
    ) -> list[ChunkOut] | None:
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
        await runtime.delete_document_index(document.id)
        await self.session.execute(delete(Chunk).where(Chunk.document_id == document.id))
        await self.session.execute(
            delete(IndexRecord).where(IndexRecord.document_id == document.id)
        )

        runtime_chunks = await self._index_runtime_document(
            runtime,
            document.artifact_path,
            document.id,
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
        return [ChunkOut.model_validate(chunk) for chunk in chunks]

    async def _index_runtime_document(
        self,
        runtime: Any,
        artifact_path: str,
        document_id: str,
    ) -> list[Any]:
        parameters = signature(runtime.index_document).parameters
        if "document_id" in parameters:
            return await runtime.index_document(artifact_path, document_id=document_id)
        return await runtime.index_document(artifact_path)

    def _runtime_factory(self, settings: AppSettings) -> Any:
        try:
            return RAGAnythingRuntimeFactory(settings)
        except TypeError:
            return RAGAnythingRuntimeFactory()

    def _health_service(self, session: AsyncSession) -> RuntimeHealthService:
        try:
            return RuntimeHealthService(session, verify_storage=True)
        except TypeError:
            return RuntimeHealthService()

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
