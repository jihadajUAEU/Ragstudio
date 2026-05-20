from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.runs import RunPage
from ragstudio.services.query_service import QueryService

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("", response_model=RunPage)
async def list_runs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> RunPage:
    items, total = await QueryService(
        session,
        request.app.state.settings.data_dir,
        settings=request.app.state.settings,
    ).list_runs(limit=limit, offset=offset)
    return RunPage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(items) < total,
    )
