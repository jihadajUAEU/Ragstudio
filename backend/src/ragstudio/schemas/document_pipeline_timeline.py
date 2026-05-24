from typing import Any, Literal

from pydantic import Field

from ragstudio.schemas.common import StageStatus, StudioModel

PipelineStageState = Literal[
    "pending",
    "running",
    "complete",
    "warning",
    "blocked",
    "failed",
    "skipped",
    "metadata_only",
]

PipelineEventSource = Literal[
    "document",
    "structured_event",
    "inferred_log",
    "job",
    "chunk",
    "index_record",
    "graph_projection",
    "contract",
    "warning",
]


class DocumentPipelineStageOut(StudioModel):
    id: str
    label: str
    state: PipelineStageState
    detail: str
    order: int
    progress: int | None = None
    is_current: bool = False
    event_count: int = 0
    warning_count: int = 0
    chunk_count: int | None = None
    source: PipelineEventSource
    started_at: str | None = None
    completed_at: str | None = None
    detail_payload: dict[str, Any] = Field(default_factory=dict)


class DocumentPipelineEventOut(StudioModel):
    sequence: int
    stage_id: str
    label: str
    detail: str
    state: PipelineStageState
    progress: int | None = None
    occurred_at: str | None = None
    source: PipelineEventSource
    job_id: str | None = None
    chunk_count: int | None = None
    warning: str | None = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    detail_payload: dict[str, Any] = Field(default_factory=dict)


class DocumentPipelineWarningGroupOut(StudioModel):
    code: str
    expected_script: str | None = None
    count: int
    message: str | None = None
    sample_chunk_ids: list[str] = Field(default_factory=list)
    sample_references: list[str] = Field(default_factory=list)
    sample_pages: list[int | str] = Field(default_factory=list)


class DocumentPipelineContractOut(StudioModel):
    contract_status: str | None = None
    verified: bool | None = None
    canonical_units: bool | None = None
    schema_type: str | None = None
    repair_status: str | None = None
    validation_status: str | None = None
    validation_matched_units: int | None = None
    selected_strategy: str | None = None
    rejection_reasons: list[str] = Field(default_factory=list)
    detail_payload: dict[str, Any] = Field(default_factory=dict)


class DocumentPipelineTotalsOut(StudioModel):
    jobs: int = 0
    chunks: int = 0
    warnings: int = 0
    graph_nodes: int = 0
    graph_edges: int = 0
    index_records: int = 0
    graph_records: int = 0


class DocumentPipelineTimelineOut(StudioModel):
    document_id: str
    filename: str
    status: StageStatus
    latest_job_id: str | None = None
    contract_version: int = 1
    stages: list[DocumentPipelineStageOut] = Field(default_factory=list)
    events: list[DocumentPipelineEventOut] = Field(default_factory=list)
    contract: DocumentPipelineContractOut
    warning_groups: list[DocumentPipelineWarningGroupOut] = Field(default_factory=list)
    totals: DocumentPipelineTotalsOut
    missing_sections: list[str] = Field(default_factory=list)
