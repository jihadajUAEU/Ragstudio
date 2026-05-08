from typing import Any

from ragstudio.schemas.common import StudioModel
from ragstudio.schemas.runs import RunOut


class ExperimentScoreOut(StudioModel):
    id: str
    run_id: str
    total: int
    details: dict[str, Any]


class ExperimentIn(StudioModel):
    name: str
    document_ids: list[str]
    evaluation_set_id: str
    variant_ids: list[str]
    objective: dict[str, Any]


class ExperimentOut(ExperimentIn):
    id: str
    runs: list[RunOut] = []
    scores: list[ExperimentScoreOut] = []
