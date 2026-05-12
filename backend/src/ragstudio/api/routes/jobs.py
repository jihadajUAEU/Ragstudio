from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.jobs import JobPage, JobQualityWarningsOut
from ragstudio.services.job_quality_warning_service import JobQualityWarningService
from ragstudio.services.job_worker import JobWorker

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=JobPage)
async def list_jobs(session: AsyncSession = Depends(get_session)) -> JobPage:
    items = await JobWorker(session).list()
    return JobPage(items=items, total=len(items))


@router.get("/{job_id}/quality-warnings", response_model=JobQualityWarningsOut)
async def job_quality_warnings(
    job_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=5000, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
) -> JobQualityWarningsOut:
    details = await JobQualityWarningService(session).details(
        job_id,
        offset=offset,
        limit=limit,
    )
    if details is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return details
