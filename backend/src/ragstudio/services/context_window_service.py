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
        seed_orders = _seed_orders(seeds)
        seed_chunk_ids = {seed.chunk_id for seed in seeds if seed.chunk_id}
        seed_relationship_ids = _seed_relationship_ids(seeds)
        seed_parent_ids = _seed_parent_ids(seeds)
        if not seed_orders and not seed_relationship_ids and not seed_parent_ids:
            return []
        scoped_documents = [document_id for document_id in document_ids if document_id]
        if not scoped_documents:
            return []

        rows = (
            await self.session.execute(
                select(Chunk).where(Chunk.document_id.in_(scoped_documents))
            )
        ).scalars().all()
        rows = sorted(
            rows,
            key=lambda row: (
                row.document_id,
                _sort_order(row.metadata_json),
                row.id,
            ),
        )
        candidates: list[EvidenceCandidate] = []
        for row in rows:
            if row.id in seed_chunk_ids:
                continue
            metadata = dict(row.metadata_json) if isinstance(row.metadata_json, dict) else {}
            order = _reading_order(metadata)
            adjacent = _is_adjacent(row.document_id, order, seed_orders)
            relationship_reasons = _relationship_reasons(
                row_id=row.id,
                metadata=metadata,
                seed_chunk_ids=seed_chunk_ids,
                seed_relationship_ids=seed_relationship_ids,
                seed_parent_ids=seed_parent_ids,
            )
            if not adjacent and not relationship_reasons:
                continue
            source_location = row.source_location if isinstance(row.source_location, dict) else {}
            evidence_context = evidence_context_from_metadata(
                metadata,
                source_location=source_location,
                content_type=row.content_type,
            )
            if evidence_context:
                metadata["evidence_context"] = evidence_context
            reasons = ["context_window"]
            if adjacent:
                reasons.append("reading_order_adjacent")
            reasons.extend(
                reason for reason in relationship_reasons if reason not in reasons
            )
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
                    reasons=reasons,
                    retrieval_pass="context_window",
                    scope_status="in_scope",
                )
            )
            if len(candidates) >= max(limit, 1):
                break
        return candidates


def _seed_orders(seeds: list[EvidenceCandidate]) -> set[tuple[str, int]]:
    orders: set[tuple[str, int]] = set()
    for seed in seeds:
        order = _reading_order(seed.metadata)
        if seed.document_id and order is not None:
            orders.add((seed.document_id, order))
    return orders


def _seed_relationship_ids(seeds: list[EvidenceCandidate]) -> set[str]:
    values: set[str] = set()
    for seed in seeds:
        values.update(_relationship_chunk_ids(seed.metadata))
    return values


def _seed_parent_ids(seeds: list[EvidenceCandidate]) -> set[str]:
    values: set[str] = set()
    for seed in seeds:
        parent_id = _string_value(seed.metadata, "parent_chunk_id")
        if parent_id:
            values.add(parent_id)
    return values


def _reading_order(metadata: dict[str, Any]) -> int | None:
    for key in ("reading_order", "block_index"):
        value = metadata.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _sort_order(metadata: Any) -> tuple[int, int]:
    order = _reading_order(metadata if isinstance(metadata, dict) else {})
    return (0, order) if order is not None else (1, 0)


def _is_adjacent(
    document_id: str,
    order: int | None,
    seed_orders: set[tuple[str, int]],
) -> bool:
    if order is None:
        return False
    return any(
        document_id == seed_document_id and abs(order - seed_order) == 1
        for seed_document_id, seed_order in seed_orders
    )


def _relationship_reasons(
    *,
    row_id: str,
    metadata: dict[str, Any],
    seed_chunk_ids: set[str],
    seed_relationship_ids: set[str],
    seed_parent_ids: set[str],
) -> list[str]:
    reasons: list[str] = []
    if row_id in seed_parent_ids:
        reasons.append("parent_context")
    if row_id in seed_relationship_ids:
        reasons.append("linked_context")
    row_parent_id = _string_value(metadata, "parent_chunk_id")
    if row_parent_id and row_parent_id in seed_parent_ids:
        reasons.append("sibling_context")
    if _relationship_chunk_ids(metadata) & seed_chunk_ids:
        reasons.append("linked_context")
    return list(dict.fromkeys(reasons))


def _relationship_chunk_ids(metadata: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in ("previous_chunk_id", "next_chunk_id"):
        value = _string_value(metadata, key)
        if value:
            values.add(value)
    return values


def _string_value(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
