from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata, ParserMode
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.canonical_assembly import CanonicalAssemblyStrategy
from ragstudio.services.chunk_quality_gate import ChunkQualityGate
from ragstudio.services.domain_metadata_quality_gate import DomainMetadataQualityGate
from ragstudio.services.http_client_provider import HttpClientProviderProtocol
from ragstudio.services.modal_preprocessor import MODAL_ROUTER_PROCESSED_FLAG
from ragstudio.services.parser_normalization import (
    ExpectedContentProfile,
    MinerUContentNormalizer,
    NormalizedBlock,
    VisionRecoveryConfig,
)
from ragstudio.services.parser_quality_intelligent_gate import ParserQualityIntelligentGate
from ragstudio.services.reference_metadata import ReferenceSemantics
from ragstudio.services.reference_unit_assembler import (
    AssembledReferenceUnit,
    ReferenceSourceBlock,
    ReferenceUnitAssembler,
)


@dataclass(frozen=True)
class ChunkProfile:
    name: str
    target_words: int
    hard_max_words: int
    semantics: ReferenceSemantics | None = None
    table_max_rows: int = 25  # Tables ≤ this stay as a single chunk
    image_context_blocks: int = 1  # Preceding text blocks attached to image chunks


REFERENCE_HEAVY_TARGET_WORDS = 500
REFERENCE_HEAVY_HARD_MAX_WORDS = 900
TAFSEER_BOOK_TARGET_WORDS = 1000
LAYOUT_TABLE_TARGET_WORDS = 800
LAYOUT_TABLE_HARD_MAX_WORDS = 1200
SHORT_REFERENCE_TARGET_WORDS = 400
SHORT_REFERENCE_HARD_MAX_WORDS = 800
GENERIC_TARGET_WORDS = 1000
FULL_WIDTH_LAYOUT_RATIO = 0.70
SEMANTIC_SPLIT_LOWER_BOUND_RATIO = 0.55


@dataclass(frozen=True)
class SplitPiece:
    text: str
    source_location: dict[str, Any]
    metadata: dict[str, Any]
    runtime_source_id: str | None
    content_type: str
    preview_ref: str | None


@dataclass(frozen=True)
class ContentListSplitResult:
    handled: bool
    pieces: list[SplitPiece]


@dataclass(frozen=True)
class ContentListKey:
    root: Path
    content_ref: str


@dataclass(frozen=True)
class OrderedTextBlock:
    text: str
    page: int | None
    warnings: list[dict[str, Any]]
    start: int
    end: int


@dataclass(frozen=True)
class OrderedTextGroup:
    text: str
    page_start: int | None
    page_end: int | None
    warnings: list[dict[str, Any]]
    blocks: list[OrderedTextBlock]


