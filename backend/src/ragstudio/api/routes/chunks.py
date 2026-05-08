from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.config import AppSettings
from ragstudio.db.engine import make_engine, make_session_factory
from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn, ChunkSearchOut
from ragstudio.schemas.jobs import JobOut
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.document_service import DocumentService
from ragstudio.services.index_lifecycle_service import IndexLifecycleService
from ragstudio.services.runtime_profile_service import RuntimeProfileNotConfiguredError

router = APIRouter(prefix="/api/chunks", tags=["chunks"])


@router.post(
    "/index/{document_id}/jobs",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_index_document_job(
    document_id: str,
    options: IndexDocumentIn,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JobOut:
    service = DocumentService(session, request.app.state.settings.data_dir)
    job = await service.create_index_job(document_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Document not found")
    background_tasks.add_task(
        _run_index_document_job,
        request.app.state.settings,
        document_id,
        job.id,
        options,
    )
    return JobOut.model_validate(job)


@router.post("/index/{document_id}", response_model=list[ChunkOut])
async def index_document_chunks(
    document_id: str,
    request: Request,
    options: IndexDocumentIn | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[ChunkOut]:
    resolved_options = options or IndexDocumentIn()
    try:
        chunks = await IndexLifecycleService(
            session,
            request.app.state.settings,
        ).reindex_document(
            document_id,
            options=resolved_options,
        )
    except RuntimeProfileNotConfiguredError:
        chunks = await ChunkService(
            session,
            request.app.state.settings.data_dir,
        ).index_document(
            document_id,
            options=resolved_options,
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


async def _run_index_document_job(
    settings: AppSettings,
    document_id: str,
    job_id: str,
    options: IndexDocumentIn,
) -> None:
    engine = make_engine(settings.resolved_database_url)
    factory = make_session_factory(engine)
    try:
        async with factory() as background_session:
            await DocumentService(
                background_session,
                settings.data_dir,
                settings=settings,
            ).run_index_job(
                document_id,
                job_id,
                options,
            )
    finally:
        await engine.dispose()
