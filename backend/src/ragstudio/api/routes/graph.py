from fastapi import APIRouter

from ragstudio.schemas.graph import GraphOut
from ragstudio.services.graph_service import GraphService

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("", response_model=GraphOut)
async def get_graph() -> GraphOut:
    return await GraphService().get_graph()
