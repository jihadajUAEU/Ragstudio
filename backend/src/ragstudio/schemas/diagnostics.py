from typing import Any

from ragstudio.schemas.common import StudioModel


class DiagnosticsOut(StudioModel):
    capabilities: dict[str, bool]
    dependency_status: dict[str, Any]
    warnings: list[str]
