from __future__ import annotations

from typing import Any

from ragstudio.db.models import Chunk
from ragstudio.services.context_contracts import context_policy_from_metadata
from ragstudio.services.evidence_context import evidence_context_from_metadata
from ragstudio.services.retrieval_evidence import EvidenceCandidate
from ragstudio.services.retrieval_policy import DEFAULT_RETRIEVAL_POLICY
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class ContextWindowService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.policy = DEFAULT_RETRIEVAL_POLICY.context_window

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
        seed_heading_paths = _seed_paths(seeds, key="heading_path", relationship="heading_path")
        seed_section_paths = _seed_paths(seeds, key="section_path", relationship="section_path")
        seed_reference_ranges = _seed_reference_ranges(seeds)
        if (
            not seed_orders
            and not seed_relationship_ids
            and not seed_parent_ids
            and not seed_heading_paths
            and not seed_section_paths
            and not seed_reference_ranges
        ):
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
            structural_reasons = _structural_relationship_reasons(
                metadata,
                seed_heading_paths=seed_heading_paths,
                seed_section_paths=seed_section_paths,
                seed_reference_ranges=seed_reference_ranges,
            )
            if not adjacent and not relationship_reasons and not structural_reasons:
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
            reasons.extend(reason for reason in structural_reasons if reason not in reasons)
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
                    base_score=self.policy.base_score,
                    boost_score=self.policy.boost_score,
                    final_score=self.policy.final_score,
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


def _seed_paths(
    seeds: list[EvidenceCandidate],
    *,
    key: str,
    relationship: str,
) -> set[tuple[str, ...]]:
    values: set[tuple[str, ...]] = set()
    for seed in seeds:
        policy = context_policy_from_metadata(seed.metadata)
        if relationship not in policy.relationships:
            continue
        path = _path_value(seed.metadata.get(key))
        if path:
            values.add(path)
    return values


def _seed_reference_ranges(
    seeds: list[EvidenceCandidate],
) -> list[tuple[dict[str, dict[str, int]], int]]:
    values: list[tuple[dict[str, dict[str, int]], int]] = []
    for seed in seeds:
        policy = context_policy_from_metadata(seed.metadata)
        if "reference_range" not in policy.relationships:
            continue
        reference_range = _reference_range_value(seed.metadata.get("reference_identity_range"))
        if reference_range:
            values.append((reference_range, policy.max_reference_distance))
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


def _structural_relationship_reasons(
    metadata: dict[str, Any],
    *,
    seed_heading_paths: set[tuple[str, ...]],
    seed_section_paths: set[tuple[str, ...]],
    seed_reference_ranges: list[tuple[dict[str, dict[str, int]], int]],
) -> list[str]:
    reasons: list[str] = []
    if _same_path(metadata, seed_heading_paths, "heading_path"):
        reasons.append("heading_path_context")
    if _same_path(metadata, seed_section_paths, "section_path"):
        reasons.append("section_path_context")
    if _near_reference_range(metadata, seed_reference_ranges):
        reasons.append("reference_range_context")
    return reasons


def _relationship_chunk_ids(metadata: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in ("previous_chunk_id", "next_chunk_id"):
        value = _string_value(metadata, key)
        if value:
            values.add(value)
    return values


def _same_path(metadata: dict[str, Any], seed_paths: set[tuple[str, ...]], key: str) -> bool:
    path = _path_value(metadata.get(key))
    return bool(path and path in seed_paths)


def _path_value(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if isinstance(item, str) and item.strip())
    return ()


def _near_reference_range(
    metadata: dict[str, Any],
    seed_ranges: list[tuple[dict[str, dict[str, int]], int]],
) -> bool:
    current = _reference_range_value(metadata.get("reference_identity_range"))
    if not current:
        return False
    return any(
        _reference_ranges_are_near(current, seed, max_distance=max_distance)
        for seed, max_distance in seed_ranges
    )


def _reference_ranges_are_near(
    current: dict[str, dict[str, int]],
    seed: dict[str, dict[str, int]],
    *,
    max_distance: int,
) -> bool:
    seed_fields = list(seed)
    if not seed_fields or not all(field in current for field in seed_fields):
        return False
    unit_field = seed_fields[-1]
    parent_fields = seed_fields[:-1]
    if any(_range_distance(seed[field], current[field]) != 0 for field in parent_fields):
        return False
    return _range_distance(seed[unit_field], current[unit_field]) <= max_distance


def _reference_range_value(value: Any) -> dict[str, dict[str, int]]:
    if not isinstance(value, dict):
        return {}
    ranges: dict[str, dict[str, int]] = {}
    for field, raw_range in value.items():
        if not isinstance(field, str) or not isinstance(raw_range, dict):
            continue
        start = raw_range.get("start")
        end = raw_range.get("end")
        if isinstance(start, int) and not isinstance(start, bool):
            if isinstance(end, int) and not isinstance(end, bool):
                ranges[field] = {"start": start, "end": end}
            else:
                ranges[field] = {"start": start, "end": start}
    return ranges


def _range_distance(left: dict[str, int], right: dict[str, int]) -> int:
    left_start = left["start"]
    left_end = left["end"]
    right_start = right["start"]
    right_end = right["end"]
    if left_start <= right_end and right_start <= left_end:
        return 0
    if left_end < right_start:
        return right_start - left_end
    return left_start - right_end


def _string_value(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
