from fastapi import HTTPException, UploadFile

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024

# Magic-byte signatures for allowed document types.
_MAGIC_SIGNATURES: list[tuple[bytes, str]] = [
    (b"%PDF", "application/pdf"),
    # DOCX / PPTX / XLSX are ZIP-based Office Open XML
    (b"PK\x03\x04", "application/vnd.openxmlformats-officedocument"),
    (b"{\\rtf", "application/rtf"),
]
# Plain text is accepted as a fallback when no binary signature matches
# and the first bytes are valid UTF-8.


def _detect_mime(header: bytes) -> str | None:
    """Return a MIME hint based on the first bytes, or None if unknown."""
    for magic, mime in _MAGIC_SIGNATURES:
        if header[: len(magic)] == magic:
            return mime
    # Heuristic: if the header is decodable as UTF-8, treat as plain text.
    try:
        header.decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        return None


async def read_upload_file(
    file: UploadFile,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail="Upload exceeds 25 MiB limit")
        chunks.append(chunk)
    content = b"".join(chunks)

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    detected = _detect_mime(content[:16])
    if detected is None:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Accepted: PDF, DOCX, PPTX, XLSX, RTF, TXT.",
        )

    return content
