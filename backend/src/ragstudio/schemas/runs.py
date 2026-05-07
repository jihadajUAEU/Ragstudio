from typing import Any

from ragstudio.schemas.common import StageStatus, StudioModel


class RunOut(StudioModel):
    id: str
    variant_id: str
    query: str
    status: StageStatus
    answer: str
    sources: list[dict[str, Any]]
    chunk_traces: list[dict[str, Any]]
    timings: dict[str, Any]
    error: str | None
