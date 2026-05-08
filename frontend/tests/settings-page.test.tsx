import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "../src/api/client";
import type { SettingsProfileOut } from "../src/api/generated";
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
    readonly status: number;
    readonly details: unknown;

    constructor(message: string, status = 500, details: unknown = null) {
      super(message);
      this.status = status;
      this.details = details;
    }
  },
}));

const settings: SettingsProfileOut = {
  id: "default",
  provider: "openai",
  llm_provider: "openai_compatible",
  llm_model: "gpt-4.1",
  llm_base_url: "",
  llm_timeout_ms: 10000,
  llm_capabilities: [],
  has_llm_api_key: false,
  embedding_model: "text-embedding-3-large",
  storage_backend: "postgres_pgvector_neo4j",
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
  runtime_mode: "runtime",
  vision_model: "vision-model",
  vision_base_url: "http://127.0.0.1:8004/v1",
  has_vision_api_key: false,
  vision_timeout_ms: 10000,
  reranker_provider: "disabled",
  reranker_model: null,
  reranker_base_url: null,
  has_reranker_api_key: false,
  reranker_timeout_ms: 10000,
  pgvector_schema: "public",
  pgvector_table_prefix: "ragstudio",
  neo4j_uri: "bolt://127.0.0.1:57687",
  neo4j_username: "neo4j",
  has_neo4j_password: false,
  parser: "mineru",
  parse_method: "auto",
  chunk_token_size: 1200,
  chunk_overlap_token_size: 100,
  enable_image_processing: true,
  enable_table_processing: true,
  enable_equation_processing: true,
  context_window: 1,
  context_mode: "page",
  max_context_tokens: 2000,
  include_headers: true,
  include_captions: true,
  query_mode: "mix",
  top_k: 40,
  chunk_top_k: 20,
  enable_rerank: true,
  cosine_better_than_threshold: 0.2,
  max_total_tokens: 30000,
  max_entity_tokens: 6000,
  max_relation_tokens: 8000,
  enable_llm_cache: true,
  enable_llm_cache_for_entity_extract: true,
  llm_model_max_async: 4,
  embedding_func_max_async: 8,
  max_parallel_insert: 2,
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
    vi.clearAllMocks();
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
    expect(screen.getByLabelText("Runtime mode")).toBeVisible();
    expect(await screen.findByDisplayValue("bolt://127.0.0.1:57687")).toBeVisible();
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

  it("keeps runtime mode and storage backend pairings explicit", async () => {
    renderSettings();

    await screen.findByDisplayValue("gpt-4.1");
    expect(screen.getByRole("option", { name: "Native runtime (blocked)" })).toBeVisible();
    expect(screen.getByText("Native adapter pending; indexing and query requests will block.")).toBeVisible();

    const runtimeMode = screen.getByLabelText("Runtime mode") as HTMLSelectElement;
    const storageBackend = screen.getByLabelText("Storage backend") as HTMLSelectElement;

    fireEvent.change(runtimeMode, { target: { value: "fallback" } });
    expect(storageBackend.value).toBe("postgres_pgvector_neo4j");
    expect(
      screen.queryByText("Native adapter pending; indexing and query requests will block."),
    ).not.toBeInTheDocument();

    fireEvent.change(storageBackend, { target: { value: "fallback_local" } });
    expect(runtimeMode.value).toBe("fallback");
    expect(
      screen.queryByText("Native adapter pending; indexing and query requests will block."),
    ).not.toBeInTheDocument();

    fireEvent.change(storageBackend, { target: { value: "postgres_pgvector_neo4j" } });
    expect(runtimeMode.value).toBe("fallback");

    fireEvent.change(runtimeMode, { target: { value: "runtime" } });
    expect(storageBackend.value).toBe("postgres_pgvector_neo4j");
    expect(screen.getByText("Native adapter pending; indexing and query requests will block.")).toBeVisible();
  });

  it("submits newly typed secret values", async () => {
    renderSettings();

    await screen.findByText("LLM generation");
    await screen.findByDisplayValue("gpt-4.1");
    fireEvent.change(screen.getByLabelText("LLM API key"), {
      target: { value: "llm-secret" },
    });
    fireEvent.change(screen.getByLabelText("Vision API key"), {
      target: { value: "vision-secret" },
    });
    fireEvent.change(screen.getByLabelText("Reranker API key"), {
      target: { value: "reranker-secret" },
    });
    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "embedding-secret" },
    });
    fireEvent.change(screen.getByLabelText("Neo4j password"), {
      target: { value: "neo4j-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    await waitFor(() => expect(apiClient.updateDefaultSettings).toHaveBeenCalled());
    expect(vi.mocked(apiClient.updateDefaultSettings).mock.calls[0][0]).toEqual(
      expect.objectContaining({
        llm_api_key: "llm-secret",
        vision_api_key: "vision-secret",
        reranker_api_key: "reranker-secret",
        embedding_api_key: "embedding-secret",
        neo4j_password: "neo4j-secret",
      }),
    );

    await waitFor(() => expect(screen.getByLabelText("LLM API key")).toHaveValue(""));
    expect(screen.getByLabelText("Vision API key")).toHaveValue("");
    expect(screen.getByLabelText("Reranker API key")).toHaveValue("");
    expect(screen.getByLabelText("API key")).toHaveValue("");
    expect(screen.getByLabelText("Neo4j password")).toHaveValue("");

    fireEvent.change(screen.getByLabelText("Neo4j password"), {
      target: { value: "typed-again" },
    });
    expect(screen.getByLabelText("Neo4j password")).toHaveValue("typed-again");
    fireEvent.click(screen.getByRole("button", { name: /^Reset$/i }));
    expect(screen.getByLabelText("Neo4j password")).toHaveValue("");
  });

  it("allows saving the first profile when settings are missing", async () => {
    vi.mocked(apiClient.defaultSettings).mockRejectedValueOnce(
      new ApiError("No default profile saved", 404, { detail: "No default profile saved" }),
    );
    renderSettings();

    expect(await screen.findByText("No default profile saved")).toBeVisible();
    expect(screen.getByLabelText("Runtime mode")).toBeEnabled();
    expect(screen.getByRole("button", { name: /^Save$/i })).toBeEnabled();

    fireEvent.change(screen.getByLabelText("Provider"), {
      target: { value: "first-provider" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    await waitFor(() => expect(apiClient.updateDefaultSettings).toHaveBeenCalled());
    expect(vi.mocked(apiClient.updateDefaultSettings).mock.calls[0][0]).toEqual(
      expect.objectContaining({
        provider: "first-provider",
        runtime_mode: "fallback",
        storage_backend: "fallback_local",
      }),
    );
  });
});
