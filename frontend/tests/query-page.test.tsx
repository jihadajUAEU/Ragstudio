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
  });

  it("summarizes reranker status outside raw JSON", async () => {
    renderQueryPage();

    fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
      target: { value: "alpha" },
    });
    fireEvent.click(await screen.findByText("source.txt"));
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(apiClient.query).toHaveBeenCalled());
    expect(await screen.findByText("Reranker failed")).toBeVisible();
    expect(screen.getByText("generic_http · ConnectError")).toBeVisible();
  });

  it("runs fast evidence mode by default", async () => {
    renderQueryPage();

    expect(await screen.findByRole("button", { name: "Fast evidence" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Full answer" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
      target: { value: "alpha" },
    });
    fireEvent.click(await screen.findByText("source.txt"));
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(apiClient.query).toHaveBeenCalled());
    expect(vi.mocked(apiClient.query).mock.calls[0][0]).toEqual(
      expect.objectContaining({
        response_mode: "fast",
        answer_budget_ms: 1000,
        response_budget_ms: 8000,
      }),
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
    fireEvent.click(await screen.findByText("source.txt"));
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    expect(await screen.findByText("Evidence-first result")).toBeVisible();
    expect(screen.getByText("LLM wording exceeded the fast budget.")).toBeVisible();
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
    fireEvent.click(await screen.findByText("source.txt"));
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
    fireEvent.click(await screen.findByText("source.txt"));
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    expect(await screen.findByText("Readable sources")).toBeVisible();
    expect(screen.getByText("source-1")).toBeVisible();
    expect(screen.getAllByText("source.txt").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Inspect evidence" })).toBeVisible();
    expect(screen.getByText("Sources")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Inspect evidence" }));

    expect(await screen.findByRole("dialog", { name: "Evidence details" })).toBeVisible();
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
              source_location: { page: 1, reference: "Book 1, Hadith 1" },
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
    fireEvent.click(await screen.findByText("source.txt"));
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    fireEvent.click(await screen.findByRole("button", { name: "Inspect evidence" }));

    expect(await screen.findByRole("dialog", { name: "Evidence details" })).toBeVisible();
    expect(screen.getByText("Source location", { selector: "summary" })).toBeVisible();
    fireEvent.click(screen.getByText("Parser quality", { selector: "summary" }));
    expect(screen.getByText("reference_unit_missing_expected_script")).toBeVisible();
    expect(screen.getAllByText("materialize").length).toBeGreaterThan(0);
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
    fireEvent.click(await screen.findByText("source.txt"));
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    const inspect = await screen.findByRole("button", { name: "Inspect evidence" });
    inspect.focus();
    fireEvent.click(inspect);

    expect(await screen.findByRole("dialog", { name: "Evidence details" })).toBeVisible();
    expectVisibleText("Parser warnings not recorded");
    expectVisibleText("Quality policy not recorded");
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
    fireEvent.click(await screen.findByText("source.txt"));
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
