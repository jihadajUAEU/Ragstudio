from typing import Any

from pydantic import AliasChoices, Field

from ragstudio.schemas.common import StudioModel


class ChunkOut(StudioModel):
    id: str
    document_id: str
    text: str
    source_location: dict[str, Any]
    metadata: dict[str, Any] = Field(
        validation_alias=AliasChoices("metadata_json", "metadata"),
        serialization_alias="metadata",
    )


class ChunkSearchIn(StudioModel):
    query: str
    document_ids: list[str] = []
    variant_id: str | None = None
    limit: int = 10


class ChunkSearchOut(StudioModel):
    items: list[ChunkOut]
    total: int
