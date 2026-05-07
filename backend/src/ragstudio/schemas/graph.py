from typing import Any

from ragstudio.schemas.common import StudioModel


class GraphOut(StudioModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
