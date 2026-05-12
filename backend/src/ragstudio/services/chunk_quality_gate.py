from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.domain_metadata_quality_gate import DomainMetadataQualityGate
from ragstudio.services.parser_normalization import ExpectedContentProfile


@dataclass(frozen=True)
class ChunkQualityGate:
    expected_profile: ExpectedContentProfile
    domain_metadata: DomainMetadata | None = None

    def warnings_for(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return DomainMetadataQualityGate().warnings_for_text(
            text,
            domain_metadata=self.domain_metadata,
            expected_profile=self.expected_profile,
            metadata=metadata,
        )
