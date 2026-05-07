from ragstudio.schemas.common import StudioModel
from ragstudio.schemas.runs import RunOut


class QueryIn(StudioModel):
    query: str
    document_ids: list[str] = []
    variant_ids: list[str]


class QueryOut(StudioModel):
    runs: list[RunOut]
