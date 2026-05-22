from ragstudio.services.query_pathway_diagnostics_service import (
    QueryPathwayDiagnosticsService,
)


def row_for(rows, stage):
    return next(row for row in rows if row["stage"] == stage)


def sample_traces():
    return [
        {
            "stage": "planner",
            "intent": "semantic",
            "retrieval_strategy": "reference_first_hybrid",
            "candidate_limit": 20,
            "query_hypothesis_status": "valid",
        },
        {
            "stage": "query_hypothesis",
            "status": "valid",
            "target_terms": [
                {"surface": "offering"},
                {"surface": "sacrifice"},
                {"surface": "eid"},
            ],
            "possible_references": ["book:13:hadith:25"],
        },
        {
            "stage": "retrieval",
            "native_status": "degraded",
            "native_candidates": 0,
            "metadata_trace": {
                "passes": [
                    {"name": "reference_exact", "candidate_count": 1},
                    {"name": "semantic_metadata", "candidate_count": 1},
                ]
            },
        },
        {"stage": "seed_fusion", "seed_candidates": 1},
        {"stage": "graph_expansion", "status": "ok", "expanded_candidates": 2},
        {"stage": "graph_hydration", "status": "ok", "unique_hydrated_chunks": 2},
        {"stage": "final_fusion", "fused_candidates": 3},
        {
            "stage": "hypothesis_verification",
            "status": "confirmed",
            "possible_reference_results": [
                {"reference": "book:13:hadith:25", "status": "confirmed"}
            ],
        },
        {"stage": "context_assembly", "included_candidates": 3, "dropped_candidates": 0},
        {"stage": "grounding_validation", "status": "grounded", "cited_labels": ["S1"]},
    ]


def test_builds_complete_fast_mode_pathway_diagnostics():
    rows = QueryPathwayDiagnosticsService().build(
        status="succeeded",
        error=None,
        error_type=None,
        timings={
            "total_ms": 7574.93,
            "planner_ms": 1915.076,
            "query_hypothesis_ms": 1543.2,
            "query_hypothesis_timeout_ms": 5000,
            "metadata_ms": 3.0,
            "native_stage_ms": 2500.1,
            "native_degraded": True,
            "native_error": "Native query timed out after 2500 ms.",
            "graph_ms": 159.3,
            "graph_hydration_ms": 3.2,
            "initial_fusion_ms": 0.05,
            "final_fusion_ms": 0.14,
            "context_assembly_ms": 0.08,
            "answer_ms": 3001.0,
            "answer_timeout_ms": 3000,
            "answer_fallback": True,
        },
        chunk_traces=sample_traces(),
        sources=[
            {
                "chunk_id": "chunk-25",
                "source_location": {"reference": "Book 13, Hadith 25"},
                "metadata": {"canonical_reference": "book:13:hadith:25"},
            }
        ],
        token_metadata={
            "answer_mode": "evidence_first",
            "llm_answer_status": "timeout",
            "fallback_reason": "llm_timeout",
        },
        query_config={
            "response_mode": "fast",
            "answer_budget_ms": 3000,
            "native_query_timeout_ms": 2500,
        },
    )

    assert [row["stage"] for row in rows] == [
        "retrieval_route_plan",
        "retrieval_lanes",
        "layout_neighbor_expansion",
        "context_window",
        "reranker",
        "planner",
        "llm_planning",
        "metadata_retrieval",
        "native_retrieval",
        "seed_fusion",
        "graph_expansion",
        "graph_hydration",
        "final_fusion",
        "hypothesis_verification",
        "context_assembly",
        "answer_generation",
        "grounding_validation",
    ]
    assert row_for(rows, "llm_planning")["output"] == (
        "target_terms: offering, sacrifice, eid; possible_references: book:13:hadith:25"
    )
    assert row_for(rows, "native_retrieval")["status"] == "warning"
    assert "metadata fallback" in row_for(rows, "native_retrieval")["diagnosis"]
    assert row_for(rows, "seed_fusion")["status"] == "success"
    assert row_for(rows, "final_fusion")["status"] == "success"
    assert row_for(rows, "context_assembly")["status"] == "success"
    assert row_for(rows, "answer_generation")["status"] == "warning"
    assert row_for(rows, "answer_generation")["budget_ms"] == 3000
    assert row_for(rows, "answer_generation")["output"] == "fallback: llm_timeout"


