from collections.abc import Awaitable, Callable
from pathlib import Path, PureWindowsPath
from typing import Any

from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn, ChunkSearchOut
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn, ParserMode
from ragstudio.services.adapter import AdapterChunk, RAGAnythingAdapter
from ragstudio.services.arabic_text import arabic_tokens, normalize_arabic_text
from ragstudio.services.chunk_lexical_search_repository import ChunkLexicalSearchRepository
from ragstudio.services.chunk_sanitizer import sanitize_db_text, sanitize_db_value
from ragstudio.services.chunk_splitter import ChunkSplitter
from ragstudio.services.document_parser_service import DocumentParserService
from ragstudio.services.hybrid_chunk_search import ChunkScore, HybridChunkSearch
from ragstudio.services.index_quality_gate import IndexQualityGate
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
        document_parser: DocumentParserService | None = None,
        quality_gate: IndexQualityGate | None = None,
    ):
        self.session = session
        self.data_dir = data_dir
        self.adapter = adapter or RAGAnythingAdapter()
        self.mineru_client_factory = mineru_client_factory or MinerUClient
        self.chunk_splitter = chunk_splitter or ChunkSplitter()
        self.chunk_search = chunk_search or HybridChunkSearch()
        self.relationship_builder = relationship_builder or MinerURelationshipBuilder()
        self.quality_gate = quality_gate or IndexQualityGate()
        self.document_parser = document_parser or DocumentParserService(
            session,
            data_dir,
            local_parser=self.adapter,
            mineru_client_factory=self.mineru_client_factory,
        )

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
        self.quality_gate.validate_adapter_chunks(
            adapter_chunks,
            language=self._quality_language(options.domain_metadata),
        )
        await self.session.execute(delete(Chunk).where(Chunk.document_id == document.id))

        chunks = []
        for adapter_chunk in adapter_chunks:
            text = sanitize_db_text(adapter_chunk.text)
            metadata = self._merge_metadata(
                adapter_chunk.metadata,
                options.domain_metadata,
                options.parser_mode,
            )
            chunks.append(
                Chunk(
                    document_id=document.id,
                    text=text,
                    text_search_ar=normalize_arabic_text(text),
                    tokens_ar=arabic_tokens(text),
                    extraction_quality=self._extraction_quality(metadata),
                    source_location=sanitize_db_value(adapter_chunk.source_location),
                    metadata_json=self._safe_metadata(metadata, document.id),
                )
            )
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
        return await self.document_parser.parse(
            document,
            options,
            on_mineru_status=on_mineru_status,
        )

    async def validate_strict_mineru_sidecar(self, options: IndexDocumentIn) -> None:
        await self.document_parser.validate_strict_mineru_sidecar(options)

    async def search(self, search_in: ChunkSearchIn) -> ChunkSearchOut:
        limit = max(search_in.limit, 0)
        statement = select(Chunk)
        if search_in.document_ids:
            statement = statement.where(Chunk.document_id.in_(search_in.document_ids))
        result = await self.session.execute(
            statement.order_by(Chunk.created_at.asc(), Chunk.id.asc())
        )
        chunks = list(result.scalars().all())
        prefiltered = await ChunkLexicalSearchRepository(self.session).arabic_prefilter(
            query=search_in.query,
            document_ids=search_in.document_ids,
            limit=max(search_in.limit, 20),
        )
        prefiltered_ids = {chunk.id for chunk in prefiltered}
        chunks = [*prefiltered, *[chunk for chunk in chunks if chunk.id not in prefiltered_ids]]

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

    async def chunks_by_id(self, chunk_ids: list[str]) -> list[ChunkOut]:
        unique_ids = list(dict.fromkeys(chunk_id for chunk_id in chunk_ids if chunk_id))
        if not unique_ids:
            return []

        result = await self.session.execute(select(Chunk).where(Chunk.id.in_(unique_ids)))
        chunks_by_id = {chunk.id: chunk for chunk in result.scalars().all()}
        return [
            ChunkOut.model_validate(chunks_by_id[chunk_id])
            for chunk_id in unique_ids
            if chunk_id in chunks_by_id
        ]

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
        if not metadata.get("text_search_ar"):
            metadata["text_search_ar"] = chunk.text_search_ar or normalize_arabic_text(output.text)
        if not metadata.get("tokens_ar"):
            metadata["tokens_ar"] = chunk.tokens_ar or arabic_tokens(output.text)
        if not metadata.get("extraction_quality"):
            metadata["extraction_quality"] = chunk.extraction_quality or {}
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

    def _extraction_quality(self, metadata: dict[str, Any]) -> dict[str, Any]:
        extraction_quality = metadata.get("extraction_quality")
        if isinstance(extraction_quality, dict):
            return sanitize_db_value(extraction_quality)
        return {}

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

    def _source_order(self, chunk: Chunk, fallback_order: int) -> tuple[int, Any, Any, Any]:
        chunk_index = chunk.metadata_json.get("chunk_index")
        if isinstance(chunk_index, int):
            return (0, chunk_index, chunk.created_at, chunk.id)
        return (1, fallback_order, chunk.created_at, chunk.id)
