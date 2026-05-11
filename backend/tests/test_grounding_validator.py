from ragstudio.services.grounding_validator import GroundingValidator
from ragstudio.services.retrieval_evidence import EvidenceCandidate


def candidate(label_ref="19:13", *, direct=True):
    return EvidenceCandidate(
        candidate_id="metadata:chunk-19-13",
        text="[19:13] وَحَنَانًا مِّن لَّدُنَّا",
        document_id="doc-quran",
        chunk_id="chunk-19-13",
        source_location={"page": 312, "reference": label_ref},
        metadata={"reference_metadata": {"references": [label_ref]}},
        tool="metadata",
        tool_rank=1,
        base_score=10,
        final_score=100,
        match_features={"reference_exact": direct},
        canonical_reference=label_ref,
    )


def candidate_with_canonical_reference_only(label_ref="19:13"):
    return EvidenceCandidate(
        candidate_id="metadata:chunk-19-13",
        text="[19:13] وَحَنَانًا مِّن لَّدُنَّا",
        document_id="doc-quran",
        chunk_id="chunk-19-13",
        source_location={"page": 312},
        metadata={},
        tool="metadata",
        tool_rank=1,
        base_score=10,
        final_score=100,
        canonical_reference=label_ref,
    )


def test_validator_passes_answer_with_existing_source_label():
    result = GroundingValidator().validate(
        answer="The evidence is from 19:13. [S1]",
        evidence=[candidate()],
        expected_references={"19:13"},
    )

    assert result.status == "grounded"
    assert result.failures == []


def test_validator_flags_missing_source_label():
    result = GroundingValidator().validate(
        answer="The evidence is from 19:13. [S2]",
        evidence=[candidate()],
        expected_references={"19:13"},
    )

    assert result.status == "failed"
    assert result.failures == [
        {
            "code": "unknown_source_label",
            "detail": "Answer cites [S2], but only [S1] is available.",
        }
    ]


def test_validator_flags_missing_source_label_when_none_are_available():
    result = GroundingValidator().validate(
        answer="The evidence is from 19:13. [S1]",
        evidence=[],
    )

    assert result.status == "failed"
    assert result.failures == [
        {
            "code": "unknown_source_label",
            "detail": "Answer cites [S1], but no source labels are available.",
        }
    ]


def test_validator_flags_missing_source_label_with_multiple_available_labels():
    result = GroundingValidator().validate(
        answer="The evidence is from 19:13. [S3]",
        evidence=[candidate("19:13"), candidate("19:14")],
    )

    assert result.status == "failed"
    assert result.failures == [
        {
            "code": "unknown_source_label",
            "detail": "Answer cites [S3], but only [S1], [S2] are available.",
        }
    ]


def test_validator_flags_not_found_answer_when_direct_evidence_exists():
    result = GroundingValidator().validate(
        answer="The available evidence does not support an answer to this question.",
        evidence=[candidate()],
        expected_references={"19:13"},
    )

    assert result.status == "failed"
    assert result.failures[0]["code"] == "direct_evidence_ignored"


def test_validator_matches_expected_reference_from_canonical_reference():
    result = GroundingValidator().validate(
        answer="The evidence is from 19:13. [S1]",
        evidence=[candidate_with_canonical_reference_only()],
        expected_references={"19:13"},
    )

    assert result.status == "grounded"
    assert result.failures == []
