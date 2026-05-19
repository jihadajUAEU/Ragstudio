"""Domain-aware multimodal routing for content-list blocks.

Routes MinerU content_list blocks to the appropriate handler based on modality,
reusing RAG-Anything's modal processors for description generation when available.
Falls back gracefully to text-only extraction if raganything is not installed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.block_types import BlockModality, classify_block
from ragstudio.services.parser_warning_utils import extract_content_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModalBlock:
    """A content block with modality classification and extracted representation."""

    modality: BlockModality
    text: str
    structured_data: dict[str, Any] = field(default_factory=dict)
    source_block: dict[str, Any] = field(default_factory=dict)
    page: int | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _try_import_raganything() -> bool:
    """Check if raganything is importable without loading heavy deps."""
    try:
        import importlib

        importlib.import_module("raganything.utils")
        return True
    except Exception:
        return False


_HAS_RAGANYTHING = _try_import_raganything()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list | tuple):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _fallback_table_markdown(table_body: Any) -> str:
    if isinstance(table_body, str):
        return table_body.strip()
    if not isinstance(table_body, list) or not table_body:
        return ""
    rows: list[list[str]] = []
    for row in table_body:
        if not isinstance(row, list | tuple):
            return ""
        rows.append([str(cell) for cell in row])
    if not rows:
        return ""
    header = rows[0]
    divider = ["---" for _ in header]
    rendered = [header, divider, *rows[1:]]
    return "\n".join("| " + " | ".join(row) + " |" for row in rendered)


class StudioModalRouter:
    """Routes content_list blocks through modality-specific handlers.

    When RAG-Anything is available, multimodal blocks (image, table, equation)
    are processed through its native processors for description generation.
    Text blocks always go through Ragstudio's existing domain-aware pipeline.

    When RAG-Anything is unavailable, all blocks fall back to text extraction.
    """

    def route(
        self,
        content_list: list[dict[str, Any]],
        *,
        domain_metadata: DomainMetadata,
    ) -> list[ModalBlock]:
        """Classify and extract content from all blocks in document order."""
        blocks: list[ModalBlock] = []

        for index, item in enumerate(content_list):
            block_type = str(item.get("type", "text")).strip().lower()
            modality = classify_block(block_type)
            page = _page_number(item)

            if modality == BlockModality.TABLE:
                blocks.append(self._process_table(item, page, index))
            elif modality == BlockModality.IMAGE:
                blocks.append(self._process_image(item, page, index))
            elif modality == BlockModality.EQUATION:
                blocks.append(self._process_equation(item, page, index))
            else:
                blocks.append(self._process_text(item, page, index))

        logger.info(
            "ModalRouter: %d blocks -> %s",
            len(content_list),
            {m.value: sum(1 for b in blocks if b.modality == m) for m in BlockModality},
        )
        return blocks

    # ------------------------------------------------------------------
    # Per-modality handlers
    # ------------------------------------------------------------------

    def _process_text(
        self, item: dict[str, Any], page: int | None, index: int
    ) -> ModalBlock:
        text = extract_content_text(item)
        return ModalBlock(
            modality=BlockModality.TEXT,
            text=text,
            source_block=item,
            page=page,
        )

    def _process_table(
        self, item: dict[str, Any], page: int | None, index: int
    ) -> ModalBlock:
        structured: dict[str, Any] = {}

        # Try RAG-Anything utilities for structured table extraction
        if _HAS_RAGANYTHING:
            try:
                from raganything.utils import (
                    format_table_body,
                    get_table_body,
                    normalize_caption_list,
                )

                table_body = get_table_body(item)
                structured["raw_body"] = table_body
                structured["markdown"] = format_table_body(table_body)
                structured["caption"] = normalize_caption_list(
                    item.get("table_caption")
                )
                structured["footnote"] = normalize_caption_list(
                    item.get("table_footnote")
                )
            except Exception:
                logger.debug("RAG-Anything table utils failed, using fallback", exc_info=True)

        if not structured.get("raw_body") and item.get("table_body") is not None:
            table_body = item.get("table_body")
            structured["raw_body"] = table_body
            structured["markdown"] = _fallback_table_markdown(table_body)
        if "caption" not in structured:
            structured["caption"] = _string_list(item.get("table_caption"))
        if "footnote" not in structured:
            structured["footnote"] = _string_list(item.get("table_footnote"))

        # Build searchable text
        text_parts = []
        caption = structured.get("caption", [])
        if caption:
            text_parts.append("Table: " + ", ".join(caption))
        markdown = structured.get("markdown", "")
        if markdown:
            text_parts.append(markdown)
        if not text_parts:
            text_parts.append(extract_content_text(item))

        return ModalBlock(
            modality=BlockModality.TABLE,
            text="\n".join(text_parts),
            structured_data=structured,
            source_block=item,
            page=page,
        )

    def _process_image(
        self, item: dict[str, Any], page: int | None, index: int
    ) -> ModalBlock:
        structured: dict[str, Any] = {}
        text_parts = []

        # Extract captions
        if _HAS_RAGANYTHING:
            try:
                from raganything.utils import normalize_caption_list

                captions = normalize_caption_list(
                    item.get("image_caption", item.get("img_caption"))
                )
                footnotes = normalize_caption_list(
                    item.get("image_footnote", item.get("img_footnote"))
                )
                structured["caption"] = captions
                structured["footnote"] = footnotes
                structured["img_path"] = item.get("img_path")
                if captions:
                    text_parts.append("Image: " + ", ".join(captions))
                if footnotes:
                    text_parts.append("Footnotes: " + ", ".join(footnotes))
            except Exception:
                logger.debug("RAG-Anything image utils failed, using fallback", exc_info=True)

        if not text_parts:
            fallback = extract_content_text(item)
            if fallback:
                text_parts.append(fallback)
            else:
                text_parts.append("[Image content]")

        return ModalBlock(
            modality=BlockModality.IMAGE,
            text="\n".join(text_parts),
            structured_data=structured,
            source_block=item,
            page=page,
        )

    def _process_equation(
        self, item: dict[str, Any], page: int | None, index: int
    ) -> ModalBlock:
        structured: dict[str, Any] = {}
        text_parts = []

        if _HAS_RAGANYTHING:
            try:
                from raganything.utils import get_equation_text_and_format

                eq_text, eq_format = get_equation_text_and_format(item)
                structured["latex"] = eq_text
                structured["format"] = eq_format
                if eq_text:
                    text_parts.append(f"Equation ({eq_format}): {eq_text}")
            except Exception:
                logger.debug("RAG-Anything equation utils failed, using fallback", exc_info=True)

        if not text_parts:
            fallback = extract_content_text(item)
            text_parts.append(fallback or "[Equation content]")

        return ModalBlock(
            modality=BlockModality.EQUATION,
            text="\n".join(text_parts),
            structured_data=structured,
            source_block=item,
            page=page,
        )


def _page_number(item: dict[str, Any]) -> int | None:
    page_idx = item.get("page_idx")
    if type(page_idx) is int:
        return page_idx + 1
    page = item.get("page")
    return page if type(page) is int else None
