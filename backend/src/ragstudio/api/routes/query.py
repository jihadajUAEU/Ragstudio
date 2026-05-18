from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.query import QueryIn, QueryOut, SimulateRetrievalIn, SimulateRetrievalOut
from ragstudio.services.query_service import QueryResourceNotFoundError, QueryService

router = APIRouter(prefix="/api/query", tags=["query"])


@router.post("", response_model=QueryOut)
async def query(
    payload: QueryIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> QueryOut:
    try:
        return await QueryService(
            session,
            request.app.state.settings.data_dir,
            settings=request.app.state.settings,
        ).run_query(payload)
    except QueryResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/simulate-retrieval", response_model=SimulateRetrievalOut)
async def simulate_retrieval(
    payload: SimulateRetrievalIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SimulateRetrievalOut:
    try:
        return await QueryService(
            session,
            request.app.state.settings.data_dir,
            settings=request.app.state.settings,
        ).simulate_retrieval(payload)
    except QueryResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