def test_builds_three_pillar_architecture_diagnostics():
    rows = QueryPathwayDiagnosticsService().build(
        status="succeeded",
        error=None,
        error_type=None,
        timings={
            "route_plan_ms": 1.2,
            "layout_neighbor_ms": 2.4,
            "context_window_ms": 2.8,
            "context_assembly_ms": 0.8,
            "rerank_ms": 4.0,
        },
        chunk_traces=[
            {
                "stage": "retrieval_route_plan",
                "domain_profile_id": "reference_heavy",
                "layout_hint": "reference",
                "materialization_hint": "graph",
                "source_of_truth": "postgres_canonical_evidence",
                "direct_evidence_required": True,
                "graph_context_required": True,
            },
            {
                "stage": "retrieval_lane_result",
                "lane": "metadata",
                "status": "ran",
                "reason": "metadata_lane_completed",
                "candidate_count": 1,
                "latency_ms": 2.1,
                "timed_out": False,
                "partial": False,
            },
            {
                "stage": "layout_neighbor_expansion",
                "status": "ran",
                "reason": "same_page_reference_layout_group_or_reading_order_neighbors",
                "candidate_count": 1,
                "layout_group_ids": ["table-srg-001"],
                "reading_order_neighbors": True,
            },
            {
                "stage": "retrieval_lane_result",
                "lane": "context_window",
                "status": "ran",
                "reason": "adjacent_parent_sibling_context_window",
                "candidate_count": 4,
                "relationship_reasons": {
                    "chunk-parent": "parent_context",
                    "chunk-prev": "reading_order_adjacent_and_linked_context",
                },
            },
            {
                "stage": "retrieval_lane_result",
                "lane": "reranker",
                "status": "ran",
                "reason": "reranker_completed",
                "candidate_count": 2,
                "rank_deltas": {
                    "chunk-a": {"before": 2, "after": 1},
                    "chunk-b": {"before": 1, "after": 2},
                },
            },
            {
                "stage": "context_assembly",
                "included_candidates": 1,
                "dropped_candidates": 1,
                "assembled_context": {
                    "evidence_ids": ["metadata:chunk-a"],
                    "grounding_status": "grounded",
                    "breadcrumbs_visible": True,
                    "layout_summary_visible": True,
                },
                "dropped_reasons": {
                    "vector:chunk-b": "lower_rank_supporting_context",
                },
            },
        ],
        sources=[],
        token_metadata={},
        query_config={"response_mode": "fast"},
    )

    assert [row["stage"] for row in rows][:5] == [
        "retrieval_route_plan",
        "retrieval_lanes",
        "layout_neighbor_expansion",
        "context_window",
        "reranker",
    ]
    assert row_for(rows, "retrieval_route_plan")["output"] == (
        "domain: reference_heavy; layout: reference; materialization: graph; "
        "source: postgres_canonical_evidence"
    )
    assert row_for(rows, "retrieval_lanes")["output"] == "metadata ran: 1 candidates"
    assert row_for(rows, "layout_neighbor_expansion")["output"] == (
        "1 candidates; layout groups: table-srg-001; reading order neighbors: yes"
    )
    assert row_for(rows, "context_window")["output"] == (
        "4 candidates; parent_context: 1; reading_order_adjacent_and_linked_context: 1"
    )
    assert row_for(rows, "reranker")["output"] == "2 candidates; rank changes: 2"
    assert row_for(rows, "context_assembly")["output"] == (
        "included: 1; dropped: 1; evidence: metadata:chunk-a; grounding: grounded"
    )


def test_build_handles_missing_traces_without_failing():
    rows = QueryPathwayDiagnosticsService().build(
        status="failed",
        error="runtime unavailable",
        error_type="RuntimeUnavailableError",
        timings={"total_ms": 12.4},
        chunk_traces=[],
        sources=[],
        token_metadata={},
        query_config={"response_mode": "fast"},
    )

    assert len(rows) == 17
    assert row_for(rows, "planner")["status"] == "unknown"
    assert row_for(rows, "planner")["diagnosis"] == "Missing trace or timing data."
    assert row_for(rows, "answer_generation")["status"] == "failed"
    assert row_for(rows, "answer_generation")["output"] == (
        "RuntimeUnavailableError: runtime unavailable"
    )
