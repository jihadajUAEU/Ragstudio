import re
from pathlib import Path, PureWindowsPath
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn, ChunkSearchOut
from ragstudio.services.adapter import RAGAnythingAdapter


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

    async def index_document(self, document_id: str) -> list[ChunkOut] | None:
        document = await self.session.get(Document, document_id)
        if document is None:
            return None

        adapter_chunks = await self.adapter.index_document(document.artifact_path)
        await self.session.execute(delete(Chunk).where(Chunk.document_id == document.id))

        chunks = [
            Chunk(
                document_id=document.id,
                text=adapter_chunk.text,
                source_location=adapter_chunk.source_location,
                metadata_json=self._safe_metadata(adapter_chunk.metadata, document.id),
            )
            for adapter_chunk in adapter_chunks
        ]
        self.session.add_all(chunks)
        await self.session.commit()

        for chunk in chunks:
            await self.session.refresh(chunk)
        return [ChunkOut.model_validate(chunk) for chunk in chunks]

    async def search(self, search_in: ChunkSearchIn) -> ChunkSearchOut:
        limit = max(search_in.limit, 0)
        statement = select(Chunk)
        if search_in.document_ids:
            statement = statement.where(Chunk.document_id.in_(search_in.document_ids))
        result = await self.session.execute(statement.order_by(Chunk.created_at.asc(), Chunk.id.asc()))
        chunks = list(result.scalars().all())

        ranked = sorted(
            ((self._score(search_in.query, chunk), source_order, chunk) for source_order, chunk in enumerate(chunks)),
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
            if key not in {"artifact_path", "path", "file_path"} and not self._is_absolute_path_value(value)
        }
        safe["document_id"] = document_id
        return safe

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
