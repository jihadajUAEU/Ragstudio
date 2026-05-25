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
    breadcrumb: str | None = None
    layout_summary: str | None = None
    context_text: str | None = None
    included_reason: str = "retrieval_fusion"
    retrieval_passes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DroppedContextCandidate:
    candidate_id: str
    drop_reason: str
    estimated_tokens: int
    detail: str | None = None


@dataclass(frozen=True)
class AssembledContext:
    evidence: list[ContextEvidence]
    dropped: list[DroppedContextCandidate]
    total_estimated_tokens: int
    grounding_status: str


class ContextAssemblyService:
    def __init__(
        self,
        *,
        max_context_tokens: int = 2400,
        hard_context_tokens: int | None = None,
    ) -> None:
        self.max_context_tokens = max_context_tokens
        self.hard_context_tokens = hard_context_tokens

    def assemble(self, candidates: list[EvidenceCandidate]) -> AssembledContext:
        ordered = sorted(candidates, key=_direct_priority, reverse=True)
        evidence: list[ContextEvidence] = []
        dropped: list[DroppedContextCandidate] = []
        seen: dict[str, int] = {}
        used_tokens = 0
        included_direct_evidence = False

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
            policy_reason = _policy_drop_reason(candidate)
            if policy_reason:
                _append_drop(
                    dropped,
                    candidate=candidate,
                    reason=policy_reason,
                    estimated_tokens=estimated_tokens,
                )
                continue

            over_budget = used_tokens + estimated_tokens > self.max_context_tokens
            if over_budget and not _is_direct(candidate):
                _append_drop(
                    dropped,
                    candidate=candidate,
                    reason="token_budget",
                    estimated_tokens=estimated_tokens,
                )
                continue
            if over_budget and _is_direct(candidate):
                _append_drop(
                    dropped,
                    candidate=candidate,
                    reason="direct_evidence_preserved_over_budget",
                    estimated_tokens=estimated_tokens,
                    detail="required_direct_evidence_was_kept",
                )

            text = candidate.text
            if self.hard_context_tokens is not None and estimated_tokens > self.hard_context_tokens:
                text = _truncate_to_logical_boundary(candidate.text, self.hard_context_tokens)
                estimated_tokens = _estimate_tokens(text)
                _append_drop(
                    dropped,
                    candidate=candidate,
                    reason="context_truncated",
                    estimated_tokens=estimated_tokens,
                    detail="required_evidence_truncated_to_hard_context_limit",
                )

            evidence_context = candidate.metadata.get("evidence_context")
            if isinstance(evidence_context, dict):
                breadcrumb = evidence_context.get("breadcrumb")
                breadcrumb = breadcrumb if isinstance(breadcrumb, str) and breadcrumb else None
                layout_summary = evidence_context.get("layout_summary")
                layout_summary = (
                    layout_summary
                    if isinstance(layout_summary, str) and layout_summary
                    else None
                )
            else:
                from ragstudio.services.evidence_context import evidence_context_from_metadata
                resolved_context = evidence_context_from_metadata(
                    candidate.metadata,
                    source_location=candidate.source_location,
                    content_type=candidate.metadata.get("content_type"),
                )
                breadcrumb = resolved_context.get("breadcrumb")
                layout_summary = resolved_context.get("layout_summary")

            item = ContextEvidence(
                candidate_id=candidate.candidate_id,
                chunk_id=candidate.chunk_id,
                document_id=candidate.document_id,
                page=_page(candidate.source_location),
                reference=_first_reference(candidate),
                original_text=text,
                breadcrumb=breadcrumb,
                layout_summary=layout_summary,
                context_text=_context_text(
                    text,
                    breadcrumb=breadcrumb,
                    layout_summary=layout_summary,
                ),
                included_reason=_included_reason(candidate),
                retrieval_passes=passes,
            )
            seen[key] = len(evidence)
            evidence.append(item)
            included_direct_evidence = included_direct_evidence or _is_direct(candidate)
            used_tokens += estimated_tokens

        grounding_status = (
            "grounded"
            if included_direct_evidence
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


def _policy_drop_reason(candidate: EvidenceCandidate) -> str | None:
    policy = candidate.metadata.get("quality_action_policy")
    if isinstance(policy, dict) and policy.get("action") == "block":
        return "quality_policy_block"
    if "runtime_bridge_missing" in candidate.risk_flags:
        return "runtime_bridge_missing"
    if "graph_projection_stale" in candidate.risk_flags:
        return "graph_projection_stale"
    if _reranker_status(candidate) == "degraded":
        return "reranker_degraded"
    return None


def _reranker_status(candidate: EvidenceCandidate) -> str | None:
    status = getattr(candidate, "reranker_status", None)
    if isinstance(status, str):
        return status
    metadata_status = candidate.metadata.get("reranker_status")
    if isinstance(metadata_status, str):
        return metadata_status
    reranker = candidate.metadata.get("reranker")
    if isinstance(reranker, dict):
        nested_status = reranker.get("status")
        if isinstance(nested_status, str):
            return nested_status
    return None


def _append_drop(
    dropped: list[DroppedContextCandidate],
    *,
    candidate: EvidenceCandidate,
    reason: str,
    estimated_tokens: int,
    detail: str | None = None,
) -> None:
    dropped.append(
        DroppedContextCandidate(
            candidate_id=candidate.candidate_id,
            drop_reason=reason,
            estimated_tokens=estimated_tokens,
            detail=detail,
        )
    )


def _included_reason(candidate: EvidenceCandidate) -> str:
    passes = _retrieval_passes(candidate)
    if "context_window" in passes and any(
        reason in candidate.reasons
        for reason in {"heading_path_context", "section_path_context", "reference_range_context"}
    ):
        return "structural_context"
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


def _context_text(
    text: str,
    *,
    breadcrumb: str | None,
    layout_summary: str | None,
) -> str:
    labels = [value for value in (breadcrumb, layout_summary) if value]
    if not labels:
        return text
    return f"[{' | '.join(labels)}]\n{text}"


def _estimate_tokens(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 1
    word_count = len(stripped.split())
    arabic_chars = sum(1 for char in stripped if "\u0600" <= char <= "\u06FF")
    code_symbols = sum(1 for char in stripped if char in "{}[]()=;:,.<>/\\|")
    char_estimate = max(1, len(stripped) // 4)
    arabic_estimate = max(1, int(arabic_chars * 0.75)) if arabic_chars else 0
    code_estimate = max(1, code_symbols // 2) if code_symbols else 0
    return max(word_count, char_estimate, arabic_estimate, code_estimate, 1)


def _truncate_to_logical_boundary(text: str, hard_context_tokens: int) -> str:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    if paragraphs:
        first = paragraphs[0]
        if _estimate_tokens(first) <= hard_context_tokens:
            return first
    words = text.split()
    return " ".join(words[:hard_context_tokens])


def _should_offload_tokenization(text: str) -> bool:
    return len(text.split()) > 10_000


def _page(source_location: dict[str, Any]) -> int | None:
    page = source_location.get("page")
    return page if isinstance(page, int) else None
