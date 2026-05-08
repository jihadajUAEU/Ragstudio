from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict


def new_id() -> str:
    return str(uuid4())


def now_utc() -> datetime:
    return datetime.now(UTC)


class Page(BaseModel):
    items: list[Any]
    total: int


class StageStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class StudioModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
