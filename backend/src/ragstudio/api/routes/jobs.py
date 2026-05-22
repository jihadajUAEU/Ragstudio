import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.db.models import Job
from ragstudio.schemas.jobs import (
    JobPage,
    JobQualityWarningRepairOut,
    JobQualityWarningsOut,
    JobStageEventOut,
)
from ragstudio.services.job_quality_warning_service import (
    JobQualityWarningRepairDocumentNotFound,
    JobQualityWarningRepairUnavailable,
    JobQualityWarningService,
)
from ragstudio.services.job_worker import JobWorker

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=JobPage)
async def list_jobs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> JobPage:
    items, total = await JobWorker(session).list(limit=limit, offset=offset)
    return JobPage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(items) < total,
    )


@router.get("/{job_id}/events")
async def job_events(
    job_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def stream() -> AsyncIterator[str]:
        sent = 0
        while True:
            current = await session.get(Job, job_id, populate_existing=True)
            if current is None:
                yield _sse_event("error", {"detail": "Job not found"})
                return

            events = _job_stage_events(current)
            for event in events[sent:]:
                yield _sse_event("job_stage", event.model_dump(mode="json"))
            sent = len(events)

            if current.status in {"succeeded", "failed"}:
                yield _sse_event(
                    "job_status",
                    {
                        "status": current.status,
                        "progress": current.progress,
                        "result": current.result or {},
                    },
                )
                return
            if await request.is_disconnected():
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/{job_id}/quality-warnings", response_model=JobQualityWarningsOut)
async def job_quality_warnings(
    job_id: str,
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=5000, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
) -> JobQualityWarningsOut:
    details = await JobQualityWarningService(
        session,
        http_client_provider=request.app.state.http_clients,
    ).details(
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
        result = await JobQualityWarningService(
            session,
            http_client_provider=request.app.state.http_clients,
        ).queue_repair_job(
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


def _job_stage_events(job: Job) -> list[JobStageEventOut]:
    result = job.result or {}
    raw_events = result.get("indexing_stage_events")
    if not isinstance(raw_events, list):
        raw_events = []
    events: list[JobStageEventOut] = []
    for event in raw_events:
        if not isinstance(event, dict):
            continue
        try:
            events.append(JobStageEventOut.model_validate(event))
        except ValueError:
            continue
    return events


def _sse_event(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
