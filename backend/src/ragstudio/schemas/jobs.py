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
