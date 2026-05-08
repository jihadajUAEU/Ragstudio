from pydantic import Field

from ragstudio.schemas.common import StudioModel
from ragstudio.schemas.runs import RunOut


class QueryIn(StudioModel):
    query: str
    document_ids: list[str] = Field(default_factory=list)
    variant_ids: list[str]
    limit: int = Field(default=8, ge=0)


class QueryOut(StudioModel):
    runs: list[RunOut]
