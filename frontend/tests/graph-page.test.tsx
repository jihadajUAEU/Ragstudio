import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../src/api/client";
import { GraphPage } from "../src/features/graph/graph-page";

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
});
