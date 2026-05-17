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

    assert len(rows) == 12
    assert row_for(rows, "planner")["status"] == "unknown"
    assert row_for(rows, "planner")["diagnosis"] == "Missing trace or timing data."
    assert row_for(rows, "answer_generation")["status"] == "failed"
    assert row_for(rows, "answer_generation")["output"] == (
        "RuntimeUnavailableError: runtime unavailable"
    )
