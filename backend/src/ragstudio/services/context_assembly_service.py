from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from ragstudio.services.retrieval_evidence import EvidenceCandidate


@dataclass(frozen=True)
class ContextEvidence:
    candidate_id: str
    chunk_id: str | None
    document_id: str | None
    page: int | None
    reference: str | None
    original_text: str
    normalized_text: None = None
    included_reason: str = "retrieval_fusion"
    retrieval_passes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DroppedContextCandidate:
    candidate_id: str
    drop_reason: str
    estimated_tokens: int


@dataclass(frozen=True)
class AssembledContext:
    evidence: list[ContextEvidence]
    dropped: list[DroppedContextCandidate]
    total_estimated_tokens: int
    grounding_status: str


class ContextAssemblyService:
    def __init__(self, *, max_context_tokens: int = 2400) -> None:
        self.max_context_tokens = max_context_tokens

    def assemble(self, candidates: list[EvidenceCandidate]) -> AssembledContext:
        ordered = sorted(candidates, key=_direct_priority, reverse=True)
        evidence: list[ContextEvidence] = []
        dropped: list[DroppedContextCandidate] = []
        seen: dict[str, int] = {}
        used_tokens = 0

        for candidate in ordered:
            key = _candidate_key(candidate)
            passes = _retrieval_passes(candidate)
            existing_index = seen.get(key)
            if existing_index is not None:
                existing = evidence[existing_index]
                evidence[existing_index] = replace(
                    existing,
                    retrieval_passes=_merge_passes(existing.retrieval_passes, passes),
                )
                continue

            estimated_tokens = _estimate_tokens(candidate.text)
            over_budget = used_tokens + estimated_tokens > self.max_context_tokens
            if over_budget and not _is_direct(candidate):
                dropped.append(
                    DroppedContextCandidate(
                        candidate_id=candidate.candidate_id,
                        drop_reason="token_budget",
                        estimated_tokens=estimated_tokens,
                    )
                )
                continue

            item = ContextEvidence(
                candidate_id=candidate.candidate_id,
                chunk_id=candidate.chunk_id,
                document_id=candidate.document_id,
                page=_page(candidate.source_location),
                reference=_first_reference(candidate),
                original_text=candidate.text,
                included_reason=_included_reason(candidate),
                retrieval_passes=passes,
            )
            seen[key] = len(evidence)
            evidence.append(item)
            used_tokens += estimated_tokens

        grounding_status = (
            "grounded"
            if any(_is_direct(candidate) for candidate in ordered)
            else "insufficient_evidence"
        )
        return AssembledContext(evidence, dropped, used_tokens, grounding_status)


def _candidate_key(candidate: EvidenceCandidate) -> str:
    return candidate.chunk_id or candidate.text.strip().casefold()


def _features(candidate: EvidenceCandidate) -> dict[str, Any]:
    if candidate.match_features:
        return candidate.match_features
    value = candidate.metadata.get("match_features")
    return value if isinstance(value, dict) else {}


def _direct_priority(candidate: EvidenceCandidate) -> int:
    features = _features(candidate)
    if features.get("reference_exact"):
        return 100
    if features.get("arabic_exact"):
        return 90
    return 10


def _is_direct(candidate: EvidenceCandidate) -> bool:
    features = _features(candidate)
    return bool(features.get("reference_exact") or features.get("arabic_exact"))


def _included_reason(candidate: EvidenceCandidate) -> str:
    features = _features(candidate)
    if features.get("reference_exact"):
        return "exact_reference_match"
    if features.get("arabic_exact"):
        return "direct_arabic_match"
    return "semantic_context"


def _first_reference(candidate: EvidenceCandidate) -> str | None:
    refs = candidate.metadata.get("reference_metadata", {}).get("references", [])
    return refs[0] if isinstance(refs, list) and refs else None


def _retrieval_passes(candidate: EvidenceCandidate) -> list[str]:
    passes = candidate.metadata.get("retrieval_passes")
    if isinstance(passes, list) and passes:
        return [str(item) for item in passes]
    if candidate.retrieval_pass:
        return [candidate.retrieval_pass]
    return [candidate.tool]


def _merge_passes(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    for item in right:
        if item not in merged:
            merged.append(item)
    return merged


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.split()))


def _page(source_location: dict[str, Any]) -> int | None:
    page = source_location.get("page")
    return page if isinstance(page, int) else None
