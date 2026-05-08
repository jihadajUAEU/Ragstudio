from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn, ChunkSearchOut
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.chunk_service import ChunkService

router = APIRouter(prefix="/api/chunks", tags=["chunks"])


@router.post("/index/{document_id}", response_model=list[ChunkOut])
async def index_document_chunks(
    document_id: str,
    request: Request,
    options: IndexDocumentIn | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[ChunkOut]:
    chunks = await ChunkService(session, request.app.state.settings.data_dir).index_document(
        document_id,
        options=options or IndexDocumentIn(),
    )
    if chunks is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return chunks


@router.post("/search", response_model=ChunkSearchOut)
async def search_chunks(
    search_in: ChunkSearchIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ChunkSearchOut:
    return await ChunkService(session, request.app.state.settings.data_dir).search(search_in)
