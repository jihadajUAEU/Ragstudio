import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChunkInspector } from "../src/features/chunks/chunk-inspector";

vi.mock("../src/api/client", () => ({
  apiClient: {
    documents: vi.fn().mockResolvedValue({
      items: [
        {
          id: "doc-1",
          filename: "hadith.pdf",
          content_type: "application/pdf",
          status: "ready",
          sha256: "sha",
        },
      ],
      total: 1,
    }),
    domainProfiles: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    createDocumentReindexJob: vi.fn(),
    searchChunks: vi.fn().mockResolvedValue({
      total: 1,
      items: [
        {
          id: "chunk-1",
          document_id: "doc-1",
          text: "Book 1, Hadith 1",
          source_location: { page: 1 },
          metadata: {
            score: 1,
            mirrored_snapshot: true,
            domain_metadata: { domain: "hadith" },
            parser_metadata: { backend: "mineru" },
            retrieval_explain: {
              query_reference: "sahih-bukhari:1",
              matched_references: ["book-1", "hadith-1"],
              relationship_refs: { collection: "sahih-bukhari", neighbor: "chunk-2" },
              signals: [
                { name: "semantic", value: 0.92 },
                { name: "reference", value: 1 },
              ],
            },
          },
          runtime_profile_id: "default",
          runtime_source_id: "runtime-chunk-1",
          content_type: "text",
          preview_ref: null,
          indexed_at: "2026-05-08T00:00:00Z",
        },
      ],
    }),
  },
}));

describe("ChunkInspector metadata", () => {
  it("renders parser controls", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ChunkInspector />
      </QueryClientProvider>,
    );

    expect(await screen.findByLabelText("Parser")).toBeVisible();
    expect(screen.getByLabelText("Domain profile")).toBeVisible();
  });

  it("shows mirrored chunk runtime badges", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ChunkInspector />
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.change(screen.getByLabelText("Question or search text"), {
      target: { value: "hadith" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Search$/i }));

    expect(await screen.findByText("profile default")).toBeVisible();
    expect(screen.getByText("snapshot true")).toBeVisible();
  });

  it("renders retrieval explain details after search", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ChunkInspector />
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.change(screen.getByLabelText("Question or search text"), {
      target: { value: "hadith" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Search$/i }));

    expect(await screen.findByRole("region", { name: "Retrieval explain" })).toBeVisible();
    expect(screen.getByText("query sahih-bukhari:1")).toBeVisible();
    expect(screen.getByText("book-1")).toBeVisible();
    expect(screen.getByText("hadith-1")).toBeVisible();
    expect(screen.getByText("collection: sahih-bukhari")).toBeVisible();
    expect(screen.getByText("neighbor: chunk-2")).toBeVisible();
    expect(screen.getByText("semantic: 0.92")).toBeVisible();
    expect(screen.getByText("reference: 1.00")).toBeVisible();
  });
});
