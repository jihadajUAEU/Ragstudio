import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../src/api/client";
import { PipelineBuilder } from "../src/features/pipeline/pipeline-builder";

vi.mock("@xyflow/react", () => ({
  Background: () => <div>Background</div>,
  Controls: () => <div>Controls</div>,
  Handle: () => null,
  MiniMap: () => <div>MiniMap</div>,
  Position: { Left: "left", Right: "right" },
  ReactFlow: ({ nodes }: { nodes: Array<{ data: { label: string; detail: string } }> }) => (
    <div aria-label="RAG pipeline flow">
      {nodes.map((node) => (
        <section key={node.data.label}>
          <h3>{node.data.label}</h3>
          <p>{node.data.detail}</p>
        </section>
      ))}
    </div>
  ),
}));

vi.mock("../src/api/client", () => ({
  apiClient: {
    documents: vi.fn(),
    variants: vi.fn(),
    runs: vi.fn(),
    graph: vi.fn(),
    diagnostics: vi.fn(),
  },
}));

function renderPipeline() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <PipelineBuilder />
    </QueryClientProvider>,
  );
}

describe("PipelineBuilder", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.documents).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.variants).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.runs).mockResolvedValue({
      items: [],
      total: 0,
      limit: 100,
      offset: 0,
      has_more: false,
    });
    vi.mocked(apiClient.graph).mockResolvedValue({ nodes: [], edges: [] });
    vi.mocked(apiClient.diagnostics).mockResolvedValue({
      capabilities: {},
      dependency_status: {},
      warnings: [],
      runtime_mode: "runtime",
      overall_status: "ready",
      checks: [],
    });
  });

  it("shows the three-pillar retrieval architecture as first-class stages", async () => {
    renderPipeline();

    expect(await screen.findAllByText("Domain resolver")).toHaveLength(2);
    expect(screen.getAllByText("Quality gate")).toHaveLength(2);
    expect(screen.getAllByText("Route planner")).toHaveLength(2);
    expect(screen.getAllByText("Layout neighbors")).toHaveLength(2);
    expect(screen.getAllByText("Context window")).toHaveLength(2);
    expect(screen.getAllByText("Context assembly")).toHaveLength(2);
  });
});
