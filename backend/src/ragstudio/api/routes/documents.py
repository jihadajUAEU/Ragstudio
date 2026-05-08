import asyncio
import json
import logging

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.api.upload_utils import read_upload_file
from ragstudio.config import AppSettings
from ragstudio.db.engine import make_engine, make_session_factory
from ragstudio.schemas.documents import DocumentOut
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.document_service import DocumentService
from ragstudio.services.index_lifecycle_service import RuntimeHealthBlockedError
from ragstudio.services.runtime_factory import RuntimeUnavailableError
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_profile_service import (
    RuntimeProfileNotConfiguredError,
    RuntimeProfileService,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = logging.getLogger(__name__)


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile,
    parser_mode: str | None = Form(default=None),
    domain_metadata: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    options = (
        _parse_index_options(parser_mode, domain_metadata)
        if parser_mode is not None or domain_metadata is not None
        else None
    )
    settings = request.app.state.settings
    try:
        profile = await RuntimeProfileService(session, settings).get_active_profile()
    except RuntimeProfileNotConfiguredError:
        profile = None
    if profile is not None and profile.runtime_mode != "fallback":
        health_service = RuntimeHealthService()
        checks = await health_service.check(profile)
        blocking = health_service.blocking_failures(checks)
        if blocking:
            detail = "; ".join(f"{item.name}: {item.detail}" for item in blocking)
            raise HTTPException(status_code=409, detail=detail)

    content = await read_upload_file(file)
    try:
        service = DocumentService(
            session,
            settings.data_dir,
            settings=settings,
        )
        document = await service.upload(
            filename=file.filename or "upload.bin",
            content_type=file.content_type or "application/octet-stream",
            content=content,
            options=options,
            index_immediately=False,
        )
        if service.queued_index_job_id is None:
            raise RuntimeError("Upload did not create an index job.")
        asyncio.create_task(
            _run_index_job(
                settings,
                document.id,
                service.queued_index_job_id,
                options or IndexDocumentIn(),
            )
        )
        return document
    except (RuntimeHealthBlockedError, RuntimeUnavailableError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _run_index_job(
    settings: AppSettings,
    document_id: str,
    job_id: str,
    options: IndexDocumentIn,
) -> None:
    engine = make_engine(settings.resolved_database_url)
    factory = make_session_factory(engine)
    try:
        async with factory() as background_session:
            service = DocumentService(
                background_session,
                settings.data_dir,
                settings=settings,
            )
            await service.run_index_job(document_id, job_id, options)
    except asyncio.CancelledError:
        await _mark_background_index_failed(
            settings,
            document_id,
            job_id,
            "Indexing task was interrupted before completion.",
        )
        raise
    except Exception as exc:
        logger.exception("Background document indexing failed for job %s", job_id)
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


def _parse_index_options(
    parser_mode: str | None,
    domain_metadata: str | None,
) -> IndexDocumentIn:
    try:
        metadata_payload = json.loads(domain_metadata or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"domain_metadata must be valid JSON: {exc.msg}",
        ) from exc
    try:
        return IndexDocumentIn.model_validate(
            {
                "parser_mode": parser_mode or "local_fallback",
                "domain_metadata": metadata_payload,
            }
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


@router.get("")
async def list_documents(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    items = await DocumentService(
        session,
        request.app.state.settings.data_dir,
        settings=request.app.state.settings,
    ).list()
    return {"items": items, "total": len(items)}


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    result = await DocumentService(
        session,
        request.app.state.settings.data_dir,
        settings=request.app.state.settings,
    ).delete_document(document_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Document not found")
    if result == "active_job":
        raise HTTPException(status_code=409, detail="Document has an active indexing job")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
