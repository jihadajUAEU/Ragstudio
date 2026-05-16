import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../src/api/client";
import type { DiagnosticsOut, SettingsProfileOut } from "../src/api/generated";
import { AppShell } from "../src/components/app-shell";

vi.mock("../src/api/client", () => ({
  DEFAULT_PARSER_MODE: "mineru_strict",
  apiClient: {
    diagnostics: vi.fn(),
    defaultSettings: vi.fn(),
    testLlmSettings: vi.fn(),
    testEmbeddingSettings: vi.fn(),
    testRerankerSettings: vi.fn(),
    testMinerUSettings: vi.fn(),
  },
}));

const readyDiagnostics: DiagnosticsOut = {
  capabilities: {},
  dependency_status: {},
  warnings: [],
  runtime_mode: "runtime",
  overall_status: "ready",
  checks: [],
};

const defaultSettings: SettingsProfileOut = {
  id: "default",
  provider: "openai-compatible",
  llm_provider: "openai_compatible",
  llm_model: "gpt-4.1",
  llm_base_url: "http://127.0.0.1:8004/v1",
  has_llm_api_key: false,
  llm_timeout_ms: 10000,
  llm_capabilities: [],
  embedding_model: "Qwen/Qwen3-Embedding-8B",
  storage_backend: "postgres_pgvector_neo4j",
  embedding_provider: "vllm_openai",
  embedding_base_url: "http://127.0.0.1:8001/v1",
  has_embedding_api_key: false,
  embedding_timeout_ms: 10000,
  embedding_dimensions: 1536,
  embedding_batch_size: 16,
  embedding_tls_verify: true,
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
  vision_model: null,
  vision_base_url: null,
  has_vision_api_key: false,
  vision_timeout_ms: 10000,
  reranker_provider: "generic_http",
  reranker_fallback_provider: "disabled",
  reranker_model: "Qwen/Qwen3-Reranker-8B",
  reranker_base_url: "http://127.0.0.1:8005/v1/rerank",
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

describe("AppShell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.diagnostics).mockResolvedValue(readyDiagnostics);
    vi.mocked(apiClient.defaultSettings).mockResolvedValue(defaultSettings);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("opens the mobile navigation as a modal dialog and returns focus on close", async () => {
    renderShell();

    const trigger = screen.getByRole("button", { name: "Open navigation" });
    trigger.focus();
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "Studio navigation" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    await waitFor(() => {
      expect(within(dialog).getByRole("button", { name: "Close navigation" })).toHaveFocus();
    });

    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Studio navigation" })).not.toBeInTheDocument();
    });
    expect(trigger).toHaveFocus();
  });

  it.each([
    ["Ready", readyDiagnostics],
    ["Degraded", { ...readyDiagnostics, overall_status: "degraded" as const }],
    [
      "Graph pending",
      { ...readyDiagnostics, dependency_status: { graph_projection: "pending" } },
    ],
    ["Indexing", { ...readyDiagnostics, dependency_status: { ready_index_jobs: 1 } }],
    [
      "Provider issue",
      {
        ...readyDiagnostics,
        overall_status: "degraded" as const,
        checks: [
          {
            name: "llm_connection",
            status: "failed" as const,
            severity: "warning" as const,
            detail: "LLM endpoint rejected the request.",
          },
        ],
      },
    ],
  ])("renders the %s runtime trust state", async (label, diagnostics) => {
    vi.mocked(apiClient.diagnostics).mockResolvedValueOnce(diagnostics);

    renderShell();

    expect(
      await screen.findByRole("button", {
        name: new RegExp(`Runtime trust status: ${label}`),
      }),
    ).toBeVisible();
  });

  it("renders blocked when diagnostics cannot load", async () => {
    vi.mocked(apiClient.diagnostics).mockRejectedValueOnce(new Error("backend offline"));

    renderShell();

    expect(await screen.findByText("Blocked")).toBeVisible();
    expect(
      screen.getByRole("button", {
        name: /Runtime trust status: Blocked\. Diagnostics unavailable: backend offline/,
      }),
    ).toBeVisible();
  });

  it("gives Blocked priority over graph pending", async () => {
    vi.mocked(apiClient.diagnostics).mockResolvedValueOnce({
      ...readyDiagnostics,
      overall_status: "failed",
      dependency_status: { graph_projection: "pending" },
    });

    renderShell();

    expect(
      await screen.findByRole("button", { name: /Runtime trust status: Blocked/ }),
    ).toBeVisible();
    expect(screen.queryByText("Graph pending")).not.toBeInTheDocument();
  });

  it("polls diagnostics every 30 seconds without running provider tests", async () => {
    vi.useFakeTimers();

    renderShell();

    await vi.waitFor(() => expect(apiClient.diagnostics).toHaveBeenCalledTimes(1));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });

    await vi.waitFor(() => expect(apiClient.diagnostics).toHaveBeenCalledTimes(2));
    expect(apiClient.defaultSettings).not.toHaveBeenCalled();
    expect(apiClient.testLlmSettings).not.toHaveBeenCalled();
    expect(apiClient.testEmbeddingSettings).not.toHaveBeenCalled();
    expect(apiClient.testRerankerSettings).not.toHaveBeenCalled();
    expect(apiClient.testMinerUSettings).not.toHaveBeenCalled();
  });

  it("opens the runtime trust panel with grouped runtime sections", async () => {
    renderShell();

    fireEvent.click(await screen.findByRole("button", { name: /Runtime trust status: Ready/ }));

    expect(screen.getByRole("dialog", { name: "Runtime trust" })).toHaveAttribute(
      "aria-modal",
      "true",
    );
    expect(screen.getByText("Backend/API")).toBeVisible();
    expect(screen.getByText("Worker/jobs")).toBeVisible();
    expect(screen.getByText("Postgres/PGVector")).toBeVisible();
    expect(screen.getByText("Neo4j/graph projection")).toBeVisible();
    expect(screen.getByText("MinerU/parser")).toBeVisible();
    expect(screen.getByText("LLM")).toBeVisible();
    expect(screen.getByText("Embeddings")).toBeVisible();
    expect(screen.getByText("Reranker")).toBeVisible();
  });

  it("refreshes status and opens Diagnostics from the runtime trust panel", async () => {
    const onNavigate = vi.fn();
    renderShell(onNavigate);

    fireEvent.click(await screen.findByRole("button", { name: /Runtime trust status: Ready/ }));
    await waitFor(() => expect(apiClient.diagnostics).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    await waitFor(() => expect(apiClient.diagnostics).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByRole("button", { name: "Open Diagnostics" }));

    expect(onNavigate).toHaveBeenCalledWith("/diagnostics");
  });

  it("runs each provider test with the saved default settings payload", async () => {
    vi.mocked(apiClient.testLlmSettings).mockResolvedValue({
      ok: true,
      provider: "openai_compatible",
      model: "gpt-4.1",
      latency_ms: 10,
      detail: "LLM ready",
    });
    vi.mocked(apiClient.testEmbeddingSettings).mockResolvedValue({
      ok: true,
      provider: "vllm_openai",
      model: "Qwen/Qwen3-Embedding-8B",
      dimensions: 1536,
      latency_ms: 8,
      detail: "Embeddings ready",
    });
    vi.mocked(apiClient.testRerankerSettings).mockResolvedValue({
      ok: true,
      provider: "generic_http",
      model: "Qwen/Qwen3-Reranker-8B",
      base_url: "http://127.0.0.1:8005/v1/rerank",
      latency_ms: 12,
      detail: "Reranker ready",
    });
    vi.mocked(apiClient.testMinerUSettings).mockResolvedValue({
      ok: true,
      base_url: "http://127.0.0.1:8765",
      latency_ms: 15,
      detail: "MinerU ready",
      optimization: {},
    });
    renderShell();

    fireEvent.click(await screen.findByRole("button", { name: /Runtime trust status: Ready/ }));
    fireEvent.click(screen.getByRole("button", { name: "Test LLM" }));
    fireEvent.click(screen.getByRole("button", { name: "Test embeddings" }));
    fireEvent.click(screen.getByRole("button", { name: "Test reranker" }));
    fireEvent.click(screen.getByRole("button", { name: "Test MinerU" }));

    expect(await screen.findByText("Connected: LLM ready")).toBeVisible();
    expect(screen.getByText("Connected: Embeddings ready (1536 dims)")).toBeVisible();
    expect(screen.getByText("Connected: Reranker ready")).toBeVisible();
    expect(screen.getByText("Connected: MinerU ready")).toBeVisible();
    expect(apiClient.testLlmSettings).toHaveBeenCalledWith(defaultSettings);
    expect(apiClient.testEmbeddingSettings).toHaveBeenCalledWith(defaultSettings);
    expect(apiClient.testRerankerSettings).toHaveBeenCalledWith(defaultSettings);
    expect(apiClient.testMinerUSettings).toHaveBeenCalledWith(defaultSettings);
  });

  it("keeps failed provider test output visible and restores focus on Escape", async () => {
    vi.mocked(apiClient.testLlmSettings).mockRejectedValueOnce(new Error("LLM timeout"));
    renderShell();

    const trigger = await screen.findByRole("button", { name: /Runtime trust status: Ready/ });
    trigger.focus();
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "Test LLM" }));

    expect(await screen.findByText("LLM timeout")).toBeVisible();
    expect(screen.getByText("LLM timeout").closest("[role='status']")).toHaveAttribute(
      "aria-live",
      "polite",
    );
    expect(screen.getByRole("dialog", { name: "Runtime trust" })).toBeVisible();

    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Runtime trust" })).not.toBeInTheDocument();
    });
    expect(trigger).toHaveFocus();
  });
});

function renderShell(onNavigate = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <AppShell activePath="/" title="Studio Dashboard" onNavigate={onNavigate}>
        <div>Dashboard content</div>
      </AppShell>
    </QueryClientProvider>,
  );
  return { onNavigate };
}
