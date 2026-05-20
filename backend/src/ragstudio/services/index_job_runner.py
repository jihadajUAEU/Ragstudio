from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from contextlib import suppress
from datetime import timedelta
from typing import Any

from ragstudio.config import AppSettings
from ragstudio.db.engine import make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document, IndexRecord, Job
from ragstudio.schemas.common import StageStatus, now_utc
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.document_service import DocumentService
from ragstudio.services.domain_metadata_quality_gate import DomainMetadataQualityGate
from ragstudio.services.graph_projection_runner import GraphProjectionRunner
from ragstudio.services.index_progress import IndexStage, update_job_stage
from ragstudio.services.job_queue_service import JobLeaseLostError, JobQueueService
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class IndexJobRunner:
    def __init__(
        self,
        session: AsyncSession,
        settings: AppSettings,
        *,
        worker_id: str,
        lease_seconds: int = 300,
        heartbeat_interval_seconds: float = 60.0,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self._external_session_factory = session_factory
        self.heartbeat_interval_seconds = min(
            heartbeat_interval_seconds,
            max(lease_seconds / 3, 1.0),
        )

    async def run(self, job: Job) -> None:
        if job.type != "index_document":
            raise RuntimeError(f"Unsupported job type: {job.type}")
        if job.target_id is None:
            raise RuntimeError(f"Index job {job.id} has no target document.")
        target_id = job.target_id

        if job.recovery_action == "resume_graph_projection":
            await self._run_with_lease(job, lambda: self._resume_graph_projection(job))
            return

        options = self._index_options(job)
        await self._run_with_lease(
            job,
            lambda: DocumentService(
                self.session,
                self.settings.data_dir,
                settings=self.settings,
            ).run_index_job(
                target_id,
                job.id,
                options,
                ensure_active_lease=lambda: self._ensure_current_lease(job.id),
            ),
        )
        await self._clear_terminal_lease(job.id)

    async def _resume_graph_projection(self, job: Job) -> None:
        document = await self.session.get(Document, job.target_id)
        if document is None:
            raise RuntimeError(f"Document {job.target_id} does not exist.")

        result = await GraphProjectionRunner(
            self.session,
            self.settings,
        ).materialize_pending(document.id)
        status = str(result.get("status") or "unknown")
        graph_warning = self._graph_materialization_warning(result)
        chunks = await self._chunks(document.id)
        chunk_count = len(chunks)
        quality_gate = DomainMetadataQualityGate()
        parser_quality = quality_gate.parser_quality_summary(chunks)
        parser_quality_details = quality_gate.parser_quality_details(chunks)
        index_quality_report = quality_gate.index_quality_report_from_chunks(chunks)
        await self._mark_index_records_succeeded(document.id, chunk_count)

        job.result = {
            **(job.result or {}),
            "document_id": document.id,
            "chunk_count": chunk_count,
            "graph_materialization": result,
            "parser_quality": parser_quality,
            "parser_quality_details": parser_quality_details,
            "index_quality_report": index_quality_report,
        }
        job.logs = [*(job.logs or []), f"Graph projection materialization {status}."][-20:]
        if graph_warning:
            job.logs = [*(job.logs or []), f"Ready with warnings: {graph_warning}"][-20:]

        await self._require_active_lease(job)
        update_job_stage(
            job,
            IndexStage.READY_WITH_WARNINGS if graph_warning else IndexStage.READY,
            detail=(
                f"Indexed {chunk_count} chunks with warnings."
                if graph_warning
                else f"Indexed {chunk_count} chunks."
            ),
            chunk_count=chunk_count,
            warning=graph_warning,
        )
        document.status = StageStatus.SUCCEEDED.value
        job.status = StageStatus.SUCCEEDED.value
        job.progress = 100
        job.worker_id = None
        job.lease_expires_at = None
        job.recovery_action = None
        await self.session.flush()
        await self.session.commit()

    def _index_options(self, job: Job) -> IndexDocumentIn:
        raw_options: dict[str, Any] | None = job.job_options or None
        if raw_options is None:
            result = job.result or {}
            fallback = result.get("index_options")
            if isinstance(fallback, dict):
                raw_options = fallback
        return IndexDocumentIn.model_validate(raw_options or {})

    async def _run_with_lease(
        self,
        job: Job,
        operation: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        await self._require_active_lease(job)
        stop_heartbeat = asyncio.Event()
        heartbeat_task = asyncio.create_task(self._heartbeat_until_stopped(job.id, stop_heartbeat))
        operation_task = asyncio.create_task(operation())
        try:
            while True:
                done, _pending = await asyncio.wait(
                    {operation_task, heartbeat_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if operation_task in done:
                    await operation_task
                    return
                if heartbeat_task in done:
                    await self._handle_heartbeat_completion(heartbeat_task, operation_task)
                    return
        finally:
            stop_heartbeat.set()
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _handle_heartbeat_completion(
        self,
        heartbeat_task: asyncio.Task[None],
        operation_task: asyncio.Task[None],
    ) -> None:
        try:
            await heartbeat_task
        except Exception:
            operation_task.cancel()
            with suppress(asyncio.CancelledError):
                await operation_task
            raise
        await operation_task

    async def _require_active_lease(self, job: Job) -> None:
        await JobQueueService(self.session).heartbeat(
            job,
            self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        await self.session.commit()

    async def _ensure_current_lease(self, job_id: str) -> None:
        timestamp = now_utc()
        with self.session.no_autoflush:
            result = await self.session.execute(
                select(Job.status, Job.worker_id, Job.lease_expires_at)
                .where(Job.id == job_id)
                .with_for_update()
            )
            row = result.one_or_none()
        if row is None:
            raise JobLeaseLostError(f"Job {job_id} no longer exists.")
        status, worker_id, lease_expires_at = row
        if (
            status != StageStatus.RUNNING.value
            or worker_id != self.worker_id
            or lease_expires_at is None
            or lease_expires_at <= timestamp
        ):
            raise JobLeaseLostError(f"Job {job_id} lease is no longer held by {self.worker_id}.")
        await self.session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                heartbeat_at=timestamp,
                lease_expires_at=timestamp + timedelta(seconds=self.lease_seconds),
            )
            .execution_options(synchronize_session=False)
        )
        await self.session.flush()

    async def _heartbeat_until_stopped(self, job_id: str, stop_heartbeat: asyncio.Event) -> None:
        engine = None
        session_factory = self._external_session_factory
        if session_factory is None:
            engine = make_engine(self.settings.resolved_database_url)
            session_factory = make_session_factory(engine)
        try:
            while not stop_heartbeat.is_set():
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        stop_heartbeat.wait(),
                        timeout=self.heartbeat_interval_seconds,
                    )
                    return
                async with session_factory() as heartbeat_session:
                    should_continue = await self._heartbeat_external(heartbeat_session, job_id)
                    await heartbeat_session.commit()
                if not should_continue:
                    return
        finally:
            if engine is not None:
                await engine.dispose()

    async def _heartbeat_external(self, session: AsyncSession, job_id: str) -> bool:
        job = await session.get(Job, job_id)
        if job is None:
            raise JobLeaseLostError(f"Job {job_id} no longer exists.")
        if job.status in {StageStatus.SUCCEEDED.value, StageStatus.FAILED.value}:
            if job.worker_id in {None, self.worker_id}:
                return False
            raise JobLeaseLostError(
                f"Job {job.id} lease is no longer held by {self.worker_id}."
            )
        await JobQueueService(session).heartbeat(
            job,
            self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        return True

    async def _clear_terminal_lease(self, job_id: str) -> None:
        job = await self.session.scalar(
            select(Job)
            .where(Job.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None or job.status not in {
            StageStatus.SUCCEEDED.value,
            StageStatus.FAILED.value,
        }:
            return
        if job.worker_id not in {None, self.worker_id}:
            raise JobLeaseLostError(f"Job {job.id} lease is no longer held by {self.worker_id}.")
        if job.worker_id == self.worker_id and job.lease_expires_at is not None:
            job.heartbeat_at = now_utc()
        job.worker_id = None
        job.lease_expires_at = None
        job.recovery_action = None
        await self.session.flush()
        await self.session.commit()

    async def _chunks(self, document_id: str) -> list[Chunk]:
        result = await self.session.execute(
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.created_at.asc(), Chunk.id.asc())
        )
        return list(result.scalars().all())

    async def _mark_index_records_succeeded(self, document_id: str, chunk_count: int) -> None:
        await self.session.execute(
            update(IndexRecord)
            .where(IndexRecord.document_id == document_id)
            .values(
                status=StageStatus.SUCCEEDED.value,
                chunk_count=chunk_count,
                error=None,
            )
            .execution_options(synchronize_session=False)
        )

    def _graph_materialization_warning(self, result: dict[str, Any]) -> str | None:
        status = result.get("status")
        if status not in {"failed", "skipped"}:
            return None
        fallback = f"Graph materialization {status}."
        return str(result.get("reason") or result.get("error") or fallback)
