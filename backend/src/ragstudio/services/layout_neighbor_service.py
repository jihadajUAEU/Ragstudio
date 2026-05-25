from __future__ import annotations

from typing import Any

from ragstudio.db.models import Chunk
from ragstudio.services.evidence_context import evidence_context_from_metadata
from ragstudio.services.layout_contracts import (
    LayoutExpansionPolicy,
    layout_policy_from_metadata,
)
from ragstudio.services.retrieval_evidence import EvidenceCandidate
from ragstudio.services.retrieval_policy import DEFAULT_RETRIEVAL_POLICY
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class LayoutNeighborService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.policy = DEFAULT_RETRIEVAL_POLICY.layout_neighbor

    async def neighbors_for(
        self,
        *,
        seed_chunk_ids: list[str],
        document_ids: list[str],
        limit: int,
    ) -> list[EvidenceCandidate]:
        seed_ids = set(seed_chunk_ids)
        if not seed_ids:
            return []

        seed_rows = (
            await self.session.execute(select(Chunk).where(Chunk.id.in_(seed_ids)))
        ).scalars().all()
        if not seed_rows:
            return []

        layout_policy = _layout_policy_for_seeds(
            seed_rows,
            default_vertical_proximity=self.policy.vertical_proximity,
        )
        pages = {
            page
            for seed in seed_rows
            if (page := _page(seed.source_location)) is not None
        }
        references = {
            reference
            for seed in seed_rows
            if (reference := _reference(seed)) is not None
        }
        layout_groups = {
            group
            for seed in seed_rows
            if (group := _layout_group(seed)) is not None
        }
        reading_orders = {
            (seed.document_id, order)
            for seed in seed_rows
            if seed.document_id
            and (order := _reading_order(seed.metadata_json)) is not None
        }
        if not pages and not references and not layout_groups and not reading_orders:
            return []

        # Map page -> seed bboxes so contract-driven spatial relationships stay local.
        seed_bboxes: dict[int, list[tuple[float, float, float, float]]] = {}
        for seed in seed_rows:
            page = _page(seed.source_location)
            if page is not None:
                bbox = _chunk_bbox(seed)
                if bbox is not None:
                    seed_bboxes.setdefault(page, []).append(bbox)

        seed_document_ids = [seed.document_id for seed in seed_rows if seed.document_id]
        scoped_document_ids = list(
            dict.fromkeys(document_ids if document_ids else seed_document_ids)
        )
        if not scoped_document_ids:
            return []

        statement = select(Chunk).where(Chunk.document_id.in_(scoped_document_ids))
        rows = (
            await self.session.execute(
                statement.order_by(Chunk.created_at.asc(), Chunk.id.asc())
            )
        ).scalars().all()

        candidates: list[EvidenceCandidate] = []
        for row in rows:
            if row.id in seed_ids:
                continue

            metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
            if _is_blocked(metadata):
                continue

            relationships = layout_policy.relationships
            same_page = "same_page" in relationships and _page(row.source_location) in pages
            same_reference = (
                "same_reference" in relationships and _reference(row) in references
            )
            same_layout_group = (
                "layout_group" in relationships and _layout_group(row) in layout_groups
            )
            reading_order_neighbor = (
                "reading_order" in relationships
                and _is_adjacent_reading_order(
                    row.document_id,
                    _reading_order(metadata),
                    reading_orders,
                )
            )
            bbox_overlap = "bbox_overlap" in relationships and _has_bbox_overlap(
                row,
                seed_bboxes,
                policy=layout_policy,
            )
            table_caption = "table_caption" in relationships and _has_caption_relation(
                seed_rows,
                row,
                family="table",
            )
            figure_caption = "figure_caption" in relationships and _has_caption_relation(
                seed_rows,
                row,
                family="figure",
            )
            equation = "equation" in relationships and _has_equation_relation(
                seed_rows,
                row,
            )
            if (
                not same_page
                and not same_reference
                and not same_layout_group
                and not reading_order_neighbor
                and not bbox_overlap
                and not table_caption
                and not figure_caption
                and not equation
            ):
                continue

            # Check spatial proximity if they are on the same page
            is_spatial_proximity = False
            page = _page(row.source_location)
            if same_page and page is not None and page in seed_bboxes:
                row_bbox = _chunk_bbox(row)
                if row_bbox is not None:
                    row_y_mid = (row_bbox[1] + row_bbox[3]) / 2
                    for seed_bbox in seed_bboxes[page]:
                        seed_y_mid = (seed_bbox[1] + seed_bbox[3]) / 2
                        if abs(row_y_mid - seed_y_mid) <= layout_policy.vertical_proximity:
                            is_spatial_proximity = True
                            break

            source_location = row.source_location if isinstance(row.source_location, dict) else {}
            candidate_metadata = dict(metadata)
            evidence_context = evidence_context_from_metadata(
                candidate_metadata,
                source_location=source_location,
                content_type=row.content_type,
            )
            if evidence_context:
                candidate_metadata["evidence_context"] = evidence_context

            reasons = ["layout_neighbor"]
            boost_score = self.policy.base_boost_score
            final_score = self.policy.base_final_score
            if is_spatial_proximity:
                reasons.append("spatial_proximity")
                boost_score += self.policy.spatial_proximity_boost
                final_score += self.policy.spatial_proximity_boost
            if bbox_overlap:
                reasons.append("bbox_overlap")
                boost_score += self.policy.spatial_proximity_boost
                final_score += self.policy.spatial_proximity_boost
            if same_layout_group:
                reasons.append("layout_group")
                boost_score += self.policy.layout_group_boost
                final_score += self.policy.layout_group_boost
            if reading_order_neighbor:
                reasons.append("reading_order_neighbor")
                boost_score += self.policy.reading_order_neighbor_boost
                final_score += self.policy.reading_order_neighbor_boost
            if table_caption:
                reasons.append("table_caption")
                boost_score += self.policy.layout_group_boost
                final_score += self.policy.layout_group_boost
            if figure_caption:
                reasons.append("figure_caption")
                boost_score += self.policy.layout_group_boost
                final_score += self.policy.layout_group_boost
            if equation:
                reasons.append("equation")
                boost_score += self.policy.layout_group_boost
                final_score += self.policy.layout_group_boost

            candidates.append(
                EvidenceCandidate(
                    candidate_id=f"layout-neighbor:{row.id}",
                    text=row.text,
                    document_id=row.document_id,
                    chunk_id=row.id,
                    source_location=source_location,
                    metadata=candidate_metadata,
                    tool="metadata",
                    tool_rank=len(candidates) + 1,
                    base_score=self.policy.base_score,
                    boost_score=boost_score,
                    final_score=final_score,
                    reasons=reasons,
                    retrieval_pass="layout_neighbor",
                    scope_status="in_scope",
                )
            )
            if len(candidates) >= max(limit, 1):
                break

        return candidates


