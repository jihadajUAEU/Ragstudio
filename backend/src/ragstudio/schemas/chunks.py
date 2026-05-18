from datetime import datetime
from typing import Any

from pydantic import AliasChoices, Field, field_validator, model_validator

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


class HybridSearchWeights(StudioModel):
    reference_exact: float | None = None
    neighbor_match: float | None = None
    same_chapter: float | None = None
    exact_phrase: float | None = None
    term_coverage: float | None = None
    semantic_density: float | None = None
    arabic_exact: float | None = None
    arabic_token: float | None = None
    metadata_boost: float | None = None
    domain_intent: float | None = None

    @model_validator(mode="after")
    def reject_negative_weights(self) -> "HybridSearchWeights":
        for key, value in self.model_dump(exclude_none=True).items():
            if value < 0:
                raise ValueError(f"{key} must be greater than or equal to 0")
        return self


class ChunkSearchIn(StudioModel):
    query: str
    document_ids: list[str] = []
    variant_id: str | None = None
    limit: int = 10
    explain: bool = True
    include_neighbors: bool = True
    search_weights: HybridSearchWeights | None = None


class ChunkSearchOut(StudioModel):
    items: list[ChunkOut]
    total: int
