import json

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Query,
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
from ragstudio.schemas.document_parse_evidence import DocumentParseEvidence
from ragstudio.schemas.documents import DocumentOut
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.document_parse_evidence_service import (
    DocumentParseEvidenceNotFoundError,
    DocumentParseEvidenceService,
)
from ragstudio.services.document_service import ActiveIndexJobError, DocumentService
from ragstudio.services.domain_metadata_contract_compiler import (
    DomainMetadataContractError,
    compile_index_options,
    validate_executable_reference_contract,
)
from ragstudio.services.graph_projection_runner import (
    GraphProjectionCleanupError,
    GraphProjectionRunner,
)
from ragstudio.services.index_lifecycle_service import RuntimeHealthBlockedError
from ragstudio.services.metadata_json_schema import validate_custom_json
from ragstudio.services.runtime_factory import RuntimeUnavailableError
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_policy import (
    DEFAULT_PARSER_MODE,
    ProductPolicyError,
    enforce_product_index_options,
)
from ragstudio.services.runtime_profile_service import (
    RuntimeProfileNotConfiguredError,
    RuntimeProfileService,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile,
    parser_mode: str | None = Form(default=None),
    domain_metadata: str | None = Form(default=None),
    mineru_parse_options: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    options = (
        _parse_index_options(parser_mode, domain_metadata, mineru_parse_options)
        if parser_mode is not None
        or domain_metadata is not None
        or mineru_parse_options is not None
        else None
    )
    compiled_options = compile_index_options(options) if options is not None else None
    index_options = compiled_options or IndexDocumentIn()
    _validate_index_options(index_options)
    settings = request.app.state.settings
    await _ensure_runtime_ready(session, settings)
    try:
        await ChunkService(
            session,
            settings.data_dir,
            http_client_provider=request.app.state.http_clients,
        ).validate_strict_mineru_sidecar(index_options)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    content = await read_upload_file(file)
    try:
        service = DocumentService(
            session,
            settings.data_dir,
            settings=settings,
            http_client_provider=request.app.state.http_clients,
        )
        document = await service.upload(
            filename=file.filename or "upload.bin",
            content_type=file.content_type or "application/octet-stream",
            content=content,
            options=compiled_options,
            index_immediately=False,
        )
        return document
    except (RuntimeHealthBlockedError, RuntimeUnavailableError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{document_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
async def reindex_document(
    document_id: str,
    options: IndexDocumentIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    settings = request.app.state.settings
    try:
        service = DocumentService(
            session,
            settings.data_dir,
            settings=settings,
            http_client_provider=request.app.state.http_clients,
        )
        if not await service.document_exists(document_id):
            raise HTTPException(status_code=404, detail="Document not found")
        options = compile_index_options(options)
        _validate_index_options(options)
        if await service.active_index_job(document_id) is not None:
            raise HTTPException(
                status_code=409,
                detail="Document already has an active indexing job",
            )
        await _ensure_runtime_ready(session, settings)
        try:
            await ChunkService(
                session,
                settings.data_dir,
                http_client_provider=request.app.state.http_clients,
            ).validate_strict_mineru_sidecar(options)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            job = await service.create_index_job(document_id, options)
        except ActiveIndexJobError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if job is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"document_id": document_id, "job_id": job.id, "status": job.status}
    except (RuntimeHealthBlockedError, RuntimeUnavailableError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{document_id}/graph/rematerialize")
async def rematerialize_document_graph(
    document_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    settings = request.app.state.settings
    service = DocumentService(
        session,
        settings.data_dir,
        settings=settings,
        http_client_provider=request.app.state.http_clients,
    )
    await service.lock_document_workflow(document_id)
    if not await service.document_exists(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    if await service.active_index_job(document_id) is not None:
        raise HTTPException(status_code=409, detail="Document already has an active indexing job")
    result = await GraphProjectionRunner(session, settings).rematerialize_document(document_id)
    await session.commit()
    return {"document_id": document_id, **result}


@router.get("/{document_id}/parse-evidence", response_model=DocumentParseEvidence)
async def get_document_parse_evidence(
    document_id: str,
    session: AsyncSession = Depends(get_session),
) -> DocumentParseEvidence:
    try:
        return await DocumentParseEvidenceService(session).get_document_evidence(document_id)
    except DocumentParseEvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc


async def _ensure_runtime_ready(session: AsyncSession, settings: AppSettings) -> None:
    try:
        profile = await RuntimeProfileService(session, settings).get_active_profile()
    except (RuntimeProfileNotConfiguredError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=_runtime_profile_detail(exc)) from exc
    health_service = RuntimeHealthService(session, verify_storage=True)
    checks = await health_service.check(profile)
    blocking = health_service.blocking_failures(checks)
    if blocking:
        detail = "; ".join(f"{item.name}: {item.detail}" for item in blocking)
        raise HTTPException(status_code=409, detail=detail)


def _runtime_profile_detail(exc: Exception) -> str:
    return (
        f"{exc}. Configure a product runtime profile before indexing: "
        "storage_backend=postgres_pgvector_neo4j, runtime_mode=runtime, "
        "embedding_provider=vllm_openai, and a ready MinerU sidecar."
    )


def _parse_index_options(
    parser_mode: str | None,
    domain_metadata: str | None,
    mineru_parse_options: str | None = None,
) -> IndexDocumentIn:
    try:
        metadata_payload = json.loads(domain_metadata or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"domain_metadata must be valid JSON: {exc.msg}",
        ) from exc
    mineru_parse_options_payload = None
    if mineru_parse_options:
        try:
            mineru_parse_options_payload = json.loads(mineru_parse_options)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"mineru_parse_options must be valid JSON: {exc.msg}",
            ) from exc
    try:
        payload = {
            "parser_mode": parser_mode or DEFAULT_PARSER_MODE,
            "domain_metadata": metadata_payload,
        }
        if mineru_parse_options_payload is not None:
            payload["mineru_parse_options"] = mineru_parse_options_payload
        return IndexDocumentIn.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


def _validate_index_options(options: IndexDocumentIn) -> None:
    try:
        enforce_product_index_options(parser_mode=options.parser_mode)
    except ProductPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        validate_custom_json(options.domain_metadata.custom_json)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        validate_executable_reference_contract(options.domain_metadata)
    except DomainMetadataContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
async def list_documents(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    items, total = await DocumentService(
        session,
        request.app.state.settings.data_dir,
        settings=request.app.state.settings,
        http_client_provider=request.app.state.http_clients,
    ).list(limit=limit, offset=offset)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        result = await DocumentService(
            session,
            request.app.state.settings.data_dir,
            settings=request.app.state.settings,
            http_client_provider=request.app.state.http_clients,
        ).delete_document(document_id)
    except (ActiveIndexJobError, GraphProjectionCleanupError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
