import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient, type DefaultsOut } from "../src/api/client";
import type { SettingsProfileOut } from "../src/api/generated";
import { SettingsPage } from "../src/features/settings/settings-page";

vi.mock("../src/api/client", () => ({
  DEFAULT_PARSER_MODE: "mineru_strict",
  apiClient: {
    defaults: vi.fn(),
    defaultSettings: vi.fn(),
    updateDefaultSettings: vi.fn(),
    testEmbeddingSettings: vi.fn(),
    testMinerUSettings: vi.fn(),
    testLlmSettings: vi.fn(),
    testRerankerSettings: vi.fn(),
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
  embedding_provider: "vllm_openai",
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
  mineru_require_hpc: true,
  mineru_backend: "pipeline",
  mineru_device: "cuda:0",
  mineru_lang: null,
  mineru_formula: true,
  mineru_table: true,
  mineru_source: null,
  mineru_max_concurrent_files: 1,
  runtime_mode: "runtime",
  vision_model: "vision-model",
  vision_base_url: "http://127.0.0.1:8004/v1",
  has_vision_api_key: false,
  vision_timeout_ms: 10000,
  reranker_provider: "disabled",
  reranker_fallback_provider: "disabled",
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

const backendDefaults: DefaultsOut = {
  runtime: {
    llm_timeout_ms: 11000,
    embedding_timeout_ms: 12000,
    embedding_dimensions: 1536,
    embedding_batch_size: 24,
    mineru_timeout_ms: 1700000,
    mineru_poll_interval_ms: 1500,
    mineru_max_concurrent_files: 3,
    vision_timeout_ms: 13000,
    reranker_timeout_ms: 14000,
    chunk_token_size: 1300,
    chunk_overlap_token_size: 120,
    context_window: 2,
    max_context_tokens: 2400,
    top_k: 77,
    chunk_top_k: 33,
    cosine_better_than_threshold: 0.25,
    max_total_tokens: 31000,
    max_entity_tokens: 6100,
    max_relation_tokens: 8100,
    llm_model_max_async: 5,
    embedding_func_max_async: 9,
    max_parallel_insert: 3,
  },
  policy_versions: {
    runtime_defaults: "2026-05-24",
  },
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
    vi.mocked(apiClient.defaults).mockResolvedValue(backendDefaults);
    vi.mocked(apiClient.defaultSettings).mockResolvedValue(settings);
    vi.mocked(apiClient.updateDefaultSettings).mockResolvedValue(settings);
    vi.mocked(apiClient.testMinerUSettings).mockResolvedValue({
      ok: true,
      base_url: "http://127.0.0.1:8765",
      latency_ms: 12,
      detail: "RAG-Anything sidecar ready (HPC coordinator mode).",
      optimization: {
        backend: "pipeline",
        device: "cuda:0",
        max_concurrent_files: 2,
      },
    });
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
        mineru_backend: "pipeline",
        mineru_device: "cuda:0",
        mineru_lang: "arabic",
        mineru_formula: false,
        mineru_table: false,
        mineru_source: "huggingface",
        mineru_max_concurrent_files: 2,
        enable_rerank: true,
        reranker_provider: "generic_http",
        reranker_model: "Qwen/Qwen3-Reranker-8B",
        reranker_base_url: "http://10.10.9.193:8005/v1/rerank",
        reranker_timeout_ms: 10000,
      },
      changed_fields: [
        "llm_base_url",
        "llm_model",
        "embedding_base_url",
        "mineru_base_url",
        "reranker_base_url",
      ],
      ignored_sections: ["stt"],
      detail: "Provider manifest preview generated.",
    });
    vi.mocked(apiClient.testRerankerSettings).mockResolvedValue({
      ok: true,
      provider: "generic_http",
      model: "Qwen/Qwen3-Reranker-8B",
      base_url: "http://10.10.9.193:8005/v1/rerank",
      latency_ms: 20,
      detail: "Reranker returned ranked results.",
    });
  });

  it("renders MinerU and LLM settings", async () => {
    renderSettings();

    expect(await screen.findByText("MinerU parser")).toBeVisible();
    await waitFor(() => expect(apiClient.defaults).toHaveBeenCalled());
    expect(screen.getByText("LLM generation")).toBeVisible();
    expect(screen.getByLabelText("Runtime mode")).toBeVisible();
    expect(await screen.findByDisplayValue("bolt://127.0.0.1:57687")).toBeVisible();
    expect(screen.getByRole("button", { name: /Test LLM/i })).toBeVisible();
    expect(await screen.findByDisplayValue("http://127.0.0.1:8765")).toBeVisible();
    expect(screen.getByLabelText("Require HPC MinerU coordinator")).toBeChecked();
    expect(screen.getByLabelText("MinerU backend")).toHaveValue("pipeline");
    expect(screen.getByLabelText("MinerU device")).toHaveValue("cuda:0");
    expect(screen.getByLabelText("MinerU source")).toHaveValue("");
    expect(screen.getByLabelText("MinerU max concurrent files")).toHaveValue(1);
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
    expect(screen.getByDisplayValue("arabic")).toBeVisible();
    expect(screen.getByLabelText("Parse formulas")).not.toBeChecked();
    expect(screen.getByDisplayValue("Qwen/Qwen3-Reranker-8B")).toBeVisible();
    expect(screen.getByDisplayValue("http://10.10.9.193:8005/v1/rerank")).toBeVisible();
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
        mineru_lang: "arabic",
        mineru_formula: false,
        mineru_table: false,
        mineru_max_concurrent_files: 2,
        enable_rerank: true,
        reranker_provider: "generic_http",
        reranker_model: "Qwen/Qwen3-Reranker-8B",
        reranker_base_url: "http://10.10.9.193:8005/v1/rerank",
      }),
    );
  });

  it("submits the MinerU HPC requirement setting", async () => {
    vi.mocked(apiClient.defaultSettings).mockResolvedValueOnce({
      ...settings,
      mineru_require_hpc: false,
    });
    renderSettings();

    await screen.findByDisplayValue("gpt-4.1");
    const checkbox = await screen.findByLabelText("Require HPC MinerU coordinator");
    expect(checkbox).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(apiClient.updateDefaultSettings).toHaveBeenCalled());
    expect(vi.mocked(apiClient.updateDefaultSettings).mock.calls[0][0]).toEqual(
      expect.objectContaining({ mineru_require_hpc: false }),
    );
  });

  it("shows MinerU sidecar optimization details after test", async () => {
    renderSettings();

    await screen.findByDisplayValue("gpt-4.1");
    fireEvent.click(screen.getByRole("button", { name: /Test MinerU/i }));

    expect(await screen.findByText(/backend=pipeline/)).toBeVisible();
    expect(screen.getByText(/device=cuda:0/)).toBeVisible();
    expect(screen.getByText(/maxConcurrentFiles=2/)).toBeVisible();
  });

  it("does not duplicate MinerU optimization details already present in backend detail", async () => {
    vi.mocked(apiClient.testMinerUSettings).mockResolvedValueOnce({
      ok: true,
      base_url: "http://127.0.0.1:8765",
      latency_ms: 12,
      detail:
        "RAG-Anything sidecar ready (HPC coordinator mode; backend=pipeline; device=cuda:0; maxConcurrentFiles=2).",
      optimization: {
        backend: "pipeline",
        device: "cuda:0",
        max_concurrent_files: 2,
      },
    });
    renderSettings();

    await screen.findByDisplayValue("gpt-4.1");
    fireEvent.click(screen.getByRole("button", { name: /Test MinerU/i }));

    const status = await screen.findByText(/Connected: RAG-Anything sidecar ready/);
    const text = status.textContent ?? "";
    expect(text.match(/backend=pipeline/g) ?? []).toHaveLength(1);
    expect(text.match(/device=cuda:0/g) ?? []).toHaveLength(1);
    expect(text.match(/maxConcurrentFiles=2/g) ?? []).toHaveLength(1);
  });

  it("keeps runtime mode and storage backend pairings explicit", async () => {
    renderSettings();

    await screen.findByDisplayValue("gpt-4.1");
    expect(screen.getByRole("option", { name: "Native runtime" })).toBeVisible();
    expect(screen.queryByRole("option", { name: "Degraded runtime" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Fallback" })).not.toBeInTheDocument();
    expect(screen.queryByText("Fallback local")).not.toBeInTheDocument();
    expect(screen.getByText("Postgres + PGVector + Neo4j")).toBeVisible();
    expect(screen.getByText("Native runtime uses RAG-Anything, PGVector, and Neo4j when dependencies are healthy.")).toBeVisible();

    const runtimeMode = screen.getByLabelText("Runtime mode") as HTMLSelectElement;
    const storageBackend = screen.getByLabelText("Storage backend") as HTMLSelectElement;

    fireEvent.change(storageBackend, { target: { value: "postgres_pgvector_neo4j" } });
    expect(runtimeMode.value).toBe("runtime");

    fireEvent.change(runtimeMode, { target: { value: "runtime" } });
    expect(storageBackend.value).toBe("postgres_pgvector_neo4j");
    expect(screen.getByText("Native runtime uses RAG-Anything, PGVector, and Neo4j when dependencies are healthy.")).toBeVisible();
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

  it("submits LLM reranker provider and fallback values", async () => {
    renderSettings();

    await screen.findByText("Vision and reranker");
    await screen.findByDisplayValue("gpt-4.1");
    fireEvent.change(screen.getByLabelText("Reranker provider"), {
      target: { value: "llm" },
    });
    fireEvent.change(screen.getByLabelText("Reranker fallback"), {
      target: { value: "llm" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    await waitFor(() => expect(apiClient.updateDefaultSettings).toHaveBeenCalled());
    expect(vi.mocked(apiClient.updateDefaultSettings).mock.calls[0][0]).toEqual(
      expect.objectContaining({
        reranker_provider: "llm",
        reranker_fallback_provider: "llm",
      }),
    );
  });

  it("tests the configured reranker", async () => {
    renderSettings();

    await screen.findByText("Vision and reranker");
    await screen.findByDisplayValue("gpt-4.1");
    fireEvent.change(screen.getByLabelText("Reranker provider"), {
      target: { value: "generic_http" },
    });
    fireEvent.change(screen.getByLabelText("Reranker model"), {
      target: { value: "Qwen/Qwen3-Reranker-8B" },
    });
    fireEvent.change(screen.getByLabelText("Reranker base URL"), {
      target: { value: "http://10.10.9.193:8005/v1/rerank" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Test Reranker/i }));

    expect(await screen.findByText(/Connected: Reranker returned ranked results/i)).toBeVisible();
    expect(vi.mocked(apiClient.testRerankerSettings).mock.calls[0][0]).toEqual(
      expect.objectContaining({
        reranker_provider: "generic_http",
        reranker_model: "Qwen/Qwen3-Reranker-8B",
        reranker_base_url: "http://10.10.9.193:8005/v1/rerank",
      }),
    );
  });

  it("shows the saved LLM key status for LLM-backed reranker tests", async () => {
    vi.mocked(apiClient.defaultSettings).mockResolvedValueOnce({
      ...settings,
      has_llm_api_key: true,
      reranker_provider: "llm",
      reranker_fallback_provider: "disabled",
    });
    renderSettings();

    expect(await screen.findByText("Saved LLM API key present")).toBeVisible();
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
        runtime_mode: "runtime",
        storage_backend: "postgres_pgvector_neo4j",
      }),
    );
  });

  it("uses backend runtime defaults when creating the first profile", async () => {
    vi.mocked(apiClient.defaultSettings).mockRejectedValueOnce(
      new ApiError("No default profile saved", 404, { detail: "No default profile saved" }),
    );
    renderSettings();

    expect(await screen.findByText("No default profile saved")).toBeVisible();
    await waitFor(() => expect(screen.getByLabelText("Top K")).toHaveValue(77));
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    await waitFor(() => expect(apiClient.updateDefaultSettings).toHaveBeenCalled());
    expect(vi.mocked(apiClient.updateDefaultSettings).mock.calls[0][0]).toEqual(
      expect.objectContaining({
        top_k: 77,
        chunk_top_k: 33,
        max_context_tokens: 2400,
      }),
    );
  });

  it("falls back to local runtime defaults when backend defaults are unavailable", async () => {
    vi.mocked(apiClient.defaults).mockRejectedValueOnce(new Error("Defaults unavailable"));
    vi.mocked(apiClient.defaultSettings).mockRejectedValueOnce(
      new ApiError("No default profile saved", 404, { detail: "No default profile saved" }),
    );
    renderSettings();

    expect(await screen.findByText("No default profile saved")).toBeVisible();
    await waitFor(() => expect(screen.getByLabelText("Top K")).toHaveValue(40));
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    await waitFor(() => expect(apiClient.updateDefaultSettings).toHaveBeenCalled());
    expect(vi.mocked(apiClient.updateDefaultSettings).mock.calls[0][0]).toEqual(
      expect.objectContaining({
        top_k: 40,
        chunk_top_k: 20,
        max_context_tokens: 2000,
      }),
    );
  });

  it("keeps numeric fields bounded and does not coerce blanks to zero", async () => {
    renderSettings();

    await screen.findByDisplayValue("gpt-4.1");
    const topK = screen.getByLabelText("Top K") as HTMLInputElement;
    const cosineThreshold = screen.getByLabelText("Cosine threshold") as HTMLInputElement;
    const rerankerTimeout = screen.getByLabelText("Reranker timeout (ms)") as HTMLInputElement;

    expect(topK).toHaveAttribute("min", "1");
    expect(topK).toHaveAttribute("max", "1000");
    expect(cosineThreshold).toHaveAttribute("min", "0");
    expect(cosineThreshold).toHaveAttribute("max", "1");
    expect(cosineThreshold).toHaveAttribute("step", "0.01");
    expect(rerankerTimeout).toHaveAttribute("min", "100");
    expect(rerankerTimeout).toHaveAttribute("max", "1800000");

    fireEvent.change(topK, { target: { value: "" } });
    expect(topK).toHaveValue(null);
    fireEvent.blur(topK);
    expect(topK).toHaveValue(40);

    fireEvent.change(cosineThreshold, { target: { value: "2" } });
    fireEvent.blur(cosineThreshold);
    expect(cosineThreshold).toHaveValue(1);

    fireEvent.change(rerankerTimeout, { target: { value: "50" } });
    fireEvent.blur(rerankerTimeout);
    expect(rerankerTimeout).toHaveValue(100);

    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    await waitFor(() => expect(apiClient.updateDefaultSettings).toHaveBeenCalled());
    expect(vi.mocked(apiClient.updateDefaultSettings).mock.calls[0][0]).toEqual(
      expect.objectContaining({
        top_k: 40,
        cosine_better_than_threshold: 1,
        reranker_timeout_ms: 100,
      }),
    );
  });
});
