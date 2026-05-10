import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { apiClient } from "../src/api/client";
import type { DiagnosticsOut } from "../src/api/generated";
import { PipelineBuilder } from "../src/features/pipeline/pipeline-builder";

vi.mock("@xyflow/react", () => ({
  Background: () => null,
  Controls: () => null,
  Handle: () => null,
  MiniMap: () => null,
  Position: { Left: "left", Right: "right" },
  ReactFlow: ({
    nodes,
    children,
  }: {
    nodes: Array<{ id: string; data: { label: string; detail: string } }>;
    children: ReactNode;
  }) => (
    <div aria-label="RAG pipeline flow">
      {nodes.map((node) => (
        <div key={node.id}>
          <span>{node.data.label}</span>
          <span>{node.data.detail}</span>
        </div>
      ))}
      {children}
    </div>
  ),
}));

const defaultDiagnostics: DiagnosticsOut = {
  capabilities: {},
  dependency_status: {},
  warnings: [],
  runtime_mode: "runtime",
  overall_status: "ready",
  checks: [],
};

vi.mock("../src/api/client", () => ({
  apiClient: {
    diagnostics: vi.fn(),
    documents: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    graph: vi.fn().mockResolvedValue({ nodes: [], edges: [] }),
    runs: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    variants: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  },
}));

describe("PipelineBuilder", () => {
  function renderPipeline() {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <PipelineBuilder />
      </QueryClientProvider>,
    );
  }

  beforeEach(() => {
    vi.mocked(apiClient.diagnostics).mockResolvedValue(defaultDiagnostics);
  });

  it("renders the core RAG stages", async () => {
    renderPipeline();

    const flow = await screen.findByLabelText("RAG pipeline flow");
    expect(flow).toHaveTextContent("Documents");
    expect(flow).toHaveTextContent("Chunking");
    expect(flow).toHaveTextContent("Variants");
    expect(flow).toHaveTextContent("Retrieval");
    expect(flow).toHaveTextContent("Generation");
    expect(flow).toHaveTextContent("Graph");
    expect(flow).toHaveTextContent("Answer");
    expect(await screen.findByText("Read-only map")).toBeVisible();
  });

  it("shows workflow actions for pipeline stages", async () => {
    renderPipeline();

    expect(await screen.findByRole("link", { name: "Open Documents" })).toHaveAttribute("href", "/documents");
    expect(screen.getByRole("link", { name: "Open Chunks" })).toHaveAttribute("href", "/chunks");
    expect(screen.getByRole("link", { name: "Open Settings" })).toHaveAttribute("href", "/settings");
    expect(screen.getByRole("link", { name: "Open Variants" })).toHaveAttribute("href", "/variants");
    expect(screen.getByRole("link", { name: "Open Query" })).toHaveAttribute("href", "/query");
    expect(screen.getByRole("link", { name: "Open Graph" })).toHaveAttribute("href", "/graph");
    expect(screen.getByRole("link", { name: "Open Diagnostics" })).toHaveAttribute("href", "/diagnostics");
  });

  it("places blocking diagnostics beside affected stages", async () => {
    vi.mocked(apiClient.diagnostics).mockResolvedValue({
      ...defaultDiagnostics,
      overall_status: "failed",
      checks: [
        {
          name: "neo4j",
          status: "failed",
          severity: "blocking",
          detail: "Neo4j connectivity and authentication failed.",
        },
      ],
      warnings: ["Native RAG-Anything scoped query is unavailable for selected-document queries."],
    });

    renderPipeline();

    expect(await screen.findByText("Neo4j connectivity and authentication failed.")).toBeVisible();
    expect(screen.getByLabelText("Graph stage")).toHaveTextContent("Neo4j connectivity and authentication failed.");

    expect(screen.getByLabelText("Retrieval stage")).toHaveTextContent(
      "Native RAG-Anything scoped query is unavailable for selected-document queries.",
    );
  });
});
