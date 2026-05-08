import json

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.api.upload_utils import read_upload_file
from ragstudio.schemas.documents import DocumentOut
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn
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
    content = await read_upload_file(file)
    metadata = DomainMetadata.model_validate(json.loads(domain_metadata or "{}"))
    options = IndexDocumentIn(parser_mode=parser_mode, domain_metadata=metadata)
    return await DocumentService(session, request.app.state.settings.data_dir).upload(
        filename=file.filename or "upload.bin",
        content_type=file.content_type or "application/octet-stream",
        content=content,
        options=options,
    )


@router.get("")
async def list_documents(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    items = await DocumentService(session, request.app.state.settings.data_dir).list()
    return {"items": items, "total": len(items)}
