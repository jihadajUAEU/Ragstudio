import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ComparisonPage } from "../src/features/comparison/comparison-page";
import type { RunOut } from "../src/api/generated";

const apiMocks = vi.hoisted(() => ({
  runs: vi.fn(),
  variants: vi.fn(),
}));

vi.mock("../src/api/client", () => ({
  apiClient: {
    runs: apiMocks.runs,
    variants: apiMocks.variants,
  },
}));

describe("ComparisonPage", () => {
  beforeEach(() => {
    apiMocks.runs.mockResolvedValue({ items: [], total: 0 });
    apiMocks.variants.mockResolvedValue({ items: [], total: 0 });
  });

  it("renders the heading", () => {
    renderComparisonPage();

    expect(screen.getByRole("heading", { name: /run comparison/i })).toBeInTheDocument();
  });

  it("shows no-selection state after the user clears the default comparison", async () => {
    apiMocks.runs.mockResolvedValue({
      items: [run("run-1", "First answer"), run("run-2", "Second answer")],
      total: 2,
    });

    renderComparisonPage();

    expect(await screen.findByText("First answer")).toBeInTheDocument();
    expect(screen.getByText("Second answer")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Compare run run-1"));
    fireEvent.click(screen.getByLabelText("Compare run run-2"));

    await waitFor(() => {
      expect(screen.getByText("No runs selected")).toBeInTheDocument();
    });
    expect(screen.queryByText("First answer")).not.toBeInTheDocument();
    expect(screen.queryByText("Second answer")).not.toBeInTheDocument();
  });
});

function renderComparisonPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ComparisonPage />
    </QueryClientProvider>,
  );
}

function run(id: string, answer: string): RunOut {
  return {
    id,
    variant_id: "variant-1",
    query: `Query ${id}`,
    status: "succeeded",
    answer,
    sources: [],
    chunk_traces: [],
    timings: {},
    error: null,
  };
}
