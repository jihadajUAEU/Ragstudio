from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata, ParserMode
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_quality_gate import ChunkQualityGate
from ragstudio.services.domain_metadata_quality_gate import DomainMetadataQualityGate
from ragstudio.services.parser_normalization import (
    ExpectedContentProfile,
    MinerUContentNormalizer,
    NormalizedBlock,
)
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


class ChunkSplitter:
    def __init__(self, *, max_words: int = 1500) -> None:
        self.max_words = max_words
        self.content_normalizer = MinerUContentNormalizer()
        self.reference_unit_assembler = ReferenceUnitAssembler()

    def split(
        self,
        chunks: list[AdapterChunk],
        *,
        domain_metadata: DomainMetadata,
        parser_mode: ParserMode,
    ) -> list[AdapterChunk]:
        del parser_mode

        profile = self._profile(domain_metadata)
        expected_profile = ExpectedContentProfile.from_domain_metadata(domain_metadata)
        output: list[AdapterChunk] = []
        for chunk in chunks:
            pieces = self._split_chunk(
                chunk,
                profile,
                expected_profile,
                domain_metadata,
            )
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
        if semantics.profile_name == "scripture_reference":
            return ChunkProfile(
                "scripture_reference",
                target_words=500,
                hard_max_words=min(self.max_words, 900),
                semantics=semantics,
            )

        domain = (metadata.domain or "").casefold()
        document_type = (metadata.document_type or "").casefold()
        if domain == "tafseer" or document_type == "book":
            return ChunkProfile("tafseer_book", target_words=1000, hard_max_words=self.max_words)
        if document_type == "paper":
            return ChunkProfile(
                "paper_section",
                target_words=800,
                hard_max_words=min(self.max_words, 1200),
            )
        if document_type == "table":
            return ChunkProfile(
                "table_block",
                target_words=400,
                hard_max_words=min(self.max_words, 800),
            )
        return ChunkProfile("generic", target_words=1000, hard_max_words=self.max_words)

    def _split_chunk(
        self,
        chunk: AdapterChunk,
        profile: ChunkProfile,
        expected_profile: ExpectedContentProfile,
        domain_metadata: DomainMetadata,
    ) -> list[SplitPiece]:
        content_list_result = self._chunks_from_content_list(
            chunk,
            profile,
            expected_profile,
            domain_metadata,
        )
        if content_list_result is not None:
            return content_list_result.pieces

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
            return [*title_pieces, *reference_units]

        pieces = [*title_sections, *self._pack_sections(body_sections, profile)]
        return [
            self._piece_from_parent(chunk, text, source_location=dict(chunk.source_location))
            for text in pieces
            if text.strip()
        ]

    def _chunks_from_content_list(
        self,
        chunk: AdapterChunk,
        profile: ChunkProfile,
        expected_profile: ExpectedContentProfile,
        domain_metadata: DomainMetadata,
    ) -> ContentListSplitResult | None:
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

        normalized_blocks = self.content_normalizer.normalize_content_list(
            data,
            domain_metadata=domain_metadata,
            expected_profile=expected_profile,
        )
        canonical_pieces = self._canonical_reference_pieces(
            chunk,
            profile,
            normalized_blocks,
            content_ref=content_ref,
        )
        if canonical_pieces:
            return ContentListSplitResult(handled=True, pieces=canonical_pieces)

        page_parts: dict[int, list[str]] = {}
        page_warnings: dict[int, list[dict[str, Any]]] = {}
        unpaged_parts: list[str] = []
        unpaged_warnings: list[dict[str, Any]] = []
        for block in normalized_blocks:
            warnings = block.warning_metadata()
            if block.page is None:
                if warnings:
                    unpaged_warnings.extend(warnings)
                if block.text.strip():
                    unpaged_parts.append(block.text.strip())
                continue
            if warnings:
                page_warnings.setdefault(block.page, []).extend(warnings)
            if block.text.strip():
                page_parts.setdefault(block.page, []).append(block.text.strip())

        pieces: list[SplitPiece] = []
        if unpaged_parts:
            text = "\n\n".join(unpaged_parts)
            metadata = dict(chunk.metadata)
            if unpaged_warnings:
                self._merge_parser_warnings(metadata, unpaged_warnings)
            unpaged_chunk = AdapterChunk(
                text=text,
                source_location=dict(chunk.source_location),
                metadata=metadata,
                runtime_source_id=chunk.runtime_source_id,
                content_type=chunk.content_type,
                preview_ref=chunk.preview_ref,
            )
            reference_units = self._reference_unit_sections(
                unpaged_chunk,
                profile,
                domain_metadata,
            )
            if reference_units:
                pieces.extend(reference_units)
            else:
                for part in self._hard_split_text(text, profile.hard_max_words):
                    pieces.append(
                        self._piece_from_parent(
                            unpaged_chunk,
                            part,
                            source_location=dict(chunk.source_location),
                        )
                    )
        elif unpaged_warnings:
            pieces.append(
                self._warning_only_piece(
                    chunk,
                    unpaged_warnings,
                    content_ref=content_ref,
                )
            )
        for page in sorted(set(page_parts) | set(page_warnings)):
            text = "\n\n".join(page_parts.get(page, []))
            if not text.strip():
                warnings = page_warnings.get(page, [])
                if warnings:
                    pieces.append(
                        self._warning_only_piece(
                            chunk,
                            warnings,
                            content_ref=content_ref,
                        )
                    )
                continue
            source_location = dict(chunk.source_location)
            source_location["page_start"] = page
            source_location["page_end"] = page
            metadata = dict(chunk.metadata)
            warnings = page_warnings.get(page, [])
            if warnings:
                self._merge_parser_warnings(metadata, warnings)
            page_chunk = AdapterChunk(
                text=text,
                source_location=source_location,
                metadata=metadata,
                runtime_source_id=chunk.runtime_source_id,
                content_type=chunk.content_type,
                preview_ref=chunk.preview_ref,
            )
            reference_units = self._reference_unit_sections(
                page_chunk,
                profile,
                domain_metadata,
            )
            if reference_units:
                pieces.extend(reference_units)
                continue
            for part in self._hard_split_text(text, profile.hard_max_words):
                pieces.append(
                    self._piece_from_parent(page_chunk, part, source_location=source_location)
                )
        return ContentListSplitResult(handled=True, pieces=pieces)

    def _canonical_reference_pieces(
        self,
        chunk: AdapterChunk,
        profile: ChunkProfile,
        normalized_blocks: list[NormalizedBlock],
        *,
        content_ref: str,
    ) -> list[SplitPiece]:
        semantics = profile.semantics
        if semantics is None or not semantics.canonical_units_enabled:
            return []

        blocks: list[ReferenceSourceBlock] = []
        for index, block in enumerate(normalized_blocks):
            warning_codes = tuple(
                warning["code"]
                for warning in block.warning_metadata()
                if isinstance(warning.get("code"), str)
            )
            blocks.append(
                ReferenceSourceBlock(
                    text=block.text,
                    page_start=block.page,
                    page_end=block.page,
                    block_type=block.block_type,
                    parser_warning_codes=warning_codes,
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

        if profile.semantics is None or profile.semantics.chunk_unit not in {
            "hadith",
            "verse",
            "reference",
            "section",
        }:
            return []

        units = profile.semantics.split_reference_units(chunk.text)
        if len(units) <= 1:
            return []

        return [
            self._piece_from_parent(chunk, text, source_location=dict(chunk.source_location))
            for unit in units
            for text in self._hard_split_text(unit, profile.hard_max_words)
            if text.strip()
        ]

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
            r"^Verse\s+\d+:\d+\b",
            r"^Surah\s+\d+\b",
            r"^\[\[?page\s+\d+\]?\]",
            r"^\[\d+\s*:\s*\d+\]",
            r"^page\s+\d+\b",
            r"^\d+[:.]\d+\b",
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

    def _hard_split_text(self, text: str, hard_max_words: int) -> list[str]:
        source_words = text.split()
        if len(source_words) <= hard_max_words:
            return [text.strip()] if text.strip() else []
        return [
            " ".join(source_words[index : index + hard_max_words])
            for index in range(0, len(source_words), hard_max_words)
        ]

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
                ChunkQualityGate(expected_profile, domain_metadata).warnings_for(
                    piece.text,
                    metadata,
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
        if ChunkQualityGate(expected_profile, domain_metadata).warnings_for(
            piece.text,
            piece.metadata,
        ):
            return True
        if profile.semantics is None:
            return False
        if profile.semantics.derive_reference_metadata(piece.text, piece.source_location):
            return True
        return self._document_title(piece.text, piece.source_location) is not None

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

        title = self._document_title(piece.text, piece.source_location)
        if title:
            document_metadata = dict(metadata.get("document_metadata") or {})
            document_metadata["title"] = title
            metadata["document_metadata"] = document_metadata

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
        source_location = dict(chunk.source_location)
        if pages:
            source_location["page_start"] = min(pages)
            source_location["page_end"] = max(pages)

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
            if self._document_title(candidate, chunk.source_location) is not None:
                remaining = sections[1:]
                if len(first_blocks) > 2:
                    remaining = ["\n\n".join(first_blocks[2:]).strip(), *remaining]
                return [candidate], remaining

        if len(sections) < 3:
            return [], sections
        candidate = "\n\n".join(sections[:2]).strip()
        if self._document_title(candidate, chunk.source_location) is not None:
            return [candidate], sections[2:]
        return [], sections

    def _document_title(
        self,
        text: str,
        source_location: dict[str, Any] | None = None,
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
        if len(joined.split()) <= 18 and not re.search(r"\d+\s*:\s*\d+", joined):
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
