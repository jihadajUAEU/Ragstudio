from __future__ import annotations

from dataclasses import dataclass
from math import log2

from ragstudio.services.operational_policy import DEFAULT_OPERATIONAL_POLICY
from ragstudio.services.retrieval_evidence import EvidenceCandidate


@dataclass(frozen=True)
class RetrievalMetrics:
    precision_at_k: float
    recall_at_k: float
    hit_rate: float
    mrr: float
    ndcg_at_k: float
    k: int
    relevant_found: int
    relevant_total: int


@dataclass(frozen=True)
class RetrievalQualityGate:
    min_precision_at_k: float = (
        DEFAULT_OPERATIONAL_POLICY.retrieval_metrics.min_precision_at_k
    )
    min_recall_at_k: float = DEFAULT_OPERATIONAL_POLICY.retrieval_metrics.min_recall_at_k
    min_mrr: float = DEFAULT_OPERATIONAL_POLICY.retrieval_metrics.min_mrr
    min_hit_rate: float = DEFAULT_OPERATIONAL_POLICY.retrieval_metrics.min_hit_rate


@dataclass(frozen=True)
class RetrievalQualityGateReport:
    passed: bool
    failures: dict[str, dict[str, float]]


def calculate_retrieval_metrics(
    candidates: list[EvidenceCandidate],
    *,
    relevant_references: set[str],
    k: int,
) -> RetrievalMetrics:
    top_k = candidates[: max(k, 0)]
    relevant_total = len(relevant_references)
    candidate_matches = [
        candidate_references(candidate) & relevant_references for candidate in top_k
    ]
    relevant_flags = [bool(matches) for matches in candidate_matches]
    relevant_candidate_count = sum(1 for flag in relevant_flags if flag)
    found_references = set().union(*candidate_matches) if candidate_matches else set()
    relevant_found = len(found_references)
    precision = relevant_candidate_count / k if k > 0 else 0.0
    recall = relevant_found / relevant_total if relevant_total else 0.0
    hit_rate = 1.0 if relevant_candidate_count else 0.0
    mrr = _mrr(relevant_flags)
    ndcg = _ndcg(
        candidate_matches,
        relevant_references,
        min(k, relevant_total if relevant_total else k),
    )
    return RetrievalMetrics(
        precision_at_k=round(precision, 6),
        recall_at_k=round(recall, 6),
        hit_rate=round(hit_rate, 6),
        mrr=round(mrr, 6),
        ndcg_at_k=round(ndcg, 6),
        k=k,
        relevant_found=relevant_found,
        relevant_total=relevant_total,
    )


def assert_quality_gate(
    metrics: RetrievalMetrics,
    gate: RetrievalQualityGate,
) -> RetrievalQualityGateReport:
    failures: dict[str, dict[str, float]] = {}
    _record_failure(
        failures,
        "precision_at_k",
        actual=metrics.precision_at_k,
        minimum=gate.min_precision_at_k,
    )
    _record_failure(
        failures,
        "recall_at_k",
        actual=metrics.recall_at_k,
        minimum=gate.min_recall_at_k,
    )
    _record_failure(failures, "mrr", actual=metrics.mrr, minimum=gate.min_mrr)
    _record_failure(
        failures,
        "hit_rate",
        actual=metrics.hit_rate,
        minimum=gate.min_hit_rate,
    )
    return RetrievalQualityGateReport(passed=not failures, failures=failures)


def candidate_references(candidate: EvidenceCandidate) -> set[str]:
    metadata = candidate.metadata
    reference_metadata = metadata.get("reference_metadata", {})
    refs = (
        reference_metadata.get("references", [])
        if isinstance(reference_metadata, dict)
        else []
    )
    source_ref = candidate.source_location.get("reference")
    values: set[str] = set()
    if isinstance(refs, list):
        values.update(str(ref) for ref in refs if ref)
    if isinstance(source_ref, str) and source_ref:
        values.add(source_ref)
    if candidate.canonical_reference:
        values.add(candidate.canonical_reference)
    return values


def _record_failure(
    failures: dict[str, dict[str, float]],
    key: str,
    *,
    actual: float,
    minimum: float,
) -> None:
    if actual < minimum:
        failures[key] = {"actual": actual, "minimum": minimum}


def _mrr(relevant_flags: list[bool]) -> float:
    for index, relevant in enumerate(relevant_flags, start=1):
        if relevant:
            return 1 / index
    return 0.0


def _ndcg(
    candidate_matches: list[set[str]],
    relevant_references: set[str],
    ideal_relevant_count: int,
) -> float:
    if ideal_relevant_count <= 0:
        return 0.0
    seen_references: set[str] = set()
    dcg = 0.0
    for index, matches in enumerate(candidate_matches, start=1):
        new_matches = matches - seen_references
        if new_matches:
            dcg += 1.0 / log2(index + 1)
            seen_references.update(new_matches)
        if seen_references >= relevant_references:
            break
    ideal = sum(1.0 / log2(index + 1) for index in range(1, ideal_relevant_count + 1))
    return dcg / ideal if ideal else 0.0
