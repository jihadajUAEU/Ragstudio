from ragstudio.services.evidence_unit_contract import MaterializationPolicy, QualityActionPolicy
from ragstudio.services.retrieval_route_planner import (
    RetrievalLaneResult,
    RetrievalRoutePlanner,
    RetrievalRouteRequest,
)


def test_route_planner_keeps_postgres_canonical_evidence_first():
    plan = RetrievalRoutePlanner().plan(RetrievalRouteRequest(domain_id="reference_heavy"))

    assert plan.lanes[0].lane == "postgres_canonical"
    assert plan.lanes[0].status == "required"
    assert plan.source_of_truth == "postgres_canonical_evidence"
    assert plan.planned_lanes() == (
        "postgres_canonical",
        "lexical_reference",
        "metadata",
        "graph",
        "vector",
        "reranker",
    )
    assert plan.top_k == plan.candidate_limit


def test_route_planner_adds_raganything_for_multimodal_runtime_lane():
    plan = RetrievalRoutePlanner().plan(
        RetrievalRouteRequest(layout_hint="table", materialization_hint="runtime")
    )

    assert plan.domain_profile_id == "multimodal_layout"
    assert plan.lane_for("raganything_runtime").status == "planned"
    assert plan.lanes[0].lane == "postgres_canonical"


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

    assert plan.planned_lanes() == ("postgres_canonical", "metadata", "reranker")
    assert plan.lane_for("vector").status == "skipped"
    assert plan.lane_for("graph").status == "skipped"
    assert plan.lane_for("raganything_runtime").status == "skipped"
    assert "vector_lane_blocked_by_quality_policy" in plan.reasons
    assert "raganything_runtime_lane_blocked_by_materialization_policy" in plan.reasons


def test_route_planner_serializes_lane_plans_and_skipped_reasons():
    plan = RetrievalRoutePlanner().plan(
        RetrievalRouteRequest(
            domain_id="multimodal_layout",
            quality_action_policy=QualityActionPolicy(index_vector=False, project_graph=False),
            materialization_policy=MaterializationPolicy(
                action="persist_only",
                allow_raganything_runtime_lane=False,
            ),
            top_k=6,
            response_budget_ms=9000,
            lane_time_budget_ms=1200,
        )
    )

    assert plan.route_plan_version == "2026-05-21"
    assert plan.candidate_limit == 6
    assert plan.response_budget_ms == 9000
    assert plan.lane_time_budget_ms == 1200
    assert [lane.lane for lane in plan.lanes] == [
        "postgres_canonical",
        "metadata",
        "raganything_runtime",
        "vector",
        "graph",
        "reranker",
    ]
    assert plan.lane_for("postgres_canonical").status == "required"
    assert plan.lane_for("vector").status == "skipped"
    assert plan.lane_for("vector").reason == "vector_lane_blocked_by_quality_policy"
    assert plan.lane_for("graph").status == "skipped"
    assert plan.lane_for("raganything_runtime").status == "skipped"

    payload = plan.as_dict()

    assert payload["route_plan_version"] == "2026-05-21"
    assert payload["candidate_limit"] == 6
    assert payload["lanes"][0]["lane"] == "postgres_canonical"
    assert payload["lanes"][0]["status"] == "required"
    assert "vector_lane_blocked_by_quality_policy" in payload["reasons"]


def test_route_planner_marks_readiness_degraded_lanes():
    plan = RetrievalRoutePlanner().plan(
        RetrievalRouteRequest(
            domain_id="multimodal_layout",
            graph_readiness={"state": "stale", "reason": "projection_older_than_chunks"},
            runtime_readiness={"state": "unavailable", "reason": "runtime_health_failed"},
            reranker_readiness={"state": "disabled", "reason": "profile_disabled"},
            top_k=8,
        )
    )

    assert plan.lane_for("graph").status == "skipped"
    assert plan.lane_for("graph").reason == "graph_projection_stale"
    assert plan.lane_for("raganything_runtime").status == "skipped"
    assert plan.lane_for("reranker").status == "skipped"
    assert plan.lane_for("reranker").reason == "reranker_disabled"
    assert plan.readiness["graph"]["state"] == "stale"


def test_route_planner_serializes_partial_recovery_contract():
    plan = RetrievalRoutePlanner().plan(
        RetrievalRouteRequest(
            document_ids=("doc-1",),
            domain_id="reference_heavy",
            top_k=5,
            response_budget_ms=3000,
        )
    )

    graph_lane = plan.lane_for("graph")

    assert graph_lane.critical is False
    assert graph_lane.timeout_ms <= 3000
    payload = graph_lane.as_dict()
    assert payload["critical"] is False
    assert payload["partial_timeout_policy"] == "return_degraded_candidates"


def test_lane_result_serializes_uniform_trace_contract():
    result = RetrievalLaneResult(
        lane="vector",
        status="timed_out",
        reason="lane_budget_exceeded",
        candidate_count=2,
        candidate_ids=("candidate-1", "candidate-2"),
        canonical_chunk_ids=("chunk-1",),
        document_ids=("doc-1",),
        latency_ms=121.5,
        timed_out=True,
        partial=True,
        warning_flags=("partial_timeout",),
        score_basis={"basis": "cosine"},
    )

    payload = result.as_dict()

    assert payload["stage"] == "retrieval_lane_result"
    assert payload["lane"] == "vector"
    assert payload["status"] == "timed_out"
    assert payload["candidate_ids"] == ["candidate-1", "candidate-2"]
    assert payload["score_basis"] == {"basis": "cosine"}
