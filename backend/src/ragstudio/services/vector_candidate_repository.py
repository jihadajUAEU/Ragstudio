from __future__ import annotations

from typing import Any

from ragstudio.db.models import Chunk
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession


class VectorCandidateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def candidate_rows(
        self,
        *,
        query: str,
        document_ids: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        terms = _terms(query)
        statement = select(Chunk)
        if document_ids:
            statement = statement.where(Chunk.document_id.in_(document_ids))
        if terms:
            statement = statement.where(
                or_(*(Chunk.text.ilike(f"%{_escape_like(term)}%", escape="\\") for term in terms))
            )
        result = await self.session.execute(
            statement.order_by(Chunk.created_at.asc(), Chunk.id.asc()).limit(max(limit, 1))
        )
        rows = []
        for rank, chunk in enumerate(result.scalars().all(), start=1):
            metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
            policy = metadata.get("quality_action_policy")
            if isinstance(policy, dict) and policy.get("index_vector") is False:
                continue
            rows.append(
                {
                    "candidate_id": f"vector-row:{chunk.id}",
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "text": chunk.text,
                    "source_location": chunk.source_location,
                    "metadata": metadata,
                    "score": max(0.01, 1.0 / rank),
                    "rank": rank,
                }
            )
        return rows


def _terms(query: str) -> list[str]:
    return [term for term in query.casefold().split() if len(term) >= 3][:5]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
