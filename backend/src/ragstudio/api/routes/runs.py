from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.runs import RunPage
from ragstudio.services.query_service import QueryService

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("", response_model=RunPage)
async def list_runs(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> RunPage:
    items = await QueryService(session, request.app.state.settings.data_dir).list_runs()
    return RunPage(items=items, total=len(items))
