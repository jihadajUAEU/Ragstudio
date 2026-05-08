import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.api.upload_utils import read_upload_file
from ragstudio.schemas.documents import DocumentOut
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.document_service import DocumentService

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile,
    parser_mode: str = Form(default="local_fallback"),
    domain_metadata: str = Form(default="{}"),
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    options = _parse_index_options(parser_mode, domain_metadata)
    content = await read_upload_file(file)
    return await DocumentService(session, request.app.state.settings.data_dir).upload(
        filename=file.filename or "upload.bin",
        content_type=file.content_type or "application/octet-stream",
        content=content,
        options=options,
    )


def _parse_index_options(parser_mode: str, domain_metadata: str) -> IndexDocumentIn:
    try:
        metadata_payload = json.loads(domain_metadata or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"domain_metadata must be valid JSON: {exc.msg}",
        ) from exc
    try:
        return IndexDocumentIn.model_validate(
            {"parser_mode": parser_mode, "domain_metadata": metadata_payload}
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


@router.get("")
async def list_documents(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    items = await DocumentService(session, request.app.state.settings.data_dir).list()
    return {"items": items, "total": len(items)}
