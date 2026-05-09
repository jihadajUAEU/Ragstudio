from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata, ParserMode
from ragstudio.services.adapter import AdapterChunk


@dataclass(frozen=True)
class ChunkProfile:
    name: str
    target_words: int
    hard_max_words: int


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
        domain = (metadata.domain or "").casefold()
        document_type = (metadata.document_type or "").casefold()
        if domain == "tafseer" or document_type == "book":
            return ChunkProfile("tafseer_book", target_words=1000, hard_max_words=self.max_words)
        if domain == "quran":
            return ChunkProfile(
                "quran_verse",
                target_words=500,
                hard_max_words=min(self.max_words, 900),
            )
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
        pieces = self._pack_sections(sections, profile)
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
            for part in self._hard_split_text(text, profile.hard_max_words):
                pieces.append(self._piece_from_parent(chunk, part, source_location=source_location))
        return pieces

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
            r"^\[\[?page\s+\d+\]?\]",
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
        return SplitPiece(
            text=text.strip(),
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
