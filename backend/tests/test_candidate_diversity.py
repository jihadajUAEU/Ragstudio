from ragstudio.services.candidate_diversity import select_diverse_candidates
from ragstudio.services.retrieval_evidence import EvidenceCandidate


def candidate(chunk_id: str, text: str, score: float) -> EvidenceCandidate:
    return EvidenceCandidate(
        candidate_id=f"metadata:{chunk_id}",
        text=text,
        document_id="doc-1",
        chunk_id=chunk_id,
        source_location={},
        metadata={},
        tool="metadata",
        tool_rank=1,
        base_score=score,
        final_score=score,
    )


def test_select_diverse_candidates_keeps_best_and_suppresses_redundant_text():
    first = candidate("a", "alpha beta gamma delta", 20)
    duplicate = candidate("b", "alpha beta gamma delta repeated", 19)
    different = candidate("c", "zakat finance charitable obligation", 12)

    selected, trace = select_diverse_candidates([first, duplicate, different], limit=2)

    assert [item.chunk_id for item in selected] == ["a", "c"]
    assert trace["suppressed_candidate_ids"] == ["metadata:b"]
    assert trace["status"] == "ran"


def test_select_diverse_candidates_keeps_parser_quality_evidence():
    first = candidate("a", "alpha beta gamma delta", 20)
    warning = candidate("b", "alpha beta gamma delta repeated", 19)
    warning = warning.__class__(
        **{
            **warning.__dict__,
            "metadata": {"parser_quality_warning_codes": ["layout_low_confidence"]},
            "reasons": ["parser_quality_warning:layout_low_confidence"],
        }
    )

    selected, trace = select_diverse_candidates([first, warning], limit=2)

    assert [item.chunk_id for item in selected] == ["a", "b"]
    assert trace["suppressed_candidate_ids"] == []
