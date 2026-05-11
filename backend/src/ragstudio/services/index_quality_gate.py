from __future__ import annotations

import re
from typing import Any

from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.arabic_text import arabic_tokens


class IndexQualityGateError(RuntimeError):
    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


class IndexQualityGate:
    raw_pdf_pattern = re.compile(r"(%PDF-\d|\b\d+\s+\d+\s+obj\b|\bxref\b|\bendobj\b)")

    def validate_adapter_chunks(
        self,
        chunks: list[AdapterChunk],
        *,
        language: str = "unknown",
    ) -> dict[str, Any]:
        text = "\n".join(chunk.text for chunk in chunks)
        if self.raw_pdf_pattern.search(text):
            raise IndexQualityGateError(
                "raw_pdf_persisted",
                "Raw PDF syntax reached chunk persistence.",
            )

        tokens = arabic_tokens(text)
        if language in {"arabic", "quran"} and not tokens:
            raise IndexQualityGateError(
                "arabic_tokens_missing",
                "Arabic document has no normalized Arabic search tokens.",
            )

        return {
            "status": "passed",
            "chunk_count": len(chunks),
            "arabic_token_count": len(tokens),
        }

