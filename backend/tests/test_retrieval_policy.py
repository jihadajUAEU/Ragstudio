from ragstudio.services.retrieval_policy import (
    DEFAULT_RETRIEVAL_POLICY,
    FusionScorePolicy,
    HybridScorePolicy,
    LayoutNeighborPolicy,
    RoutePlanningPolicy,
)


def test_hybrid_score_policy_preserves_current_weights() -> None:
    policy = HybridScorePolicy()

    assert policy.reference_exact == 100.0
    assert policy.same_chapter_reference_query == 60.0
    assert policy.same_chapter_with_verse_query == 5.0
    assert policy.neighbor_match == 30.0
    assert policy.term_coverage_multiplier == 10.0
    assert policy.semantic_density_multiplier == 2.0
    assert policy.metadata_boost_cap == 12.0
    assert policy.layout_context_cap == 16.0
    assert policy.arabic_exact == 40.0
    assert policy.arabic_token == 24.0
    assert policy.answer_bearing_count == 30.0
    assert policy.guidance_request == 40.0
    assert policy.exact_query_phrase == 8.0
    assert policy.answer_bearing_phrase == 24.0


def test_fusion_policy_preserves_current_priorities() -> None:
    policy = FusionScorePolicy()

    assert policy.rrf_k == 60
    assert policy.direct_priority["reference_exact"] == 100
    assert policy.direct_priority["arabic_exact"] == 90
    assert policy.direct_priority["target_phrase"] == 80
    assert policy.lane_priority["metadata"] == 40
    assert policy.lane_priority["graph"] == 30
    assert policy.direct_boost["reference_exact"] == 100.0


def test_layout_and_route_policies_preserve_current_thresholds() -> None:
    assert LayoutNeighborPolicy().vertical_proximity == 150.0
    assert RoutePlanningPolicy().lane_timeout_ms(None) == 8000
    assert RoutePlanningPolicy().lane_timeout_ms(10_000) == 3500
    assert DEFAULT_RETRIEVAL_POLICY.policy_version == "2026-05-24"
