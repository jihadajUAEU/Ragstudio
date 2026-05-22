from __future__ import annotations

from ragstudio.services.retrieval_evidence import EvidenceCandidate


def select_diverse_candidates(
    candidates: list[EvidenceCandidate],
    *,
    limit: int,
    similarity_threshold: float = 0.65,
) -> tuple[list[EvidenceCandidate], dict[str, object]]:
    selected: list[EvidenceCandidate] = []
    suppressed: list[str] = []
    for candidate in candidates:
        if len(selected) >= max(limit, 1):
            break
        if not _must_keep(candidate) and any(
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
    warning_codes = candidate.metadata.get("parser_quality_warning_codes")
    if isinstance(warning_codes, list) and warning_codes:
        return True
    return any(reason.startswith("parser_quality_warning:") for reason in candidate.reasons)
