from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import Run
from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.query import QueryIn, QueryOut
from ragstudio.schemas.runs import RunOut
from ragstudio.services.adapter import AdapterChunk, RAGAnythingAdapter
from ragstudio.services.chunk_service import ChunkService


class QueryService:
    def __init__(
        self,
        session: AsyncSession,
        data_dir: Path,
        adapter: RAGAnythingAdapter | None = None,
    ):
        self.session = session
        self.data_dir = data_dir
        self.adapter = adapter or RAGAnythingAdapter()

    async def run_query(self, payload: QueryIn) -> QueryOut:
        runs: list[RunOut] = []
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
                result = await self.adapter.query(payload.query, adapter_chunks, limit=payload.limit)
                query_ms = self._elapsed_ms(query_started_at)

                result_timings = result.get("timings", {})
                if not isinstance(result_timings, dict):
                    result_timings = {}
                run.status = StageStatus.SUCCEEDED.value
                run.answer = str(result.get("answer", ""))
                run.sources = self._result_list(result.get("sources")) or [self._source(chunk) for chunk in search.items]
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

            await self.session.commit()
            await self.session.refresh(run)
            runs.append(RunOut.model_validate(run))
        return QueryOut(runs=runs)

    async def list_runs(self) -> list[RunOut]:
        result = await self.session.execute(select(Run).order_by(Run.created_at.desc()))
        return [RunOut.model_validate(item) for item in result.scalars().all()]

    def _adapter_chunk(self, chunk: ChunkOut) -> AdapterChunk:
        metadata = {**chunk.metadata, "chunk_id": chunk.id, "document_id": chunk.document_id}
        return AdapterChunk(text=chunk.text, source_location=chunk.source_location, metadata=metadata)

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
