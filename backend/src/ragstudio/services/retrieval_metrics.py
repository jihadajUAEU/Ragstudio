from __future__ import annotations

from dataclasses import dataclass
from math import log2

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
    min_precision_at_k: float = 0.75
    min_recall_at_k: float = 0.70
    min_mrr: float = 0.80
    min_hit_rate: float = 1.0


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
    relevant_flags = [
        bool(candidate_references(candidate) & relevant_references)
        for candidate in top_k
    ]
    relevant_found = sum(1 for flag in relevant_flags if flag)
    precision = relevant_found / k if k > 0 else 0.0
    recall = relevant_found / relevant_total if relevant_total else 0.0
    hit_rate = 1.0 if relevant_found else 0.0
    mrr = _mrr(relevant_flags)
    ndcg = _ndcg(relevant_flags, min(k, relevant_total if relevant_total else k))
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
    refs = metadata.get("reference_metadata", {}).get("references", [])
    source_ref = candidate.source_location.get("reference")
    values: set[str] = set()
    if isinstance(refs, list):
        values.update(str(ref) for ref in refs if ref)
    if isinstance(source_ref, str) and source_ref:
        values.add(source_ref)
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


def _ndcg(relevant_flags: list[bool], ideal_relevant_count: int) -> float:
    if ideal_relevant_count <= 0:
        return 0.0
    dcg = sum(
        (1.0 / log2(index + 1))
        for index, relevant in enumerate(relevant_flags, start=1)
        if relevant
    )
    ideal = sum(1.0 / log2(index + 1) for index in range(1, ideal_relevant_count + 1))
    return dcg / ideal if ideal else 0.0
