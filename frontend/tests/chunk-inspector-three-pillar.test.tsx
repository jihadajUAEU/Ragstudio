import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../src/api/client";
import { ChunkInspector } from "../src/features/chunks/chunk-inspector";

vi.mock("../src/api/client", () => ({
  DEFAULT_PARSER_MODE: "mineru_strict",
  apiClient: {
    documents: vi.fn(),
    domainProfiles: vi.fn(),
    searchChunks: vi.fn(),
    createDocumentReindexJob: vi.fn(),
  },
}));

function renderChunkInspector() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ChunkInspector />
    </QueryClientProvider>,
  );
}

describe("ChunkInspector three-pillar metadata", () => {
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
    vi.mocked(apiClient.domainProfiles).mockResolvedValue({ items: [] });
    vi.mocked(apiClient.searchChunks).mockResolvedValue({
      items: [
        {
          id: "chunk-1",
          document_id: "doc-1",
          runtime_profile_id: "default",
          text: "Evidence text",
          source_location: { page_start: 1, page_end: 1 },
          metadata: {
            score: 0.91,
            domain_metadata: { domain: "hadith" },
            quality_action_policy: "materialize",
            materialization_hint: "graph",
            layout_group_id: "table-srg-001",
            layout_role: "table_cell",
            reading_order: 12,
            parent_chunk_id: "chunk-parent",
            previous_chunk_id: "chunk-prev",
            next_chunk_id: "chunk-next",
          },
          content_type: "text",
          relationship_refs: {},
        },
      ],
      total: 1,
    });
  });

  it("shows layout and context metadata outside raw JSON", async () => {
    renderChunkInspector();

    fireEvent.change(await screen.findByPlaceholderText("12:13"), { target: { value: "alpha" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(apiClient.searchChunks).toHaveBeenCalled());
    fireEvent.click(await screen.findByRole("button", { name: "Preview" }));

    expect(screen.getByText("Layout group")).toBeVisible();
    expect(screen.getByText("table-srg-001")).toBeVisible();
    expect(screen.getByText("Reading order")).toBeVisible();
    expect(screen.getByText("12")).toBeVisible();
    expect(screen.getByText("Parent")).toBeVisible();
    expect(screen.getByText("chunk-parent")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Inspect" }));
    fireEvent.click(await screen.findByText("Context chain", { selector: "summary" }));
    expect(screen.getAllByText("chunk-next").length).toBeGreaterThan(0);
  });
});
