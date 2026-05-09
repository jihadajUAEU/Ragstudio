from typing import Any, Literal

from pydantic import Field

from ragstudio.schemas.common import StudioModel

ParserMode = Literal["local_fallback", "mineru_strict", "mineru_with_fallback"]


class DomainMetadata(StudioModel):
    domain: str = "generic"
    document_type: str = "document"
    language: str = "unknown"
    tags: list[str] = Field(default_factory=list)
    authority: str | None = None
    source: str | None = None
    collection: str | None = None
    citation_style: str | None = None
    expected_structure: str | None = None
    custom_json: dict[str, Any] = Field(default_factory=dict)
    reference_pattern: str | None = None
    script: str | None = None
    content_role: str | None = None
    metadata_sources: list[str] = Field(default_factory=list)


class DomainProfileOut(StudioModel):
    id: str
    name: str
    description: str
    metadata: DomainMetadata


class DomainProfileListOut(StudioModel):
    items: list[DomainProfileOut]
    total: int


class DomainProfileIn(StudioModel):
    id: str
    name: str
    description: str = ""
    metadata: DomainMetadata


class DomainMetadataSuggestIn(StudioModel):
    filename: str
    content_type: str = "application/octet-stream"
    profile_id: str | None = None
    sample_text: str = ""


class DomainMetadataSuggestOut(StudioModel):
    domain_metadata: DomainMetadata
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_pages: list[int] = Field(default_factory=list)
    rationale: str = ""
    warnings: list[str] = Field(default_factory=list)


class IndexDocumentIn(StudioModel):
    parser_mode: ParserMode = "local_fallback"
    domain_metadata: DomainMetadata = Field(default_factory=DomainMetadata)
