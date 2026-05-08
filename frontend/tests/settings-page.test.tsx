import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SettingsPage } from "../src/features/settings/settings-page";

vi.mock("../src/api/client", () => ({
  apiClient: {
    defaultSettings: vi.fn().mockResolvedValue({
      provider: "openai",
      llm_model: "gpt-4.1",
      embedding_model: "text-embedding-3-large",
      storage_backend: "local",
      embedding_provider: "fallback",
      embedding_base_url: "",
      embedding_timeout_ms: 10000,
      embedding_dimensions: 1536,
      embedding_batch_size: 16,
      embedding_tls_verify: true,
      has_embedding_api_key: false,
      mineru_enabled: true,
      mineru_base_url: "http://127.0.0.1:8765",
      mineru_timeout_ms: 1800000,
      mineru_poll_interval_ms: 1000,
    }),
    updateDefaultSettings: vi.fn(),
    testEmbeddingSettings: vi.fn(),
    testMinerUSettings: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status = 500;
  },
}));

describe("SettingsPage MinerU", () => {
  it("renders MinerU parser settings", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <SettingsPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("MinerU parser")).toBeVisible();
    expect(await screen.findByDisplayValue("http://127.0.0.1:8765")).toBeVisible();
    expect(screen.getByRole("button", { name: /Test MinerU/i })).toBeVisible();
  });
});
