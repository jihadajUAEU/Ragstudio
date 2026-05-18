from typing import Literal

from pydantic import Field

from ragstudio.schemas.chunks import ChunkOut, HybridSearchWeights
from ragstudio.schemas.common import StudioModel
from ragstudio.schemas.runs import RunOut

QueryResponseMode = Literal["fast", "full"]


class QueryIn(StudioModel):
    query: str
    document_ids: list[str] = Field(default_factory=list)
    variant_ids: list[str]
    limit: int = Field(default=8, ge=0)
    response_mode: QueryResponseMode = "fast"
    answer_budget_ms: int | None = Field(default=None, ge=500, le=120_000)
    response_budget_ms: int | None = Field(default=None, ge=1000, le=120_000)
    search_weights: HybridSearchWeights | None = None


class QueryOut(StudioModel):
    runs: list[RunOut]


class SimulateRetrievalIn(StudioModel):
    query: str
    document_ids: list[str] = Field(default_factory=list)
    variant_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=8, ge=0, le=50)
    search_weights: HybridSearchWeights | None = None


class SimulateRetrievalOut(StudioModel):
    items: list[ChunkOut]
    total: int
