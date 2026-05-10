from __future__ import annotations

from typing import Any

from ragstudio.config import AppSettings
from ragstudio.db.models import Chunk, GraphProjectionRecord
from ragstudio.schemas.common import new_id
from ragstudio.services.graph_materialization_service import GraphMaterializationService
from ragstudio.services.runtime_profile_service import RuntimeProfileService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class GraphProjectionRunner:
    def __init__(
        self,
        session: AsyncSession,
        settings: AppSettings,
        *,
        materialization_service: GraphMaterializationService | None = None,
    ):
        self.session = session
        self.settings = settings
        self.materialization_service = materialization_service or GraphMaterializationService()

    async def materialize_pending(self, document_id: str) -> dict[str, Any]:
        record = await self._latest_record(document_id, status="pending")
        if record is None:
            return {
                "status": "not_run",
                "node_count": 0,
                "edge_count": 0,
                "reason": "no_pending_projection",
            }

        record.projection_run_id = new_id()
        try:
            profile = await RuntimeProfileService(self.session, self.settings).get_active_profile()
            chunks = list(
                (
                    await self.session.execute(
                        select(Chunk)
                        .where(Chunk.document_id == document_id)
                        .order_by(Chunk.created_at.asc(), Chunk.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            result = await self.materialization_service.replace_document_graph(
                document_id=document_id,
                profile=profile,
                chunks=chunks,
            )
        except Exception as exc:
            result = GraphMaterializationService.failure(str(exc))
        record.status = result.status
        record.node_count = result.node_count
        record.edge_count = result.edge_count
        record.error = result.reason
        await self.session.flush()
        return result.to_dict()

    async def _latest_record(
        self,
        document_id: str,
        *,
        status: str | None = None,
    ) -> GraphProjectionRecord | None:
        statement = select(GraphProjectionRecord).where(
            GraphProjectionRecord.document_id == document_id
        )
        if status is not None:
            statement = statement.where(GraphProjectionRecord.status == status)
        statement = statement.order_by(GraphProjectionRecord.created_at.desc()).limit(1)
        return await self.session.scalar(statement)
