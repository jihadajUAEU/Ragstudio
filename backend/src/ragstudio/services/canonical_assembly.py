from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.parser_normalization import NormalizedBlock
from ragstudio.services.reference_metadata import ReferenceSemantics
from ragstudio.services.reference_unit_assembler import AssembledReferenceUnit
from ragstudio.services.script_detection import detect_scripts


@dataclass(frozen=True)
class EvidenceBoundingBox:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class EvidenceSourceRef:
    artifact_ref: str
    block_index: int

    @property
    def key(self) -> str:
        return f"{self.artifact_ref}:block:{self.block_index}"


@dataclass(frozen=True)
class EvidenceBlockView:
    text: str
    block_type: str
    page_start: int | None
    page_end: int | None
    source_ref: EvidenceSourceRef
    bbox: EvidenceBoundingBox | None = None
    modality: str = "text"
    parser_warnings: tuple[dict[str, Any], ...] = ()
    scripts: frozenset[str] = field(default_factory=frozenset)
    raw_item: dict[str, Any] = field(default_factory=dict)

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())


def block_views_from_normalized(
    blocks: list[NormalizedBlock],
    *,
    content_list_ref: str,
    block_indices: list[int] | None = None,
) -> list[EvidenceBlockView]:
    views: list[EvidenceBlockView] = []
    for index, block in enumerate(blocks):
        source_index = (
            block_indices[index] if block_indices and index < len(block_indices) else index
        )
        text = block.text.replace("\x00", "").strip()
        page_start = _page_value(block.source_item.get("page_start")) or block.page
        page_end = _page_value(block.source_item.get("page_end")) or block.page
        views.append(
            EvidenceBlockView(
                text=text,
                block_type=block.block_type,
                page_start=page_start,
                page_end=page_end,
                source_ref=EvidenceSourceRef(content_list_ref, source_index),
                bbox=_bbox(block.source_item.get("bbox")),
                modality=_modality(block.block_type),
                parser_warnings=tuple(block.warning_metadata()),
                scripts=frozenset(detect_scripts(text)),
                raw_item=dict(block.source_item),
            )
        )
    return views


def _page_value(value: Any) -> int | None:
    return value if type(value) is int else None


def _bbox(value: Any) -> EvidenceBoundingBox | None:
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    try:
        return EvidenceBoundingBox(*(float(part) for part in value))
    except (TypeError, ValueError):
        return None


def _modality(block_type: str) -> str:
    if block_type in {"image", "figure"}:
        return "image"
    if block_type == "table":
        return "table"
    if block_type in {"equation", "interline_equation"}:
        return "formula"
    return "text"


class CanonicalAssemblyStrategy:
    def assemble(
        self,
        normalized_blocks: list[NormalizedBlock],
        *,
        domain_metadata: DomainMetadata,
        content_list_ref: str,
        block_indices: list[int] | None = None,
        parent_metadata: dict[str, Any],
        parent_source_location: dict[str, Any],
        runtime_source_id: str | None,
        content_type: str,
        preview_ref: str | None,
        reference_semantics: ReferenceSemantics | None = None,
        max_page_gap: int | None = None,
        preserve_original_blocks: bool = False,
        block_preview_chars: int = 160,
        store_text_hash: bool = False,
    ) -> list[AssembledReferenceUnit]:
        from ragstudio.services.domain_resolvers import (
            ResolverContext,
            resolvers_for_context,
        )
        from ragstudio.services.evidence_graph import EvidenceGraph

        context = ResolverContext(
            domain_metadata=domain_metadata,
            parent_metadata=parent_metadata,
            parent_source_location=parent_source_location,
            runtime_source_id=runtime_source_id,
            content_type=content_type,
            preview_ref=preview_ref,
            reference_semantics=reference_semantics,
            max_page_gap=max_page_gap,
            preserve_original_blocks=preserve_original_blocks,
            block_preview_chars=block_preview_chars,
            store_text_hash=store_text_hash,
        )
        graph = EvidenceGraph.from_blocks(
            block_views_from_normalized(
                normalized_blocks,
                content_list_ref=content_list_ref,
                block_indices=block_indices,
            )
        )
        for resolver in resolvers_for_context(context):
            units = resolver.resolve_units(graph, context=context)
            if units:
                return [
                    AssembledReferenceUnit(
                        text=unit.text,
                        source_location=dict(unit.source_location),
                        metadata=dict(unit.metadata),
                        runtime_source_id=unit.runtime_source_id,
                        content_type=unit.content_type,
                        preview_ref=unit.preview_ref,
                    )
                    for unit in units
                ]
        return []
