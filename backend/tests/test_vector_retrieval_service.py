from ragstudio.services.vector_retrieval_service import (
    prepare_vector_candidates,
    vector_lane_allowed,
    vector_lane_diagnostics,
)


def test_vector_lane_is_disabled_without_baseline_gate():
    assert vector_lane_allowed({}) is False

    diagnostics = vector_lane_diagnostics({})

    assert diagnostics.status == "skipped"
    assert diagnostics.reason == "vector_lane_skipped_baseline_gate_missing"
    assert diagnostics.as_dict()["gate"] == {"provided": False}


def test_vector_lane_allows_supplied_passing_baseline_gate():
    baseline = {
        "direct_hit_regressed": False,
        "mrr_regressed": False,
        "ndcg_regressed": False,
        "recall_regressed": False,
        "latency_budget_regressed": False,
    }

    assert vector_lane_allowed({}, baseline_gate=baseline) is True


def test_vector_lane_rejects_quality_blocked_chunks_even_when_gate_passes():
    metadata = {
        "quality_action_policy": {
            "action": "allow",
            "index_vector": False,
            "reasons": ["low_confidence_layout"],
        }
    }

    diagnostics = vector_lane_diagnostics(metadata, baseline_gate={"passed": True})

    assert vector_lane_allowed(metadata, baseline_gate={"passed": True}) is False
    assert diagnostics.status == "skipped"
    assert diagnostics.reason == "vector_lane_blocked_by_quality_policy"


def test_vector_lane_rejects_action_block_even_when_baseline_passes():
    metadata = {"quality_action_policy": {"action": "block", "index_vector": True}}

    result = prepare_vector_candidates(
        [{"chunk_id": "chunk-1", "document_id": "doc-1", "text": "unsafe"}],
        metadata=metadata,
        baseline_gate={"passed": True},
    )

    assert result.status == "skipped"
    assert result.reason == "vector_lane_blocked_by_quality_policy"


def test_prepare_vector_candidates_hydrates_to_canonical_chunk_identity():
    result = prepare_vector_candidates(
        [
            {
                "candidate_id": "pgvector-row-9",
                "chunk_id": "chunk-1",
                "score": 0.91,
                "rank": 2,
                "metadata": {"raw_vector_index": "proof-v1"},
            }
        ],
        baseline_gate={"passed": True},
        canonical_chunks={
            "chunk-1": {
                "id": "chunk-1",
                "document_id": "doc-1",
                "text": "Canonical chunk text",
                "source_location": {"page": 3},
                "metadata_json": {"chunk_identity": "doc-1|page-3|chunk-1"},
            }
        },
    )

    assert result.status == "ran"
    assert result.reason == "vector_candidates_hydrated_to_canonical_chunks"
    assert result.diagnostics.candidate_count == 1
    assert result.diagnostics.hydrated_count == 1
    assert len(result.candidates) == 1

    candidate = result.candidates[0]
    assert candidate.candidate_id == "vector:chunk-1"
    assert candidate.chunk_id == "chunk-1"
    assert candidate.document_id == "doc-1"
    assert candidate.text == "Canonical chunk text"
    assert candidate.source_location == {"page": 3}
    assert candidate.metadata["canonical_chunk_id"] == "chunk-1"
    assert candidate.metadata["chunk_identity"] == "doc-1|page-3|chunk-1"
    assert candidate.metadata["vector_retrieval"]["original_candidate_id"] == "pgvector-row-9"
    assert candidate.retrieval_pass == "vector_db"


def test_prepare_vector_candidates_preserves_raw_evidence_context_on_hydration():
    result = prepare_vector_candidates(
        [
            {
                "candidate_id": "pgvector-row-context",
                "chunk_id": "chunk-context",
                "score": 0.91,
                "metadata": {
                    "evidence_context": {
                        "breadcrumb": "Synthetic Tafseer > 1:5",
                        "layout_summary": "text; page=1",
                        "page": 1,
                        "reference": "1:5",
                    }
                },
            }
        ],
        baseline_gate={"passed": True},
        canonical_chunks={
            "chunk-context": {
                "id": "chunk-context",
                "document_id": "doc-context",
                "text": "Canonical chunk text",
                "source_location": {"page": 1},
                "metadata_json": {"chunk_identity": "doc-context|page-1|chunk-context"},
            }
        },
    )

    assert result.candidates[0].metadata["evidence_context"] == {
        "breadcrumb": "Synthetic Tafseer > 1:5",
        "layout_summary": "text; page=1",
        "page": 1,
        "reference": "1:5",
    }


def test_prepare_vector_candidates_reports_failed_hydration():
    result = prepare_vector_candidates(
        [{"candidate_id": "pgvector-row-9", "chunk_id": "missing", "score": 0.6}],
        baseline_gate={"passed": True},
        canonical_chunks={},
    )

    assert result.status == "failed"
    assert result.reason == "canonical_hydration_failed"
    assert result.candidates == ()
    assert result.diagnostics.failed_candidate_ids == ("pgvector-row-9",)
    assert result.diagnostics.warning_flags == ("vector_candidates_not_hydrated",)


def test_prepare_vector_candidates_reports_skipped_gate_with_candidate_count():
    result = prepare_vector_candidates(
        [{"candidate_id": "pgvector-row-9", "chunk_id": "chunk-1", "score": 0.6}],
        baseline_gate=None,
        canonical_chunks={},
    )

    assert result.status == "skipped"
    assert result.reason == "vector_lane_skipped_baseline_gate_missing"
    assert result.candidates == ()
    assert result.diagnostics.candidate_count == 1
