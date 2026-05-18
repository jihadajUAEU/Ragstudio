import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../src/api/client";
import { DocumentEvidencePage } from "../src/features/document-evidence/document-evidence-page";
import type { DocumentParseEvidence } from "../src/features/document-evidence/types";

vi.mock("../src/api/client", () => ({
  apiClient: {
    documentParseEvidence: vi.fn(),
  },
}));

const evidence: DocumentParseEvidence = {
  document: {
    id: "doc-1",
    filename: "synthetic.pdf",
    content_type: "application/pdf",
    status: "succeeded",
    parser_mode: "mineru_strict",
  },
  source_artifacts: [],
  parser_blocks: [],
  normalization_decisions: [
    {
      id: "decision-1",
      decision_type: "chunk_materialization",
      title: "Chunk materialization",
      summary: "Chunks were materialized.",
      input_block_ids: [],
      output_chunk_ids: ["chunk-1"],
      warning_ids: [],
      status: "recorded",
    },
  ],
  chunks: [
    {
      id: "chunk-1",
      text_preview: "Chunk text",
      source_location: {},
      metadata: {},
      warning_ids: [],
    },
  ],
  warnings: [],
  proof: {
    mode: "local",
    limitations: [],
    redaction_summary: [],
  },
  missing_sections: [],
};

function renderPage(path = "/document-evidence?documentId=doc-1", client?: QueryClient) {
  window.history.pushState(null, "", path);
  const queryClient = client ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });

  return render(
    <QueryClientProvider client={queryClient}>
      <DocumentEvidencePage />
    </QueryClientProvider>,
  );
}

describe("DocumentEvidencePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.documentParseEvidence).mockResolvedValue(evidence);
  });

  it("asks for a document id when missing", () => {
    renderPage("/document-evidence");

    expect(screen.getByText("Select a document")).toBeVisible();
    expect(apiClient.documentParseEvidence).not.toHaveBeenCalled();
  });

  it("shows a loading state while the evidence request is pending", () => {
    vi.mocked(apiClient.documentParseEvidence).mockReturnValue(new Promise(() => {}));

    renderPage();

    expect(screen.getByText("Loading evidence")).toBeVisible();
  });

  it("loads and renders document parse evidence", async () => {
    renderPage();

    expect(await screen.findByText("synthetic.pdf")).toBeVisible();
    expect(screen.getByRole("button", { name: /Chunk materialization/i })).toBeVisible();
    expect(apiClient.documentParseEvidence).toHaveBeenCalledWith("doc-1");
  });

  it("shows API errors", async () => {
    vi.mocked(apiClient.documentParseEvidence).mockRejectedValue(new Error("Document not found"));

    renderPage();

    expect(await screen.findByText("Document not found")).toBeVisible();
  });

  it("keeps cached evidence visible when a refetch fails", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["document-parse-evidence", "doc-1"], evidence);
    vi.mocked(apiClient.documentParseEvidence).mockRejectedValue(new Error("Backend timed out"));

    renderPage("/document-evidence?documentId=doc-1", client);

    expect(await screen.findByText("synthetic.pdf")).toBeVisible();
    expect(await screen.findByText("Showing cached evidence")).toBeVisible();
    expect(screen.getByText("Backend timed out")).toBeVisible();
    expect(screen.getByRole("button", { name: "Retry" })).toBeVisible();
  });

  it("resets the selected decision when the document changes on the same route", async () => {
    const firstEvidence: DocumentParseEvidence = {
      ...evidence,
      normalization_decisions: [
        {
          id: "decision-1",
          decision_type: "chunk_materialization",
          title: "Doc one first decision",
          summary: "First document first decision.",
          input_block_ids: [],
          output_chunk_ids: ["chunk-1"],
          warning_ids: [],
          status: "recorded",
        },
        {
          id: "decision-2",
          decision_type: "quality_warning",
          title: "Doc one second decision",
          summary: "First document second decision.",
          input_block_ids: [],
          output_chunk_ids: ["chunk-1"],
          warning_ids: [],
          status: "recorded",
        },
      ],
    };
    const secondEvidence: DocumentParseEvidence = {
      ...evidence,
      document: {
        ...evidence.document,
        id: "doc-2",
        filename: "second.pdf",
      },
      normalization_decisions: [
        {
          id: "decision-1",
          decision_type: "chunk_materialization",
          title: "Doc two first decision",
          summary: "Second document first decision.",
          input_block_ids: [],
          output_chunk_ids: ["chunk-1"],
          warning_ids: [],
          status: "recorded",
        },
        {
          id: "decision-2",
          decision_type: "quality_warning",
          title: "Doc two second decision",
          summary: "Second document second decision.",
          input_block_ids: [],
          output_chunk_ids: ["chunk-1"],
          warning_ids: [],
          status: "recorded",
        },
      ],
    };
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.mocked(apiClient.documentParseEvidence).mockImplementation((documentId) =>
      Promise.resolve(documentId === "doc-2" ? secondEvidence : firstEvidence),
    );
    const view = () => (
      <QueryClientProvider client={client}>
        <DocumentEvidencePage />
      </QueryClientProvider>
    );

    window.history.pushState(null, "", "/document-evidence?documentId=doc-1");
    const { rerender } = render(view());
    fireEvent.click(await screen.findByRole("button", { name: /Doc one second decision/i }));
    expect(screen.getByRole("button", { name: /Doc one second decision/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    window.history.pushState(null, "", "/document-evidence?documentId=doc-2");
    rerender(view());

    expect(await screen.findByText("second.pdf")).toBeVisible();
    expect(screen.getByRole("button", { name: /Doc two first decision/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: /Doc two second decision/i })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});
