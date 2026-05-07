from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.query import QueryIn, QueryOut
from ragstudio.services.query_service import QueryService

router = APIRouter(prefix="/api/query", tags=["query"])


@router.post("", response_model=QueryOut)
async def query(
    payload: QueryIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> QueryOut:
    return await QueryService(session, request.app.state.settings.data_dir).run_query(payload)
