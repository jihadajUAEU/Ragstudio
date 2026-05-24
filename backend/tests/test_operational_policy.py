from ragstudio.services.operational_policy import DEFAULT_OPERATIONAL_POLICY


def test_operational_policy_preserves_current_limits() -> None:
    policy = DEFAULT_OPERATIONAL_POLICY

    assert policy.upload.max_upload_bytes == 25 * 1024 * 1024
    assert policy.upload.upload_chunk_bytes == 1024 * 1024
    assert policy.worker.lease_seconds == 300
    assert policy.chunk_persistence.min_expected_chunks == 2
    assert policy.chunk_persistence.max_expected_chunks == 5000
    assert policy.chunk_persistence.persist_batch_size == 500
    assert policy.chunk_search.fallback_candidate_limit == 100
    assert policy.candidate_diversity.similarity_threshold == 0.65


def test_evaluation_and_retrieval_gate_defaults_are_named() -> None:
    policy = DEFAULT_OPERATIONAL_POLICY

    assert policy.evaluation.expected_answer_weight == 50.0
    assert policy.evaluation.must_include_weight == 35.0
    assert policy.evaluation.must_avoid_weight == 15.0
    assert policy.retrieval_metrics.min_precision_at_k == 0.75
    assert policy.retrieval_metrics.min_recall_at_k == 0.70
    assert policy.retrieval_metrics.min_mrr == 0.80
    assert policy.retrieval_metrics.min_hit_rate == 1.0


def test_variant_presets_are_backend_policy_not_ui_only() -> None:
    policy = DEFAULT_OPERATIONAL_POLICY

    assert policy.variant_presets["balanced"] == {
        "top_k": 5,
        "temperature": 0.2,
        "enable_rerank": True,
    }
    assert policy.variant_presets["fast"] == {
        "top_k": 4,
        "temperature": 0.0,
        "enable_rerank": False,
    }
