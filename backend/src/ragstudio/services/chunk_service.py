import re
from pathlib import Path, PureWindowsPath
from typing import Any

from ragstudio.db.models import Chunk, Document, SettingsProfile
from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn, ChunkSearchOut
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn, ParserMode
from ragstudio.services.adapter import AdapterChunk, RAGAnythingAdapter
from ragstudio.services.mineru_client import MinerUClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


class ChunkService:
    def __init__(
        self,
        session: AsyncSession,
        data_dir: Path,
        adapter: RAGAnythingAdapter | None = None,
    ):
        self.session = session
        self.data_dir = data_dir
        self.adapter = adapter or RAGAnythingAdapter()

    async def index_document(
        self,
        document_id: str,
        *,
        options: IndexDocumentIn | None = None,
        commit: bool = True,
    ) -> list[ChunkOut] | None:
        document = await self.session.get(Document, document_id)
        if document is None:
            return None

        options = options or IndexDocumentIn()
        adapter_chunks = await self._adapter_chunks(document, options)
        await self.session.execute(delete(Chunk).where(Chunk.document_id == document.id))

        chunks = [
            Chunk(
                document_id=document.id,
                text=adapter_chunk.text,
                source_location=adapter_chunk.source_location,
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
    ) -> list[AdapterChunk]:
        if options.parser_mode == "local_fallback":
            return await self.adapter.index_document(document.artifact_path)
        try:
            return await self._mineru_adapter_chunks(document.id, options=options)
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
    ) -> list[AdapterChunk]:
        document = await self.session.get(Document, document_id)
        if document is None:
            return []
        settings = await self.session.get(SettingsProfile, "default")
        if settings is None or not settings.mineru_base_url:
            raise RuntimeError("MinerU base URL is not configured.")
        client = MinerUClient(
            base_url=settings.mineru_base_url,
            timeout_ms=settings.mineru_timeout_ms or 1_800_000,
            poll_interval_ms=settings.mineru_poll_interval_ms or 1_000,
        )
        artifact_dir = self.data_dir / "mineru-artifacts" / document.id
        job_result = await client.parse_document(
            artifact_path=document.artifact_path,
            document_id=document.id,
            artifact_dir=artifact_dir,
        )
        return client.normalize_artifact_zip(
            artifact_zip=job_result.artifact_zip,
            extract_dir=artifact_dir / "extracted",
            document_id=document.id,
            parser_mode=options.parser_mode,
            parse_job_id=job_result.parse_job_id,
        )

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
                (self._score(search_in.query, chunk), source_order, chunk)
                for source_order, chunk in enumerate(chunks)
            ),
            key=lambda item: (
                -item[0],
                self._source_order(item[2], item[1]),
            ),
        )
        if search_in.query.strip():
            ranked = [item for item in ranked if item[0] > 0]

        items = [self._chunk_out_with_score(chunk, score) for score, _, chunk in ranked[:limit]]
        return ChunkSearchOut(items=items, total=len(items))

    def _chunk_out_with_score(self, chunk: Chunk, score: float) -> ChunkOut:
        output = ChunkOut.model_validate(chunk)
        output.metadata = {**output.metadata, "score": score}
        return output

    def _safe_metadata(self, metadata: dict[str, Any], document_id: str) -> dict[str, Any]:
        safe = {
            key: value
            for key, value in metadata.items()
            if key not in {"artifact_path", "path", "file_path"}
            and not self._is_absolute_path_value(value)
        }
        safe["document_id"] = document_id
        return safe

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

    def _is_absolute_path_value(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()

    def _source_order(self, chunk: Chunk, fallback_order: int) -> tuple[int, Any, Any, Any]:
        chunk_index = chunk.metadata_json.get("chunk_index")
        if isinstance(chunk_index, int):
            return (0, chunk_index, chunk.created_at, chunk.id)
        return (1, fallback_order, chunk.created_at, chunk.id)

    def _score(self, query: str, chunk: Chunk) -> float:
        query_text = query.strip().lower()
        chunk_text = chunk.text.lower()
        if not query_text:
            return 1.0

        query_terms = self._terms(query_text)
        chunk_terms = self._terms(chunk_text)
        if not query_terms or not chunk_terms:
            return 0.0

        overlap = query_terms & chunk_terms
        coverage = len(overlap) / len(query_terms)
        density = len(overlap) / len(chunk_terms)
        phrase_bonus = 1.0 if query_text in chunk_text else 0.0
        return (coverage * 10.0) + (density * 2.0) + phrase_bonus

    def _terms(self, value: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", value.lower()))
