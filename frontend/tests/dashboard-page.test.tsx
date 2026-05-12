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

const jobDefaults = {
  worker_id: null,
  lease_expires_at: null,
  heartbeat_at: null,
  attempts: 0,
  max_attempts: 3,
  recovery_action: null,
};

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
            ...jobDefaults,
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
            ...jobDefaults,
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

  it("does not show empty dashboard tables while data is still loading", () => {
    vi.mocked(apiClient.health).mockReturnValue(new Promise(() => undefined));
    vi.mocked(apiClient.documents).mockReturnValue(new Promise(() => undefined));

    renderDashboardPage();

    expect(screen.getByText("Checking")).toBeVisible();
    expect(screen.getAllByText("Loading").length).toBeGreaterThan(0);
    expect(screen.queryByText("No documents indexed")).not.toBeInTheDocument();
  });

  it("shows a section error instead of an empty table when a dashboard query fails", async () => {
    vi.mocked(apiClient.documents).mockRejectedValueOnce(new Error("documents failed"));

    renderDashboardPage();

    expect(await screen.findByText("Data unavailable")).toBeVisible();
    expect(screen.getByText("documents failed")).toBeVisible();
    expect(screen.queryByText("No documents indexed")).not.toBeInTheDocument();
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
