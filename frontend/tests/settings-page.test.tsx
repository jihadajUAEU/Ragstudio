import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../src/api/client";
import { SettingsPage } from "../src/features/settings/settings-page";

vi.mock("../src/api/client", () => ({
  apiClient: {
    defaultSettings: vi.fn(),
    updateDefaultSettings: vi.fn(),
    testEmbeddingSettings: vi.fn(),
    testMinerUSettings: vi.fn(),
    testLlmSettings: vi.fn(),
    syncProviderPreview: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status = 500;
  },
}));

const settings = {
  id: "default",
  provider: "openai",
  llm_provider: "openai_compatible",
  llm_model: "gpt-4.1",
  llm_base_url: "",
  llm_timeout_ms: 10000,
  llm_capabilities: [],
  has_llm_api_key: false,
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
};

function renderSettings() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <SettingsPage />
    </QueryClientProvider>,
  );
}

describe("SettingsPage provider sync", () => {
  beforeEach(() => {
    vi.mocked(apiClient.defaultSettings).mockResolvedValue(settings);
    vi.mocked(apiClient.updateDefaultSettings).mockResolvedValue(settings);
    vi.mocked(apiClient.syncProviderPreview).mockResolvedValue({
      ok: true,
      manifest_url: "https://updates.jihadaj.com/providers.json",
      manifest_version: 2,
      updated_at: "2026-05-07T08:23:27.928Z",
      patch: {
        llm_provider: "openai_compatible",
        llm_base_url: "http://10.10.9.195:8004/v1",
        llm_model: "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
        llm_timeout_ms: 5000,
        llm_capabilities: ["text", "vision", "reasoning"],
        embedding_provider: "vllm_openai",
        embedding_base_url: "http://10.10.9.192:8001/v1",
        embedding_model: "Qwen/Qwen3-Embedding-8B",
        embedding_dimensions: 1536,
        embedding_timeout_ms: 10000,
        mineru_enabled: true,
        mineru_base_url: "http://10.10.9.19:8765",
        mineru_timeout_ms: 1800000,
      },
      changed_fields: ["llm_base_url", "llm_model", "embedding_base_url", "mineru_base_url"],
      ignored_sections: ["stt"],
      detail: "Provider manifest preview generated.",
    });
  });

  it("renders MinerU and LLM settings", async () => {
    renderSettings();

    expect(await screen.findByText("MinerU parser")).toBeVisible();
    expect(screen.getByText("LLM generation")).toBeVisible();
    expect(screen.getByRole("button", { name: /Test LLM/i })).toBeVisible();
    expect(await screen.findByDisplayValue("http://127.0.0.1:8765")).toBeVisible();
  });

  it("previews provider sync changes without saving", async () => {
    renderSettings();

    await screen.findByText("LLM generation");
    fireEvent.change(await screen.findByLabelText("Provider manifest URL"), {
      target: { value: "https://updates.jihadaj.com/providers.json" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Sync$/i }));

    expect(await screen.findByDisplayValue("http://10.10.9.195:8004/v1")).toBeVisible();
    expect(screen.getByDisplayValue("QuantTrio/Qwen3-VL-32B-Instruct-AWQ")).toBeVisible();
    expect(screen.getByDisplayValue("http://10.10.9.192:8001/v1")).toBeVisible();
    expect(screen.getByDisplayValue("http://10.10.9.19:8765")).toBeVisible();
    expect(screen.getByText("Vision")).toBeVisible();
    expect(screen.getByText(/Synced preview/i)).toBeVisible();
    expect(apiClient.updateDefaultSettings).not.toHaveBeenCalled();
  });

  it("saves the synced form values after preview", async () => {
    renderSettings();

    await screen.findByText("LLM generation");
    fireEvent.change(await screen.findByLabelText("Provider manifest URL"), {
      target: { value: "https://updates.jihadaj.com/providers.json" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Sync$/i }));
    await screen.findByDisplayValue("http://10.10.9.195:8004/v1");
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    await waitFor(() => expect(apiClient.updateDefaultSettings).toHaveBeenCalled());
    expect(vi.mocked(apiClient.updateDefaultSettings).mock.calls[0][0]).toEqual(
      expect.objectContaining({
        llm_provider: "openai_compatible",
        llm_base_url: "http://10.10.9.195:8004/v1",
        llm_model: "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
        llm_timeout_ms: 5000,
        llm_capabilities: ["text", "vision", "reasoning"],
        embedding_provider: "vllm_openai",
        embedding_base_url: "http://10.10.9.192:8001/v1",
        mineru_base_url: "http://10.10.9.19:8765",
      }),
    );
  });
});