class ChunkSplitter:
    def __init__(
        self,
        *,
        max_words: int = 1500,
        vision_recovery_config: VisionRecoveryConfig | None = None,
        http_client_provider: HttpClientProviderProtocol | None = None,
    ) -> None:
        self.max_words = max_words
        self.vision_recovery_config = vision_recovery_config
        self.content_normalizer = MinerUContentNormalizer(
            http_client_provider=http_client_provider
        )
        self.reference_unit_assembler = ReferenceUnitAssembler()
        self.canonical_assembly = CanonicalAssemblyStrategy()

    def split(
        self,
        chunks: list[AdapterChunk],
        *,
        domain_metadata: DomainMetadata,
        parser_mode: ParserMode,
    ) -> list[AdapterChunk] | Awaitable[list[AdapterChunk]]:
        split_task = self._split_async(
            chunks,
            domain_metadata=domain_metadata,
            parser_mode=parser_mode,
        )
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(split_task)
        return split_task

    async def _split_async(
        self,
        chunks: list[AdapterChunk],
        *,
        domain_metadata: DomainMetadata,
        parser_mode: ParserMode,
    ) -> list[AdapterChunk]:

        profile = self._profile(domain_metadata)
        expected_profile = ExpectedContentProfile.from_domain_metadata(domain_metadata)
        output: list[AdapterChunk] = []
        processed_content_lists: set[ContentListKey] = set()
        for chunk in chunks:
            content_list_key = self._content_list_key(chunk)
            if content_list_key is not None and content_list_key in processed_content_lists:
                continue
            split_result = await self._split_chunk(
                chunk,
                profile,
                expected_profile,
                domain_metadata,
            )
            pieces = split_result.pieces
            if content_list_key is not None and split_result.handled:
                processed_content_lists.add(content_list_key)
            if len(pieces) == 1 and pieces[0].text == chunk.text:
                if self._should_preserve_piece(pieces[0], chunk) or self._should_enrich_unchanged(
                    pieces[0],
                    profile,
                    expected_profile,
                    domain_metadata,
                ):
                    output.append(
                        self._with_split_metadata(
                            pieces[0],
                            parent=chunk,
                            profile=profile,
                            expected_profile=expected_profile,
                            domain_metadata=domain_metadata,
                            split_index=0,
                            split_count=1,
                        )
                    )
                    continue
                output.append(chunk)
                continue

            split_count = len(pieces)
            for split_index, piece in enumerate(pieces):
                output.append(
                    self._with_split_metadata(
                        piece,
                        parent=chunk,
                        profile=profile,
                        expected_profile=expected_profile,
                        domain_metadata=domain_metadata,
                        split_index=split_index,
                        split_count=split_count,
                    )
                )

        return [item for item in output if item.text.strip()]

    def _profile(self, metadata: DomainMetadata) -> ChunkProfile:
        semantics = ReferenceSemantics.from_metadata(metadata)
        if semantics.canonical_units_enabled:
            return ChunkProfile(
                "reference_contract",
                target_words=REFERENCE_HEAVY_TARGET_WORDS,
                hard_max_words=min(self.max_words, REFERENCE_HEAVY_HARD_MAX_WORDS),
                semantics=semantics,
            )

        domain = (metadata.domain or "").casefold()
        document_type = (metadata.document_type or "").casefold()
        if domain == "tafseer" or document_type == "book":
            return ChunkProfile(
                "tafseer_book",
                target_words=TAFSEER_BOOK_TARGET_WORDS,
                hard_max_words=self.max_words,
            )
        if document_type == "paper":
            return ChunkProfile(
                "paper_section",
                target_words=LAYOUT_TABLE_TARGET_WORDS,
                hard_max_words=min(self.max_words, LAYOUT_TABLE_HARD_MAX_WORDS),
            )
        if document_type == "table":
            return ChunkProfile(
                "table_block",
                target_words=SHORT_REFERENCE_TARGET_WORDS,
                hard_max_words=min(self.max_words, SHORT_REFERENCE_HARD_MAX_WORDS),
            )
        return ChunkProfile(
            "generic",
            target_words=GENERIC_TARGET_WORDS,
            hard_max_words=self.max_words,
        )

    async def _split_chunk(
        self,
        chunk: AdapterChunk,
        profile: ChunkProfile,
        expected_profile: ExpectedContentProfile,
        domain_metadata: DomainMetadata,
    ) -> ContentListSplitResult:
        content_list_result = await self._chunks_from_content_list(
            chunk,
            profile,
            expected_profile,
            domain_metadata,
        )
        if content_list_result is not None:
            return content_list_result

        sections = self._markdown_sections(chunk.text)
        title_sections, body_sections = self._split_title_sections(sections, chunk, profile)
        title_pieces = [
            self._piece_from_parent(chunk, text, source_location=dict(chunk.source_location))
            for text in title_sections
            if text.strip()
        ]
        body_text = "\n\n".join(body_sections).strip()
        body_chunk = AdapterChunk(
            text=body_text,
            source_location=chunk.source_location,
            metadata=chunk.metadata,
            runtime_source_id=chunk.runtime_source_id,
            content_type=chunk.content_type,
            preview_ref=chunk.preview_ref,
        )
        reference_units = self._reference_unit_sections(body_chunk, profile, domain_metadata)
        if reference_units:
            return ContentListSplitResult(handled=False, pieces=[*title_pieces, *reference_units])

        pieces = [*title_sections, *self._pack_sections(body_sections, profile)]
        return ContentListSplitResult(
            handled=False,
            pieces=[
                self._piece_from_parent(chunk, text, source_location=dict(chunk.source_location))
                for text in pieces
                if text.strip()
            ],
        )

    def _content_list_key(self, chunk: AdapterChunk) -> ContentListKey | None:
        if chunk.metadata.get(MODAL_ROUTER_PROCESSED_FLAG) is True:
            return None
        parser_metadata = self._parser_metadata(chunk)
        extract_dir = parser_metadata.get("artifact_extract_dir")
        content_ref = parser_metadata.get("content_list_ref")
        if not isinstance(extract_dir, str) or not isinstance(content_ref, str):
            return None
        if not extract_dir.strip() or not content_ref.strip():
            return None
        return ContentListKey(Path(extract_dir).resolve(), content_ref)

    async def _chunks_from_content_list(
        self,
        chunk: AdapterChunk,
        profile: ChunkProfile,
        expected_profile: ExpectedContentProfile,
        domain_metadata: DomainMetadata,
    ) -> ContentListSplitResult | None:
        if chunk.metadata.get(MODAL_ROUTER_PROCESSED_FLAG) is True:
            return None

        parser_metadata = self._parser_metadata(chunk)
        extract_dir = parser_metadata.get("artifact_extract_dir")
        content_ref = parser_metadata.get("content_list_ref")
        if not isinstance(extract_dir, str) or not isinstance(content_ref, str):
            return None

        root = Path(extract_dir).resolve()
        target = (root / content_ref).resolve()
        if target != root and root not in target.parents:
            return None

        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        if not isinstance(data, list):
            return None

        normalized_blocks = await self.content_normalizer.normalize_content_list(
            data,
            domain_metadata=domain_metadata,
            expected_profile=expected_profile,
            artifact_root=root,
            content_list_path=target,
            vision_recovery_config=self.vision_recovery_config,
        )
        canonical_pieces = self._canonical_reference_pieces(
            chunk,
            profile,
            normalized_blocks,
            content_ref=content_ref,
            domain_metadata=domain_metadata,
        )
        if canonical_pieces:
            return ContentListSplitResult(handled=True, pieces=canonical_pieces)

        pieces: list[SplitPiece] = []
        for group in self._ordered_text_groups(normalized_blocks):
            source_location = self._source_location_with_page_range(
                chunk.source_location,
                page_start=group.page_start,
                page_end=group.page_end,
            )

            if not group.text.strip():
                if group.warnings:
                    pieces.append(
                        self._warning_only_piece(
                            chunk,
                            group.warnings,
                            source_location=source_location,
                            content_ref=content_ref,
                        )
                    )
                continue

            grouped_chunk = AdapterChunk(
                text=group.text,
                source_location=source_location,
                metadata=dict(chunk.metadata),
                runtime_source_id=chunk.runtime_source_id,
                content_type=chunk.content_type,
                preview_ref=chunk.preview_ref,
            )
            reference_units = self._reference_unit_sections_for_ordered_group(
                grouped_chunk,
                group,
                profile,
                domain_metadata,
            )
            if reference_units:
                pieces.extend(reference_units)
                continue
            metadata = dict(chunk.metadata)
            if group.warnings:
                self._merge_parser_warnings(metadata, group.warnings)
            grouped_chunk = AdapterChunk(
                text=group.text,
                source_location=source_location,
                metadata=metadata,
                runtime_source_id=chunk.runtime_source_id,
                content_type=chunk.content_type,
                preview_ref=chunk.preview_ref,
            )
            for part in self._hard_split_text(group.text, profile.hard_max_words):
                pieces.append(
                    self._piece_from_parent(grouped_chunk, part, source_location=source_location)
                )
        return ContentListSplitResult(handled=True, pieces=pieces)

    def _ordered_text_groups(self, blocks: list[NormalizedBlock]) -> list[OrderedTextGroup]:
        groups: list[OrderedTextGroup] = []
        current_text_parts: list[str] = []
        current_blocks: list[OrderedTextBlock] = []
        current_warnings: list[dict[str, Any]] = []
        current_page_start: int | None = None
        current_page_end: int | None = None

        def merge_page_range(page_start: int | None, page_end: int | None) -> None:
            nonlocal current_page_start, current_page_end
            if page_start is None:
                page_start = page_end
            if page_end is None:
                page_end = page_start
            if page_start is None or page_end is None:
                return
            current_page_start = (
                page_start
                if current_page_start is None
                else min(current_page_start, page_start)
            )
            current_page_end = (
                page_end if current_page_end is None else max(current_page_end, page_end)
            )

        def flush() -> None:
            nonlocal current_page_start, current_page_end
            if not current_text_parts and not current_warnings:
                return
            groups.append(
                OrderedTextGroup(
                    text="\n\n".join(current_text_parts).strip(),
                    page_start=current_page_start,
                    page_end=current_page_end,
                    warnings=list(current_warnings),
                    blocks=list(current_blocks),
                )
            )
            current_text_parts.clear()
            current_blocks.clear()
            current_warnings.clear()
            current_page_start = None
            current_page_end = None

        for block in blocks:
            text = block.text.strip()
            warnings = block.warning_metadata()

            if not text:
                if warnings:
                    flush()
                    current_warnings.extend(warnings)
                    merge_page_range(
                        self._normalized_page_start(block),
                        self._normalized_page_end(block),
                    )
                    flush()
                continue

            if current_text_parts and self._starts_new_logical_section(text):
                flush()

            start = sum(len(part) for part in current_text_parts) + 2 * len(current_text_parts)
            current_text_parts.append(text)
            current_blocks.append(
                OrderedTextBlock(
                    text=text,
                    page=block.page,
                    warnings=warnings,
                    start=start,
                    end=start + len(text),
                )
            )
            current_warnings.extend(warnings)
            merge_page_range(
                self._normalized_page_start(block),
                self._normalized_page_end(block),
            )

        flush()
        return groups

    def _normalized_page_start(self, block: NormalizedBlock) -> int | None:
        page_start = block.source_item.get("page_start")
        return page_start if type(page_start) is int else block.page

    def _normalized_page_end(self, block: NormalizedBlock) -> int | None:
        page_end = block.source_item.get("page_end")
        return page_end if type(page_end) is int else block.page

    def _starts_new_logical_section(self, text: str) -> bool:
        return bool(re.match(r"^#{1,4}\s+", text.strip()))

    def _canonical_reference_pieces(
        self,
        chunk: AdapterChunk,
        profile: ChunkProfile,
        normalized_blocks: list[NormalizedBlock],
        *,
        content_ref: str,
        domain_metadata: DomainMetadata,
    ) -> list[SplitPiece]:
        semantics = profile.semantics
        if semantics is None or not semantics.canonical_units_enabled:
            return []

        ordered_blocks = self._canonical_block_order(
            normalized_blocks,
            domain_metadata=domain_metadata,
        )
        strategy_units = self.canonical_assembly.assemble(
            [block for _, block in ordered_blocks],
            domain_metadata=domain_metadata,
            content_list_ref=content_ref,
            block_indices=[index for index, _ in ordered_blocks],
            parent_metadata=dict(chunk.metadata),
            parent_source_location=dict(chunk.source_location),
            runtime_source_id=chunk.runtime_source_id,
            content_type=chunk.content_type,
            preview_ref=chunk.preview_ref,
            reference_semantics=semantics,
            max_page_gap=semantics.max_page_gap,
            preserve_original_blocks=semantics.preserve_original_blocks,
            block_preview_chars=semantics.block_preview_chars,
            store_text_hash=semantics.store_text_hash,
        )
        if strategy_units:
            return [self._piece_from_assembled(unit) for unit in strategy_units]

        blocks: list[ReferenceSourceBlock] = []
        for index, block in ordered_blocks:
            warning_metadata = tuple(block.warning_metadata())
            warning_codes = tuple(
                warning["code"]
                for warning in warning_metadata
                if isinstance(warning.get("code"), str)
            )
            blocks.append(
                ReferenceSourceBlock(
                    text=block.text,
                    page_start=block.page,
                    page_end=block.page,
                    block_type=block.block_type,
                    parser_warning_codes=warning_codes,
                    parser_warnings=warning_metadata,
                    source_block_ref=self._source_block_ref(
                        block,
                        content_ref=content_ref,
                        index=index,
                    ),
                )
            )

        assembled_units = self.reference_unit_assembler.assemble(
            blocks,
            semantics=semantics,
            parent_metadata=dict(chunk.metadata),
            parent_source_location=dict(chunk.source_location),
            runtime_source_id=chunk.runtime_source_id,
            content_type=chunk.content_type,
            preview_ref=chunk.preview_ref,
        )
        return [self._piece_from_assembled(unit) for unit in assembled_units]

    def _canonical_block_order(
        self,
        normalized_blocks: list[NormalizedBlock],
        *,
        domain_metadata: DomainMetadata | None = None,
    ) -> list[tuple[int, NormalizedBlock]]:
        indexed_blocks = list(enumerate(normalized_blocks))
        if not any(self._source_bbox(block) is not None for _, block in indexed_blocks):
            return indexed_blocks

        grouped: dict[int | None, list[tuple[int, NormalizedBlock]]] = {}
        for item in indexed_blocks:
            grouped.setdefault(item[1].page, []).append(item)

        ordered: list[tuple[int, NormalizedBlock]] = []
        for page_blocks in sorted(
            grouped.values(),
            key=lambda blocks: (
                blocks[0][1].page is None,
                blocks[0][1].page if blocks[0][1].page is not None else blocks[0][0],
                blocks[0][0],
            ),
        ):
            if all(self._source_bbox(block) is not None for _, block in page_blocks):
                ordered.extend(
                    self._banded_visual_order(
                        page_blocks,
                        domain_metadata=domain_metadata,
                    )
                )
                continue
            ordered.extend(page_blocks)
        return ordered

    def _banded_visual_order(
        self,
        page_blocks: list[tuple[int, NormalizedBlock]],
        *,
        domain_metadata: DomainMetadata | None,
    ) -> list[tuple[int, NormalizedBlock]]:
        page_width = self._page_width(page_blocks)
        full_width_threshold = page_width * FULL_WIDTH_LAYOUT_RATIO
        full_width: list[tuple[int, NormalizedBlock]] = []
        column_blocks: list[tuple[int, NormalizedBlock]] = []
        for item in page_blocks:
            bbox = self._source_bbox(item[1])
            if bbox is None:
                column_blocks.append(item)
                continue
            x0, _y0, x1, _y1 = bbox
            if x1 - x0 >= full_width_threshold:
                full_width.append(item)
            else:
                column_blocks.append(item)

        if len(column_blocks) < 2:
            return sorted(page_blocks, key=lambda item: self._visual_order_key(item[0], item[1]))

        full_width_sorted = sorted(
            full_width,
            key=lambda item: self._visual_order_key(item[0], item[1]),
        )
        bands: dict[int, list[tuple[int, NormalizedBlock]]] = {}
        for item in column_blocks:
            band = self._band_index(item[1], full_width_sorted)
            bands.setdefault(band, []).append(item)

        ordered: list[tuple[int, NormalizedBlock]] = []
        for band in range(len(full_width_sorted) + 1):
            ordered.extend(
                self._order_columns_in_band(
                    bands.get(band, []),
                    page_width=page_width,
                    rtl=self._is_rtl_domain(domain_metadata),
                )
            )
            if band < len(full_width_sorted):
                ordered.append(full_width_sorted[band])
        return ordered

    def _page_width(self, page_blocks: list[tuple[int, NormalizedBlock]]) -> float:
        widths: list[float] = []
        max_x1 = 0.0
        for _index, block in page_blocks:
            bbox = self._source_bbox(block)
            if bbox is None:
                continue
            x0, _y0, x1, _y1 = bbox
            widths.append(x1 - x0)
            max_x1 = max(max_x1, x1)
        return max(1.0, max_x1, *(widths or [0.0]))

    def _band_index(
        self,
        block: NormalizedBlock,
        full_width_sorted: list[tuple[int, NormalizedBlock]],
    ) -> int:
        bbox = self._source_bbox(block)
        if bbox is None:
            return 0
        _x0, y0, _x1, y1 = bbox
        midpoint = (y0 + y1) / 2
        band = 0
        for _original_index, separator in full_width_sorted:
            sep_bbox = self._source_bbox(separator)
            if sep_bbox is None:
                continue
            _sx0, sy0, _sx1, _sy1 = sep_bbox
            if midpoint >= sy0:
                band += 1
        return band

    def _order_columns_in_band(
        self,
        blocks: list[tuple[int, NormalizedBlock]],
        *,
        page_width: float,
        rtl: bool,
    ) -> list[tuple[int, NormalizedBlock]]:
        if not blocks:
            return []
        clusters = self._column_clusters(blocks, gap_tolerance=page_width * 0.05)
        clusters = sorted(
            clusters,
            key=lambda cluster: self._cluster_x0(cluster),
            reverse=rtl,
        )
        ordered: list[tuple[int, NormalizedBlock]] = []
        for cluster in clusters:
            ordered.extend(
                sorted(
                    cluster,
                    key=lambda item: self._visual_order_key(item[0], item[1]),
                )
            )
        return ordered

    def _column_clusters(
        self,
        blocks: list[tuple[int, NormalizedBlock]],
        *,
        gap_tolerance: float,
    ) -> list[list[tuple[int, NormalizedBlock]]]:
        sorted_blocks = sorted(
            blocks,
            key=lambda item: (self._source_bbox(item[1]) or (0.0, 0.0, 0.0, 0.0))[0],
        )
        clusters: list[list[tuple[int, NormalizedBlock]]] = []
        current: list[tuple[int, NormalizedBlock]] = []
        current_right: float | None = None
        for item in sorted_blocks:
            bbox = self._source_bbox(item[1])
            if bbox is None:
                continue
            x0, _y0, x1, _y1 = bbox
            if current and current_right is not None and x0 - current_right > gap_tolerance:
                clusters.append(current)
                current = []
                current_right = None
            current.append(item)
            current_right = max(current_right if current_right is not None else x1, x1)
        if current:
            clusters.append(current)
        return clusters

    def _cluster_x0(self, cluster: list[tuple[int, NormalizedBlock]]) -> float:
        values = [
            bbox[0]
            for _index, block in cluster
            if (bbox := self._source_bbox(block)) is not None
        ]
        return min(values) if values else 0.0

    def _is_rtl_domain(self, domain_metadata: DomainMetadata | None) -> bool:
        if domain_metadata is None:
            return False
        values = [
            domain_metadata.script,
            domain_metadata.language,
            domain_metadata.domain,
            *domain_metadata.tags,
        ]
        normalized = {str(value).casefold() for value in values if value}
        return bool({"arabic", "ar", "arab"} & normalized)

    def _visual_order_key(
        self,
        index: int,
        block: NormalizedBlock,
    ) -> tuple[int, int, float, float, int]:
        page = block.page
        if page is None:
            return (1, index, 0.0, 0.0, index)
        bbox = self._source_bbox(block)
        if bbox is None:
            return (0, page, float(index), 0.0, index)
        x0, y0, _x1, _y1 = bbox
        return (0, page, y0, x0, index)

    def _source_bbox(self, block: NormalizedBlock) -> tuple[float, float, float, float] | None:
        value = block.source_item.get("bbox")
        if not isinstance(value, list | tuple) or len(value) != 4:
            return None
        coords: list[float] = []
        for item in value:
            if not isinstance(item, int | float):
                return None
            coords.append(float(item))
        x0, y0, x1, y1 = coords
        if x1 <= x0 or y1 <= y0:
            return None
        return x0, y0, x1, y1

    def _piece_from_assembled(self, unit: AssembledReferenceUnit) -> SplitPiece:
        return SplitPiece(
            text=unit.text,
            source_location=dict(unit.source_location),
            metadata=dict(unit.metadata),
            runtime_source_id=unit.runtime_source_id,
            content_type=unit.content_type,
            preview_ref=unit.preview_ref,
        )

    def _source_block_ref(
        self,
        block: NormalizedBlock,
        *,
        content_ref: str,
        index: int,
    ) -> str:
        for key in ("id", "block_id"):
            value = block.source_item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return f"{content_ref}:block:{index}"

    def _reference_unit_sections(
        self,
        chunk: AdapterChunk,
        profile: ChunkProfile,
        domain_metadata: DomainMetadata,
    ) -> list[SplitPiece]:
        del domain_metadata

        if profile.semantics is None or not profile.semantics.canonical_units_enabled:
            return []

        units = self._reference_text_units(chunk.text, profile)
        if len(units) <= 1:
            return []

        return [
            self._piece_from_parent(chunk, text, source_location=dict(chunk.source_location))
            for unit in units
            for text in self._hard_split_text(unit, profile.hard_max_words)
            if text.strip()
        ]

    def _reference_unit_sections_for_ordered_group(
        self,
        chunk: AdapterChunk,
        group: OrderedTextGroup,
        profile: ChunkProfile,
        domain_metadata: DomainMetadata,
    ) -> list[SplitPiece]:
        del domain_metadata

        if profile.semantics is None or not profile.semantics.canonical_units_enabled:
            return []

        units = self._reference_text_units(chunk.text, profile)
        if len(units) <= 1:
            return []

        pieces: list[SplitPiece] = []
        cursor = 0
        for unit in units:
            unit_start = chunk.text.find(unit, cursor)
            if unit_start < 0:
                unit_start = chunk.text.find(unit)
            unit_end = unit_start + len(unit) if unit_start >= 0 else len(chunk.text)
            cursor = unit_end
            unit_location = self._source_location_for_text_span(
                chunk.source_location,
                group,
                start=unit_start,
                end=unit_end,
            )
            unit_chunk = AdapterChunk(
                text=unit,
                source_location=unit_location,
                metadata=dict(chunk.metadata),
                runtime_source_id=chunk.runtime_source_id,
                content_type=chunk.content_type,
                preview_ref=chunk.preview_ref,
            )
            hard_split_parts = self._hard_split_text(unit, profile.hard_max_words)
            if len(hard_split_parts) <= 1:
                metadata = dict(chunk.metadata)
                warnings = self._warnings_for_text_span(group, start=unit_start, end=unit_end)
                if warnings:
                    self._merge_parser_warnings(metadata, warnings)
                unit_chunk = AdapterChunk(
                    text=unit,
                    source_location=unit_location,
                    metadata=metadata,
                    runtime_source_id=chunk.runtime_source_id,
                    content_type=chunk.content_type,
                    preview_ref=chunk.preview_ref,
                )

            pieces.extend(
                self._reference_unit_hard_split_pieces(
                    unit_chunk,
                    group,
                    hard_split_parts,
                    unit_start=unit_start,
                    unit_end=unit_end,
                )
            )
        return pieces

    def _reference_text_units(self, text: str, profile: ChunkProfile) -> list[str]:
        if profile.semantics is None:
            return []
        if (
            profile.semantics.inline_reference_policy == "cross_reference_only"
            and profile.semantics.has_primary_unit_anchor
        ):
            return profile.semantics.split_primary_anchor_units(text)
        return profile.semantics.split_reference_units(text)

    def _source_location_for_text_span(
        self,
        source_location: dict[str, Any],
        group: OrderedTextGroup,
        *,
        start: int,
        end: int,
    ) -> dict[str, Any]:
        blocks = self._blocks_for_text_span(group, start=start, end=end)
        pages = [block.page for block in blocks if block.page is not None]
        if not pages:
            return dict(source_location)
        return self._source_location_with_page_range(
            source_location,
            page_start=min(pages),
            page_end=max(pages),
        )

    def _warnings_for_text_span(
        self,
        group: OrderedTextGroup,
        *,
        start: int,
        end: int,
    ) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        for block in self._blocks_for_text_span(group, start=start, end=end):
            warnings.extend(block.warnings)
        return warnings

    def _reference_unit_hard_split_pieces(
        self,
        chunk: AdapterChunk,
        group: OrderedTextGroup,
        parts: list[str],
        *,
        unit_start: int,
        unit_end: int,
    ) -> list[SplitPiece]:
        if len(parts) <= 1:
            return [
                self._piece_from_parent(
                    chunk,
                    part,
                    source_location=dict(chunk.source_location),
                )
                for part in parts
                if part.strip()
            ]

        pieces: list[SplitPiece] = []
        word_cursor = 0
        for part in parts:
            if not part.strip():
                continue
            span = self._text_span_for_split_child(
                group.text,
                part,
                start=unit_start,
                end=unit_end,
                word_cursor=word_cursor,
            )
            metadata = dict(chunk.metadata)
            if span is None:
                source_location = self._broad_source_location(chunk.source_location)
            else:
                child_start, child_end, word_cursor = span
                source_location = self._source_location_for_text_span(
                    chunk.source_location,
                    group,
                    start=child_start,
                    end=child_end,
                )
                warnings = self._warnings_for_text_span(group, start=child_start, end=child_end)
                if warnings:
                    self._merge_parser_warnings(metadata, warnings)

            child_chunk = AdapterChunk(
                text=part,
                source_location=source_location,
                metadata=metadata,
                runtime_source_id=chunk.runtime_source_id,
                content_type=chunk.content_type,
                preview_ref=chunk.preview_ref,
            )
            pieces.append(
                self._piece_from_parent(
                    child_chunk,
                    part,
                    source_location=source_location,
                )
            )
        return pieces

    def _text_span_for_split_child(
        self,
        text: str,
        child_text: str,
        *,
        start: int,
        end: int,
        word_cursor: int,
    ) -> tuple[int, int, int] | None:
        child_words = child_text.split()
        if not child_words:
            return None

        word_spans = [
            (match.group(0), match.start(), match.end())
            for match in re.finditer(r"\S+", text)
            if match.end() > start and match.start() < end
        ]
        if not word_spans:
            return None

        search_start = max(word_cursor, 0)
        max_start = len(word_spans) - len(child_words)
        for index in range(search_start, max_start + 1):
            candidate = [
                word
                for word, _start, _end in word_spans[index : index + len(child_words)]
            ]
            if candidate == child_words:
                return (
                    word_spans[index][1],
                    word_spans[index + len(child_words) - 1][2],
                    index + len(child_words),
                )
        return None

    def _broad_source_location(self, source_location: dict[str, Any]) -> dict[str, Any]:
        updated = dict(source_location)
        if "page_start" in updated or "page_end" in updated:
            updated.pop("page", None)
        return updated

    def _blocks_for_text_span(
        self,
        group: OrderedTextGroup,
        *,
        start: int,
        end: int,
    ) -> list[OrderedTextBlock]:
        if start < 0:
            return group.blocks
        blocks = [
            block
            for block in group.blocks
            if block.end > start and block.start < end
        ]
        return blocks or group.blocks

    def _source_location_with_page_range(
        self,
        source_location: dict[str, Any],
        *,
        page_start: int | None,
        page_end: int | None,
    ) -> dict[str, Any]:
        updated = dict(source_location)
        if page_start is not None:
            updated["page_start"] = page_start
        if page_end is not None:
            updated["page_end"] = page_end
        if page_start is not None or page_end is not None:
            updated.pop("page", None)
        return updated

    def _markdown_sections(self, text: str) -> list[str]:
        blocks = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
        sections: list[str] = []
        current: list[str] = []
        for block in blocks:
            if current and self._starts_boundary(block):
                sections.append("\n\n".join(current).strip())
                current = []
            current.append(block)

        if current:
            sections.append("\n\n".join(current).strip())
        return sections or ([text.strip()] if text.strip() else [])

    def _starts_boundary(self, block: str) -> bool:
        patterns = (
            r"^#{1,6}\s+",
            r"^\[\[?page\s+\d+\]?\]",
            r"^page\s+\d+\b",
            r"^\d+\.\s+",
        )
        return any(re.match(pattern, block, flags=re.IGNORECASE) for pattern in patterns)

    def _pack_sections(self, sections: list[str], profile: ChunkProfile) -> list[str]:
        packed: list[str] = []
        current: list[str] = []
        current_words = 0

        for section in sections:
            for part in self._hard_split_text(section, profile.hard_max_words):
                part_words = self._word_count(part)
                if current and current_words + part_words > profile.target_words:
                    packed.append("\n\n".join(current).strip())
                    current = []
                    current_words = 0

                current.append(part)
                current_words += part_words
                if current_words >= profile.hard_max_words:
                    packed.append("\n\n".join(current).strip())
                    current = []
                    current_words = 0

        if current:
            packed.append("\n\n".join(current).strip())
        return packed

    # Sentence-boundary pattern: split after punctuation followed by whitespace.
    _SENTENCE_END_RE = re.compile(
        r"(?<=[.!?\u061f\u0964\u3002])\s+"
    )
    _SEMANTIC_BOUNDARY_RE = re.compile(r"\n+|(?<=[.!?\u061f\u0964\u3002,;:])\s+")

    def _hard_split_text(self, text: str, hard_max_words: int) -> list[str]:
        source_words = text.split()
        if len(source_words) <= hard_max_words:
            return [text.strip()] if text.strip() else []

        # Sentence-aware splitting: pack sentences into chunks.
        sentences = self._SENTENCE_END_RE.split(text)
        chunks: list[str] = []
        current: list[str] = []
        current_words = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            sentence_word_count = len(sentence.split())

            # If a single sentence exceeds the limit, prefer a nearby semantic boundary.
            if sentence_word_count > hard_max_words:
                if current:
                    chunks.append(" ".join(current))
                    current = []
                    current_words = 0
                chunks.extend(self._split_oversized_sentence(sentence, hard_max_words))
                continue

            if current_words + sentence_word_count > hard_max_words and current:
                chunks.append(" ".join(current))
                current = []
                current_words = 0

            current.append(sentence)
            current_words += sentence_word_count

        if current:
            chunks.append(" ".join(current))

        return [c for c in chunks if c.strip()]

    def _split_oversized_sentence(self, text: str, hard_max_words: int) -> list[str]:
        chunks: list[str] = []
        remaining = text.strip()

        while remaining:
            remaining_words = remaining.split()
            if len(remaining_words) <= hard_max_words:
                chunks.append(remaining)
                break

            split_index = self._semantic_split_index(remaining, hard_max_words)
            if split_index is None:
                chunks.append(" ".join(remaining_words[:hard_max_words]))
                remaining = " ".join(remaining_words[hard_max_words:]).strip()
                continue

            chunks.append(remaining[:split_index].strip())
            remaining = remaining[split_index:].strip()

        return chunks

    def _semantic_split_index(self, text: str, hard_max_words: int) -> int | None:
        word_matches = list(re.finditer(r"\S+", text))
        if len(word_matches) <= hard_max_words:
            return None

        lower_word_index = max(1, int(hard_max_words * SEMANTIC_SPLIT_LOWER_BOUND_RATIO))
        lower_bound = word_matches[lower_word_index - 1].end()
        upper_bound = word_matches[hard_max_words - 1].end()
        split_index: int | None = None

        for match in self._SEMANTIC_BOUNDARY_RE.finditer(text):
            if match.end() <= lower_bound:
                continue
            if match.end() > upper_bound:
                break
            split_index = match.end()

        return split_index

    def _with_split_metadata(
        self,
        piece: SplitPiece,
        *,
        parent: AdapterChunk,
        profile: ChunkProfile,
        expected_profile: ExpectedContentProfile,
        domain_metadata: DomainMetadata,
        split_index: int,
        split_count: int,
    ) -> AdapterChunk:
        metadata = dict(piece.metadata)
        self._enrich_metadata(metadata, piece=piece, profile=profile)
        if not self._is_provenance_only_piece(piece):
            self._merge_parser_warnings(
                metadata,
                self._classified_quality_warnings(
                    piece.text,
                    metadata,
                    expected_profile=expected_profile,
                    domain_metadata=domain_metadata,
                ),
            )
        parser_metadata = dict(self._parser_metadata(parent))
        parser_metadata.update(self._parser_metadata(piece))
        parent_parser_metadata = self._parser_metadata(parent)
        parser_metadata.update(
            {
                "split_strategy": "metadata_profile",
                "split_profile": profile.name,
                "parent_artifact_ref": parent_parser_metadata.get("artifact_ref")
                or parent.source_location.get("artifact"),
                "parent_chunk_index": parent_parser_metadata.get("chunk_index"),
                "split_index": split_index,
                "split_count": split_count,
                "chunk_index": split_index,
            }
        )
        metadata["parser_metadata"] = parser_metadata
        return AdapterChunk(
            text=piece.text,
            source_location=dict(piece.source_location),
            metadata=metadata,
            runtime_source_id=piece.runtime_source_id,
            content_type=piece.content_type,
            preview_ref=piece.preview_ref,
        )

    def _is_provenance_only_piece(self, piece: SplitPiece) -> bool:
        if piece.content_type == "reference_provenance":
            return True
        parser_metadata = self._parser_metadata(piece)
        return bool(parser_metadata.get("provenance_only"))

    def _piece_from_parent(
        self,
        parent: AdapterChunk,
        text: str,
        *,
        source_location: dict[str, Any],
    ) -> SplitPiece:
        cleaned = self._clean_mineru_noise(text)
        return SplitPiece(
            text=cleaned.strip(),
            source_location=dict(source_location),
            metadata=dict(parent.metadata),
            runtime_source_id=parent.runtime_source_id,
            content_type=parent.content_type,
            preview_ref=parent.preview_ref,
        )

    def _parser_metadata(self, chunk: AdapterChunk | SplitPiece) -> dict[str, Any]:
        value = chunk.metadata.get("parser_metadata")
        return dict(value) if isinstance(value, dict) else {}

    def _word_count(self, text: str) -> int:
        return len(text.split())

    def _should_preserve_piece(self, piece: SplitPiece, parent: AdapterChunk) -> bool:
        if piece.source_location != parent.source_location:
            return True
        return piece.metadata != parent.metadata

    def _should_enrich_unchanged(
        self,
        piece: SplitPiece,
        profile: ChunkProfile,
        expected_profile: ExpectedContentProfile,
        domain_metadata: DomainMetadata,
    ) -> bool:
        warnings = [
            *self._classified_existing_parser_warnings(
                piece.metadata,
                domain_metadata=domain_metadata,
            ),
            *self._classified_quality_warnings(
                piece.text,
                piece.metadata,
                expected_profile=expected_profile,
                domain_metadata=domain_metadata,
            ),
        ]
        if self._warnings_require_chunk_enrichment(warnings):
            return True
        if profile.semantics is None:
            return False
        if profile.semantics.derive_reference_metadata(piece.text, piece.source_location):
            return True
        return self._document_title(piece.text, piece.source_location) is not None

    def _classified_quality_warnings(
        self,
        text: str,
        metadata: dict[str, Any],
        *,
        expected_profile: ExpectedContentProfile,
        domain_metadata: DomainMetadata,
    ) -> list[dict[str, Any]]:
        warnings = ChunkQualityGate(expected_profile, domain_metadata).warnings_for(
            text,
            metadata,
        )
        existing_codes = self._existing_parser_warning_codes(metadata)
        warnings = [
            warning
            for warning in warnings
            if not isinstance(warning.get("code"), str) or warning["code"] not in existing_codes
        ]
        return ParserQualityIntelligentGate().classify_warnings(
            warnings,
            domain_metadata=domain_metadata,
        )

    def _classified_existing_parser_warnings(
        self,
        metadata: dict[str, Any],
        *,
        domain_metadata: DomainMetadata,
    ) -> list[dict[str, Any]]:
        extraction_quality = metadata.get("extraction_quality")
        if not isinstance(extraction_quality, dict):
            return []
        warnings = extraction_quality.get("parser_warnings")
        if not isinstance(warnings, list):
            return []
        return ParserQualityIntelligentGate().classify_warnings(
            [warning for warning in warnings if isinstance(warning, dict)],
            domain_metadata=domain_metadata,
        )

    def _existing_parser_warning_codes(self, metadata: dict[str, Any]) -> set[str]:
        extraction_quality = metadata.get("extraction_quality")
        if not isinstance(extraction_quality, dict):
            return set()
        warnings = extraction_quality.get("parser_warnings")
        if not isinstance(warnings, list):
            return set()
        return {
            code
            for warning in warnings
            if isinstance(warning, dict)
            for code in (warning.get("code"),)
            if isinstance(code, str) and code
        }

    def _warnings_require_chunk_enrichment(
        self,
        warnings: list[dict[str, Any]],
    ) -> bool:
        return any(not bool(warning.get("suppressed_from_counts")) for warning in warnings)

    def _enrich_metadata(
        self,
        metadata: dict[str, Any],
        *,
        piece: SplitPiece,
        profile: ChunkProfile,
    ) -> None:
        if profile.semantics is None:
            return

        reference_metadata = profile.semantics.derive_reference_metadata(
            piece.text,
            piece.source_location,
        )
        if reference_metadata:
            metadata["reference_metadata"] = reference_metadata
            self._enrich_canonical_reference_unit(
                metadata,
                reference_metadata=reference_metadata,
                profile=profile,
            )

        title = self._document_title(piece.text, piece.source_location)
        if title:
            document_metadata = dict(metadata.get("document_metadata") or {})
            document_metadata["title"] = title
            metadata["document_metadata"] = document_metadata

    def _enrich_canonical_reference_unit(
        self,
        metadata: dict[str, Any],
        *,
        reference_metadata: dict[str, Any],
        profile: ChunkProfile,
    ) -> None:
        semantics = profile.semantics
        if semantics is None or not semantics.canonical_units_enabled:
            return
        if isinstance(metadata.get("canonical_reference_unit"), dict):
            return
        references = reference_metadata.get("references")
        if not isinstance(references, list) or len(references) != 1:
            return
        reference = references[0]
        if not isinstance(reference, str) or not reference:
            return
        metadata["canonical_reference_unit"] = {
            "reference": reference,
            "unit": semantics.chunk_unit,
            "answerable": True,
            "body_status": "split_unit",
            "assembly_strategy": "structured_reference_metadata",
        }

    def _merge_parser_warnings(
        self,
        metadata: dict[str, Any],
        warnings: list[dict[str, Any]],
    ) -> None:
        DomainMetadataQualityGate.merge_parser_warnings(metadata, warnings)

    def _warning_only_piece(
        self,
        chunk: AdapterChunk,
        warnings: list[dict[str, Any]],
        *,
        source_location: dict[str, Any] | None = None,
        content_ref: str,
    ) -> SplitPiece:
        metadata = dict(chunk.metadata)
        self._merge_parser_warnings(metadata, warnings)
        parser_metadata = dict(self._parser_metadata(chunk))
        parser_metadata["parser_quality_only"] = True
        parser_metadata["content_list_ref"] = content_ref
        metadata["parser_metadata"] = parser_metadata

        pages = [
            warning.get("page")
            for warning in warnings
            if isinstance(warning.get("page"), int)
        ]
        source_location = dict(source_location or chunk.source_location)
        if pages:
            source_location["page_start"] = min(pages)
            source_location["page_end"] = max(pages)
            source_location.pop("page", None)

        return SplitPiece(
            text=(
                "[Parser quality gate quarantined this content-list page; "
                "no trusted text was extracted.]"
            ),
            source_location=source_location,
            metadata=metadata,
            runtime_source_id=chunk.runtime_source_id,
            content_type="parser_quality_warning",
            preview_ref=chunk.preview_ref,
        )

    def _split_title_sections(
        self,
        sections: list[str],
        chunk: AdapterChunk,
        profile: ChunkProfile,
    ) -> tuple[list[str], list[str]]:
        if profile.semantics is None or not self._is_early_source_location(chunk.source_location):
            return [], sections

        first_blocks = [
            block.strip()
            for block in re.split(r"\n{2,}", sections[0] if sections else "")
            if block.strip()
        ]
        if len(first_blocks) >= 2:
            candidate = "\n\n".join(first_blocks[:2]).strip()
            if (
                self._document_title(
                    candidate,
                    chunk.source_location,
                    semantics=profile.semantics,
                )
                is not None
            ):
                remaining = sections[1:]
                if len(first_blocks) > 2:
                    remaining = ["\n\n".join(first_blocks[2:]).strip(), *remaining]
                return [candidate], remaining

        if len(sections) < 3:
            return [], sections
        candidate = "\n\n".join(sections[:2]).strip()
        if (
            self._document_title(
                candidate,
                chunk.source_location,
                semantics=profile.semantics,
            )
            is not None
        ):
            return [candidate], sections[2:]
        return [], sections

    def _document_title(
        self,
        text: str,
        source_location: dict[str, Any] | None = None,
        *,
        semantics: ReferenceSemantics | None = None,
    ) -> str | None:
        if not self._is_early_source_location(source_location):
            return None

        blocks = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
        if len(blocks) < 2:
            return None

        title_blocks = blocks[:2]
        if any(self._starts_boundary(block) for block in title_blocks):
            return None
        joined = " ".join(title_blocks).strip()
        if semantics is not None and semantics.extract_primary_anchor_references(joined):
            return None
        if len(joined.split()) <= 18:
            return joined
        return None

    def _is_early_source_location(self, source_location: dict[str, Any] | None) -> bool:
        if not isinstance(source_location, dict):
            return True
        page = source_location.get("page_start", source_location.get("page"))
        if page is None:
            return True
        return isinstance(page, int) and page <= 2

    def _clean_mineru_noise(self, text: str) -> str:
        # Remove isolated LaTeX math blocks that MinerU sometimes hallucinates around OCR text.
        cleaned = re.sub(
            r"\$\$\s*(?:(?:\\?(?:sin|cos|tan|cot|theta|alpha|beta|pi|rho|angle|infty|Join|hookrightarrow))|[,|=\s])+\s*\$\$",
            " ",
            text,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"(?m)^\s*(?:[=\-|,|]|\\(?:theta|alpha|beta|pi|rho|angle|infty))\s*$",
            "",
            cleaned,
        )
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()
