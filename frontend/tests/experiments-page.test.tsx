import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../src/api/client";
import type { ExperimentOut, ExperimentSummaryOut } from "../src/api/generated";
import { ExperimentsPage } from "../src/features/experiments/experiments-page";

vi.mock("../src/api/client", () => ({
  DEFAULT_PARSER_MODE: "mineru_strict",
  FIRST_LIST_PAGE: { limit: 500, offset: 0 },
  apiClient: {
    documents: vi.fn(),
    variants: vi.fn(),
    evaluationSets: vi.fn(),
    experiments: vi.fn(),
    getExperiment: vi.fn(),
    createExperiment: vi.fn(),
  },
}));

describe("ExperimentsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-1",
          filename: "alpha.txt",
          content_type: "text/plain",
          sha256: "sha",
          status: "ready",
          latest_index_options: null,
        },
      ],
      total: 1,
    });
    vi.mocked(apiClient.variants).mockResolvedValue({
      items: [{ id: "variant-1", name: "Balanced", preset: "balanced", parameters: {} }],
      total: 1,
    });
    vi.mocked(apiClient.evaluationSets).mockResolvedValue({
      items: [
        {
          id: "eval-1",
          name: "Smoke cases",
          cases: [
            {
              id: "case-1",
              query: "alpha",
              documents: [],
              expected_answer: "alpha beta",
              expected_sources: [],
              must_include: [],
              must_avoid: [],
              expected_media: [],
              expected_structure: {},
              rubric: {},
              objective: {},
              variant_hints: {},
            },
          ],
        },
      ],
      total: 1,
    });
    vi.mocked(apiClient.experiments)
      .mockResolvedValueOnce({ items: [experimentSummary("experiment-old", "Prior experiment")], total: 1 })
      .mockResolvedValue({ items: [experimentSummary("experiment-new", "New experiment")], total: 1 });
    vi.mocked(apiClient.getExperiment).mockResolvedValue(
      experiment("experiment-old", "Prior experiment"),
    );
    vi.mocked(apiClient.createExperiment).mockResolvedValue(
      experiment("experiment-new", "New experiment"),
    );
  });

  it("requests the first page of documents and experiments", async () => {
    renderExperimentsPage();

    await waitFor(() => {
      expect(apiClient.documents).toHaveBeenCalledWith({ limit: 500, offset: 0 });
      expect(apiClient.experiments).toHaveBeenCalledWith({ limit: 500, offset: 0 });
    });
  });

  it("renders API-backed experiment history and refetches it after create", async () => {
    renderExperimentsPage();

    expect(await screen.findByText("Prior experiment")).toBeVisible();
    expect(screen.getByText("metric")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /^View$/i }));

    await waitFor(() => expect(apiClient.getExperiment).toHaveBeenCalledWith("experiment-old"));
    expect(await screen.findByText("experiment-old-run")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "New experiment" } });
    fireEvent.change(screen.getByLabelText("Evaluation set"), { target: { value: "eval-1" } });
    fireEvent.click(await screen.findByLabelText(/alpha\.txt/i));
    fireEvent.click(screen.getByLabelText(/Balanced/i));
    fireEvent.click(screen.getByRole("button", { name: /^Run$/i }));

    await waitFor(() => expect(apiClient.createExperiment).toHaveBeenCalled());
    await waitFor(() => expect(apiClient.experiments).toHaveBeenCalledTimes(2));
    expect(vi.mocked(apiClient.createExperiment).mock.calls[0][0]).toEqual({
      name: "New experiment",
      document_ids: ["doc-1"],
      evaluation_set_id: "eval-1",
      variant_ids: ["variant-1"],
      objective: { metric: "total" },
    });
    await waitFor(() => expect(screen.getAllByText("New experiment").length).toBeGreaterThan(0));
  });
});

function renderExperimentsPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ExperimentsPage />
    </QueryClientProvider>,
  );
}

function experiment(id: string, name: string): ExperimentOut {
  return {
    id,
    name,
    document_ids: ["doc-1"],
    evaluation_set_id: "eval-1",
    variant_ids: ["variant-1"],
    objective: { metric: "total" },
    runs: [
      {
        id: `${id}-run`,
        variant_id: "variant-1",
        experiment_id: id,
        query: "alpha",
        status: "succeeded",
        answer: "alpha beta",
        sources: [],
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
    scores: [
      {
        id: `${id}-score`,
        run_id: `${id}-run`,
        total: 100,
        details: { scoreable: true },
      },
    ],
  };
}

function experimentSummary(id: string, name: string): ExperimentSummaryOut {
  return {
    id,
    name,
    document_ids: ["doc-1"],
    evaluation_set_id: "eval-1",
    variant_ids: ["variant-1"],
    objective: { metric: "total" },
    run_count: 1,
    score_count: 1,
  };
}
