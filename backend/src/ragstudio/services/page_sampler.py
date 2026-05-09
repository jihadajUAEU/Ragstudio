from __future__ import annotations

import base64
from dataclasses import dataclass


@dataclass(frozen=True)
class SampledPage:
    page_number: int
    text: str
    image_data_url: str | None = None


class PageSampler:
    def __init__(self, max_pages: int = 4, max_text_chars: int = 4000):
        self.max_pages = max_pages
        self.max_text_chars = max_text_chars
        self.warnings: list[str] = []

    def sample(self, data: bytes, *, filename: str, content_type: str) -> list[SampledPage]:
        self.warnings = []
        lower_name = filename.lower()
        if content_type == "application/pdf" or lower_name.endswith(".pdf"):
            return self._sample_pdf(data)
        return self._sample_text(data)

    def _sample_pdf(self, data: bytes) -> list[SampledPage]:
        try:
            import fitz

            document = fitz.open(stream=data, filetype="pdf")
            indexes = self._representative_indexes(document.page_count)
            pages: list[SampledPage] = []
            for index in indexes:
                page = document.load_page(index)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                image_data = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
                pages.append(
                    SampledPage(
                        page_number=index + 1,
                        text=page.get_text("text")[: self.max_text_chars].strip(),
                        image_data_url=f"data:image/png;base64,{image_data}",
                    )
                )
            document.close()
            return pages
        except Exception as exc:
            self.warnings.append(f"Could not sample PDF pages: {exc}")
            return []

    def _sample_text(self, data: bytes) -> list[SampledPage]:
        text = data.decode("utf-8", errors="replace")
        if not text.strip():
            return []
        segment_length = max(len(text) // 3, 1)
        starts = [
            0,
            max((len(text) - segment_length) // 2, 0),
            max(len(text) - segment_length, 0),
        ]
        pages: list[SampledPage] = []
        seen: set[int] = set()
        for page_number, start in enumerate(starts, start=1):
            if start in seen:
                continue
            seen.add(start)
            pages.append(
                SampledPage(
                    page_number=page_number,
                    text=text[start : start + self.max_text_chars].strip(),
                )
            )
        return pages

    def _representative_indexes(self, page_count: int) -> list[int]:
        if page_count <= 0:
            return []
        candidates = [0, 1, page_count // 2, page_count - 1]
        indexes: list[int] = []
        for candidate in candidates:
            bounded = min(max(candidate, 0), page_count - 1)
            if bounded not in indexes:
                indexes.append(bounded)
            if len(indexes) == self.max_pages:
                break
        return indexes
