"""Shared parser warning and content extraction utilities.

Consolidates logic previously duplicated across:
- domain_metadata_quality_gate.py (merge_parser_warnings)
- reference_unit_assembler.py   (merge_parser_warnings, _page_range)
- reference_metadata.py         (_page_range)
- parser_normalization.py       (content text extraction)
- native_raganything_adapter.py (content text extraction)
"""

from __future__ import annotations

import json
from typing import Any


def merge_parser_warnings(
    metadata: dict[str, Any],
    warnings: list[dict[str, Any]],
) -> None:
    """Merge *warnings* into ``metadata["parser_warnings"]``, deduplicating by JSON repr."""
    existing = metadata.get("parser_warnings")
    if not isinstance(existing, list):
        existing = []
    seen = {json.dumps(w, sort_keys=True, default=str) for w in existing}
    for warning in warnings:
        key = json.dumps(warning, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            existing.append(warning)
    metadata["parser_warnings"] = existing


def page_range(source_location: dict[str, Any] | None) -> dict[str, Any]:
    """Extract a normalised page-range dict from a source_location."""
    if not isinstance(source_location, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("page", "page_start", "page_end"):
        value = source_location.get(key)
        if isinstance(value, int) and value > 0:
            result[key] = value
    return result


def extract_content_text(item: dict[str, Any]) -> str:
    """Extract the best-effort text representation from a content-list item.

    Checks keys in priority order to cover MinerU, Docling, and RAG-Anything
    content-list schemas.
    """
    for key in (
        "text",
        "content",
        "paragraph_content",
        "table_body",
        "latex",
        "image_caption",
        "table_caption",
    ):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            joined = " ".join(str(v).strip() for v in value if str(v).strip())
            if joined:
                return joined
    return ""
