from typing import Any

from ragstudio.schemas.common import StudioModel


class ChunkOut(StudioModel):
    id: str
    document_id: str
    text: str
    source_location: dict[str, Any]
    metadata: dict[str, Any]


class ChunkSearchIn(StudioModel):
    query: str
    document_ids: list[str] = []
    variant_id: str | None = None
    limit: int = 10


class ChunkSearchOut(StudioModel):
    items: list[ChunkOut]
    total: int
