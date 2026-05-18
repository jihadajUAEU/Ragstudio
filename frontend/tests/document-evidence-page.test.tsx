import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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

function renderPage(path = "/document-evidence?documentId=doc-1") {
  window.history.pushState(null, "", path);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  return render(
    <QueryClientProvider client={client}>
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
});
