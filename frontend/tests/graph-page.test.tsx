import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
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
    edges,
    children,
  }: {
    nodes: Array<{ id: string; data: { label: string; type: string; detail: string } }>;
    edges: Array<{ id: string; label?: string; source: string; target: string }>;
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
      {edges.map((edge) => (
        <div key={edge.id}>
          <span>{edge.id}</span>
          <span>{edge.label}</span>
          <span>{edge.source}</span>
          <span>{edge.target}</span>
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

  it("filters the graph map by node type", async () => {
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
        { id: "verse-1", labels: ["Reference"], properties: { label: "2:255" } },
        { id: "topic-1", labels: ["Topic"], properties: { label: "Throne Verse" } },
      ],
      edges: [{ source: "verse-1", target: "topic-1", type: "mentions" }],
    });

    renderGraphPage();

    fireEvent.change(await screen.findByLabelText("Node type"), {
      target: { value: "Reference" },
    });

    const map = await screen.findByLabelText("Graph relationship map");
    expect(map).toHaveTextContent("2:255");
    expect(map).not.toHaveTextContent("Throne Verse");
    expect(screen.getByText("Visible nodes")).toBeInTheDocument();
  });

  it("filters duplicate-endpoint edges by document id from edge properties", async () => {
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
        { id: "verse-1", labels: ["Reference"], properties: { label: "2:255" } },
        { id: "topic-1", labels: ["Topic"], properties: { label: "Throne Verse" } },
        { id: "topic-2", labels: ["Topic"], properties: { label: "Different Topic" } },
      ],
      edges: [
        { id: "edge-doc-7", source: "verse-1", target: "topic-1", type: "mentions", properties: { document_ids: ["doc-7"] } },
        { id: "edge-doc-9", source: "verse-1", target: "topic-1", type: "related", properties: { document_ids: ["doc-9"] } },
        { id: "edge-other", source: "topic-1", target: "topic-2", type: "related", properties: { document_ids: ["doc-9"] } },
      ],
    });

    renderGraphPage();

    fireEvent.change(await screen.findByLabelText("Document id"), {
      target: { value: "doc-7" },
    });

    const map = await screen.findByLabelText("Graph relationship map");
    expect(map).toHaveTextContent("2:255");
    expect(map).toHaveTextContent("Throne Verse");
    expect(map).toHaveTextContent("edge-doc-7");
    expect(map).not.toHaveTextContent("edge-doc-9");
    expect(map).not.toHaveTextContent("edge-other");
    expect(map).not.toHaveTextContent("Different Topic");
  });

  it("resolves edge endpoints from properties", async () => {
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
        { id: "source-node", labels: ["Reference"], properties: { label: "Source ref" } },
        { id: "target-node", labels: ["Topic"], properties: { label: "Target topic" } },
      ],
      edges: [
        {
          id: "property-edge",
          type: "mentions",
          properties: { source: "source-node", target: "target-node", document_id: "doc-props" },
        },
      ],
    });

    renderGraphPage();

    const map = await screen.findByLabelText("Graph relationship map");
    expect(map).toHaveTextContent("Source ref");
    expect(map).toHaveTextContent("Target topic");
    expect(map).toHaveTextContent("property-edge");
    expect(map).toHaveTextContent("mentions");
  });

  it("filters by reference search, shows no-match state, and resets", async () => {
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
        { id: "verse-1", labels: ["Reference"], properties: { label: "2:255", page: 12 } },
        { id: "topic-1", labels: ["Topic"], properties: { label: "Throne Verse" } },
      ],
      edges: [
        {
          id: "edge-page-12",
          source: "verse-1",
          target: "topic-1",
          type: "mentions",
          properties: { reference: "2:255", page: 12 },
        },
      ],
    });

    renderGraphPage();

    const search = await screen.findByLabelText("Page or reference");
    fireEvent.change(search, { target: { value: "2:255" } });

    let map = await screen.findByLabelText("Graph relationship map");
    expect(map).toHaveTextContent("2:255");
    expect(map).toHaveTextContent("edge-page-12");

    fireEvent.change(search, { target: { value: "missing reference" } });

    expect(await screen.findByText("No graph matches")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Reset"));

    map = await screen.findByLabelText("Graph relationship map");
    expect(map).toHaveTextContent("Throne Verse");
    expect(map).toHaveTextContent("edge-page-12");
  });
});
