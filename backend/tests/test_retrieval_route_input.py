import pytest

from ragstudio.services.query_understanding import QueryUnderstanding
from ragstudio.services.retrieval_route_input import (
    ScopeAccessViolationError,
    build_retrieval_route_request,
)
from ragstudio.services.retrieval_route_planner import RetrievalRouteRequest


def test_route_input_preserves_scope_domain_readiness_and_budgets():
    understanding = QueryUnderstanding(
        query="show Book 13 Hadith 25",
        intent="reference",
        answer_type="reference",
        retrieval_strategy="reference_first_hybrid",
        expanded_terms=["sacrifice"],
        retrieval_passes=[],
        direct_evidence_required=True,
        graph_context_required=True,
    )

    request = build_retrieval_route_request(
        query="show Book 13 Hadith 25",
        document_ids=["doc-hadith"],
        runtime_profile_id="profile-1",
        variant_id="variant-1",
        query_intent="reference",
        retrieval_strategy="reference_first_hybrid",
        query_understanding=understanding,
        domain_metadata=[{"domain": "hadith", "tags": ["hadith"]}],
        query_config={
            "limit": 5,
            "response_budget_ms": 9000,
            "lane_time_budget_ms": 1200,
            "scope_policy": "strict_document_scope",
            "graph_readiness": {"state": "stale", "reason": "projection_older_than_chunks"},
        },
        runtime_readiness={"state": "ready"},
        reranker_readiness={"state": "disabled", "reason": "profile_disabled"},
    )

    assert isinstance(request, RetrievalRouteRequest)
    assert request.document_ids == ("doc-hadith",)
    assert request.scope_policy == "strict_document_scope"
    assert request.runtime_profile_id == "profile-1"
    assert request.variant_id == "variant-1"
    assert request.query_intent == "reference"
    assert request.retrieval_strategy == "reference_first_hybrid"
    assert request.domain_id == "reference_heavy"
    assert request.layout_hint == "reference"
    assert request.direct_evidence_required is True
    assert request.graph_context_required is True
    assert request.top_k == 20
    assert request.response_budget_ms == 9000
    assert request.lane_time_budget_ms == 1200
    assert request.runtime_readiness["state"] == "ready"
    assert request.graph_readiness["state"] == "stale"
    assert request.reranker_readiness["reason"] == "profile_disabled"


def test_route_input_carries_document_policy_and_disables_vector_without_gate():
    request = build_retrieval_route_request(
        query="show evidence",
        document_ids=["doc-1"],
        runtime_profile_id="profile-1",
        variant_id="variant-1",
        query_intent="semantic",
        retrieval_strategy="semantic_hybrid",
        query_understanding=None,
        domain_metadata=[
            {
                "domain": "policy",
                "quality_action_policy": {
                    "index_vector": True,
                    "project_graph": False,
                    "reasons": ["graph_blocked_by_quality"],
                },
                "materialization_policy": {
                    "action": "persist_only",
                    "allow_raganything_runtime_lane": False,
                    "reasons": ["runtime_bridge_missing"],
                },
            }
        ],
        query_config={"limit": 5},
    )

    assert request.quality_action_policy.index_vector is False
    assert request.quality_action_policy.project_graph is False
    assert "vector_lane_skipped_baseline_gate_missing" in request.quality_action_policy.reasons
    assert request.materialization_policy.allow_raganything_runtime_lane is False
    assert request.materialization_policy.action == "persist_only"


def test_route_input_disables_vector_when_baseline_gate_fails():
    request = build_retrieval_route_request(
        query="show evidence",
        document_ids=["doc-1"],
        runtime_profile_id="profile-1",
        variant_id="variant-1",
        query_intent="semantic",
        retrieval_strategy="semantic_hybrid",
        query_understanding=None,
        domain_metadata=[{"domain": "research"}],
        query_config={
            "limit": 5,
            "vector_baseline_gate": {"passed": False},
        },
    )

    assert request.quality_action_policy.index_vector is False
    assert "vector_lane_skipped_baseline_gate_failed" in request.quality_action_policy.reasons


def test_route_input_allows_vector_when_baseline_gate_passes():
    request = build_retrieval_route_request(
        query="show evidence",
        document_ids=["doc-1"],
        runtime_profile_id="profile-1",
        variant_id="variant-1",
        query_intent="semantic",
        retrieval_strategy="semantic_hybrid",
        query_understanding=None,
        domain_metadata=[{"domain": "research"}],
        query_config={
            "limit": 5,
            "vector_baseline_gate": {"passed": True},
        },
    )

    assert request.quality_action_policy.index_vector is True


def test_route_input_sets_multimodal_layout_domain_from_layout_metadata():
    request = build_retrieval_route_request(
        query="summarize the table",
        document_ids=["doc-report"],
        runtime_profile_id=None,
        variant_id=None,
        query_intent="semantic",
        retrieval_strategy="semantic_hybrid",
        query_understanding=None,
        domain_metadata=[{"domain": "finance", "layout_types": ["table", "figure"]}],
        query_config={"limit": 12},
    )

    assert request.document_ids == ("doc-report",)
    assert request.domain_id == "multimodal_layout"
    assert request.layout_hint == "table"
    assert request.top_k == 24
    assert request.graph_readiness["state"] == "ready"
    assert request.runtime_readiness["state"] == "ready"
    assert request.reranker_readiness["state"] == "ready"


def test_route_input_rejects_empty_document_scope_for_strict_profiles():
    with pytest.raises(ScopeAccessViolationError, match="strict document scope"):
        build_retrieval_route_request(
            query="show evidence",
            document_ids=[],
            runtime_profile_id="profile-1",
            variant_id="variant-1",
            query_intent="semantic",
            retrieval_strategy="semantic_hybrid",
            query_understanding=None,
            domain_metadata=[],
            query_config={"scope_policy": "strict_document_scope"},
        )
