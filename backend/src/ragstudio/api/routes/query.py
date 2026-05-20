from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.query import QueryIn, QueryOut
from ragstudio.services.query_service import QueryResourceNotFoundError, QueryService
from ragstudio.services.reranker_service import RerankerService

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
            session_factory=request.app.state.session_factory,
            reranker_service=RerankerService(
                allowed_hosts=request.app.state.settings.allowed_reranker_hosts,
                http_client_provider=request.app.state.http_clients,
            ),
        ).run_query(payload)
    except QueryResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
