from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.evidence_graph import EvidenceGraph
from ragstudio.services.reference_metadata import ReferenceSemantics


@dataclass(frozen=True)
class AssemblyDecision:
    code: str
    reason: str
    source_block_refs: tuple[str, ...] = ()
    confidence: str = "high"


@dataclass(frozen=True)
class CanonicalUnit:
    text: str
    source_location: dict[str, object]
    metadata: dict[str, object]
    runtime_source_id: str | None
    content_type: str
    preview_ref: str | None
    decisions: tuple[AssemblyDecision, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ResolverContext:
    domain_metadata: DomainMetadata
    parent_metadata: dict[str, object]
    parent_source_location: dict[str, object]
    runtime_source_id: str | None
    content_type: str
    preview_ref: str | None
    reference_semantics: ReferenceSemantics | None = None
    max_page_gap: int | None = None
    preserve_original_blocks: bool = False
    block_preview_chars: int = 160
    store_text_hash: bool = False


class DomainResolver(Protocol):
    def can_resolve(self, context: ResolverContext) -> bool:
        ...

    def resolve_units(
        self,
        graph: EvidenceGraph,
        *,
        context: ResolverContext,
    ) -> list[CanonicalUnit]:
        ...


def resolver_key(context: ResolverContext) -> str:
    domain = (context.domain_metadata.domain or "generic").strip().casefold()
    document_type = (
        context.domain_metadata.document_type or "unknown"
    ).strip().casefold()
    return f"{domain}:{document_type}"
