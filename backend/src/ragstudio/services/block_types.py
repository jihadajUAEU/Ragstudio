"""Centralized block type constants and modality classification.

Single source of truth for MinerU content-list block type sets.
Replaces duplicate definitions across parser_normalization.py,
parser_quality_intelligent_gate.py, and mineru_client.py.
"""

from __future__ import annotations

from enum import Enum

TEXT_BLOCK_TYPES = frozenset(
    {
        "caption",
        "heading",
        "list",
        "list_item",
        "paragraph",
        "para",
        "section",
        "table",
        "table_body",
        "text",
        "title",
    }
)
TABLE_BLOCK_TYPES = frozenset({"table", "table_body"})
IMAGE_BLOCK_TYPES = frozenset({"figure", "image", "picture"})
EQUATION_BLOCK_TYPES = frozenset({"equation", "equation_interline", "interline_equation"})
VISION_TARGET_BLOCK_TYPES = IMAGE_BLOCK_TYPES | EQUATION_BLOCK_TYPES


class BlockModality(str, Enum):
    """Modality classification for a content-list block."""

    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"
    EQUATION = "equation"
    UNKNOWN = "unknown"


def classify_block(block_type: str) -> BlockModality:
    """Map a raw MinerU block type string to its modality."""
    normalised = block_type.strip().lower()
    if normalised in IMAGE_BLOCK_TYPES:
        return BlockModality.IMAGE
    if normalised in EQUATION_BLOCK_TYPES:
        return BlockModality.EQUATION
    if normalised in TABLE_BLOCK_TYPES:
        return BlockModality.TABLE
    if normalised in TEXT_BLOCK_TYPES:
        return BlockModality.TEXT
    return BlockModality.UNKNOWN
