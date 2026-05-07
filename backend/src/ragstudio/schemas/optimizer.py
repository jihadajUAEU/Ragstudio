from typing import Any

from pydantic import Field

from ragstudio.schemas.common import StudioModel


class OptimizerIn(StudioModel):
    experiment_id: str
    objective: dict[str, Any] = Field(default_factory=dict)


class OptimizerCandidateSummary(StudioModel):
    variant_id: str
    run_count: int
    average_score: float
    total_score: float
    best_run_id: str | None
    best_run_score: float | None


class OptimizerOut(StudioModel):
    id: str
    experiment_id: str
    objective: dict[str, Any]
    selected_variant_id: str | None
    selected_run_id: str | None
    explanation: str
    tried_variant_ids: list[str]
    candidate_summaries: list[OptimizerCandidateSummary] = []
