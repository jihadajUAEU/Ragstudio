from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.graph import GraphOut
from ragstudio.services.graph_service import GraphService, RuntimeGraphUnavailableError

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("", response_model=GraphOut)
async def get_graph(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> GraphOut:
    try:
        return await GraphService(session, request.app.state.settings).get_graph()
    except RuntimeGraphUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
