from __future__ import annotations

from enum import StrEnum
from typing import Any


class IndexStage(StrEnum):
    QUEUED = "queued"
    MINERU_PARSING = "mineru_parsing"
    MINERU_VALIDATED = "mineru_validated"
    CHUNKS_PERSISTING = "chunks_persisting"
    CHUNKS_PERSISTED = "chunks_persisted"
    SEARCH_READY = "search_ready"
    RUNTIME_ENRICHING = "runtime_enriching"
    GRAPH_ENRICHING = "graph_enriching"
    READY = "ready"
    READY_WITH_WARNINGS = "ready_with_warnings"
    FAILED = "failed"


_STAGE_PROGRESS = {
    IndexStage.QUEUED: 1,
    IndexStage.MINERU_PARSING: 25,
    IndexStage.MINERU_VALIDATED: 45,
    IndexStage.CHUNKS_PERSISTING: 55,
    IndexStage.CHUNKS_PERSISTED: 65,
    IndexStage.SEARCH_READY: 75,
    IndexStage.RUNTIME_ENRICHING: 85,
    IndexStage.GRAPH_ENRICHING: 95,
    IndexStage.READY: 100,
    IndexStage.READY_WITH_WARNINGS: 100,
    IndexStage.FAILED: 100,
}

_STAGE_LABELS = {
    IndexStage.QUEUED: "Queued",
    IndexStage.MINERU_PARSING: "MinerU parsing",
    IndexStage.MINERU_VALIDATED: "MinerU validated",
    IndexStage.CHUNKS_PERSISTING: "Persisting chunks",
    IndexStage.CHUNKS_PERSISTED: "Chunks persisted",
    IndexStage.SEARCH_READY: "Search ready",
    IndexStage.RUNTIME_ENRICHING: "Runtime enrichment",
    IndexStage.GRAPH_ENRICHING: "Graph enrichment",
    IndexStage.READY: "Ready",
    IndexStage.READY_WITH_WARNINGS: "Ready with warnings",
    IndexStage.FAILED: "Failed",
}


def stage_progress(stage: IndexStage) -> int:
    return _STAGE_PROGRESS[stage]


def stage_payload(
    stage: IndexStage,
    *,
    detail: str,
    chunk_count: int | None = None,
    warning: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": stage.value,
        "label": _STAGE_LABELS[stage],
        "detail": detail,
        "progress": stage_progress(stage),
    }
    if chunk_count is not None:
        payload["chunk_count"] = chunk_count
    if warning:
        payload["warning"] = warning
    return payload


def update_job_stage(
    job: Any,
    stage: IndexStage,
    *,
    detail: str,
    chunk_count: int | None = None,
    warning: str | None = None,
) -> None:
    payload = stage_payload(
        stage,
        detail=detail,
        chunk_count=chunk_count,
        warning=warning,
    )
    job.progress = payload["progress"]
    result = dict(job.result or {})
    result["indexing_stage"] = payload
    if warning:
        warnings = list(result.get("warnings") or [])
        if warning not in warnings:
            warnings.append(warning)
        result["warnings"] = warnings
    job.result = result
    log_line = f"{payload['label']}: {detail}"
    job.logs = [*(job.logs or []), log_line][-20:]


def index_shape_compatible(
    stored_shape: dict[str, Any],
    required_shape: dict[str, Any],
) -> bool:
    if not isinstance(stored_shape, dict) or not isinstance(required_shape, dict):
        return False
    for key, required_value in required_shape.items():
        if key not in stored_shape:
            return False
        stored_value = stored_shape[key]
        if isinstance(required_value, dict):
            if not index_shape_compatible(stored_value, required_value):
                return False
        elif stored_value != required_value:
            return False
    return True
