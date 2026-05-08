import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

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

vi.mock("../src/api/client", () => ({
  apiClient: {
    diagnostics: vi.fn().mockResolvedValue({
      capabilities: {},
      dependency_status: {},
      warnings: [],
      runtime_mode: "runtime",
      overall_status: "ready",
      checks: [],
    }),
    documents: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    graph: vi.fn().mockResolvedValue({ nodes: [], edges: [] }),
    runs: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    variants: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  },
}));

describe("PipelineBuilder", () => {
  it("renders the core RAG stages", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <PipelineBuilder />
      </QueryClientProvider>,
    );

    const flow = await screen.findByLabelText("RAG pipeline flow");
    expect(flow).toHaveTextContent("Documents");
    expect(flow).toHaveTextContent("Chunking");
    expect(flow).toHaveTextContent("Variants");
    expect(flow).toHaveTextContent("Retrieval");
    expect(flow).toHaveTextContent("Generation");
    expect(flow).toHaveTextContent("Graph");
    expect(flow).toHaveTextContent("Answer");
  });
});
