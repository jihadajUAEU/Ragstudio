from __future__ import annotations

from typing import Any

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.domain_metadata_quality_gate import (
    DomainMetadataQualityGate,
    DomainMetadataQualityGateError,
)


class IndexQualityGateError(RuntimeError):
    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


class IndexQualityGate:
    raw_pdf_pattern = DomainMetadataQualityGate.raw_pdf_pattern

    def __init__(self, domain_gate: DomainMetadataQualityGate | None = None) -> None:
        self.domain_gate = domain_gate or DomainMetadataQualityGate()

    def validate_adapter_chunks(
        self,
        chunks: list[AdapterChunk],
        *,
        language: str = "unknown",
        domain_metadata: DomainMetadata | None = None,
    ) -> dict[str, Any]:
        try:
            return self.domain_gate.validate_adapter_chunks(
                chunks,
                language=language,
                domain_metadata=domain_metadata,
            )
        except DomainMetadataQualityGateError as exc:
            raise IndexQualityGateError(exc.reason, exc.detail) from exc
