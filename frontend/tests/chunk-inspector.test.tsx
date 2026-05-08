import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChunkInspector } from "../src/features/chunks/chunk-inspector";

vi.mock("../src/api/client", () => ({
  apiClient: {
    documents: vi.fn().mockResolvedValue({
      items: [{ id: "doc-1", filename: "hadith.pdf", status: "ready" }],
      total: 1,
    }),
    domainProfiles: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    indexDocumentChunks: vi.fn(),
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
            domain_metadata: { domain: "hadith" },
            parser_metadata: { backend: "mineru" },
          },
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
});
