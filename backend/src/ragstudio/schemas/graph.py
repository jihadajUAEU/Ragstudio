from typing import Any

from ragstudio.schemas.common import StudioModel


class GraphOut(StudioModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    detail: str | None = None
    total: int | None = None
    limit: int | None = None
    offset: int | None = None
    has_more: bool | None = None
