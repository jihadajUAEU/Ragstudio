import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../src/api/client";
import { QueryPage } from "../src/features/query/query-page";

vi.mock("../src/api/client", () => ({
  DEFAULT_PARSER_MODE: "mineru_strict",
  apiClient: {
    documents: vi.fn(),
    variants: vi.fn(),
    query: vi.fn(),
    simulateRetrieval: vi.fn(),
  },
}));

function renderQueryPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={queryClient}>
      <QueryPage />
    </QueryClientProvider>,
  );
}

describe("QueryPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-1",
          filename: "source.txt",
          content_type: "text/plain",
          status: "succeeded",
          sha256: "sha",
        },
      ],
      total: 1,
    });
    vi.mocked(apiClient.variants).mockResolvedValue({
      items: [{ id: "variant-1", name: "Balanced", preset: "balanced", parameters: {} }],
      total: 1,
    });
    vi.mocked(apiClient.query).mockResolvedValue({
      runs: [
        {
          id: "run-1",
          variant_id: "variant-1",
          experiment_id: null,
          query: "alpha",
          status: "succeeded",
          answer: "answer",
          sources: [],
          chunk_traces: [],
          timings: {},
          error: null,
          runtime_profile_id: null,
          document_ids: ["doc-1"],
          query_config: {},
          reranker_traces: [
            { status: "failed", provider: "generic_http", error_type: "ConnectError" },
          ],
          token_metadata: {},
          error_type: null,
        },
      ],
    });
    vi.mocked(apiClient.simulateRetrieval).mockResolvedValue({
      items: [
        {
          id: "chunk-1",
          document_id: "doc-1",
          text: "Preview evidence",
          source_location: { page: 1 },
          metadata: { score: 1 },
          content_type: "text",
          relationship_refs: {},
        },
      ],
      total: 1,
    });
  });

  it("summarizes reranker status outside raw JSON", async () => {
    renderQueryPage();

    fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
      target: { value: "alpha" },
    });
    fireEvent.click((await screen.findAllByText("source.txt"))[0]);
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(apiClient.query).toHaveBeenCalled());
    expect(await screen.findByText("Reranker failed")).toBeVisible();
    expect(screen.getByText("generic_http · ConnectError")).toBeVisible();
  });

  it("runs fast evidence mode by default", async () => {
    renderQueryPage();

    expect(await screen.findByRole("button", { name: "Fast" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Full" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
      target: { value: "alpha" },
    });
    fireEvent.click((await screen.findAllByText("source.txt"))[0]);
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(apiClient.query).toHaveBeenCalled());
    expect(vi.mocked(apiClient.query).mock.calls[0][0]).toEqual(
      expect.objectContaining({
        response_mode: "fast",
        answer_budget_ms: 3000,
        response_budget_ms: 15000,
        search_weights: null,
      }),
    );
  });

  it("opens search tuning and simulates with updated metadata boost", async () => {
    renderQueryPage();

    fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
      target: { value: "alpha" },
    });
    fireEvent.click((await screen.findAllByText("source.txt"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Tune retrieval" }));

    expect(await screen.findByRole("dialog", { name: "Search tuning" })).toBeVisible();
    await waitFor(() =>
      expect(apiClient.simulateRetrieval).toHaveBeenCalledWith(
        expect.objectContaining({ search_weights: null }),
      ),
    );
    const metadataBoost = screen.getByLabelText("Metadata boost");
    fireEvent.change(metadataBoost, { target: { value: "2" } });

    await waitFor(() =>
      expect(apiClient.simulateRetrieval).toHaveBeenCalledWith(
        expect.objectContaining({
          search_weights: expect.objectContaining({ metadata_boost: 2 }),
        }),
      ),
    );
  });

  it("labels evidence-first fallback results", async () => {
    vi.mocked(apiClient.query).mockResolvedValue({
      runs: [
        {
          id: "run-1",
          variant_id: "variant-1",
          experiment_id: null,
          query: "alpha",
          status: "succeeded",
          answer: "Evidence-first result\n\nGrounded evidence:\n[S1] alpha",
          sources: [],
          chunk_traces: [],
          timings: {},
          error: null,
          runtime_profile_id: null,
          document_ids: [],
          query_config: { response_mode: "fast" },
          reranker_traces: [],
          token_metadata: {
            answer_mode: "evidence_first",
            llm_answer_status: "timeout",
          },
          error_type: null,
        },
      ],
    });
    renderQueryPage();

    fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
      target: { value: "alpha" },
    });
    fireEvent.click((await screen.findAllByText("source.txt"))[0]);
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    expect(await screen.findByText("Evidence-first result")).toBeVisible();
    expect(screen.getByText("LLM wording exceeded the fast budget.")).toBeVisible();
  });

  it("opens query pathway details with stage status, results, and timings", async () => {
    vi.mocked(apiClient.query).mockResolvedValue({
      runs: [
        {
          id: "run-1",
          variant_id: "variant-1",
          experiment_id: null,
          query: "Which hadith mentions Eid sacrifice?",
          status: "succeeded",
          answer: "Evidence-first result",
          sources: [
            {
              chunk_id: "chunk-25",
              source_location: { reference: "Book 13, Hadith 25" },
              metadata: { canonical_reference: "book:13:hadith:25" },
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
            },
            {
              stage: "layout_neighbor_expansion",
              status: "ran",
              reason: "same_page_reference_layout_group_or_reading_order_neighbors",
              candidate_count: 1,
              layout_group_ids: ["table-srg-001"],
              reading_order_neighbors: true,
            },
            {
              stage: "retrieval_lane_result",
              lane: "context_window",
              status: "ran",
              reason: "adjacent_parent_sibling_context_window",
              candidate_count: 4,
              relationship_reasons: { "chunk-parent": "parent_context" },
            },
            {
              stage: "retrieval_lane_result",
              lane: "reranker",
              status: "ran",
              reason: "reranker_completed",
              candidate_count: 2,
              rank_deltas: { "chunk-25": { before: 2, after: 1 } },
            },
            {
              stage: "planner",
              intent: "semantic",
              retrieval_strategy: "semantic_hybrid",
              candidate_limit: 20,
              query_hypothesis_status: "valid",
            },
            {
              stage: "query_hypothesis",
              status: "valid",
              target_terms: [{ surface: "sacrifice" }, { surface: "eid" }],
              possible_references: ["book:13:hadith:25"],
            },
            {
              stage: "retrieval",
              native_status: "degraded",
              native_candidates: 0,
              metadata_trace: {
                passes: [
                  { name: "reference_exact", candidate_count: 1 },
                  { name: "semantic_metadata", candidate_count: 1 },
                ],
              },
            },
            { stage: "seed_fusion", seed_candidates: 1 },
            { stage: "graph_expansion", status: "ok", expanded_candidates: 2 },
            { stage: "graph_hydration", status: "ok", unique_hydrated_chunks: 2 },
            { stage: "final_fusion", fused_candidates: 3 },
            {
              stage: "hypothesis_verification",
              status: "confirmed",
              possible_reference_results: [
                { reference: "book:13:hadith:25", status: "confirmed" },
              ],
            },
            {
              stage: "context_assembly",
              included_candidates: 3,
              dropped_candidates: 1,
              assembled_context: {
                evidence_ids: ["metadata:chunk-25"],
                grounding_status: "grounded",
                breadcrumbs_visible: true,
                layout_summary_visible: true,
              },
              dropped_reasons: { "vector:chunk-1": "lower_rank_supporting_context" },
            },
            { stage: "grounding_validation", status: "grounded", cited_labels: ["S1"] },
          ],
          timings: {
            total_ms: 7574.93,
            planner_ms: 1915.076,
            query_hypothesis_ms: 1842.868,
            query_hypothesis_timeout_ms: 5000,
            metadata_ms: 4492.731,
            native_stage_ms: 4303.248,
            native_degraded: true,
            native_error: "Native query timed out after 2500 ms.",
            graph_ms: 159.334,
            graph_hydration_ms: 3.274,
            initial_fusion_ms: 0.053,
            final_fusion_ms: 0.146,
            context_assembly_ms: 0.081,
            answer_ms: 3000,
            answer_fallback: true,
          },
          error: null,
          runtime_profile_id: null,
          document_ids: ["doc-1"],
          query_config: { response_mode: "fast" },
          reranker_traces: [],
          token_metadata: {
            answer_mode: "evidence_first",
            llm_answer_status: "timeout",
            fallback_reason: "llm_timeout",
          },
          pathway_diagnostics: [
            {
              stage: "llm_planning",
              label: "LLM planning",
              input: "query + selected document metadata",
              action: "Generate target terms and possible references",
              output:
                "target_terms: sacrifice, eid; possible_references: book:13:hadith:25",
              status: "success",
              time_ms: 1842.868,
              budget_ms: 5000,
              diagnosis: "Healthy. Used 37% of budget.",
              suggested_action: "None",
            },
            {
              stage: "native_retrieval",
              label: "Native retrieval",
              input: "query + native runtime scope",
              action: "Search native RAG runtime",
              output: "Native query timed out after 2500 ms.",
              status: "warning",
              time_ms: 4303.248,
              budget_ms: 2500,
              diagnosis: "Timed out or degraded; metadata fallback used.",
              suggested_action: "Check native runtime latency.",
            },
            {
              stage: "answer_generation",
              label: "Answer generation",
              input: "assembled evidence context",
              action: "Generate final answer wording or evidence-first fallback",
              output: "fallback: llm_timeout",
              status: "warning",
              time_ms: 3000,
              budget_ms: 3000,
              diagnosis: "Timed out; evidence-first answer used.",
              suggested_action: "Use full mode if natural LLM wording is required.",
            },
          ],
          error_type: null,
        },
      ],
    });
    renderQueryPage();

    fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
      target: { value: "alpha" },
    });
    fireEvent.click((await screen.findAllByText("source.txt"))[0]);
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    fireEvent.click(await screen.findByRole("button", { name: "View pathway" }));

    expect(await screen.findByRole("dialog", { name: "Query pathway" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Domain-aware" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Layout-aware" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Context-aware" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Raw traces" })).toBeVisible();
    expect(screen.getByText("Route plan", { selector: "summary" })).toBeVisible();
    expect(screen.getByText("Lane results", { selector: "summary" })).toBeVisible();
    expect(screen.queryByText("Planner", { selector: "summary" })).not.toBeInTheDocument();
    expect(screen.queryByText("Retrieval", { selector: "summary" })).not.toBeInTheDocument();
    expect(screen.queryByText("Answer", { selector: "summary" })).not.toBeInTheDocument();
    expect(screen.getByText("reference_heavy")).toBeVisible();
    expect(screen.getByText("postgres_canonical_evidence")).toBeVisible();
    expect(screen.getByText("metadata")).toBeVisible();
    expect(screen.getByText("metadata_lane_completed")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Layout-aware" }));
    expect(screen.getByText("Layout neighbors", { selector: "summary" })).toBeVisible();
    expect(screen.getByText("table-srg-001")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Context-aware" }));
    expect(screen.getByText("Context window", { selector: "summary" })).toBeVisible();
    expect(screen.getByText("Context assembly", { selector: "summary" })).toBeVisible();
    expect(screen.getByText("Reranker rank changes", { selector: "summary" })).toBeVisible();
    expect(screen.getAllByText(/parent_context/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("Reranker rank changes", { selector: "summary" }));
    expect(screen.getAllByText("chunk-25").length).toBeGreaterThan(0);
    expect(screen.getByText("2 -> 1")).toBeVisible();
    fireEvent.click(screen.getByText("Timeline", { selector: "summary" }));
    expect(screen.getByText("LLM planning")).toBeVisible();
    expect(screen.getAllByText("Input").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Action").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Output").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Diagnosis").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Suggested action").length).toBeGreaterThan(0);
    expect(screen.getAllByText("book:13:hadith:25").length).toBeGreaterThan(0);
    expect(screen.getByText("3000 ms / 3000 ms")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Raw traces" }));
    expect(screen.getByText("Raw traces", { selector: "summary" })).toBeVisible();
  });

  it("summarizes disabled reranker traces", async () => {
    vi.mocked(apiClient.query).mockResolvedValue({
      runs: [
        {
          id: "run-1",
          variant_id: "variant-1",
          experiment_id: null,
          query: "alpha",
          status: "succeeded",
          answer: "answer",
          sources: [],
          chunk_traces: [],
          timings: {},
          error: null,
          runtime_profile_id: null,
          document_ids: ["doc-1"],
          query_config: {},
          reranker_traces: [{ status: "disabled", provider: "disabled" }],
          token_metadata: {},
          error_type: null,
        },
      ],
    });
    renderQueryPage();

    fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
      target: { value: "alpha" },
    });
    fireEvent.click((await screen.findAllByText("source.txt"))[0]);
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(apiClient.query).toHaveBeenCalled());
    expect(await screen.findByText("Reranker disabled")).toBeVisible();
    expect(screen.getByText("disabled")).toBeVisible();
  });

  it("renders readable source rows and opens the evidence viewer", async () => {
    vi.mocked(apiClient.query).mockResolvedValue({
      runs: [
        {
          id: "run-1",
          variant_id: "variant-1",
          experiment_id: null,
          query: "alpha",
          status: "succeeded",
          answer: "answer",
          sources: [
            {
              id: "source-1",
              chunk_id: "chunk-1",
              document_id: "doc-1",
              document_name: "source.txt",
              text: "Book 1, Hadith 1",
              source_location: { page: 1, reference: "Book 1, Hadith 1" },
              metadata: { domain: "hadith" },
              parser_quality_warning_codes: ["reference_unit_missing_expected_script"],
              quality_action_policy: "materialize",
            },
          ],
          chunk_traces: [],
          timings: {},
          error: null,
          runtime_profile_id: "profile-1",
          document_ids: ["doc-1"],
          query_config: {},
          reranker_traces: [
            { status: "succeeded", provider: "generic_http", model: "rerank-model" },
          ],
          token_metadata: {},
          error_type: null,
        },
      ],
    });
    renderQueryPage();

    fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
      target: { value: "alpha" },
    });
    fireEvent.click((await screen.findAllByText("source.txt"))[0]);
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    expect(await screen.findByText("Readable sources")).toBeVisible();
    expect(screen.getByText("source-1")).toBeVisible();
    expect(screen.getAllByText("source.txt").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Inspect evidence" })).toBeVisible();
    expect(screen.getByText("Sources")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Inspect evidence" }));

    const dialog = await screen.findByRole("dialog", { name: "Evidence details" });
    expect(dialog).toBeVisible();
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveClass("fixed", "inset-0", "overflow-hidden", "sm:right-0");
    expect(screen.getAllByText("source-1").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("Reranker", { selector: "summary" }));
    expect(screen.getByText("Run-level reranker summary; not source-specific")).toBeVisible();
  });

  it("shows parser, quality, and source-location evidence details", async () => {
    vi.mocked(apiClient.query).mockResolvedValue({
      runs: [
        {
          id: "run-1",
          variant_id: "variant-1",
          experiment_id: null,
          query: "alpha",
          status: "succeeded",
          answer: "answer",
          sources: [
            {
              id: "source-1",
              chunk_id: "chunk-1",
              document_id: "doc-1",
              text: "Book 1, Hadith 1",
              source_location: {
                label: "source.txt · page 1",
                page_start: 1,
                page_end: 1,
                reference: "Book 1, Hadith 1",
              },
              parser_quality_warning_codes: ["reference_unit_missing_expected_script"],
              quality_action_policy: "materialize",
            },
          ],
          chunk_traces: [],
          timings: {},
          error: null,
          runtime_profile_id: "profile-1",
          document_ids: ["doc-1"],
          query_config: {},
          reranker_traces: [],
          token_metadata: {},
          error_type: null,
        },
      ],
    });
    renderQueryPage();

    fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
      target: { value: "alpha" },
    });
    fireEvent.click((await screen.findAllByText("source.txt"))[0]);
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    fireEvent.click(await screen.findByRole("button", { name: "Inspect evidence" }));

    expect(await screen.findByRole("dialog", { name: "Evidence details" })).toBeVisible();
    expect(screen.getByText("Source location", { selector: "summary" })).toBeVisible();
    expect(screen.getAllByText("source.txt · page 1").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("Parser quality", { selector: "summary" }));
    expect(screen.getByText("reference_unit_missing_expected_script")).toBeVisible();
    expect(screen.getAllByText("materialize").length).toBeGreaterThan(0);
  });

  it("derives evidence summary from nested metadata when root fields are absent", async () => {
    vi.mocked(apiClient.query).mockResolvedValue({
      runs: [
        {
          id: "run-1",
          variant_id: "variant-1",
          experiment_id: null,
          query: "alpha",
          status: "succeeded",
          answer: "answer",
          sources: [
            {
              chunk_id: "chunk-1",
              document_id: "doc-1",
              text: "Evidence text",
              source_location: { page_start: 412, page_end: 412 },
              metadata: {
                filename: "quran_arabic_english.pdf",
                index_shape: { runtime_profile_id: "default" },
                extraction_quality: {
                  parser_warnings: [
                    {
                      code: "recovered_text_from_misclassified_block",
                      quality_gate_action: "review_warning",
                    },
                  ],
                },
              },
            },
          ],
          chunk_traces: [],
          timings: {},
          error: null,
          runtime_profile_id: null,
          document_ids: ["doc-1"],
          query_config: {},
          reranker_traces: [],
          token_metadata: {},
          error_type: null,
        },
      ],
    });
    renderQueryPage();

    fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
      target: { value: "alpha" },
    });
    fireEvent.click((await screen.findAllByText("source.txt"))[0]);
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    expect(await screen.findByText("quran_arabic_english.pdf")).toBeVisible();
    expect(screen.getAllByText("412").length).toBeGreaterThan(0);
    expect(screen.getByText("1 parser warning: review_warning")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Inspect evidence" }));
    expect(await screen.findByRole("dialog", { name: "Evidence details" })).toBeVisible();
    expect(screen.getAllByText("default").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("Parser quality", { selector: "summary" }));
    expect(screen.getByText("recovered_text_from_misclassified_block")).toBeVisible();
  });

  it("shows explicit missing states and restores focus after Escape", async () => {
    vi.mocked(apiClient.query).mockResolvedValue({
      runs: [
        {
          id: "run-1",
          variant_id: "variant-1",
          experiment_id: null,
          query: "alpha",
          status: "succeeded",
          answer: "answer",
          sources: [{ id: "source-1" }],
          chunk_traces: [],
          timings: {},
          error: null,
          runtime_profile_id: null,
          document_ids: ["doc-1"],
          query_config: {},
          reranker_traces: [],
          token_metadata: {},
          error_type: null,
        },
      ],
    });
    renderQueryPage();

    fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
      target: { value: "alpha" },
    });
    fireEvent.click((await screen.findAllByText("source.txt"))[0]);
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    const inspect = await screen.findByRole("button", { name: "Inspect evidence" });
    inspect.focus();
    fireEvent.click(inspect);

    expect(await screen.findByRole("dialog", { name: "Evidence details" })).toBeVisible();
    expectVisibleText("No parser warnings for this evidence");
    expectVisibleText("Default quality policy");
    expectVisibleText("Source location not recorded");
    expectVisibleText("No graph relationship recorded for this evidence");
    fireEvent.click(screen.getByText("Route links", { selector: "summary" }));
    expectVisibleText("Document link not recorded");

    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Evidence details" })).not.toBeInTheDocument();
    });
    expect(inspect).toHaveFocus();
  });

  it("shows graph unavailable detail from selected evidence", async () => {
    vi.mocked(apiClient.query).mockResolvedValue({
      runs: [
        {
          id: "run-1",
          variant_id: "variant-1",
          experiment_id: null,
          query: "alpha",
          status: "succeeded",
          answer: "answer",
          sources: [{ id: "source-1", graph_unavailable_detail: "Graph projection is pending" }],
          chunk_traces: [],
          timings: {},
          error: null,
          runtime_profile_id: null,
          document_ids: ["doc-1"],
          query_config: {},
          reranker_traces: [],
          token_metadata: {},
          error_type: null,
        },
      ],
    });
    renderQueryPage();

    fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
      target: { value: "alpha" },
    });
    fireEvent.click((await screen.findAllByText("source.txt"))[0]);
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    fireEvent.click(await screen.findByRole("button", { name: "Inspect evidence" }));

    expect(await screen.findByRole("dialog", { name: "Evidence details" })).toBeVisible();
    fireEvent.click(screen.getByText("Graph context", { selector: "summary" }));
    expect(screen.getAllByText("Graph projection is pending").length).toBeGreaterThan(0);
  });
});

function expectVisibleText(text: string) {
  const visibleElement = screen.getAllByText(text).find((element) => {
    try {
      expect(element).toBeVisible();
      return true;
    } catch {
      return false;
    }
  });
  expect(visibleElement).toBeTruthy();
}
