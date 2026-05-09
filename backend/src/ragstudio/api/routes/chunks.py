import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.background import create_background_task
from ragstudio.api.deps import get_session
from ragstudio.config import AppSettings
from ragstudio.db.engine import make_engine, make_session_factory
from ragstudio.db.models import Document
from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn, ChunkSearchOut
from ragstudio.schemas.jobs import JobOut
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.document_service import ActiveIndexJobError, DocumentService
from ragstudio.services.index_lifecycle_service import (
    IndexLifecycleService,
    RuntimeHealthBlockedError,
)
from ragstudio.services.metadata_json_schema import validate_custom_json
from ragstudio.services.runtime_factory import RuntimeUnavailableError
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_profile_service import (
    RuntimeProfileNotConfiguredError,
    RuntimeProfileService,
)

router = APIRouter(prefix="/api/chunks", tags=["chunks"])
logger = logging.getLogger(__name__)


@router.post(
    "/index/{document_id}/jobs",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_index_document_job(
    document_id: str,
    options: IndexDocumentIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JobOut:
    settings = request.app.state.settings
    _validate_index_options(options)
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        profile = await RuntimeProfileService(session, settings).get_active_profile()
    except RuntimeProfileNotConfiguredError:
        profile = None
    if profile is not None and profile.runtime_mode != "fallback":
        health_service = _runtime_health_service(session)
        checks = await health_service.check(profile)
        blocking = health_service.blocking_failures(checks)
        if blocking:
            detail = "; ".join(f"{item.name}: {item.detail}" for item in blocking)
            raise HTTPException(status_code=409, detail=detail)

    try:
        await ChunkService(session, settings.data_dir).validate_strict_mineru_sidecar(options)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    service = DocumentService(
        session,
        settings.data_dir,
        settings=settings,
    )
    try:
        job = await service.create_index_job(document_id)
    except ActiveIndexJobError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Document not found")
    create_background_task(
        request.app,
        _run_index_document_job(request.app.state.settings, document_id, job.id, options)
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
    settings = request.app.state.settings
    _validate_index_options(resolved_options)
    try:
        profile = await RuntimeProfileService(session, settings).get_active_profile()
    except RuntimeProfileNotConfiguredError:
        profile = None

    if profile is None or profile.runtime_mode == "fallback":
        chunks = await ChunkService(
            session,
            settings.data_dir,
        ).index_document(
            document_id,
            options=resolved_options,
        )
    else:
        try:
            chunks = await IndexLifecycleService(
                session,
                settings,
            ).reindex_document(
                document_id,
                options=resolved_options,
            )
        except (RuntimeHealthBlockedError, RuntimeUnavailableError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    if chunks is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await session.commit()
    return chunks


@router.post("/search", response_model=ChunkSearchOut)
async def search_chunks(
    search_in: ChunkSearchIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ChunkSearchOut:
    return await ChunkService(session, request.app.state.settings.data_dir).search(search_in)


def _validate_index_options(options: IndexDocumentIn) -> None:
    try:
        validate_custom_json(options.domain_metadata.custom_json)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _runtime_health_service(session: AsyncSession) -> RuntimeHealthService:
    try:
        return RuntimeHealthService(session, verify_storage=True)
    except TypeError:
        return RuntimeHealthService()


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
    except asyncio.CancelledError:
        await _mark_background_index_failed(
            settings,
            document_id,
            job_id,
            "Indexing task was interrupted before completion.",
        )
        raise
    except Exception as exc:
        logger.exception("Background reindexing failed for job %s", job_id)
        await _mark_background_index_failed(settings, document_id, job_id, str(exc))
    finally:
        await engine.dispose()


async def _mark_background_index_failed(
    settings: AppSettings,
    document_id: str,
    job_id: str,
    reason: str,
) -> None:
    engine = make_engine(settings.resolved_database_url)
    factory = make_session_factory(engine)
    try:
        async with factory() as background_session:
            await DocumentService(
                background_session,
                settings.data_dir,
                settings=settings,
            ).mark_index_job_failed(document_id, job_id, reason)
    except Exception:
        logger.exception("Failed to persist background indexing failure for job %s", job_id)
    finally:
        await engine.dispose()
