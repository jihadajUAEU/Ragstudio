import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../src/api/client";
import { DashboardPage } from "../src/features/dashboard/dashboard-page";

vi.mock("../src/api/client", () => ({
  DEFAULT_PARSER_MODE: "mineru_strict",
  apiClient: {
    health: vi.fn(),
    documents: vi.fn(),
    jobs: vi.fn(),
    variants: vi.fn(),
    runs: vi.fn(),
    diagnostics: vi.fn(),
    graph: vi.fn(),
  },
}));

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.health).mockResolvedValue({ status: "ok", service: "ragstudio-api" });
    vi.mocked(apiClient.documents).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.jobs).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.variants).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.runs).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.diagnostics).mockResolvedValue({
      capabilities: {},
      dependency_status: {},
      warnings: [],
      runtime_mode: "runtime",
      overall_status: "ready",
      checks: [],
    });
    vi.mocked(apiClient.graph).mockResolvedValue({ nodes: [], edges: [] });
  });

  it("polls jobs and refreshes documents once jobs complete", async () => {
    vi.useFakeTimers();
    vi.mocked(apiClient.jobs)
      .mockResolvedValueOnce({
        items: [
          {
            id: "job-1",
            type: "index_document",
            status: "running",
            target_id: "doc-1",
            progress: 10,
            logs: [],
            result: {},
          },
        ],
        total: 1,
      })
      .mockResolvedValue({
        items: [
          {
            id: "job-1",
            type: "index_document",
            status: "succeeded",
            target_id: "doc-1",
            progress: 100,
            logs: [],
            result: {},
          },
        ],
        total: 1,
      });

    try {
      renderDashboardPage();

      await vi.waitFor(() => {
        expect(apiClient.jobs).toHaveBeenCalledTimes(1);
        expect(apiClient.documents).toHaveBeenCalledTimes(1);
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });

      await vi.waitFor(() => {
        expect(apiClient.jobs).toHaveBeenCalledTimes(2);
      });
      await vi.waitFor(() => {
        expect(apiClient.documents).toHaveBeenCalledTimes(3);
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows per-query loading states instead of empty document and job tables", async () => {
    vi.mocked(apiClient.documents).mockReturnValue(new Promise<never>(() => undefined));
    vi.mocked(apiClient.jobs).mockReturnValue(new Promise<never>(() => undefined));

    renderDashboardPage();

    expect(screen.getByText("Loading documents")).toBeVisible();
    expect(screen.getByText("Loading jobs")).toBeVisible();
    expect(screen.queryByText("No documents indexed")).not.toBeInTheDocument();
    expect(screen.queryByText("No jobs running")).not.toBeInTheDocument();
  });

  it("shows per-query errors instead of false empty document and job tables", async () => {
    vi.mocked(apiClient.documents).mockRejectedValue(new Error("Documents request failed"));
    vi.mocked(apiClient.jobs).mockRejectedValue(new Error("Jobs request failed"));

    renderDashboardPage();

    expect(await screen.findByText("Documents unavailable")).toBeVisible();
    expect(screen.getByText("Documents request failed")).toBeVisible();
    expect(await screen.findByText("Jobs unavailable")).toBeVisible();
    expect(screen.getByText("Jobs request failed")).toBeVisible();
    expect(screen.queryByText("No documents indexed")).not.toBeInTheDocument();
    expect(screen.queryByText("No jobs running")).not.toBeInTheDocument();
  });
});

function renderDashboardPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <DashboardPage />
    </QueryClientProvider>,
  );
}
