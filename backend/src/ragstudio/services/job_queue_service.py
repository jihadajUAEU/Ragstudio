from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from ragstudio.db.models import Document, Job
from ragstudio.schemas.common import StageStatus, new_id, now_utc
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession


class JobLeaseLostError(RuntimeError):
    pass


class JobQueueService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def enqueue_index_document(
        self,
        document_id: str,
        options: dict[str, Any],
    ) -> Job:
        job = Job(
            id=new_id(),
            type="index_document",
            target_id=document_id,
            status=StageStatus.READY.value,
            progress=0,
            logs=["Indexing queued."],
            result={"document_id": document_id, "index_options": options},
            job_options=options,
            max_attempts=3,
            available_at=now_utc(),
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def claim_next(
        self,
        worker_id: str,
        job_types: Sequence[str],
        lease_seconds: int = 300,
    ) -> Job | None:
        if not job_types:
            return None

        timestamp = now_utc()
        job = await self.session.scalar(
            select(Job)
            .where(
                Job.type.in_(list(job_types)),
                Job.status == StageStatus.READY.value,
                Job.available_at <= timestamp,
                Job.attempts < Job.max_attempts,
            )
            .order_by(Job.created_at.asc(), Job.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None

        job.status = StageStatus.RUNNING.value
        job.worker_id = worker_id
        job.lease_expires_at = timestamp + timedelta(seconds=lease_seconds)
        job.heartbeat_at = timestamp
        job.attempts += 1
        job.logs = self._append_log(job.logs, f"Worker {worker_id} claimed job.")
        await self.session.flush()
        return job

    async def heartbeat(
        self,
        job: Job,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> None:
        timestamp = now_utc()
        current = await self._require_active_lease(job, worker_id, timestamp)
        current.heartbeat_at = timestamp
        current.lease_expires_at = timestamp + timedelta(seconds=lease_seconds)
        await self.session.flush()

    async def mark_succeeded(
        self,
        job: Job,
        *,
        worker_id: str,
        log: str,
        result_patch: dict[str, Any],
    ) -> None:
        timestamp = now_utc()
        current = await self._require_active_lease(job, worker_id, timestamp)
        current.status = StageStatus.SUCCEEDED.value
        current.progress = 100
        current.worker_id = None
        current.lease_expires_at = None
        current.recovery_action = None
        current.heartbeat_at = timestamp
        current.logs = self._append_log(current.logs, log)
        current.result = {**(current.result or {}), **result_patch}
        await self.session.flush()

    async def mark_failed(self, job: Job, *, worker_id: str, reason: str) -> None:
        timestamp = now_utc()
        current = await self._require_active_lease(job, worker_id, timestamp)
        current.status = StageStatus.FAILED.value
        current.progress = 100
        current.worker_id = None
        current.lease_expires_at = None
        current.heartbeat_at = timestamp
        current.logs = self._append_log(current.logs, reason)
        current.result = {**(current.result or {}), "error": reason}
        await self._mark_index_document_failed(current, reason)
        await self.session.flush()

    async def recover_expired_jobs(self, now: datetime | None = None) -> int:
        timestamp = now or now_utc()
        result = await self.session.execute(
            select(Job)
            .where(
                Job.status == StageStatus.RUNNING.value,
                or_(Job.lease_expires_at.is_(None), Job.lease_expires_at < timestamp),
            )
            .with_for_update(skip_locked=True)
        )

        recovered = 0
        for job in result.scalars().all():
            missing_lease = job.lease_expires_at is None
            job.worker_id = None
            job.lease_expires_at = None
            job.heartbeat_at = timestamp
            if job.attempts >= job.max_attempts:
                lease_state = "missing" if missing_lease else "expired"
                log = f"Worker lease {lease_state} after maximum attempts; indexing failed."
                job.status = StageStatus.FAILED.value
                job.progress = 100
                job.recovery_action = None
                job.result = {**(job.result or {}), "error": log}
                await self._mark_index_document_failed(job, log)
            else:
                stage = (job.result or {}).get("indexing_stage")
                stage_name = stage.get("stage") if isinstance(stage, dict) else None

                job.status = StageStatus.READY.value
                if stage_name in {"search_ready", "graph_enriching"}:
                    job.recovery_action = "resume_graph_projection"
                    log = (
                        f"Recovered {'missing' if missing_lease else 'expired'} worker lease; "
                        "graph projection will resume "
                        "from persisted chunks."
                    )
                else:
                    job.recovery_action = "retry_full_index"
                    lease_state = "missing" if missing_lease else "expired"
                    log = f"Recovered {lease_state} worker lease; full indexing will retry."
            job.logs = self._append_log(job.logs, log)
            recovered += 1

        await self.session.flush()
        return recovered

    async def _mark_index_document_failed(self, job: Job, reason: str) -> None:
        if job.type != "index_document" or not job.target_id:
            return
        job.result = {
            **(job.result or {}),
            "error": reason,
            "indexing_stage": {
                "stage": "failed",
                "label": "Failed",
                "detail": reason,
                "progress": 100,
            },
        }
        document = await self.session.get(Document, job.target_id, with_for_update=True)
        if document is not None:
            document.status = StageStatus.FAILED.value

    async def _require_active_lease(self, job: Job, worker_id: str, timestamp: datetime) -> Job:
        current = await self.session.scalar(
            select(Job)
            .where(Job.id == job.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            current is None
            or current.status != StageStatus.RUNNING.value
            or current.worker_id != worker_id
            or current.lease_expires_at is None
            or current.lease_expires_at <= timestamp
        ):
            raise JobLeaseLostError(f"Job {job.id} lease is no longer held by {worker_id}.")
        return current

    @staticmethod
    def _append_log(logs: list[str] | None, log: str) -> list[str]:
        return [*(logs or []), log][-20:]
