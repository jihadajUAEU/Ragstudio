from ragstudio.services.retrieval_evidence import EvidenceCandidate


def _source(reference, chunk_id, rank):
    return EvidenceCandidate(
        candidate_id=f"test:{chunk_id}",
        text=f"[{reference}] sample text",
        document_id="doc-quran",
        chunk_id=chunk_id,
        source_location={"page": rank},
        metadata={"reference_metadata": {"references": [reference]}},
        tool="test",
        tool_rank=rank,
        base_score=1.0,
        final_score=1.0,
    )


def precision_at_k(results, expected_reference, k):
    top = results[:k]
    return sum(_has_reference(item, expected_reference) for item in top) / max(len(top), 1)


def reciprocal_rank(results, expected_reference):
    for index, item in enumerate(results, start=1):
        if _has_reference(item, expected_reference):
            return 1 / index
    return 0.0


def _has_reference(candidate, expected_reference):
    refs = candidate.metadata.get("reference_metadata", {}).get("references", [])
    return expected_reference in refs


def test_quran_arabic_word_gate_metrics():
    results = [
        _source("19:13", "quran-19-13", 1),
        _source("19:12", "quran-19-12", 2),
    ]

    assert precision_at_k(results, "19:13", 5) >= 0.5
    assert reciprocal_rank(results, "19:13") == 1.0


def test_quran_light_reference_gate_metrics():
    results = [
        _source("24:35", "quran-24-35", 1),
        _source("24:36", "quran-24-36", 2),
    ]

    assert precision_at_k(results, "24:35", 5) >= 0.5
    assert reciprocal_rank(results, "24:35") == 1.0
