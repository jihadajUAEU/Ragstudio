from __future__ import annotations

from ragstudio.services.operational_policy import DEFAULT_OPERATIONAL_POLICY
from ragstudio.services.retrieval_evidence import EvidenceCandidate


def select_diverse_candidates(
    candidates: list[EvidenceCandidate],
    *,
    limit: int,
    similarity_threshold: float = (
        DEFAULT_OPERATIONAL_POLICY.candidate_diversity.similarity_threshold
    ),
) -> tuple[list[EvidenceCandidate], dict[str, object]]:
    selected: list[EvidenceCandidate] = []
    suppressed: list[str] = []
    for candidate in candidates:
        must_keep = _must_keep(candidate)
        if len(selected) >= max(limit, 1) and not must_keep:
            continue
        if not must_keep and any(
            _jaccard(candidate.text, existing.text) >= similarity_threshold
            for existing in selected
        ):
            suppressed.append(candidate.candidate_id)
            continue
        selected.append(candidate)

    return selected, {
        "stage": "candidate_diversity",
        "status": "ran",
        "input_count": len(candidates),
        "selected_count": len(selected),
        "suppressed_candidate_ids": suppressed,
        "similarity_threshold": similarity_threshold,
    }


def _jaccard(left: str, right: str) -> float:
    left_terms = _terms(left)
    right_terms = _terms(right)
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def _terms(value: str) -> set[str]:
    return {term.casefold() for term in value.split() if len(term) > 2}


def _must_keep(candidate: EvidenceCandidate) -> bool:
    features = candidate.match_features
    metadata_features = candidate.metadata.get("match_features")
    if not features and isinstance(metadata_features, dict):
        features = metadata_features
    if features.get("reference_exact") or features.get("arabic_exact"):
        return True

    warning_codes = candidate.metadata.get("parser_quality_warning_codes")
    if isinstance(warning_codes, list) and warning_codes:
        return True
    return any(reason.startswith("parser_quality_warning:") for reason in candidate.reasons)
