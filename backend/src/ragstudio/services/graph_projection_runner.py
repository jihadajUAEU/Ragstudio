from __future__ import annotations

from datetime import UTC, datetime
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
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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

        profile_service = RuntimeProfileService(self.session, self.settings)
        live_profiles: dict[str, Any | None] = {}
        missing_profile_errors: dict[str, str | None] = {}
        for runtime_profile_id in sorted({record.runtime_profile_id for record in records}):
            live_profile, missing_profile_error = await self._cleanup_live_profile(
                profile_service,
                runtime_profile_id,
            )
            live_profiles[runtime_profile_id] = live_profile
            missing_profile_errors[runtime_profile_id] = missing_profile_error

        targets: dict[
            tuple[str | None, str | None, str | None],
            list[GraphProjectionRecord],
        ] = {}
        for record in records:
            targets.setdefault(
                _effective_target_key(record, live_profiles[record.runtime_profile_id]),
                [],
            ).append(record)

        cleaned_target_groups = [
            (target_key, target_records)
            for target_key, target_records in targets.items()
            if any(record.cleanup_status == "succeeded" for record in target_records)
        ]
        for target_key, target_records in cleaned_target_groups:
            if any(record.cleanup_status != "succeeded" for record in target_records):
                await self._mark_cleanup_succeeded(target_records, target_key)

        cleanup_target_groups = [
            (target_key, target_records)
            for target_key, target_records in targets.items()
            if not any(record.cleanup_status == "succeeded" for record in target_records)
            and any(_needs_graph_cleanup(record) for record in target_records)
        ]
        if not cleanup_target_groups:
            await self._delete_projection_records(document_id)
            await self.session.flush()
            if cleaned_target_groups:
                return {
                    "status": "succeeded",
                    "node_count": 0,
                    "edge_count": 0,
                    "reason": None,
                }
            return {
                "status": "skipped",
                "node_count": 0,
                "edge_count": 0,
                "reason": "no_materialized_projection",
            }

        node_count = 0
        edge_count = 0
        for target_key, target_records in cleanup_target_groups:
            target_record = _cleanup_target_representative(target_records, live_profiles)
            live_profile = live_profiles.get(target_record.runtime_profile_id)
            if live_profile is None and not _target_key_has_stored_graph_target(target_key):
                raise GraphProjectionCleanupError(
                    missing_profile_errors.get(target_record.runtime_profile_id)
                )
            await self._mark_cleanup_running(target_records, target_key)
            try:
                result = await self.materialization_service.delete_document_graph(
                    document_id=document_id,
                    profile=self._profile_for_record(live_profile, target_record),
                )
            except Exception as exc:
                message = f"Graph projection cleanup failed: {exc}"
                await self._mark_cleanup_failed(target_records, target_key, message)
                raise GraphProjectionCleanupError(message) from exc
            if result.status != "succeeded":
                detail = f": {result.reason}" if result.reason else ""
                message = f"Graph projection cleanup {result.status}{detail}"
                await self._mark_cleanup_failed(target_records, target_key, message)
                raise GraphProjectionCleanupError(message)
            await self._mark_cleanup_succeeded(target_records, target_key)
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

    async def _mark_cleanup_running(
        self,
        records: list[GraphProjectionRecord],
        target_key: tuple[str | None, str | None, str | None],
    ) -> None:
        await self._persist_cleanup_marker(
            records,
            target_key=target_key,
            cleanup_status="running",
            cleanup_error=None,
        )

    async def _mark_cleanup_succeeded(
        self,
        records: list[GraphProjectionRecord],
        target_key: tuple[str | None, str | None, str | None],
    ) -> None:
        await self._persist_cleanup_marker(
            records,
            target_key=target_key,
            cleanup_status="succeeded",
            cleanup_error=None,
        )

    async def _mark_cleanup_failed(
        self,
        records: list[GraphProjectionRecord],
        target_key: tuple[str | None, str | None, str | None],
        error: str,
    ) -> None:
        await self._persist_cleanup_marker(
            records,
            target_key=target_key,
            cleanup_status="failed",
            cleanup_error=error,
        )

    async def _persist_cleanup_marker(
        self,
        records: list[GraphProjectionRecord],
        *,
        target_key: tuple[str | None, str | None, str | None],
        cleanup_status: str,
        cleanup_error: str | None,
    ) -> None:
        attempted_at = datetime.now(UTC)
        (
            graph_workspace_label,
            graph_storage_uri,
            graph_storage_username,
        ) = target_key
        record_ids = [record.id for record in records]
        for record in records:
            record.graph_workspace_label = graph_workspace_label
            record.graph_storage_uri = graph_storage_uri
            record.graph_storage_username = graph_storage_username
            record.cleanup_status = cleanup_status
            record.cleanup_error = cleanup_error
            record.cleanup_attempted_at = attempted_at
        bind = self.session.bind
        if bind is None:
            bind = self.session.get_bind()
        marker_session_factory = async_sessionmaker(bind, expire_on_commit=False)
        async with marker_session_factory() as marker_session:
            async with marker_session.begin():
                await marker_session.execute(
                    update(GraphProjectionRecord)
                    .where(GraphProjectionRecord.id.in_(record_ids))
                    .values(
                        graph_workspace_label=graph_workspace_label,
                        graph_storage_uri=graph_storage_uri,
                        graph_storage_username=graph_storage_username,
                        cleanup_status=cleanup_status,
                        cleanup_error=cleanup_error,
                        cleanup_attempted_at=attempted_at,
                    )
                )

    async def _projection_records(self, document_id: str) -> list[GraphProjectionRecord]:
        return list(
            (
                await self.session.execute(
                    select(GraphProjectionRecord)
                    .where(GraphProjectionRecord.document_id == document_id)
                    .order_by(
                        GraphProjectionRecord.created_at.asc(),
                        GraphProjectionRecord.id.asc(),
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
    if record.cleanup_status == "succeeded":
        return False
    if record.status == "succeeded":
        return True
    return record.node_count > 0 or record.edge_count > 0


def _has_stored_graph_target(record: GraphProjectionRecord) -> bool:
    return bool(record.graph_workspace_label and record.graph_storage_uri)


def _has_stored_graph_auth(record: GraphProjectionRecord) -> bool:
    return _has_stored_graph_target(record) and (
        record.graph_storage_username is None or record.graph_storage_password is not None
    )


def _cleanup_target_representative(
    records: list[GraphProjectionRecord],
    live_profiles: dict[str, Any | None],
) -> GraphProjectionRecord:
    return min(
        records,
        key=lambda record: (
            live_profiles.get(record.runtime_profile_id) is None,
            not _has_stored_graph_auth(record),
        ),
    )


def _target_key_has_stored_graph_target(
    target_key: tuple[str | None, str | None, str | None],
) -> bool:
    return bool(target_key[0] and target_key[1])


def _effective_target_key(
    record: GraphProjectionRecord,
    profile: Any | None,
) -> tuple[str | None, str | None, str | None]:
    if profile is None:
        return _target_key(record)
    return (
        record.graph_workspace_label or workspace_label(profile),
        record.graph_storage_uri or getattr(profile, "neo4j_uri", None),
        record.graph_storage_username or getattr(profile, "neo4j_username", None),
    )


def _target_key(
    record: GraphProjectionRecord,
) -> tuple[str | None, str | None, str | None]:
    return (
        record.graph_workspace_label,
        record.graph_storage_uri,
        record.graph_storage_username,
    )