def _layout_policy_for_seeds(
    seed_rows: list[Chunk],
    *,
    default_vertical_proximity: float,
) -> LayoutExpansionPolicy:
    verified_policies: list[LayoutExpansionPolicy] = []
    for seed in seed_rows:
        metadata = seed.metadata_json if isinstance(seed.metadata_json, dict) else {}
        contract = metadata.get("layout_contract")
        if isinstance(contract, dict) and contract.get("verified") is True:
            verified_policies.append(layout_policy_from_metadata(metadata))
    if not verified_policies:
        policy = LayoutExpansionPolicy()
        return LayoutExpansionPolicy(
            relationships=policy.relationships,
            vertical_proximity=default_vertical_proximity,
            horizontal_overlap_min=policy.horizontal_overlap_min,
        )
    return LayoutExpansionPolicy(
        relationships=frozenset().union(
            *(policy.relationships for policy in verified_policies)
        ),
        vertical_proximity=max(policy.vertical_proximity for policy in verified_policies),
        horizontal_overlap_min=min(
            policy.horizontal_overlap_min for policy in verified_policies
        ),
    )


def _page(source_location: Any) -> int | None:
    if not isinstance(source_location, dict):
        return None
    page = source_location.get("page") or source_location.get("page_start")
    return page if isinstance(page, int) else None


def _reference(chunk: Chunk) -> str | None:
    if isinstance(chunk.source_location, dict) and isinstance(
        chunk.source_location.get("reference"), str
    ):
        return chunk.source_location["reference"]

    metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
    reference_metadata = metadata.get("reference_metadata")
    if not isinstance(reference_metadata, dict):
        return None
    references = reference_metadata.get("references")
    if isinstance(references, list) and references:
        return str(references[0])
    return None


