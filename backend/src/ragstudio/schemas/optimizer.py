from typing import Any

from pydantic import Field

from ragstudio.schemas.common import StudioModel


class OptimizerIn(StudioModel):
    experiment_id: str
    objective: dict[str, Any] = Field(default_factory=dict)


class OptimizerOut(StudioModel):
    id: str
    experiment_id: str
    objective: dict[str, Any]
    selected_variant_id: str | None
    selected_run_id: str | None
    explanation: str
    tried_variant_ids: list[str]
