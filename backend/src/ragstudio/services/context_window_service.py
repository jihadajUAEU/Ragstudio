from __future__ import annotations

from typing import Any

from ragstudio.db.models import Chunk
from ragstudio.services.evidence_context import evidence_context_from_metadata
from ragstudio.services.retrieval_evidence import EvidenceCandidate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class ContextWindowService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def window_for(
        self,
        seeds: list[EvidenceCandidate],
        *,
        document_ids: list[str],
        limit: int,
    ) -> list[EvidenceCandidate]:
        seed_orders = {
            (seed.document_id, _reading_order(seed.metadata))
            for seed in seeds
            if seed.document_id and _reading_order(seed.metadata) is not None
        }
        if not seed_orders:
            return []
        scoped_documents = [document_id for document_id in document_ids if document_id]
        if not scoped_documents:
            return []

        rows = (
            await self.session.execute(
                select(Chunk).where(Chunk.document_id.in_(scoped_documents))
            )
        ).scalars().all()
        seed_chunk_ids = {seed.chunk_id for seed in seeds if seed.chunk_id}
        rows = sorted(
            rows,
            key=lambda row: (
                row.document_id,
                _reading_order(row.metadata_json if isinstance(row.metadata_json, dict) else {})
                or 0,
                row.id,
            ),
        )
        candidates: list[EvidenceCandidate] = []
        for row in rows:
            if row.id in seed_chunk_ids:
                continue
            metadata = dict(row.metadata_json) if isinstance(row.metadata_json, dict) else {}
            order = _reading_order(metadata)
            if order is None:
                continue
            if not _is_adjacent(row.document_id, order, seed_orders):
                continue
            source_location = row.source_location if isinstance(row.source_location, dict) else {}
            evidence_context = evidence_context_from_metadata(
                metadata,
                source_location=source_location,
                content_type=row.content_type,
            )
            if evidence_context:
                metadata["evidence_context"] = evidence_context
            candidates.append(
                EvidenceCandidate(
                    candidate_id=f"context-window:{row.id}",
                    text=row.text,
                    document_id=row.document_id,
                    chunk_id=row.id,
                    source_location=source_location,
                    metadata=metadata,
                    tool="metadata",
                    tool_rank=len(candidates) + 1,
                    base_score=8.0,
                    boost_score=1.0,
                    final_score=9.0,
                    reasons=["context_window"],
                    retrieval_pass="context_window",
                    scope_status="in_scope",
                )
            )
            if len(candidates) >= max(limit, 1):
                break
        return candidates


def _reading_order(metadata: dict[str, Any]) -> int | None:
    value = metadata.get("reading_order") or metadata.get("block_index")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _is_adjacent(
    document_id: str,
    order: int,
    seed_orders: set[tuple[str | None, int | None]],
) -> bool:
    return any(
        document_id == seed_document_id
        and seed_order is not None
        and abs(order - seed_order) == 1
        for seed_document_id, seed_order in seed_orders
    )
