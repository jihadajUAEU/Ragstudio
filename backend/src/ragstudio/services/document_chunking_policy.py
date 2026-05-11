from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from ragstudio.services.adapter import AdapterChunk

REFERENCE_PATTERN = re.compile(r"\[(\d{1,3}:\d{1,3})\]")


class DocumentChunkingPolicy:
    def __init__(self, *, max_chars: int = 1800, neighbor_window: int = 1) -> None:
        self.max_chars = max_chars
        self.neighbor_window = neighbor_window

    def split_mineru_chunks(
        self,
        chunks: list[AdapterChunk],
        *,
        domain_metadata: dict[str, Any] | None = None,
    ) -> list[AdapterChunk]:
        domain = (domain_metadata or {}).get("domain")
        output: list[AdapterChunk] = []
        for chunk in chunks:
            if domain == "quran" or self._references(chunk):
                output.extend(self._split_reference_chunk(chunk))
            else:
                output.extend(self._split_plain_chunk(chunk))
        return output

    def neighbor_context(
        self,
        chunks: list[AdapterChunk],
        *,
        target_reference: str,
    ) -> list[AdapterChunk]:
        selected: list[AdapterChunk] = []
        target_family, target_number = _reference_parts(target_reference)
        if target_family is None or target_number is None:
            return selected

        for chunk in chunks:
            refs = self._references(chunk)
            if not refs:
                continue
            ref_family, ref_number = _reference_parts(refs[0])
            if (
                refs[0] != target_reference
                and ref_family == target_family
                and ref_number is not None
                and abs(ref_number - target_number) <= self.neighbor_window
            ):
                selected.append(chunk)
        return selected

    def _split_reference_chunk(self, chunk: AdapterChunk) -> list[AdapterChunk]:
        spans = list(REFERENCE_PATTERN.finditer(chunk.text))
        if len(chunk.text) <= self.max_chars or not spans:
            return [chunk]

        split_chunks: list[AdapterChunk] = []
        for index, match in enumerate(spans):
            start = match.start()
            end = spans[index + 1].start() if index + 1 < len(spans) else len(chunk.text)
            text = chunk.text[start:end].strip()
            if not text:
                continue
            reference = match.group(1)
            metadata = {
                **chunk.metadata,
                "reference_metadata": {"references": [reference]},
                "chunking": {
                    "policy": "reference_boundary",
                    "parent_runtime_source_id": chunk.runtime_source_id,
                },
            }
            split_chunks.append(replace(chunk, text=text, metadata=metadata))
        return split_chunks

    def _split_plain_chunk(self, chunk: AdapterChunk) -> list[AdapterChunk]:
        if len(chunk.text) <= self.max_chars:
            return [chunk]
        parts = [
            chunk.text[index : index + self.max_chars].strip()
            for index in range(0, len(chunk.text), self.max_chars)
        ]
        return [
            replace(
                chunk,
                text=part,
                metadata={
                    **chunk.metadata,
                    "chunking": {"policy": "hard_char_limit", "part": index},
                },
            )
            for index, part in enumerate(parts)
            if part
        ]

    def _references(self, chunk: AdapterChunk) -> list[str]:
        metadata_refs = chunk.metadata.get("reference_metadata", {}).get("references", [])
        if isinstance(metadata_refs, list) and metadata_refs:
            return [str(ref) for ref in metadata_refs]
        return [match.group(1) for match in REFERENCE_PATTERN.finditer(chunk.text)]


def _reference_parts(reference: str) -> tuple[str | None, int | None]:
    family, separator, number = reference.partition(":")
    if not separator:
        return None, None
    try:
        return family, int(number)
    except ValueError:
        return family, None
