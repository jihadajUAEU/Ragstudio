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
        "Graph is unavailable because fallback mode uses the local placeholder adapter.",
      ],
      runtime_mode: "fallback",
      overall_status: "fallback",
      checks: [],
    });
  });

  it("shows the diagnostics reason when graph capability is disabled", async () => {
    renderGraphPage();

    expect(await screen.findByText("Graph unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("Graph is unavailable because fallback mode uses the local placeholder adapter."),
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

  it("renders returned graph data when diagnostics marks graph unavailable", async () => {
    vi.mocked(apiClient.graph).mockResolvedValue({
      nodes: [
        {
          id: "fallback-chunk",
          labels: ["FallbackRelationship"],
          properties: { label: "Runtime chunk", document_id: "doc-1", page: 7 },
        },
        { id: "topic-runtime", label: "Runtime fallback", type: "topic" },
      ],
      edges: [{ source: "fallback-chunk", target: "topic-runtime", type: "mentions" }],
    });

    renderGraphPage();

    const map = await screen.findByLabelText("Graph relationship map");
    expect(map).toHaveTextContent("Runtime chunk");
    expect(map).toHaveTextContent("FallbackRelationship");
    expect(screen.queryByText("Graph unavailable")).not.toBeInTheDocument();
  });
});
