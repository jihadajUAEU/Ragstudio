from collections.abc import Awaitable, Callable
from pathlib import Path, PureWindowsPath
from typing import Any

import httpx
from ragstudio.db.models import Chunk, Document, SettingsProfile
from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn, ChunkSearchOut
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn, ParserMode
from ragstudio.services.adapter import AdapterChunk, RAGAnythingAdapter
from ragstudio.services.chunk_sanitizer import sanitize_db_text, sanitize_db_value
from ragstudio.services.chunk_splitter import ChunkSplitter
from ragstudio.services.hybrid_chunk_search import ChunkScore, HybridChunkSearch
from ragstudio.services.mineru_client import MinerUClient
from ragstudio.services.mineru_relationship_builder import MinerURelationshipBuilder
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

MinerUStatusCallback = Callable[[dict[str, Any]], Awaitable[None]]


class ChunkService:
    def __init__(
        self,
        session: AsyncSession,
        data_dir: Path,
        adapter: RAGAnythingAdapter | None = None,
        mineru_client_factory: type[MinerUClient] | None = None,
        chunk_splitter: ChunkSplitter | None = None,
        chunk_search: HybridChunkSearch | None = None,
        relationship_builder: MinerURelationshipBuilder | None = None,
    ):
        self.session = session
        self.data_dir = data_dir
        self.adapter = adapter or RAGAnythingAdapter()
        self.mineru_client_factory = mineru_client_factory or MinerUClient
        self.chunk_splitter = chunk_splitter or ChunkSplitter()
        self.chunk_search = chunk_search or HybridChunkSearch()
        self.relationship_builder = relationship_builder or MinerURelationshipBuilder()

    async def index_document(
        self,
        document_id: str,
        *,
        options: IndexDocumentIn | None = None,
        commit: bool = True,
        on_mineru_status: MinerUStatusCallback | None = None,
    ) -> list[ChunkOut] | None:
        document = await self.session.get(Document, document_id)
        if document is None:
            return None

        options = options or IndexDocumentIn()
        adapter_chunks = await self._adapter_chunks(
            document,
            options,
            on_mineru_status=on_mineru_status,
        )
        adapter_chunks = [
            self._chunk_with_parser_metadata(adapter_chunk, options.parser_mode)
            for adapter_chunk in adapter_chunks
        ]
        adapter_chunks = self.chunk_splitter.split(
            adapter_chunks,
            domain_metadata=options.domain_metadata,
            parser_mode=options.parser_mode,
        )
        adapter_chunks = self.relationship_builder.annotate(
            adapter_chunks,
            options.domain_metadata,
        )
        await self.session.execute(delete(Chunk).where(Chunk.document_id == document.id))

        chunks = [
            Chunk(
                document_id=document.id,
                text=sanitize_db_text(adapter_chunk.text),
                source_location=sanitize_db_value(adapter_chunk.source_location),
                metadata_json=self._safe_metadata(
                    self._merge_metadata(
                        adapter_chunk.metadata,
                        options.domain_metadata,
                        options.parser_mode,
                    ),
                    document.id,
                ),
            )
            for adapter_chunk in adapter_chunks
        ]
        self.session.add_all(chunks)
        if commit:
            await self.session.commit()
        else:
            await self.session.flush()

        for chunk in chunks:
            await self.session.refresh(chunk)
        return [ChunkOut.model_validate(chunk) for chunk in chunks]

    async def _adapter_chunks(
        self,
        document: Document,
        options: IndexDocumentIn,
        *,
        on_mineru_status: MinerUStatusCallback | None = None,
    ) -> list[AdapterChunk]:
        if options.parser_mode == "local_fallback":
            return await self.adapter.index_document(document.artifact_path)
        try:
            return await self._mineru_adapter_chunks(
                document.id,
                options=options,
                on_mineru_status=on_mineru_status,
            )
        except Exception as exc:
            if options.parser_mode == "mineru_strict":
                raise
            chunks = await self.adapter.index_document(document.artifact_path)
            return [
                AdapterChunk(
                    text=chunk.text,
                    source_location=chunk.source_location,
                    metadata={
                        **chunk.metadata,
                        "parser_metadata": {
                            "backend": "fallback",
                            "parser_mode": "mineru_with_fallback",
                            "mineru_error": str(exc),
                            "fallback_used": True,
                        },
                    },
                )
                for chunk in chunks
            ]

    async def _mineru_adapter_chunks(
        self,
        document_id: str,
        *,
        options: IndexDocumentIn,
        on_mineru_status: MinerUStatusCallback | None = None,
    ) -> list[AdapterChunk]:
        document = await self.session.get(Document, document_id)
        if document is None:
            return []
        _, client = await self._validated_mineru_client()
        artifact_dir = self.data_dir / "mineru-artifacts" / document.id
        job_result = await client.parse_document(
            artifact_path=document.artifact_path,
            document_id=document.id,
            artifact_dir=artifact_dir,
            content_type=document.content_type,
            sha256=document.sha256,
            domain_metadata=options.domain_metadata.model_dump(exclude_none=True),
            on_status=on_mineru_status,
        )
        return client.normalize_artifact_zip(
            artifact_zip=job_result.artifact_zip,
            extract_dir=artifact_dir / "extracted",
            document_id=document.id,
            parser_mode=options.parser_mode,
            parse_job_id=job_result.parse_job_id,
        )

    async def validate_strict_mineru_sidecar(self, options: IndexDocumentIn) -> None:
        if options.parser_mode != "mineru_strict":
            return
        await self._validated_mineru_client()

    async def _validated_mineru_client(self) -> tuple[SettingsProfile, MinerUClient]:
        settings = await self.session.get(SettingsProfile, "default")
        if settings is None or not settings.mineru_base_url:
            raise RuntimeError("MinerU base URL is not configured.")
        if not settings.mineru_enabled:
            raise RuntimeError("MinerU is disabled in settings.")
        client = self.mineru_client_factory(
            base_url=settings.mineru_base_url,
            timeout_ms=settings.mineru_timeout_ms or 14_400_000,
            poll_interval_ms=settings.mineru_poll_interval_ms or 1_000,
        )
        try:
            health = await client.health()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"MinerU health check failed: {exc}") from exc
        if not health.ready:
            raise RuntimeError(health.detail or "MinerU sidecar is not ready.")
        if settings.mineru_require_hpc and not health.is_hpc_coordinator:
            mode = health.hpc_mode or "unknown"
            raise RuntimeError(
                "MinerU sidecar is not in HPC coordinator mode. "
                f"Health detail: {health.detail or 'no detail'}; "
                f"hpcMineru.enabled={health.hpc_enabled}; mode={mode}. "
                "Start the HPC MinerU sidecar/coordinator or disable "
                "'Require HPC MinerU coordinator' in Settings."
            )
        return settings, client

    async def search(self, search_in: ChunkSearchIn) -> ChunkSearchOut:
        limit = max(search_in.limit, 0)
        statement = select(Chunk)
        if search_in.document_ids:
            statement = statement.where(Chunk.document_id.in_(search_in.document_ids))
        result = await self.session.execute(
            statement.order_by(Chunk.created_at.asc(), Chunk.id.asc())
        )
        chunks = list(result.scalars().all())

        ranked = sorted(
            (
                (self.chunk_search.score(search_in.query, chunk), source_order, chunk)
                for source_order, chunk in enumerate(chunks)
            ),
            key=lambda item: (
                -item[0].score,
                self._source_order(item[2], item[1]),
            ),
        )
        if search_in.query.strip():
            ranked = [item for item in ranked if item[0].score > 0]

        items = [
            self._chunk_out_with_score(
                chunk,
                score,
                explain=search_in.explain,
                include_neighbors=search_in.include_neighbors,
            )
            for score, _, chunk in ranked[:limit]
        ]
        return ChunkSearchOut(items=items, total=len(items))

    def _chunk_out_with_score(
        self,
        chunk: Chunk,
        score: ChunkScore,
        *,
        explain: bool = True,
        include_neighbors: bool = True,
    ) -> ChunkOut:
        output = ChunkOut.model_validate(chunk)
        breakdown = dict(score.breakdown)
        retrieval_explain = breakdown.pop("retrieval_explain", None)
        metadata = {
            **output.metadata,
            "score": score.score,
            "score_breakdown": breakdown,
        }
        if explain and isinstance(retrieval_explain, dict):
            metadata["retrieval_explain"] = retrieval_explain
            output.retrieval_explain = retrieval_explain
            relationship_refs = retrieval_explain.get("relationship_refs")
            if include_neighbors and isinstance(relationship_refs, dict):
                output.relationship_refs = {
                    key: value
                    for key, value in relationship_refs.items()
                    if isinstance(key, str) and isinstance(value, str)
                }
        output.metadata = metadata
        return output

    def _safe_metadata(self, metadata: dict[str, Any], document_id: str) -> dict[str, Any]:
        safe = {
            key: value
            for key, value in metadata.items()
            if key not in {"artifact_path", "path", "file_path"}
            and not self._is_absolute_path_value(value)
        }
        safe["document_id"] = document_id
        return sanitize_db_value(safe)

    def _merge_metadata(
        self,
        parser_metadata: dict[str, Any],
        domain_metadata: DomainMetadata,
        parser_mode: ParserMode,
    ) -> dict[str, Any]:
        metadata = dict(parser_metadata)
        metadata["domain_metadata"] = domain_metadata.model_dump(exclude_none=True)
        if "parser_metadata" not in metadata:
            metadata["parser_metadata"] = {
                "backend": metadata.get("backend", "fallback"),
                "parser_mode": parser_mode,
                "artifact_ref": metadata.get("artifact_ref"),
                "chunk_index": metadata.get("chunk_index"),
                "source_type": metadata.get("source_type"),
            }
        metadata.pop("backend", None)
        metadata.pop("artifact_ref", None)
        metadata.pop("chunk_index", None)
        metadata.pop("source_type", None)
        return metadata

    def _chunk_with_parser_metadata(
        self,
        chunk: AdapterChunk,
        parser_mode: ParserMode,
    ) -> AdapterChunk:
        if isinstance(chunk.metadata.get("parser_metadata"), dict):
            return chunk

        metadata = dict(chunk.metadata)
        metadata["parser_metadata"] = {
            "backend": metadata.get("backend", "fallback"),
            "parser_mode": parser_mode,
            "artifact_ref": metadata.get("artifact_ref"),
            "chunk_index": metadata.get("chunk_index"),
            "source_type": metadata.get("source_type"),
        }
        return AdapterChunk(
            text=chunk.text,
            source_location=chunk.source_location,
            metadata=metadata,
            runtime_source_id=chunk.runtime_source_id,
            content_type=chunk.content_type,
            preview_ref=chunk.preview_ref,
        )

    def _is_absolute_path_value(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()

    def _source_order(self, chunk: Chunk, fallback_order: int) -> tuple[int, Any, Any, Any]:
        chunk_index = chunk.metadata_json.get("chunk_index")
        if isinstance(chunk_index, int):
            return (0, chunk_index, chunk.created_at, chunk.id)
        return (1, fallback_order, chunk.created_at, chunk.id)
