from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata, ParserMode
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.reference_metadata import ReferenceSemantics


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


class ChunkSplitter:
    def __init__(self, *, max_words: int = 1500) -> None:
        self.max_words = max_words

    def split(
        self,
        chunks: list[AdapterChunk],
        *,
        domain_metadata: DomainMetadata,
        parser_mode: ParserMode,
    ) -> list[AdapterChunk]:
        del parser_mode

        profile = self._profile(domain_metadata)
        output: list[AdapterChunk] = []
        for chunk in chunks:
            pieces = self._split_chunk(chunk, profile)
            if len(pieces) == 1 and pieces[0].text == chunk.text:
                if self._should_enrich_unchanged(pieces[0], profile):
                    output.append(
                        self._with_split_metadata(
                            pieces[0],
                            parent=chunk,
                            profile=profile,
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

    def _split_chunk(self, chunk: AdapterChunk, profile: ChunkProfile) -> list[SplitPiece]:
        content_list_chunks = self._chunks_from_content_list(chunk, profile)
        if content_list_chunks:
            return content_list_chunks

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
        reference_units = self._reference_unit_sections(body_chunk, profile)
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
    ) -> list[SplitPiece]:
        parser_metadata = self._parser_metadata(chunk)
        extract_dir = parser_metadata.get("artifact_extract_dir")
        content_ref = parser_metadata.get("content_list_ref")
        if not isinstance(extract_dir, str) or not isinstance(content_ref, str):
            return []

        root = Path(extract_dir).resolve()
        target = (root / content_ref).resolve()
        if target != root and root not in target.parents:
            return []

        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        if not isinstance(data, list):
            return []

        page_parts: dict[int, list[str]] = {}
        for item in data:
            if not isinstance(item, dict):
                continue

            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                text = item.get("content")
            page_idx = item.get("page_idx")
            if not isinstance(text, str) or not text.strip() or not isinstance(page_idx, int):
                continue

            page_parts.setdefault(page_idx + 1, []).append(text.strip())

        pieces: list[SplitPiece] = []
        for page in sorted(page_parts):
            text = "\n\n".join(page_parts[page])
            source_location = dict(chunk.source_location)
            source_location["page_start"] = page
            source_location["page_end"] = page
            page_chunk = AdapterChunk(
                text=text,
                source_location=source_location,
                metadata=chunk.metadata,
                runtime_source_id=chunk.runtime_source_id,
                content_type=chunk.content_type,
                preview_ref=chunk.preview_ref,
            )
            reference_units = self._reference_unit_sections(page_chunk, profile)
            if reference_units:
                pieces.extend(reference_units)
                continue
            for part in self._hard_split_text(text, profile.hard_max_words):
                pieces.append(self._piece_from_parent(chunk, part, source_location=source_location))
        return pieces

    def _reference_unit_sections(
        self,
        chunk: AdapterChunk,
        profile: ChunkProfile,
    ) -> list[SplitPiece]:
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
        split_index: int,
        split_count: int,
    ) -> AdapterChunk:
        metadata = dict(piece.metadata)
        self._enrich_metadata(metadata, piece=piece, profile=profile)
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

    def _should_enrich_unchanged(self, piece: SplitPiece, profile: ChunkProfile) -> bool:
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
