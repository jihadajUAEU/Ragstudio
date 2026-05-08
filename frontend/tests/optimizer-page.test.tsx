import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OptimizerPage } from "../src/features/optimizer/optimizer-page";
import type { RunOut } from "../src/api/generated";

const apiMocks = vi.hoisted(() => ({
  runs: vi.fn(),
  variants: vi.fn(),
  optimize: vi.fn(),
}));

vi.mock("../src/api/client", () => ({
  apiClient: {
    runs: apiMocks.runs,
    variants: apiMocks.variants,
    optimize: apiMocks.optimize,
  },
}));

describe("OptimizerPage", () => {
  beforeEach(() => {
    apiMocks.runs.mockResolvedValue({ items: [], total: 0 });
    apiMocks.variants.mockResolvedValue({ items: [], total: 0 });
  });

  it("auto-fills the latest experiment id from recorded runs", async () => {
    apiMocks.runs.mockResolvedValue({
      items: [run("run-1", "experiment-123")],
      total: 1,
    });

    renderOptimizerPage();

    expect(await screen.findByDisplayValue("experiment-123")).toBeInTheDocument();
    expect(screen.getByText(/recent experiment:/i)).toBeInTheDocument();
  });
});

function renderOptimizerPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <OptimizerPage />
    </QueryClientProvider>,
  );
}

function run(id: string, experimentId: string): RunOut {
  return {
    id,
    variant_id: "variant-1",
    experiment_id: experimentId,
    query: `Query ${id}`,
    status: "succeeded",
    answer: "Answer",
    sources: [],
    chunk_traces: [],
    timings: {},
    error: null,
  };
}
