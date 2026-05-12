from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.jobs import (
    JobPage,
    JobQualityWarningRepairOut,
    JobQualityWarningsOut,
)
from ragstudio.services.job_quality_warning_service import (
    JobQualityWarningRepairDocumentNotFound,
    JobQualityWarningRepairUnavailable,
    JobQualityWarningService,
)
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


@router.post(
    "/{job_id}/quality-warnings/fix",
    response_model=JobQualityWarningRepairOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def fix_job_quality_warnings(
    job_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JobQualityWarningRepairOut:
    settings = request.app.state.settings
    try:
        result = await JobQualityWarningService(session).queue_repair_job(
            job_id,
            data_dir=settings.data_dir,
            settings=settings,
        )
    except JobQualityWarningRepairDocumentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JobQualityWarningRepairUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return result
