import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RunOut } from "../src/api/generated";
import { QueryPathwayViewer } from "../src/features/query/query-pathway-viewer";

const run: RunOut = {
  id: "run-7",
  variant_id: "variant-1",
  experiment_id: null,
  query: "show the trace reasons",
  status: "succeeded",
  answer: "answer",
  sources: [],
  chunk_traces: [
    {
      stage: "retrieval_route_plan",
      domain_profile_id: "reference_heavy",
      domain_reasons: [
        "domain_profile:reference_heavy",
        "verified_reference_contract",
        "materialization:graph",
      ],
      layout_hint: "reference",
      materialization_hint: "graph",
      source_of_truth: "postgres_canonical_evidence",
      direct_evidence_required: true,
      graph_context_required: false,
    },
    {
      stage: "layout_neighbor_expansion",
      status: "ran",
      reason: "contract_layout_neighbors",
      layout_reasons: ["bbox_overlap", "layout_group"],
      candidate_count: 2,
      layout_group_ids: ["layout-1"],
      canonical_chunk_ids: ["chunk-2"],
    },
    {
      stage: "retrieval_lane_result",
      lane: "context_window",
      status: "ran",
      reason: "parent_sibling_context_window",
      context_reasons: ["heading_path_context", "linked_context"],
      candidate_count: 1,
      relationship_reasons: { "chunk-3": "heading_path_context" },
    },
    {
      stage: "context_assembly",
      included_candidates: 1,
      dropped_candidates: 0,
      assembled_context: {
        grounding_status: "grounded",
        evidence_ids: ["metadata:chunk-1"],
      },
    },
  ],
  timings: { total_ms: 15 },
  error: null,
  runtime_profile_id: "default",
  document_ids: ["doc-1"],
  query_config: {},
  reranker_traces: [],
  token_metadata: {},
  error_type: null,
};

describe("QueryPathwayViewer", () => {
  it("renders backend-provided three-pillar reason chips", () => {
    render(<QueryPathwayViewer run={run} open onClose={vi.fn()} />);

    expect(screen.getByText("Contract reasons")).toBeVisible();
    expect(screen.getByText("verified_reference_contract")).toBeVisible();
    expect(screen.getByText("materialization:graph")).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "Layout-aware" }));
    expect(screen.getByText("Layout reasons")).toBeVisible();
    expect(screen.getByText("bbox_overlap")).toBeVisible();
    expect(screen.getByText("layout_group")).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "Context-aware" }));
    expect(screen.getByText("Context reasons")).toBeVisible();
    expect(screen.getByText("heading_path_context")).toBeVisible();
    expect(screen.getByText("linked_context")).toBeVisible();
  });
});
