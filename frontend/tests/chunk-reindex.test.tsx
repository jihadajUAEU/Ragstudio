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
    createDocumentReindexJob: vi.fn(),
    searchChunks: vi.fn(),
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

describe("ChunkInspector reindex jobs", () => {
  beforeEach(() => {
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-1",
          filename: "quran_arabic_english.pdf",
          content_type: "application/pdf",
          status: "ready",
          sha256: "sha",
        },
      ],
      total: 1,
    });
    vi.mocked(apiClient.domainProfiles).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.createDocumentReindexJob).mockResolvedValue({
      document_id: "doc-1",
      job_id: "job-1",
      status: "ready",
    });
  });

  it("schedules a strict MinerU reindex job", async () => {
    renderChunkInspector();

    fireEvent.change(await screen.findByLabelText("Parser"), {
      target: { value: "mineru_strict" },
    });
    fireEvent.click(screen.getByRole("button", { name: /index/i }));

    await waitFor(() => {
      expect(apiClient.createDocumentReindexJob).toHaveBeenCalledWith("doc-1", {
        parser_mode: "mineru_strict",
        domain_metadata: { domain: "generic", document_type: "document", tags: [] },
      });
    });
    expect(await screen.findByText("Index job queued: job-1")).toBeVisible();
  });
});
