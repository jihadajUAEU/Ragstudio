from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ragstudio.schemas.common import StudioModel


class DocumentEvidenceSummary(StudioModel):
    id: str
    filename: str
    content_type: str
    status: str
    page_count: int | None = None
    parser_mode: str | None = None


class SourceArtifactEvidence(StudioModel):
    id: str
    kind: str
    path: str | None = None
    checksum: str | None = None
    preview_available: bool = False
    preview_capped: bool = False
    hidden_count: int = 0


class ParserBlockEvidence(StudioModel):
    id: str
    page: int | None = None
    block_index: int | None = None
    block_type: str
    text_preview: str
    bbox: list[float] | None = None
    modality: str | None = None
    warning_ids: list[str] = Field(default_factory=list)


class NormalizationDecisionEvidence(StudioModel):
    id: str
    decision_type: Literal[
        "page_stitch",
        "modal_route",
        "quality_gate",
        "quality_warning",
        "chunk_materialization",
        "unresolved",
    ]
    title: str
    summary: str
    input_block_ids: list[str] = Field(default_factory=list)
    output_chunk_ids: list[str] = Field(default_factory=list)
    warning_ids: list[str] = Field(default_factory=list)
    status: str = "recorded"


class ChunkEvidence(StudioModel):
    id: str
    text_preview: str
    page_start: int | None = None
    page_end: int | None = None
    source_location: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    modality: str | None = None
    quality_status: str | None = None
    warning_ids: list[str] = Field(default_factory=list)


class WarningEvidence(StudioModel):
    id: str
    code: str
    message: str
    severity: str = "warning"
    page: int | None = None
    block_id: str | None = None
    block_type: str | None = None
    quality_gate_action: str | None = None
    suppressed_from_counts: bool = False
    decision_id: str | None = None
    affected_chunk_ids: list[str] = Field(default_factory=list)


class ProofEvidence(StudioModel):
    source_commit: str | None = None
    proof_packet_id: str | None = None
    mode: Literal["local", "static-fixture", "export"] = "local"
    replay_command: str | None = None
    limitations: list[str] = Field(default_factory=list)
    redaction_summary: list[str] = Field(default_factory=list)


class DocumentParseEvidence(StudioModel):
    document: DocumentEvidenceSummary
    source_artifacts: list[SourceArtifactEvidence] = Field(default_factory=list)
    parser_blocks: list[ParserBlockEvidence] = Field(default_factory=list)
    normalization_decisions: list[NormalizationDecisionEvidence] = Field(default_factory=list)
    chunks: list[ChunkEvidence] = Field(default_factory=list)
    warnings: list[WarningEvidence] = Field(default_factory=list)
    proof: ProofEvidence
    missing_sections: list[str] = Field(default_factory=list)
