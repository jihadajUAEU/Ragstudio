import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { apiClient } from "../src/api/client";
import { GraphPage } from "../src/features/graph/graph-page";

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
    nodes: Array<{ id: string; data: { label: string; type: string; detail: string } }>;
    children: ReactNode;
  }) => (
    <div aria-label="Graph relationship map">
      {nodes.map((node) => (
        <div key={node.id}>
          <span>{node.data.label}</span>
          <span>{node.data.type}</span>
          <span>{node.data.detail}</span>
        </div>
      ))}
      {children}
    </div>
  ),
}));

vi.mock("../src/api/client", () => ({
  DEFAULT_PARSER_MODE: "mineru_strict",
  apiClient: {
    diagnostics: vi.fn(),
    graph: vi.fn(),
  },
}));

function renderGraphPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={queryClient}>
      <GraphPage />
    </QueryClientProvider>,
  );
}

describe("GraphPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.graph).mockResolvedValue({ nodes: [], edges: [] });
    vi.mocked(apiClient.diagnostics).mockResolvedValue({
      capabilities: { graph: false },
      dependency_status: {},
      warnings: [
        "Graph is unavailable because the runtime graph is not ready.",
      ],
      runtime_mode: "runtime",
      overall_status: "failed",
      checks: [],
    });
  });

  it("shows the diagnostics reason when graph capability is disabled", async () => {
    renderGraphPage();

    expect(await screen.findByText("Graph unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("Graph is unavailable because the runtime graph is not ready."),
    ).toBeInTheDocument();
  });

  it("renders a relationship map when graph data is available", async () => {
    vi.mocked(apiClient.diagnostics).mockResolvedValue({
      capabilities: { graph: true },
      dependency_status: {},
      warnings: [],
      runtime_mode: "runtime",
      overall_status: "ready",
      checks: [],
    });
    vi.mocked(apiClient.graph).mockResolvedValue({
      nodes: [
        {
          id: "verse-1",
          labels: ["Reference"],
          properties: { label: "2:255", document_id: "doc-1", page: 12 },
        },
        { id: "topic-1", label: "Throne Verse", type: "topic" },
      ],
      edges: [{ source: "verse-1", target: "topic-1", type: "mentions" }],
    });

    renderGraphPage();

    const map = await screen.findByLabelText("Graph relationship map");
    expect(map).toHaveTextContent("2:255");
    expect(map).toHaveTextContent("Reference");
    expect(map).toHaveTextContent("document doc-1");
  });

  it("shows graph detail returned by the backend", async () => {
    vi.mocked(apiClient.diagnostics).mockResolvedValue({
      capabilities: { graph: true },
      dependency_status: {},
      warnings: [],
      runtime_mode: "runtime",
      overall_status: "failed",
      checks: [],
    });
    vi.mocked(apiClient.graph).mockResolvedValue({
      nodes: [],
      edges: [],
      detail: "No runtime graph or relationship metadata is available.",
    });

    renderGraphPage();

    expect(
      await screen.findByText("No runtime graph or relationship metadata is available."),
    ).toBeInTheDocument();
  });

  it("shows a prominent visual preview truncation warning", async () => {
    vi.mocked(apiClient.diagnostics).mockResolvedValue({
      capabilities: { graph: true },
      dependency_status: {},
      warnings: [],
      runtime_mode: "runtime",
      overall_status: "ready",
      checks: [],
    });
    const nodes = Array.from({ length: 51 }, (_, index) => ({
      id: `node-${index + 1}`,
      label: `Node ${index + 1}`,
    }));
    const edges = [
      ...Array.from({ length: 49 }, (_, index) => ({
        source: `node-${index + 1}`,
        target: `node-${index + 2}`,
        type: "related",
      })),
      { source: "node-1", target: "node-51", type: "outside-preview" },
    ];
    vi.mocked(apiClient.graph).mockResolvedValue({ nodes, edges });

    renderGraphPage();

    expect(
      await screen.findByText(
        "Showing 50 of 51 nodes and 49 of 50 edges in the visual preview.",
      ),
    ).toBeInTheDocument();
  });
});
