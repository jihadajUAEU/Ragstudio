from datetime import datetime
from typing import Any

from ragstudio.schemas.common import StageStatus, StudioModel


class JobOut(StudioModel):
    id: str
    type: str
    status: StageStatus
    target_id: str | None
    progress: int
    logs: list[str]
    result: dict[str, Any]
    worker_id: str | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    attempts: int
    max_attempts: int
    recovery_action: str | None


class JobPage(StudioModel):
    items: list[JobOut]
    total: int
    limit: int = 100
    offset: int = 0
    has_more: bool = False


class JobStageEventOut(StudioModel):
    sequence: int
    occurred_at: str
    stage: str
    label: str
    detail: str
    progress: int
    chunk_count: int | None = None
    warning: str | None = None


class ParserQualityWarningOut(StudioModel):
    chunk_id: str
    chunk_preview: str
    source_location: dict[str, Any]
    parser_metadata: dict[str, Any]
    reference_metadata: dict[str, Any] | None = None
    code: str | None = None
    message: str | None = None
    block_type: str | None = None
    page: int | str | None = None
    warning: dict[str, Any]


class JobQualityWarningsOut(StudioModel):
    job_id: str
    document_id: str | None
    parser_quality: dict[str, Any]
    index_quality_report: dict[str, Any] | None = None
    job_warnings: list[str]
    warning_counts: dict[str, int]
    affected_chunks: int
    total: int
    offset: int
    limit: int
    truncated: bool
    items: list[ParserQualityWarningOut]


class JobQualityWarningRepairOut(StudioModel):
    source_job_id: str
    document_id: str
    queued_job_id: str
    queued_job_status: StageStatus
    index_options: dict[str, Any]
    repair_plan: dict[str, Any]
    message: str
