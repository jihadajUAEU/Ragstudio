from ragstudio.services.retrieval_evidence import EvidenceCandidate
from ragstudio.services.retrieval_metrics import (
    RetrievalQualityGate,
    assert_quality_gate,
    calculate_retrieval_metrics,
)


def _source(reference, chunk_id, rank, *, direct=False):
    return EvidenceCandidate(
        candidate_id=f"test:{chunk_id}",
        text=f"[{reference}] sample text",
        document_id="doc-quran",
        chunk_id=chunk_id,
        source_location={"page": rank, "reference": reference},
        metadata={
            "reference_metadata": {"references": [reference]},
            "match_features": {"reference_exact": direct},
        },
        tool="test",
        tool_rank=rank,
        base_score=1.0,
        final_score=1.0,
    )


def test_quran_arabic_word_gate_metrics():
    results = [
        _source("19:13", "quran-19-13", 1, direct=True),
        _source("19:12", "quran-19-12", 2),
    ]

    metrics = calculate_retrieval_metrics(results, relevant_references={"19:13"}, k=5)
    report = assert_quality_gate(
        metrics,
        RetrievalQualityGate(
            min_precision_at_k=0.20,
            min_recall_at_k=1.00,
            min_mrr=1.00,
            min_hit_rate=1.00,
        ),
    )

    assert report.passed is True


def test_quran_light_reference_gate_metrics():
    results = [
        _source("24:35", "quran-24-35", 1, direct=True),
        _source("24:36", "quran-24-36", 2),
    ]

    metrics = calculate_retrieval_metrics(results, relevant_references={"24:35"}, k=5)
    report = assert_quality_gate(
        metrics,
        RetrievalQualityGate(
            min_precision_at_k=0.20,
            min_recall_at_k=1.00,
            min_mrr=1.00,
            min_hit_rate=1.00,
        ),
    )

    assert report.passed is True
