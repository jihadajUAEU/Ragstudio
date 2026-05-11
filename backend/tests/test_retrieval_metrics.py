import pytest

from ragstudio.services.retrieval_evidence import EvidenceCandidate
from ragstudio.services.retrieval_metrics import (
    RetrievalQualityGate,
    assert_quality_gate,
    calculate_retrieval_metrics,
)


def candidate(chunk_id: str, refs: list[str], rank: int) -> EvidenceCandidate:
    return EvidenceCandidate(
        candidate_id=f"test:{chunk_id}",
        text=f"{chunk_id} text",
        document_id="doc-quran",
        chunk_id=chunk_id,
        source_location={"page": rank},
        metadata={"reference_metadata": {"references": refs}},
        tool="test",
        tool_rank=rank,
        base_score=1.0,
        final_score=1.0,
    )


def test_retrieval_metrics_calculate_precision_recall_mrr_ndcg_and_hit_rate():
    results = [
        candidate("chunk-1", ["19:12"], 1),
        candidate("chunk-2", ["19:13"], 2),
        candidate("chunk-3", ["19:14"], 3),
    ]

    metrics = calculate_retrieval_metrics(
        results,
        relevant_references={"19:13", "19:14"},
        k=3,
    )

    assert metrics.precision_at_k == pytest.approx(2 / 3)
    assert metrics.recall_at_k == pytest.approx(1.0)
    assert metrics.hit_rate == pytest.approx(1.0)
    assert metrics.mrr == pytest.approx(0.5)
    assert metrics.ndcg_at_k == pytest.approx(0.693426, rel=1e-4)


def test_quality_gate_reports_all_failed_thresholds():
    results = [candidate("chunk-1", ["19:12"], 1)]
    metrics = calculate_retrieval_metrics(
        results,
        relevant_references={"19:13"},
        k=5,
    )
    gate = RetrievalQualityGate(
        min_precision_at_k=0.75,
        min_recall_at_k=0.70,
        min_mrr=0.80,
        min_hit_rate=1.0,
    )

    report = assert_quality_gate(metrics, gate)

    assert report.passed is False
    assert report.failures == {
        "precision_at_k": {"actual": 0.0, "minimum": 0.75},
        "recall_at_k": {"actual": 0.0, "minimum": 0.70},
        "mrr": {"actual": 0.0, "minimum": 0.80},
        "hit_rate": {"actual": 0.0, "minimum": 1.0},
    }
