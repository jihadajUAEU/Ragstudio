from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class VectorReadinessError(RuntimeError):
    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


class VectorIndexPolicy:
    def assert_query_dimension(
        self,
        query_vector: Sequence[float],
        *,
        expected_dimension: int,
        profile_id: str | None = None,
    ) -> dict[str, Any]:
        observed = len(query_vector)
        if observed != expected_dimension:
            raise VectorReadinessError(
                "embedding_dimension_mismatch",
                f"expected {expected_dimension}, observed {observed}",
            )
        return {
            "status": "ready",
            "expected_dimension": expected_dimension,
            "observed_dimension": observed,
            "profile_id": profile_id,
        }

    def validate_pgvector_ready(self, state: dict[str, Any]) -> dict[str, Any]:
        if not state.get("extension_available"):
            raise VectorReadinessError(
                "pgvector_extension_unavailable",
                "Postgres vector extension is not installed.",
            )
        index_type = state.get("index_type")
        if not index_type:
            raise VectorReadinessError(
                "pgvector_index_unavailable",
                "No PGVector index exists for chunk embeddings.",
            )
        if index_type != "hnsw" and state.get("hnsw_supported", True):
            raise VectorReadinessError(
                "pgvector_hnsw_missing",
                "HNSW is supported but the production index is not HNSW.",
            )
        return {
            "status": "ready" if index_type == "hnsw" else "compatibility",
            "index_type": index_type,
            "extension_available": True,
            "hnsw_supported": bool(state.get("hnsw_supported", False)),
        }
