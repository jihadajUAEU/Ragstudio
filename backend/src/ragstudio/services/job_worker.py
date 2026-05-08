from ragstudio.db.models import Job
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.jobs import JobOut
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class JobWorker:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def build(job_type: str, target_id: str | None) -> Job:
        return Job(type=job_type, target_id=target_id, status=StageStatus.READY.value, progress=0)

    async def enqueue(self, job_type: str, target_id: str | None) -> JobOut:
        job = self.build(job_type, target_id)
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return JobOut.model_validate(job)

    async def mark_running(self, job: Job, log: str | None = None) -> None:
        job.status = StageStatus.RUNNING.value
        job.progress = max(job.progress, 1)
        if log:
            job.logs = [*job.logs, log]
        await self.session.commit()

    async def update_progress(
        self,
        job: Job,
        *,
        progress: int | None = None,
        log: str | None = None,
        result_patch: dict[str, object] | None = None,
    ) -> None:
        if progress is not None:
            job.progress = max(0, min(progress, 99))
        if log:
            job.logs = [*job.logs, log]
        if result_patch:
            job.result = {**job.result, **result_patch}
        await self.session.commit()

    async def mark_succeeded(
        self,
        job: Job,
        *,
        progress: int = 100,
        log: str | None = None,
        result_patch: dict[str, object] | None = None,
    ) -> None:
        job.status = StageStatus.SUCCEEDED.value
        job.progress = progress
        if log:
            job.logs = [*job.logs, log]
        if result_patch:
            job.result = {**job.result, **result_patch}
        await self.session.commit()

    async def mark_failed(self, job: Job, exc: Exception) -> None:
        job.status = StageStatus.FAILED.value
        job.progress = 100
        job.logs = [*job.logs, str(exc)]
        job.result = {**job.result, "error": str(exc)}
        await self.session.commit()

    async def list(self) -> list[JobOut]:
        result = await self.session.execute(select(Job).order_by(Job.created_at.desc()))
        return [JobOut.model_validate(item) for item in result.scalars().all()]
