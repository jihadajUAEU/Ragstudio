from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ragstudio.services.adapter import AdapterChunk


class MinerUExtractionContractError(RuntimeError):
    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class MinerUExtractionReport:
    chunk_count: int
    character_count: int
    page_count: int
    total_pages: int | None
    arabic_character_count: int
    parser_backend: str


class MinerUExtractionValidator:
    _ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
    _RAW_PDF_RE = re.compile(
        r"(%PDF-\d|/Type\s*/Page\b|/Filter\s*/FlateDecode\b|xref\s+\d|"
        r"\bobj\s*<<|\bendobj\b|\bstream\r?\n|\bendstream\b)"
    )

    def __init__(
        self,
        *,
        min_text_chars: int = 8,
        min_page_coverage_ratio: float = 0.5,
    ) -> None:
        self.min_text_chars = min_text_chars
        self.min_page_coverage_ratio = min_page_coverage_ratio

    def validate(
        self,
        chunks: list[AdapterChunk],
        *,
        expected_language: str = "unknown",
    ) -> MinerUExtractionReport:
        non_empty_chunks = [chunk for chunk in chunks if chunk.text.strip()]
        if not non_empty_chunks:
            raise MinerUExtractionContractError(
                "empty_extraction",
                "MinerU returned no text chunks.",
            )

        text = "\n".join(chunk.text.strip() for chunk in non_empty_chunks)
        if len(text) < self.min_text_chars:
            raise MinerUExtractionContractError(
                "text_too_short",
                "MinerU text is too short to index.",
            )
        if self._RAW_PDF_RE.search(text):
            raise MinerUExtractionContractError(
                "raw_pdf_syntax",
                "Extraction contains PDF object syntax.",
            )

        parser_backends = {
            self._parser_metadata(chunk).get("backend")
            for chunk in non_empty_chunks
        }
        if parser_backends != {"mineru"}:
            raise MinerUExtractionContractError(
                "non_mineru_backend",
                "All production chunks must come from MinerU.",
            )

        arabic_character_count = len(self._ARABIC_RE.findall(text))
        if expected_language.lower() == "arabic" and arabic_character_count == 0:
            raise MinerUExtractionContractError(
                "arabic_text_missing",
                "Expected Arabic text, but MinerU extraction contained none.",
            )

        pages = self._observed_pages(non_empty_chunks)
        total_pages = self._total_pages(non_empty_chunks)
        if total_pages is not None and total_pages > 1:
            coverage = len(pages) / total_pages
            if coverage < self.min_page_coverage_ratio:
                raise MinerUExtractionContractError(
                    "insufficient_page_coverage",
                    "MinerU extraction covers too few source pages.",
                )

        return MinerUExtractionReport(
            chunk_count=len(non_empty_chunks),
            character_count=len(text),
            page_count=len(pages),
            total_pages=total_pages,
            arabic_character_count=arabic_character_count,
            parser_backend="mineru",
        )

    def _parser_metadata(self, chunk: AdapterChunk) -> dict[str, Any]:
        metadata = chunk.metadata.get("parser_metadata")
        return metadata if isinstance(metadata, dict) else {}

    def _observed_pages(self, chunks: list[AdapterChunk]) -> set[int]:
        pages: set[int] = set()
        for chunk in chunks:
            for value in (
                chunk.source_location.get("page"),
                chunk.source_location.get("page_start"),
                self._parser_metadata(chunk).get("page"),
                self._parser_metadata(chunk).get("pageNumber"),
            ):
                if isinstance(value, int) and value > 0:
                    pages.add(value)
            start = chunk.source_location.get("page_start")
            end = chunk.source_location.get("page_end")
            if isinstance(start, int) and isinstance(end, int) and start > 0 and end >= start:
                pages.update(range(start, end + 1))
        return pages

    def _total_pages(self, chunks: list[AdapterChunk]) -> int | None:
        for chunk in chunks:
            parser_metadata = self._parser_metadata(chunk)
            for key in ("total_pages", "page_count", "pages"):
                value = parser_metadata.get(key)
                if isinstance(value, int) and value > 0:
                    return value
        return None
