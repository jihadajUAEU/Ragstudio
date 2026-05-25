from typing import Any, Literal

from pydantic import Field, field_validator

from ragstudio.schemas.common import StudioModel
from ragstudio.services.runtime_policy import DEFAULT_PARSER_MODE

ParserMode = Literal["mineru_strict"]


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


class MinerUParseOptionsIn(StudioModel):
    parser: str | None = None
    parse_method: str | None = None
    backend: str | None = None
    device: str | None = None
    lang: str | None = None
    formula: bool | None = None
    table: bool | None = None
    source: str | None = None
    max_concurrent_files: int | None = Field(default=None, ge=1, le=8)

    @field_validator("parser", "parse_method", "backend", "device", "lang", "source")
    @classmethod
    def normalize_text_option(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized:
            return normalized
        return None

    @field_validator("max_concurrent_files", mode="before")
    @classmethod
    def reject_bool_capacity(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("max_concurrent_files must be an integer")
        return value


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


class AnalysisBinding(StudioModel):
    filename: str
    size_bytes: int = Field(ge=0)
    sha256: str


class ContractStateSummary(StudioModel):
    state: Literal["verified", "metadata_only", "generic"]
    canonical_units: bool = False
    reason: str = ""
    matched_units: int | None = None
    selected_strategy: str | None = None
    identity_fields: list[str] = Field(default_factory=list)


class DomainMetadataSuggestOut(StudioModel):
    domain_metadata: DomainMetadata
    raw_domain_metadata: DomainMetadata | None = None
    reference_contract_validation: dict[str, Any] | None = None
    analysis_binding: AnalysisBinding | None = None
    contract_state: ContractStateSummary | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_pages: list[int] = Field(default_factory=list)
    rationale: str = ""
    warnings: list[str] = Field(default_factory=list)


class IndexDocumentIn(StudioModel):
    parser_mode: ParserMode = DEFAULT_PARSER_MODE
    domain_metadata: DomainMetadata = Field(default_factory=DomainMetadata)
    mineru_parse_options: MinerUParseOptionsIn | None = None
    analysis_binding: AnalysisBinding | None = None
