from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.chunks import ChunkSearchIn, ChunkSearchOut
from ragstudio.services.chunk_service import ChunkService

router = APIRouter(prefix="/api/chunks", tags=["chunks"])


@router.post("/search", response_model=ChunkSearchOut)
async def search_chunks(
    search_in: ChunkSearchIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ChunkSearchOut:
    return await ChunkService(
        session,
        request.app.state.settings.data_dir,
        http_client_provider=request.app.state.http_clients,
    ).search(search_in)
