from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
from typing import Any, overload

from ragstudio.services.runtime_types import RuntimeChunk, RuntimeQueryResult

AdapterChunk = RuntimeChunk


class RAGAnythingAdapter:
    """Safe adapter boundary for optional raganything integration."""

    def __init__(self) -> None:
        self._package_available = find_spec("raganything") is not None

    def capability_report(self) -> dict[str, Any]:
        return {
            "raganything_available": self._package_available,
            "active_backend": "fallback",
            "indexing": "line_split_fallback",
            "query": "simple_fallback",
            "graph": "placeholder",
        }

    async def delete_document_index(self, document_id: str) -> None:
        return None

    async def index_document(self, artifact_path: str | Path) -> list[RuntimeChunk]:
        return self._line_split_index(Path(artifact_path))

    @overload
    async def query(
        self,
        query: str,
        chunks: list[AdapterChunk],
        limit: int = 10,
    ) -> dict[str, Any]: ...

    @overload
    async def query(
        self,
        query: str,
        chunks: None = None,
        limit: int = 10,
        *,
        document_ids: list[str],
        query_config: dict[str, Any],
    ) -> RuntimeQueryResult: ...

    async def query(
        self,
        query: str,
        chunks: list[AdapterChunk] | None = None,
        limit: int = 10,
        *,
        document_ids: list[str] | None = None,
        query_config: dict[str, Any] | None = None,
    ) -> dict[str, Any] | RuntimeQueryResult:
        if chunks is None:
            return RuntimeQueryResult(
                answer="",
                timings={},
                error="Fallback runtime query requires mirrored chunks.",
                error_type="fallback_runtime_without_chunks",
            )
        selected = chunks[:limit]
        return {
            "answer": self._simple_answer(query, selected),
            "chunk_traces": [
                {
                    "rank": index + 1,
                    "source_location": chunk.source_location,
                    "metadata": chunk.metadata,
                    "inclusion_status": "prompt-included",
                }
                for index, chunk in enumerate(selected)
            ],
        }

    async def graph(self) -> dict[str, Any]:
        return {"nodes": [], "edges": [], "placeholder": True}

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

    def _simple_answer(self, query: str, chunks: list[AdapterChunk]) -> str:
        if not chunks:
            return ""
        excerpts = " ".join(chunk.text for chunk in chunks)
        return f"{query.strip()}: {excerpts}" if query.strip() else excerpts
