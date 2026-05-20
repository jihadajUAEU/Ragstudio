from datetime import datetime
from typing import Any

from pydantic import AliasChoices, Field, field_validator

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
    runtime_profile_id: str | None = None
    runtime_source_id: str | None = None
    content_type: str = "text"
    preview_ref: str | None = None
    indexed_at: datetime | None = None
    retrieval_explain: dict[str, Any] | None = None
    relationship_refs: dict[str, str] = Field(default_factory=dict)

    @field_validator("content_type", mode="before")
    @classmethod
    def _default_content_type(cls, value: Any) -> Any:
        return "text" if value is None or value == "" else value


class ChunkSearchIn(StudioModel):
    query: str
    document_ids: list[str] = []
    variant_id: str | None = None
    limit: int = 10
    offset: int = 0
    explain: bool = True
    include_neighbors: bool = True


class ChunkSearchOut(StudioModel):
    items: list[ChunkOut]
    total: int
    has_more: bool = False
