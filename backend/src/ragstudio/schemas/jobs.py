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