def _layout_group(chunk: Chunk) -> str | None:
    metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
    for key in ("layout_group_id", "table_id", "figure_id", "caption_group_id"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _is_blocked(metadata: dict[str, Any]) -> bool:
    policy = metadata.get("quality_action_policy")
    if not isinstance(policy, dict):
        return False
    if policy.get("action") == "block":
        return True
    return policy.get("index_vector") is False and policy.get("project_graph") is False


def _reading_order(metadata: Any) -> int | None:
    if not isinstance(metadata, dict):
        return None
    for key in ("reading_order", "block_index"):
        value = metadata.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _is_adjacent_reading_order(
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


def _chunk_bbox(chunk: Chunk) -> tuple[float, float, float, float] | None:
    sl = chunk.source_location
    if isinstance(sl, dict):
        for key in ("bbox", "coordinates"):
            val = sl.get(key)
            if isinstance(val, list | tuple) and len(val) == 4:
                try:
                    return (float(val[0]), float(val[1]), float(val[2]), float(val[3]))
                except (ValueError, TypeError):
                    pass
    mj = chunk.metadata_json
    if isinstance(mj, dict):
        for key in ("bbox", "coordinates"):
            val = mj.get(key)
            if isinstance(val, list | tuple) and len(val) == 4:
                try:
                    return (float(val[0]), float(val[1]), float(val[2]), float(val[3]))
                except (ValueError, TypeError):
                    pass
    return None


def _has_bbox_overlap(
    row: Chunk,
    seed_bboxes: dict[int, list[tuple[float, float, float, float]]],
    *,
    policy: LayoutExpansionPolicy,
) -> bool:
    page = _page(row.source_location)
    if page is None or page not in seed_bboxes:
        return False
    row_bbox = _chunk_bbox(row)
    if row_bbox is None:
        return False
    row_y_mid = (row_bbox[1] + row_bbox[3]) / 2
    for seed_bbox in seed_bboxes[page]:
        seed_y_mid = (seed_bbox[1] + seed_bbox[3]) / 2
        if abs(row_y_mid - seed_y_mid) > policy.vertical_proximity:
            continue
        if _horizontal_overlap_ratio(seed_bbox, row_bbox) >= policy.horizontal_overlap_min:
            return True
    return False


def _horizontal_overlap_ratio(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    overlap = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    width = max(1.0, min(left[2] - left[0], right[2] - right[0]))
    return overlap / width


def _has_caption_relation(seed_rows: list[Chunk], row: Chunk, *, family: str) -> bool:
    return any(
        _share_layout_group(seed, row)
        and (
            (_is_caption(seed) and _is_layout_family(row, family))
            or (_is_caption(row) and _is_layout_family(seed, family))
        )
        for seed in seed_rows
    )


def _has_equation_relation(seed_rows: list[Chunk], row: Chunk) -> bool:
    return any(
        _share_layout_group(seed, row)
        and (_is_layout_family(seed, "equation") or _is_layout_family(row, "equation"))
        for seed in seed_rows
    )


def _share_layout_group(left: Chunk, right: Chunk) -> bool:
    return bool(_layout_group_values(left) & _layout_group_values(right))


def _layout_group_values(chunk: Chunk) -> set[str]:
    metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
    source_location = chunk.source_location if isinstance(chunk.source_location, dict) else {}
    values: set[str] = set()
    for key in ("layout_group_id", "table_id", "figure_id", "caption_group_id"):
        for container in (metadata, source_location):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                values.add(value.strip())
    return values


def _is_caption(chunk: Chunk) -> bool:
    return "caption" in _layout_tokens(chunk)


def _is_layout_family(chunk: Chunk, family: str) -> bool:
    tokens = _layout_tokens(chunk)
    if family == "table":
        return bool(tokens & {"table", "table_cell", "table_row", "table_header"})
    if family == "figure":
        return bool(tokens & {"figure", "image", "picture"})
    if family == "equation":
        return bool(tokens & {"equation", "formula"})
    return family in tokens


def _layout_tokens(chunk: Chunk) -> set[str]:
    metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
    values: list[Any] = [
        chunk.content_type,
        metadata.get("content_type"),
        metadata.get("layout_role"),
        metadata.get("block_type"),
    ]
    layout = metadata.get("layout")
    if isinstance(layout, dict):
        values.extend([layout.get("role"), layout.get("type")])
    tokens: set[str] = set()
    for value in values:
        if isinstance(value, str):
            normalized = value.lower().replace("-", "_").replace("/", " ")
            for part in normalized.split():
                if not part:
                    continue
                tokens.add(part)
                tokens.update(piece for piece in part.split("_") if piece)
    return tokens
