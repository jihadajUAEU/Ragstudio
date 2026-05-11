from typing import Any

from pydantic import Field

from ragstudio.schemas.common import StudioModel
from ragstudio.schemas.runtime import RuntimeHealthCheck, RuntimeOverallStatus


class DiagnosticsOut(StudioModel):
    capabilities: dict[str, bool]
    dependency_status: dict[str, Any]
    warnings: list[str]
    runtime_mode: str = "runtime"
    overall_status: RuntimeOverallStatus = "failed"
    checks: list[RuntimeHealthCheck] = Field(default_factory=list)
