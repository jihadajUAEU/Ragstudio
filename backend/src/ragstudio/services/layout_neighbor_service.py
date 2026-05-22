from __future__ import annotations

from typing import Any

from ragstudio.db.models import Chunk
from ragstudio.services.evidence_context import evidence_context_from_metadata
from ragstudio.services.retrieval_evidence import EvidenceCandidate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class LayoutNeighborService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
        if not pages and not references:
            return []

        statement = select(Chunk)
        if document_ids:
            statement = statement.where(Chunk.document_id.in_(document_ids))
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

            same_page = _page(row.source_location) in pages
            same_reference = _reference(row) in references
            if not same_page and not same_reference:
                continue

            source_location = row.source_location if isinstance(row.source_location, dict) else {}
            candidate_metadata = dict(metadata)
            evidence_context = evidence_context_from_metadata(
                candidate_metadata,
                source_location=source_location,
                content_type=row.content_type,
            )
            if evidence_context:
                candidate_metadata["evidence_context"] = evidence_context

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
                    base_score=9.0,
                    boost_score=1.5,
                    final_score=10.5,
                    reasons=["layout_neighbor"],
                    retrieval_pass="layout_neighbor",
                    scope_status="in_scope",
                )
            )
            if len(candidates) >= max(limit, 1):
                break

        return candidates


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


def _is_blocked(metadata: dict[str, Any]) -> bool:
    policy = metadata.get("quality_action_policy")
    if not isinstance(policy, dict):
        return False
    if policy.get("action") == "block":
        return True
    return policy.get("index_vector") is False and policy.get("project_graph") is False
