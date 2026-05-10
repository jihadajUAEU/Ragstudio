from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ragstudio.config import AppSettings
from ragstudio.db.models import Chunk, GraphProjectionRecord
from ragstudio.schemas.common import new_id
from ragstudio.services.graph_materialization_service import GraphMaterializationService
from ragstudio.services.graph_workspace import workspace_label
from ragstudio.services.runtime_profile_service import (
    RuntimeProfileNotConfiguredError,
    RuntimeProfileService,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


class GraphProjectionCleanupError(RuntimeError):
    pass


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
            profile = await RuntimeProfileService(self.session, self.settings).get_profile(
                record.runtime_profile_id
            )
            self._ensure_projection_target(record, profile)
            chunks = await self._chunks(document_id)
            result = await self.materialization_service.replace_document_graph(
                document_id=document_id,
                profile=self._profile_for_record(profile, record),
                chunks=chunks,
            )
        except Exception as exc:
            result = GraphMaterializationService.failure(str(exc))
        record.status = result.status
        record.node_count = result.node_count
        record.edge_count = result.edge_count
        record.error = result.reason
        if result.status == "succeeded":
            await self._delete_stale_records_for_target(record)
        await self.session.flush()
        return result.to_dict()

    async def rematerialize_document(self, document_id: str) -> dict[str, Any]:
        record: GraphProjectionRecord | None = None
        try:
            profile = await RuntimeProfileService(self.session, self.settings).get_active_profile()
            chunks = await self._chunks(document_id)
            record = GraphProjectionRecord(
                document_id=document_id,
                runtime_profile_id=profile.id,
                status="pending",
                projection_run_id=new_id(),
                graph_workspace_label=workspace_label(profile),
                graph_storage_uri=profile.neo4j_uri,
                graph_storage_username=profile.neo4j_username,
                graph_storage_password=None,
            )
            self.session.add(record)
            await self.session.flush()
            result = await self.materialization_service.replace_document_graph(
                document_id=document_id,
                profile=self._profile_for_record(profile, record),
                chunks=chunks,
            )
        except Exception as exc:
            result = GraphMaterializationService.failure(str(exc))
            if record is None:
                record = GraphProjectionRecord(
                    document_id=document_id,
                    runtime_profile_id="unknown",
                    status="failed",
                    projection_run_id=new_id(),
                    error=result.reason,
                )
                self.session.add(record)
        record.status = result.status
        record.node_count = result.node_count
        record.edge_count = result.edge_count
        record.error = result.reason
        await self.session.flush()
        return result.to_dict()

    async def delete_document_graph(self, document_id: str) -> dict[str, Any]:
        records = await self._projection_records(document_id)
        if not records:
            return {
                "status": "skipped",
                "node_count": 0,
                "edge_count": 0,
                "reason": "no_projection_records",
            }

        cleanup_profile_ids = sorted(
            {
                record.runtime_profile_id
                for record in records
                if _needs_graph_cleanup(record)
            }
        )
        if not cleanup_profile_ids:
            await self._delete_projection_records(document_id)
            await self.session.flush()
            return {
                "status": "skipped",
                "node_count": 0,
                "edge_count": 0,
                "reason": "no_materialized_projection",
            }

        node_count = 0
        edge_count = 0
        profile_service = RuntimeProfileService(self.session, self.settings)
        for runtime_profile_id in cleanup_profile_ids:
            profile_records = [
                record
                for record in records
                if record.runtime_profile_id == runtime_profile_id
                and _needs_graph_cleanup(record)
            ]
            targets = {_target_key(record): record for record in profile_records}
            live_profile, missing_profile_error = await self._cleanup_live_profile(
                profile_service,
                runtime_profile_id,
            )
            for target_record in targets.values():
                if live_profile is None and not _has_stored_graph_target(target_record):
                    raise GraphProjectionCleanupError(missing_profile_error)
                if live_profile is not None:
                    self._ensure_projection_target(
                        target_record,
                        live_profile,
                        preserve_password=True,
                    )
                result = await self.materialization_service.delete_document_graph(
                    document_id=document_id,
                    profile=self._profile_for_record(live_profile, target_record),
                )
                if result.status != "succeeded":
                    detail = f": {result.reason}" if result.reason else ""
                    raise GraphProjectionCleanupError(
                        f"Graph projection cleanup {result.status}{detail}"
                    )
                node_count += result.node_count
                edge_count += result.edge_count

        await self._delete_projection_records(document_id)
        await self.session.flush()
        return {
            "status": "succeeded",
            "node_count": node_count,
            "edge_count": edge_count,
            "reason": None,
        }

    async def _chunks(self, document_id: str) -> list[Chunk]:
        return list(
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

    async def _delete_projection_records(self, document_id: str) -> None:
        await self.session.execute(
            delete(GraphProjectionRecord).where(GraphProjectionRecord.document_id == document_id)
        )

    async def _projection_records(self, document_id: str) -> list[GraphProjectionRecord]:
        return list(
            (
                await self.session.execute(
                    select(GraphProjectionRecord).where(
                        GraphProjectionRecord.document_id == document_id
                    )
                )
            )
            .scalars()
            .all()
        )

    async def _cleanup_live_profile(
        self,
        profile_service: RuntimeProfileService,
        runtime_profile_id: str,
    ) -> tuple[Any | None, str | None]:
        try:
            return await profile_service.get_profile(runtime_profile_id), None
        except RuntimeProfileNotConfiguredError as exc:
            return None, str(exc)

    async def _delete_stale_records_for_target(self, record: GraphProjectionRecord) -> None:
        stale_records = await self._projection_records(record.document_id)
        target = _target_key(record)
        stale_ids = [
            stale_record.id
            for stale_record in stale_records
            if stale_record.id != record.id and _target_key(stale_record) == target
        ]
        if not stale_ids:
            return
        await self.session.execute(
            delete(GraphProjectionRecord).where(GraphProjectionRecord.id.in_(stale_ids))
        )

    def _ensure_projection_target(
        self,
        record: GraphProjectionRecord,
        profile: Any,
        *,
        preserve_password: bool = False,
    ) -> None:
        if not record.graph_workspace_label:
            record.graph_workspace_label = workspace_label(profile)
        if not record.graph_storage_uri:
            record.graph_storage_uri = getattr(profile, "neo4j_uri", None)
        if not record.graph_storage_username:
            record.graph_storage_username = getattr(profile, "neo4j_username", None)
        if not preserve_password:
            record.graph_storage_password = None

    def _profile_for_record(
        self,
        profile: Any | None,
        record: GraphProjectionRecord,
    ) -> Any:
        fallback_username = getattr(profile, "neo4j_username", None)
        fallback_password = getattr(profile, "neo4j_password", None)
        return SimpleNamespace(
            id=getattr(profile, "id", record.runtime_profile_id),
            graph_workspace_label=record.graph_workspace_label,
            neo4j_uri=record.graph_storage_uri or getattr(profile, "neo4j_uri", None),
            neo4j_username=record.graph_storage_username or fallback_username,
            neo4j_password=record.graph_storage_password or fallback_password,
        )

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


def _needs_graph_cleanup(record: GraphProjectionRecord) -> bool:
    if record.status == "succeeded":
        return True
    return record.node_count > 0 or record.edge_count > 0


def _has_stored_graph_target(record: GraphProjectionRecord) -> bool:
    return bool(record.graph_workspace_label and record.graph_storage_uri)


def _target_key(
    record: GraphProjectionRecord,
) -> tuple[str, str | None, str | None, str | None, str | None]:
    return (
        record.runtime_profile_id,
        record.graph_workspace_label,
        record.graph_storage_uri,
        record.graph_storage_username,
        record.graph_storage_password,
    )
