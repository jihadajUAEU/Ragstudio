from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

from ragstudio.services.runtime_types import RuntimeChunk

AdapterChunk = RuntimeChunk


class RAGAnythingAdapter:
    """Safe adapter boundary for optional raganything integration."""

    def __init__(self) -> None:
        self._package_available = self._can_import("raganything")

    def capability_report(self) -> dict[str, Any]:
        return {
            "raganything_available": self._package_available,
            "active_backend": "local_parser",
            "parser": "line_split",
            "indexing": "line_split_local",
        }

    async def delete_document_index(self, document_id: str) -> None:
        return None

    async def index_document(self, artifact_path: str | Path) -> list[RuntimeChunk]:
        return self._line_split_index(Path(artifact_path))

    def _line_split_index(self, artifact_path: Path) -> list[RuntimeChunk]:
        artifact_ref = artifact_path.name
        content = artifact_path.read_bytes().decode("utf-8", errors="replace")
        lines = content.splitlines()
        chunks: list[RuntimeChunk] = []

        for line_number, line in enumerate(lines, start=1):
            text = line.strip()
            if not text:
                continue
            chunks.append(
                RuntimeChunk(
                    text=text,
                    source_location={"line": line_number},
                    metadata={
                        "backend": "fallback",
                        "artifact_ref": artifact_ref,
                        "chunk_index": len(chunks),
                        "source_type": "text",
                    },
                )
            )

        if not chunks and content.strip():
            chunks.append(
                RuntimeChunk(
                    text=content.strip(),
                    source_location={"line": 1},
                    metadata={
                        "backend": "fallback",
                        "artifact_ref": artifact_ref,
                        "chunk_index": 0,
                        "source_type": "text",
                    },
                )
            )

        return chunks

    def _can_import(self, module: str) -> bool:
        try:
            import_module(module)
        except Exception:
            return False
        return True
