from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EvidenceUnitType = Literal["text", "table", "figure", "equation", "reference", "mixed"]
QualityAction = Literal["allow", "warn", "repair", "quarantine", "block"]
MaterializationAction = Literal[
    "persist_only",
    "index_vector",
    "project_graph",
    "runtime_lane",
    "full",
]


@dataclass(frozen=True, slots=True)
class PageBlockProvenance:
    page_number: int | None = None
    block_id: str | None = None
    block_type: str | None = None
    reading_order: int | None = None
    bbox: tuple[float, float, float, float] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "page_number": self.page_number,
                "block_id": self.block_id,
                "block_type": self.block_type,
                "reading_order": self.reading_order,
                "bbox": self.bbox,
            }.items()
            if value is not None
        }


@dataclass(frozen=True, slots=True)
class QualityActionPolicy:
    action: QualityAction = "allow"
    persist_chunk: bool = True
    index_vector: bool = True
    project_graph: bool = True
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "persist_chunk": self.persist_chunk,
            "index_vector": self.index_vector,
            "project_graph": self.project_graph,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class MaterializationPolicy:
    action: MaterializationAction = "full"
    source_of_truth: str = "postgres_canonical_evidence"
    allow_raganything_runtime_lane: bool = True
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "source_of_truth": self.source_of_truth,
            "allow_raganything_runtime_lane": self.allow_raganything_runtime_lane,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class EvidenceUnit:
    document_id: str
    chunk_id: str
    runtime_source_id: str
    unit_type: EvidenceUnitType
    canonical_reference: str
    provenance: PageBlockProvenance
    quality_action_policy: QualityActionPolicy = field(default_factory=QualityActionPolicy)
    materialization_policy: MaterializationPolicy = field(default_factory=MaterializationPolicy)

    def __post_init__(self) -> None:
        required = {
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "runtime_source_id": self.runtime_source_id,
            "canonical_reference": self.canonical_reference,
        }
        missing = [field_name for field_name, value in required.items() if not value]
        if missing:
            raise ValueError(f"EvidenceUnit missing required fields: {', '.join(missing)}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "runtime_source_id": self.runtime_source_id,
            "unit_type": self.unit_type,
            "canonical_reference": self.canonical_reference,
            "page_block_provenance": self.provenance.as_dict(),
            "quality_action_policy": self.quality_action_policy.as_dict(),
            "materialization_policy": self.materialization_policy.as_dict(),
        }
