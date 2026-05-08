from typing import Any

from pydantic import Field

from ragstudio.schemas.common import StageStatus, StudioModel


class RunOut(StudioModel):
    id: str
    variant_id: str
    experiment_id: str | None
    query: str
    status: StageStatus
    answer: str
    sources: list[dict[str, Any]]
    chunk_traces: list[dict[str, Any]]
    timings: dict[str, Any]
    error: str | None
    runtime_profile_id: str | None = None
    document_ids: list[str] = Field(default_factory=list)
    query_config: dict[str, Any] = Field(default_factory=dict)
    reranker_traces: list[dict[str, Any]] = Field(default_factory=list)
    token_metadata: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None


class RunPage(StudioModel):
    items: list[RunOut]
    total: int
