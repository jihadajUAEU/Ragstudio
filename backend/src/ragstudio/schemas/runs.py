from typing import Any, Literal

from pydantic import Field

from ragstudio.schemas.common import StageStatus, StudioModel

PathwayDiagnosticStatus = Literal["success", "warning", "failed", "skipped", "unknown"]


class PathwayDiagnosticOut(StudioModel):
    stage: str
    label: str
    input: str = "not recorded"
    action: str = "not recorded"
    output: str = "not recorded"
    status: PathwayDiagnosticStatus = "unknown"
    time_ms: float | None = None
    budget_ms: int | None = None
    diagnosis: str = "not recorded"
    suggested_action: str = "None"


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
    pathway_diagnostics: list[PathwayDiagnosticOut] = Field(default_factory=list)


class RunPage(StudioModel):
    items: list[RunOut]
    total: int
