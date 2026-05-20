from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.graph import GraphOut
from ragstudio.services.graph_service import GraphService, RuntimeGraphUnavailableError

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("", response_model=GraphOut, response_model_exclude_none=True)
async def get_graph(
    request: Request,
    document_id: str | None = Query(default=None),
    limit: int = Query(default=2_000, ge=0),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> GraphOut:
    try:
        include_page_info = bool(
            {"document_id", "limit", "offset"}.intersection(request.query_params.keys())
        )
        return await GraphService(session, request.app.state.settings).get_graph(
            document_id=document_id,
            limit=limit,
            offset=offset,
            include_page_info=include_page_info,
        )
    except RuntimeGraphUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
