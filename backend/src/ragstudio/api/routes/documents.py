from email.parser import BytesParser
from email.policy import default

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.documents import DocumentOut
from ragstudio.services.document_service import DocumentService

router = APIRouter(prefix="/api/documents", tags=["documents"])


async def _read_upload(request: Request) -> tuple[str, str, bytes]:
    content_type = request.headers.get("content-type", "")
    body = await request.body()
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    )
    if not message.is_multipart():
        raise HTTPException(status_code=400, detail="Expected multipart file upload")

    for part in message.iter_parts():
        if part.get_param("name", header="content-disposition") == "file":
            filename = part.get_filename() or "upload.bin"
            part_content_type = part.get_content_type() or "application/octet-stream"
            payload = part.get_payload(decode=True) or b""
            return filename, part_content_type, payload

    raise HTTPException(status_code=400, detail="Missing file upload")


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    filename, content_type, content = await _read_upload(request)
    return await DocumentService(session, request.app.state.settings.data_dir).upload(
        filename=filename,
        content_type=content_type,
        content=content,
    )


@router.get("")
async def list_documents(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    items = await DocumentService(session, request.app.state.settings.data_dir).list()
    return {"items": items, "total": len(items)}
