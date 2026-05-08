from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class RuntimeChunk:
    text: str
    source_location: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    runtime_source_id: str | None = None
    content_type: str = "text"
    preview_ref: str | None = None


@dataclass(frozen=True)
class RuntimeQueryResult:
    answer: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    chunk_traces: list[dict[str, Any]] = field(default_factory=list)
    reranker_traces: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, Any] = field(default_factory=dict)
    token_metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_type: str | None = None


class RuntimeAdapter(Protocol):
    def capability_report(self) -> dict[str, Any]:
        raise NotImplementedError

    async def index_document(self, artifact_path: str | Path) -> list[RuntimeChunk]:
        raise NotImplementedError

    async def query(
        self,
        query: str,
        *,
        document_ids: list[str],
        query_config: dict[str, Any],
    ) -> RuntimeQueryResult:
        raise NotImplementedError

    async def delete_document_index(self, document_id: str) -> None:
        raise NotImplementedError
