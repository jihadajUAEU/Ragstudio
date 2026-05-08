import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.api.upload_utils import read_upload_file
from ragstudio.schemas.documents import DocumentOut
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.document_service import DocumentService
from ragstudio.services.index_lifecycle_service import RuntimeHealthBlockedError
from ragstudio.services.runtime_factory import RuntimeUnavailableError

router = APIRouter(prefix="/api/documents", tags=["documents"])


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
    content = await read_upload_file(file)
    try:
        return await DocumentService(
            session,
            request.app.state.settings.data_dir,
            settings=request.app.state.settings,
        ).upload(
            filename=file.filename or "upload.bin",
            content_type=file.content_type or "application/octet-stream",
            content=content,
            options=options,
        )
    except (RuntimeHealthBlockedError, RuntimeUnavailableError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
