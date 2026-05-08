from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.services.job_worker import JobWorker

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    items = await JobWorker(session).list()
    return {"items": items, "total": len(items)}
