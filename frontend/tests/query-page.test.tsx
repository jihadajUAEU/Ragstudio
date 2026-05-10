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
});
