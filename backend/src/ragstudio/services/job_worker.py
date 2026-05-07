from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import Job
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.jobs import JobOut


class JobWorker:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def enqueue(self, job_type: str, target_id: str | None) -> JobOut:
        job = Job(type=job_type, target_id=target_id, status=StageStatus.READY.value, progress=0)
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return JobOut.model_validate(job)

    async def list(self) -> list[JobOut]:
        result = await self.session.execute(select(Job).order_by(Job.created_at.desc()))
        return [JobOut.model_validate(item) for item in result.scalars().all()]
