from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_CONTEXT_PREFIX = "[Context:"


def evidence_context_from_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    source_location: Mapping[str, Any] | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    metadata = metadata if isinstance(metadata, Mapping) else {}
    source_location = source_location if isinstance(source_location, Mapping) else {}
    reference = _reference(metadata, source_location)
    breadcrumb = _breadcrumb(metadata, reference)
    page = _page(metadata, source_location)
    layout_summary = _layout_summary(
        metadata,
        content_type=content_type,
        page=page,
    )

    context = {
        "breadcrumb": breadcrumb,
        "layout_summary": layout_summary,
        "page": page,
        "reference": reference,
    }
    return {key: value for key, value in context.items() if value is not None}


def prefixed_embedding_text(
    text: str,
    metadata: Mapping[str, Any] | None,
    *,
    source_location: Mapping[str, Any] | None = None,
    content_type: str | None = None,
) -> str:
    if text.lstrip().startswith(_CONTEXT_PREFIX):
        return text

    context = evidence_context_from_metadata(
        metadata,
        source_location=source_location,
        content_type=content_type,
    )
    breadcrumb = context.get("breadcrumb")
    if not isinstance(breadcrumb, str) or not breadcrumb:
        return text
    return f"[Context: {breadcrumb}]\n{text}"


def _breadcrumb(metadata: Mapping[str, Any], reference: str | None) -> str | None:
    parts: list[str] = []
    document_metadata = metadata.get("document_metadata")
    if isinstance(document_metadata, Mapping):
        _append_text(parts, document_metadata.get("title"))

    for key in ("section_path", "heading_path", "breadcrumbs"):
        _append_many(parts, metadata.get(key))
    _append_text(parts, reference)

    return " > ".join(parts) if parts else None


def _layout_summary(
    metadata: Mapping[str, Any],
    *,
    content_type: str | None,
    page: Any,
) -> str | None:
    parts: list[str] = []
    resolved_content_type = content_type or _string(metadata.get("content_type"))
    _append_text(parts, resolved_content_type)
    if page is not None:
        parts.append(f"page={page}")

    block = _first_provenance_block(metadata)
    if block is not None:
        block_type = _string(block.get("block_type"))
        role = _string(block.get("role"))
        if block_type:
            parts.append(f"block={block_type}")
        if role:
            parts.append(f"role={role}")

    return "; ".join(parts) if parts else None


def _first_provenance_block(metadata: Mapping[str, Any]) -> Mapping[str, Any] | None:
    provenance = metadata.get("provenance")
    if not isinstance(provenance, Mapping):
        return None
    blocks = provenance.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return None
    first = blocks[0]
    return first if isinstance(first, Mapping) else None


def _reference(
    metadata: Mapping[str, Any],
    source_location: Mapping[str, Any],
) -> str | None:
    reference = _string(source_location.get("reference"))
    if reference:
        return reference

    reference_metadata = metadata.get("reference_metadata")
    if isinstance(reference_metadata, Mapping):
        references = reference_metadata.get("references")
        if isinstance(references, list) and references:
            return _string(references[0])
        return _string(reference_metadata.get("reference"))
    return _string(metadata.get("reference"))


def _page(metadata: Mapping[str, Any], source_location: Mapping[str, Any]) -> Any:
    for key in ("page", "page_number", "page_start"):
        value = source_location.get(key)
        if value is not None:
            return value

    block = _first_provenance_block(metadata)
    if block is not None:
        for key in ("page", "page_number", "page_start"):
            value = block.get(key)
            if value is not None:
                return value
    return None


def _append_many(parts: list[str], value: Any) -> None:
    if isinstance(value, str):
        _append_text(parts, value)
        return
    if not isinstance(value, list):
        return
    for item in value:
        _append_text(parts, item)


def _append_text(parts: list[str], value: Any) -> None:
    text = _string(value)
    if text:
        parts.append(text)


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
