import { describe, expect, it } from "vitest";

import type { RunOut } from "../src/api/generated";
import { buildThreePillarTrace } from "../src/features/query/three-pillar-trace";

const run: RunOut = {
  id: "run-1",
  variant_id: "variant-1",
  experiment_id: null,
  query: "Which reference was blocked?",
  status: "succeeded",
  answer: "answer",
  sources: [
    {
      id: "source-1",
      chunk_id: "chunk-a",
      metadata: {
        domain_metadata: { domain: "hadith" },
        layout_group_id: "table-srg-001",
        layout_role: "table_cell",
        reading_order: 12,
        parent_chunk_id: "chunk-parent",
        previous_chunk_id: "chunk-prev",
        next_chunk_id: "chunk-next",
        quality_action_policy: "materialize",
        materialization_hint: "graph",
      },
    },
  ],
  chunk_traces: [
    {
      stage: "retrieval_route_plan",
      domain_profile_id: "reference_heavy",
      layout_hint: "reference",
      materialization_hint: "graph",
      source_of_truth: "postgres_canonical_evidence",
      direct_evidence_required: true,
      graph_context_required: true,
    },
    {
      stage: "retrieval_lane_result",
      lane: "metadata",
      status: "ran",
      reason: "metadata_lane_completed",
      candidate_count: 1,
      latency_ms: 2.1,
      timed_out: false,
      partial: false,
      canonical_chunk_ids: ["chunk-a"],
    },
    {
      stage: "layout_neighbor_expansion",
      status: "ran",
      reason: "same_page_reference_layout_group_or_reading_order_neighbors",
      candidate_count: 1,
      layout_group_ids: ["table-srg-001"],
      reading_order_neighbors: true,
      canonical_chunk_ids: ["chunk-b"],
    },
    {
      stage: "retrieval_lane_result",
      lane: "context_window",
      status: "ran",
      reason: "adjacent_parent_sibling_context_window",
      candidate_count: 4,
      relationship_reasons: {
        "chunk-parent": "parent_context",
        "chunk-prev": "reading_order_adjacent_and_linked_context",
      },
    },
    {
      stage: "retrieval_lane_result",
      lane: "reranker",
      status: "ran",
      reason: "reranker_completed",
      candidate_count: 2,
      rank_deltas: {
        "chunk-a": { before: 2, after: 1 },
        "chunk-b": { before: 1, after: 2 },
      },
    },
    {
      stage: "context_assembly",
      included_candidates: 1,
      dropped_candidates: 1,
      assembled_context: {
        evidence_ids: ["metadata:chunk-a"],
        grounding_status: "grounded",
        breadcrumbs_visible: true,
        layout_summary_visible: true,
      },
      dropped_reasons: { "vector:chunk-b": "lower_rank_supporting_context" },
    },
  ],
  timings: { total_ms: 21, rerank_ms: 4 },
  error: null,
  runtime_profile_id: "default",
  document_ids: ["doc-1"],
  query_config: {},
  reranker_traces: [{ status: "succeeded", provider: "generic_http", model: "rerank-model" }],
  token_metadata: {},
  error_type: null,
};

describe("buildThreePillarTrace", () => {
  it("summarizes route, lanes, layout, context, assembly, and reranker rank deltas", () => {
    const summary = buildThreePillarTrace(run);

    expect(summary.route.domainProfileId).toBe("reference_heavy");
    expect(summary.route.materializationHint).toBe("graph");
    expect(summary.lanes.map((lane) => lane.lane)).toEqual([
      "metadata",
      "context_window",
      "reranker",
    ]);
    expect(summary.layout.layoutGroupIds).toEqual(["table-srg-001"]);
    expect(summary.layout.readingOrderNeighbors).toBe(true);
    expect(summary.context.relationshipReasons).toEqual([
      { chunkId: "chunk-parent", reason: "parent_context" },
      { chunkId: "chunk-prev", reason: "reading_order_adjacent_and_linked_context" },
    ]);
    expect(summary.assembly.evidenceIds).toEqual(["metadata:chunk-a"]);
    expect(summary.assembly.droppedReasons).toEqual([
      { candidateId: "vector:chunk-b", reason: "lower_rank_supporting_context" },
    ]);
    expect(summary.reranker.rankDeltas).toEqual([
      { candidateId: "chunk-a", before: 2, after: 1, delta: 1 },
      { candidateId: "chunk-b", before: 1, after: 2, delta: -1 },
    ]);
    expect(summary.sources[0].layout.readingOrder).toBe("12");
    expect(summary.sources[0].context.parentChunkId).toBe("chunk-parent");
  });
});
