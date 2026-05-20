from ragstudio.services.evidence_unit_contract import MaterializationPolicy, QualityActionPolicy
from ragstudio.services.retrieval_route_planner import (
    RetrievalRoutePlanner,
    RetrievalRouteRequest,
)


def test_route_planner_keeps_postgres_canonical_evidence_first():
    plan = RetrievalRoutePlanner().plan(RetrievalRouteRequest(domain_id="reference_heavy"))

    assert plan.lanes[0] == "postgres_canonical"
    assert plan.source_of_truth == "postgres_canonical_evidence"
    assert plan.lanes == ("postgres_canonical", "lexical_reference", "graph", "vector")


def test_route_planner_adds_raganything_for_multimodal_runtime_lane():
    plan = RetrievalRoutePlanner().plan(
        RetrievalRouteRequest(layout_hint="table", materialization_hint="runtime")
    )

    assert plan.domain_profile_id == "multimodal_layout"
    assert "raganything_runtime" in plan.lanes
    assert plan.lanes[0] == "postgres_canonical"


def test_route_planner_honors_quality_and_materialization_blocks():
    plan = RetrievalRoutePlanner().plan(
        RetrievalRouteRequest(
            domain_id="multimodal_layout",
            quality_action_policy=QualityActionPolicy(index_vector=False, project_graph=False),
            materialization_policy=MaterializationPolicy(
                action="persist_only",
                allow_raganything_runtime_lane=False,
            ),
        )
    )

    assert plan.lanes == ("postgres_canonical",)
    assert "vector_lane_blocked_by_quality_policy" in plan.reasons
    assert "raganything_runtime_lane_blocked_by_materialization_policy" in plan.reasons
