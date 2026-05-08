import { type FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, PlugZap, RefreshCcw, RotateCcw, Save, Settings } from "lucide-react";

import { ApiError, apiClient } from "../../api/client";
import type { SettingsProfileIn, SettingsProfileOut } from "../../api/generated";
import { Button } from "../../components/ui/button";

const queryKeys = {
  settings: ["settings", "default"],
} as const;

const DEFAULT_MANIFEST_URL = "https://updates.jihadaj.com/providers.json";
const DEFAULT_FORM_VALUES: SettingsProfileIn = {
  provider: "openai-compatible",
  llm_provider: "openai_compatible",
  llm_model: "gpt-4o-mini",
  llm_base_url: "",
  llm_timeout_ms: 10000,
  llm_capabilities: [],
  embedding_model: "fallback",
  storage_backend: "fallback_local",
  embedding_provider: "fallback",
  embedding_base_url: "",
  embedding_timeout_ms: 10000,
  embedding_dimensions: 1536,
  embedding_batch_size: 16,
  embedding_tls_verify: true,
  mineru_enabled: false,
  mineru_base_url: "",
  mineru_timeout_ms: 1_800_000,
  mineru_poll_interval_ms: 1_000,
  runtime_mode: "fallback",
  vision_model: "",
  vision_base_url: "",
  vision_timeout_ms: 10000,
  reranker_provider: "disabled",
  reranker_model: "",
  reranker_base_url: "",
  reranker_timeout_ms: 10000,
  pgvector_schema: "public",
  pgvector_table_prefix: "ragstudio",
  neo4j_uri: "",
  neo4j_username: "",
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

export function SettingsPage() {
  const queryClient = useQueryClient();
  const [formOverride, setFormOverride] = useState<SettingsProfileIn | null>(null);
  const [manifestUrl, setManifestUrl] = useState(DEFAULT_MANIFEST_URL);
  const [syncMessage, setSyncMessage] = useState("");

  const settingsQuery = useQuery({
    queryKey: queryKeys.settings,
    queryFn: apiClient.defaultSettings,
    retry: (failureCount, error) =>
      error instanceof ApiError && error.status === 404 ? false : failureCount < 2,
  });

  const settingsMissing =
    settingsQuery.error instanceof ApiError && settingsQuery.error.status === 404;
  const loadedValues = settingsQuery.data
    ? settingsToFormValues(settingsQuery.data)
    : settingsMissing
      ? DEFAULT_FORM_VALUES
      : null;
  const formValues = formOverride ?? loadedValues;

  const updateSettings = useMutation({
    mutationFn: apiClient.updateDefaultSettings,
    onSuccess: (settings) => {
      queryClient.setQueryData(queryKeys.settings, settings);
      setFormOverride(settingsToFormValues(settings));
    },
  });
  const syncProvider = useMutation({
    mutationFn: apiClient.syncProviderPreview,
    onSuccess: (result) => {
      setFormOverride((current) => (formValues ? { ...formValues, ...current, ...result.patch } : current));
      const changed = result.changed_fields.length
        ? result.changed_fields.join(", ")
        : "no saved values changed";
      setSyncMessage(`Synced preview: ${changed}`);
    },
    onError: (error) => {
      setSyncMessage(error instanceof Error ? error.message : "Provider sync failed");
    },
  });
  const testEmbedding = useMutation({
    mutationFn: apiClient.testEmbeddingSettings,
  });
  const testLlm = useMutation({
    mutationFn: apiClient.testLlmSettings,
  });
  const testMinerU = useMutation({
    mutationFn: apiClient.testMinerUSettings,
  });

  const updateField = <K extends keyof SettingsProfileIn>(key: K, value: SettingsProfileIn[K]) => {
    setFormOverride((current) => (formValues ? { ...formValues, ...current, [key]: value } : current));
  };

  const updateRuntimeMode = (value: SettingsProfileIn["runtime_mode"]) => {
    setFormOverride((current) => {
      if (!formValues) {
        return current;
      }
      const next = { ...formValues, ...current, runtime_mode: value };
      if (value === "runtime" && next.storage_backend === "fallback_local") {
        next.storage_backend = "postgres_pgvector_neo4j";
      }
      return next;
    });
  };

  const updateStorageBackend = (value: SettingsProfileIn["storage_backend"]) => {
    setFormOverride((current) => {
      if (!formValues) {
        return current;
      }
      const next = { ...formValues, ...current, storage_backend: value };
      if (value === "fallback_local") {
        next.runtime_mode = "fallback";
      }
      return next;
    });
  };

  const buildPayload = (form: HTMLFormElement): SettingsProfileIn | null => {
    if (!formValues) {
      return null;
    }
    const formData = new FormData(form);
    const embeddingApiKey = String(formData.get("embedding_api_key") ?? "").trim();
    const llmApiKey = String(formData.get("llm_api_key") ?? "").trim();
    const visionApiKey = String(formData.get("vision_api_key") ?? "").trim();
    const rerankerApiKey = String(formData.get("reranker_api_key") ?? "").trim();
    const neo4jPassword = String(formData.get("neo4j_password") ?? "").trim();
    const payload: SettingsProfileIn = {
      ...formValues,
      llm_provider: formValues.llm_provider ?? "openai_compatible",
      llm_capabilities: formValues.llm_capabilities ?? [],
      embedding_provider: formValues.embedding_provider ?? "fallback",
      embedding_tls_verify: formValues.embedding_tls_verify ?? true,
      mineru_enabled: formValues.mineru_enabled ?? false,
      runtime_mode: formValues.runtime_mode ?? "fallback",
      storage_backend: formValues.storage_backend ?? "fallback_local",
      vision_timeout_ms: formValues.vision_timeout_ms ?? 10000,
      reranker_provider: formValues.reranker_provider ?? "disabled",
      reranker_timeout_ms: formValues.reranker_timeout_ms ?? 10000,
      pgvector_schema: formValues.pgvector_schema ?? "public",
      pgvector_table_prefix: formValues.pgvector_table_prefix ?? "ragstudio",
      parser: formValues.parser ?? "mineru",
      parse_method: formValues.parse_method ?? "auto",
      chunk_token_size: formValues.chunk_token_size ?? 1200,
      chunk_overlap_token_size: formValues.chunk_overlap_token_size ?? 100,
      enable_image_processing: formValues.enable_image_processing ?? true,
      enable_table_processing: formValues.enable_table_processing ?? true,
      enable_equation_processing: formValues.enable_equation_processing ?? true,
      context_window: formValues.context_window ?? 1,
      context_mode: formValues.context_mode ?? "page",
      max_context_tokens: formValues.max_context_tokens ?? 2000,
      include_headers: formValues.include_headers ?? true,
      include_captions: formValues.include_captions ?? true,
      query_mode: formValues.query_mode ?? "mix",
      top_k: formValues.top_k ?? 40,
      chunk_top_k: formValues.chunk_top_k ?? 20,
      enable_rerank: formValues.enable_rerank ?? true,
      cosine_better_than_threshold: formValues.cosine_better_than_threshold ?? 0.2,
      max_total_tokens: formValues.max_total_tokens ?? 30000,
      max_entity_tokens: formValues.max_entity_tokens ?? 6000,
      max_relation_tokens: formValues.max_relation_tokens ?? 8000,
      enable_llm_cache: formValues.enable_llm_cache ?? true,
      enable_llm_cache_for_entity_extract: formValues.enable_llm_cache_for_entity_extract ?? true,
      llm_model_max_async: formValues.llm_model_max_async ?? 4,
      embedding_func_max_async: formValues.embedding_func_max_async ?? 8,
      max_parallel_insert: formValues.max_parallel_insert ?? 2,
    };
    if (embeddingApiKey) {
      payload.embedding_api_key = embeddingApiKey;
    }
    if (llmApiKey) {
      payload.llm_api_key = llmApiKey;
    }
    if (visionApiKey) {
      payload.vision_api_key = visionApiKey;
    }
    if (rerankerApiKey) {
      payload.reranker_api_key = rerankerApiKey;
    }
    if (neo4jPassword) {
      payload.neo4j_password = neo4jPassword;
    }
    return payload;
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const payload = buildPayload(event.currentTarget);
    if (payload) {
      updateSettings.mutate(payload);
    }
  };

  const syncFromManifest = () => {
    setSyncMessage("");
    syncProvider.mutate({ manifest_url: manifestUrl });
  };

  const submitForTest = (
    form: HTMLFormElement | null,
    mutation: typeof testEmbedding | typeof testLlm | typeof testMinerU,
  ) => {
    if (!form?.reportValidity()) {
      return;
    }
    const payload = buildPayload(form);
    if (payload) {
      mutation.mutate(payload);
    }
  };

  const message = getMessage(settingsQuery.error, updateSettings.error);
  const testMessage = testEmbedding.error
    ? testEmbedding.error.message
    : testEmbedding.data
      ? `${testEmbedding.data.ok ? "Connected" : "Failed"}: ${testEmbedding.data.detail}${
          testEmbedding.data.dimensions ? ` (${testEmbedding.data.dimensions} dims)` : ""
        }`
      : settingsQuery.data?.has_embedding_api_key
        ? "Saved API key present"
        : "";
  const llmTestMessage = testLlm.error
    ? testLlm.error.message
    : testLlm.data
      ? `${testLlm.data.ok ? "Connected" : "Failed"}: ${testLlm.data.detail}`
      : settingsQuery.data?.has_llm_api_key
        ? "Saved API key present"
        : "";
  const mineruTestMessage = testMinerU.error
    ? testMinerU.error.message
    : testMinerU.data
      ? `${testMinerU.data.ok ? "Connected" : "Failed"}: ${testMinerU.data.detail}`
      : "";

  const busy = updateSettings.isPending || !formValues;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <section className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium text-[#176b87]">Settings</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-normal text-[#1f2933]">
            Default runtime profile
          </h2>
        </div>
        <Button
          type="button"
          variant="secondary"
          onClick={() => void settingsQuery.refetch()}
          disabled={settingsQuery.isFetching}
        >
          {settingsQuery.isFetching ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
          )}
          Reload
        </Button>
      </section>

      <form onSubmit={submit} className="flex flex-col gap-4">
        <section className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
          <div className="mb-5 flex items-center gap-2">
            <RefreshCcw className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
            <h3 className="truncate text-base font-semibold text-[#1f2933]">Provider sync</h3>
          </div>
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
            <label className="min-w-0 text-sm font-medium text-[#3a4a53]">
              <span className="mb-1.5 block truncate">Provider manifest URL</span>
              <input
                className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20 disabled:bg-[#f4f7f8]"
                value={manifestUrl}
                onChange={(event) => setManifestUrl(event.target.value)}
                placeholder={DEFAULT_MANIFEST_URL}
                disabled={syncProvider.isPending || busy}
              />
            </label>
            <Button
              type="button"
              variant="secondary"
              onClick={syncFromManifest}
              disabled={syncProvider.isPending || busy}
            >
              {syncProvider.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <RefreshCcw className="h-4 w-4" aria-hidden="true" />
              )}
              Sync
            </Button>
          </div>
          <p className="mt-3 min-h-5 text-sm text-[#62717a]" role="status">
            {syncMessage}
          </p>
        </section>

        <section className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
          <div className="mb-5 flex items-center gap-2">
            <Settings className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
            <h3 className="truncate text-base font-semibold text-[#1f2933]">Runtime profile</h3>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Provider"
              name="provider"
              value={formValues?.provider ?? ""}
              placeholder="openai"
              disabled={busy}
              onChange={(value) => updateField("provider", value)}
            />
            <SelectField
              label="Runtime mode"
              name="runtime_mode"
              value={formValues?.runtime_mode ?? "fallback"}
              disabled={busy}
              onChange={(value) => updateRuntimeMode(value as SettingsProfileIn["runtime_mode"])}
              options={[
                { value: "fallback", label: "Fallback" },
                { value: "runtime", label: "Native runtime" },
              ]}
            />
            <SelectField
              label="Storage backend"
              name="storage_backend"
              value={formValues?.storage_backend ?? "fallback_local"}
              disabled={busy}
              onChange={(value) => updateStorageBackend(value as SettingsProfileIn["storage_backend"])}
              options={[
                { value: "fallback_local", label: "Fallback local" },
                { value: "postgres_pgvector_neo4j", label: "Postgres / PGVector / Neo4j" },
              ]}
            />
            <Field
              label="PGVector schema"
              name="pgvector_schema"
              value={formValues?.pgvector_schema ?? "public"}
              placeholder="public"
              disabled={busy}
              onChange={(value) => updateField("pgvector_schema", value)}
            />
            <Field
              label="PGVector table prefix"
              name="pgvector_table_prefix"
              value={formValues?.pgvector_table_prefix ?? "ragstudio"}
              placeholder="ragstudio"
              disabled={busy}
              onChange={(value) => updateField("pgvector_table_prefix", value)}
            />
            <Field
              label="Neo4j URI"
              name="neo4j_uri"
              value={formValues?.neo4j_uri ?? ""}
              placeholder="bolt://127.0.0.1:57687"
              disabled={busy}
              required={false}
              onChange={(value) => updateField("neo4j_uri", value)}
            />
            <Field
              label="Neo4j username"
              name="neo4j_username"
              value={formValues?.neo4j_username ?? ""}
              placeholder="neo4j"
              disabled={busy}
              required={false}
              onChange={(value) => updateField("neo4j_username", value)}
            />
            <Field
              label="Neo4j password"
              name="neo4j_password"
              value=""
              placeholder={settingsQuery.data?.has_neo4j_password ? "Saved password present" : "optional"}
              disabled={busy}
              required={false}
              type="password"
            />
          </div>
        </section>

        <section className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
          <div className="mb-5 flex items-center gap-2">
            <PlugZap className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
            <h3 className="truncate text-base font-semibold text-[#1f2933]">Vision and reranker</h3>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Vision model"
              name="vision_model"
              value={formValues?.vision_model ?? ""}
              placeholder="optional"
              disabled={busy}
              required={false}
              onChange={(value) => updateField("vision_model", value)}
            />
            <Field
              label="Vision base URL"
              name="vision_base_url"
              value={formValues?.vision_base_url ?? ""}
              placeholder="http://127.0.0.1:8004/v1"
              disabled={busy}
              required={false}
              onChange={(value) => updateField("vision_base_url", value)}
            />
            <Field
              label="Vision API key"
              name="vision_api_key"
              value=""
              placeholder={settingsQuery.data?.has_vision_api_key ? "Saved key present" : "optional"}
              disabled={busy}
              required={false}
              type="password"
            />
            <Field
              label="Vision timeout (ms)"
              name="vision_timeout_ms"
              value={String(formValues?.vision_timeout_ms ?? 10000)}
              placeholder="10000"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("vision_timeout_ms", Number(value))}
            />
            <SelectField
              label="Reranker provider"
              name="reranker_provider"
              value={formValues?.reranker_provider ?? "disabled"}
              disabled={busy}
              onChange={(value) => updateField("reranker_provider", value as SettingsProfileIn["reranker_provider"])}
              options={[
                { value: "disabled", label: "Disabled" },
                { value: "cohere_compatible", label: "Cohere-compatible" },
                { value: "jina_compatible", label: "Jina-compatible" },
                { value: "generic_http", label: "Generic HTTP" },
              ]}
            />
            <Field
              label="Reranker model"
              name="reranker_model"
              value={formValues?.reranker_model ?? ""}
              placeholder="optional"
              disabled={busy}
              required={false}
              onChange={(value) => updateField("reranker_model", value)}
            />
            <Field
              label="Reranker base URL"
              name="reranker_base_url"
              value={formValues?.reranker_base_url ?? ""}
              placeholder="http://127.0.0.1:8005/v1"
              disabled={busy}
              required={false}
              onChange={(value) => updateField("reranker_base_url", value)}
            />
            <Field
              label="Reranker API key"
              name="reranker_api_key"
              value=""
              placeholder={settingsQuery.data?.has_reranker_api_key ? "Saved key present" : "optional"}
              disabled={busy}
              required={false}
              type="password"
            />
            <Field
              label="Reranker timeout (ms)"
              name="reranker_timeout_ms"
              value={String(formValues?.reranker_timeout_ms ?? 10000)}
              placeholder="10000"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("reranker_timeout_ms", Number(value))}
            />
          </div>
        </section>

        <section className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
          <div className="mb-5 flex items-center gap-2">
            <PlugZap className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
            <h3 className="truncate text-base font-semibold text-[#1f2933]">LLM generation</h3>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <SelectField
              label="LLM provider"
              name="llm_provider"
              value={formValues?.llm_provider ?? "openai_compatible"}
              disabled={busy}
              onChange={(value) => updateField("llm_provider", value as "openai_compatible")}
              options={[{ value: "openai_compatible", label: "OpenAI-compatible" }]}
            />
            <Field
              label="LLM model"
              name="llm_model"
              value={formValues?.llm_model ?? ""}
              placeholder="QuantTrio/Qwen3-VL-32B-Instruct-AWQ"
              disabled={busy}
              onChange={(value) => updateField("llm_model", value)}
            />
            <Field
              label="LLM base URL"
              name="llm_base_url"
              value={formValues?.llm_base_url ?? ""}
              placeholder="http://10.10.9.195:8004/v1"
              disabled={busy}
              required={false}
              onChange={(value) => updateField("llm_base_url", value)}
            />
            <Field
              label="LLM API key"
              name="llm_api_key"
              value=""
              placeholder={settingsQuery.data?.has_llm_api_key ? "Saved key present" : "optional"}
              disabled={busy}
              required={false}
              type="password"
            />
            <Field
              label="LLM timeout (ms)"
              name="llm_timeout_ms"
              value={String(formValues?.llm_timeout_ms ?? 10000)}
              placeholder="10000"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("llm_timeout_ms", Number(value))}
            />
            <div className="min-w-0 text-sm font-medium text-[#3a4a53]">
              <span className="mb-1.5 block truncate">Capabilities</span>
              <div className="flex min-h-10 flex-wrap items-center gap-2 rounded-md border border-[#cfd8dd] px-3 py-2">
                {(formValues?.llm_capabilities ?? []).map((capability) => (
                  <span
                    key={capability}
                    className="rounded bg-[#e8f3f6] px-2 py-1 text-xs font-semibold text-[#176b87]"
                  >
                    {formatCapability(capability)}
                  </span>
                ))}
              </div>
            </div>
          </div>
          <div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="min-h-5 text-sm text-[#62717a]" role="status">
              {llmTestMessage}
            </p>
            <Button
              type="button"
              variant="secondary"
              onClick={(event) => submitForTest(event.currentTarget.form, testLlm)}
              disabled={testLlm.isPending || busy}
            >
              {testLlm.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <PlugZap className="h-4 w-4" aria-hidden="true" />
              )}
              Test LLM
            </Button>
          </div>
        </section>

        <section className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
          <div className="mb-5 flex items-center gap-2">
            <PlugZap className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
            <h3 className="truncate text-base font-semibold text-[#1f2933]">MinerU parser</h3>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="flex h-10 items-center gap-2 self-end rounded-md border border-[#cfd8dd] px-3 text-sm font-medium text-[#3a4a53]">
              <input
                name="mineru_enabled"
                type="checkbox"
                checked={formValues?.mineru_enabled ?? false}
                onChange={(event) => updateField("mineru_enabled", event.target.checked)}
                disabled={busy}
              />
              Enable MinerU
            </label>
            <Field
              label="MinerU base URL"
              name="mineru_base_url"
              value={formValues?.mineru_base_url ?? ""}
              placeholder="http://127.0.0.1:8765"
              disabled={busy}
              required={false}
              onChange={(value) => updateField("mineru_base_url", value)}
            />
            <Field
              label="MinerU timeout (ms)"
              name="mineru_timeout_ms"
              value={String(formValues?.mineru_timeout_ms ?? 1800000)}
              placeholder="1800000"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("mineru_timeout_ms", Number(value))}
            />
            <Field
              label="MinerU poll interval (ms)"
              name="mineru_poll_interval_ms"
              value={String(formValues?.mineru_poll_interval_ms ?? 1000)}
              placeholder="1000"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("mineru_poll_interval_ms", Number(value))}
            />
          </div>
          <div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="min-h-5 text-sm text-[#62717a]" role="status">
              {mineruTestMessage}
            </p>
            <Button
              type="button"
              variant="secondary"
              onClick={(event) => submitForTest(event.currentTarget.form, testMinerU)}
              disabled={testMinerU.isPending || busy}
            >
              {testMinerU.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <PlugZap className="h-4 w-4" aria-hidden="true" />
              )}
              Test MinerU
            </Button>
          </div>
        </section>

        <section className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
          <div className="mb-5 flex items-center gap-2">
            <Settings className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
            <h3 className="truncate text-base font-semibold text-[#1f2933]">Parser, chunking, and context</h3>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Parser"
              name="parser"
              value={formValues?.parser ?? "mineru"}
              placeholder="mineru"
              disabled={busy}
              onChange={(value) => updateField("parser", value)}
            />
            <Field
              label="Parse method"
              name="parse_method"
              value={formValues?.parse_method ?? "auto"}
              placeholder="auto"
              disabled={busy}
              onChange={(value) => updateField("parse_method", value)}
            />
            <Field
              label="Chunk token size"
              name="chunk_token_size"
              value={String(formValues?.chunk_token_size ?? 1200)}
              placeholder="1200"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("chunk_token_size", Number(value))}
            />
            <Field
              label="Chunk overlap tokens"
              name="chunk_overlap_token_size"
              value={String(formValues?.chunk_overlap_token_size ?? 100)}
              placeholder="100"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("chunk_overlap_token_size", Number(value))}
            />
            <CheckboxField
              label="Process images"
              name="enable_image_processing"
              checked={formValues?.enable_image_processing ?? true}
              disabled={busy}
              onChange={(checked) => updateField("enable_image_processing", checked)}
            />
            <CheckboxField
              label="Process tables"
              name="enable_table_processing"
              checked={formValues?.enable_table_processing ?? true}
              disabled={busy}
              onChange={(checked) => updateField("enable_table_processing", checked)}
            />
            <CheckboxField
              label="Process equations"
              name="enable_equation_processing"
              checked={formValues?.enable_equation_processing ?? true}
              disabled={busy}
              onChange={(checked) => updateField("enable_equation_processing", checked)}
            />
            <CheckboxField
              label="Include headers"
              name="include_headers"
              checked={formValues?.include_headers ?? true}
              disabled={busy}
              onChange={(checked) => updateField("include_headers", checked)}
            />
            <CheckboxField
              label="Include captions"
              name="include_captions"
              checked={formValues?.include_captions ?? true}
              disabled={busy}
              onChange={(checked) => updateField("include_captions", checked)}
            />
            <Field
              label="Context window"
              name="context_window"
              value={String(formValues?.context_window ?? 1)}
              placeholder="1"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("context_window", Number(value))}
            />
            <Field
              label="Context mode"
              name="context_mode"
              value={formValues?.context_mode ?? "page"}
              placeholder="page"
              disabled={busy}
              onChange={(value) => updateField("context_mode", value)}
            />
            <Field
              label="Max context tokens"
              name="max_context_tokens"
              value={String(formValues?.max_context_tokens ?? 2000)}
              placeholder="2000"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("max_context_tokens", Number(value))}
            />
          </div>
        </section>

        <section className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
          <div className="mb-5 flex items-center gap-2">
            <Settings className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
            <h3 className="truncate text-base font-semibold text-[#1f2933]">Query defaults, cache, and concurrency</h3>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <SelectField
              label="Query mode"
              name="query_mode"
              value={formValues?.query_mode ?? "mix"}
              disabled={busy}
              onChange={(value) => updateField("query_mode", value as SettingsProfileIn["query_mode"])}
              options={[
                { value: "mix", label: "Mix" },
                { value: "hybrid", label: "Hybrid" },
                { value: "local", label: "Local" },
                { value: "global", label: "Global" },
                { value: "naive", label: "Naive" },
              ]}
            />
            <Field
              label="Top K"
              name="top_k"
              value={String(formValues?.top_k ?? 40)}
              placeholder="40"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("top_k", Number(value))}
            />
            <Field
              label="Chunk top K"
              name="chunk_top_k"
              value={String(formValues?.chunk_top_k ?? 20)}
              placeholder="20"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("chunk_top_k", Number(value))}
            />
            <Field
              label="Cosine threshold"
              name="cosine_better_than_threshold"
              value={String(formValues?.cosine_better_than_threshold ?? 0.2)}
              placeholder="0.2"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("cosine_better_than_threshold", Number(value))}
            />
            <Field
              label="Max total tokens"
              name="max_total_tokens"
              value={String(formValues?.max_total_tokens ?? 30000)}
              placeholder="30000"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("max_total_tokens", Number(value))}
            />
            <Field
              label="Max entity tokens"
              name="max_entity_tokens"
              value={String(formValues?.max_entity_tokens ?? 6000)}
              placeholder="6000"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("max_entity_tokens", Number(value))}
            />
            <Field
              label="Max relation tokens"
              name="max_relation_tokens"
              value={String(formValues?.max_relation_tokens ?? 8000)}
              placeholder="8000"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("max_relation_tokens", Number(value))}
            />
            <CheckboxField
              label="Enable rerank"
              name="enable_rerank"
              checked={formValues?.enable_rerank ?? true}
              disabled={busy}
              onChange={(checked) => updateField("enable_rerank", checked)}
            />
            <CheckboxField
              label="LLM cache"
              name="enable_llm_cache"
              checked={formValues?.enable_llm_cache ?? true}
              disabled={busy}
              onChange={(checked) => updateField("enable_llm_cache", checked)}
            />
            <CheckboxField
              label="Entity cache"
              name="enable_llm_cache_for_entity_extract"
              checked={formValues?.enable_llm_cache_for_entity_extract ?? true}
              disabled={busy}
              onChange={(checked) => updateField("enable_llm_cache_for_entity_extract", checked)}
            />
            <Field
              label="LLM max async"
              name="llm_model_max_async"
              value={String(formValues?.llm_model_max_async ?? 4)}
              placeholder="4"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("llm_model_max_async", Number(value))}
            />
            <Field
              label="Embedding max async"
              name="embedding_func_max_async"
              value={String(formValues?.embedding_func_max_async ?? 8)}
              placeholder="8"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("embedding_func_max_async", Number(value))}
            />
            <Field
              label="Max parallel insert"
              name="max_parallel_insert"
              value={String(formValues?.max_parallel_insert ?? 2)}
              placeholder="2"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("max_parallel_insert", Number(value))}
            />
          </div>
        </section>

        <section className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
          <div className="mb-5 flex items-center gap-2">
            <PlugZap className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
            <h3 className="truncate text-base font-semibold text-[#1f2933]">Embeddings</h3>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <SelectField
              label="Embedding provider"
              name="embedding_provider"
              value={formValues?.embedding_provider ?? "fallback"}
              disabled={busy}
              onChange={(value) =>
                updateField("embedding_provider", value as "fallback" | "vllm_openai")
              }
              options={[
                { value: "fallback", label: "Local fallback" },
                { value: "vllm_openai", label: "vLLM / OpenAI-compatible" },
              ]}
            />
            <Field
              label="Embedding model"
              name="embedding_model"
              value={formValues?.embedding_model ?? ""}
              placeholder="Qwen/Qwen3-Embedding-8B"
              disabled={busy}
              onChange={(value) => updateField("embedding_model", value)}
            />
            <Field
              label="Base URL"
              name="embedding_base_url"
              value={formValues?.embedding_base_url ?? ""}
              placeholder="http://127.0.0.1:8001/v1"
              disabled={busy}
              required={false}
              onChange={(value) => updateField("embedding_base_url", value)}
            />
            <Field
              label="API key"
              name="embedding_api_key"
              value=""
              placeholder={settingsQuery.data?.has_embedding_api_key ? "Saved key present" : "optional"}
              disabled={busy}
              required={false}
              type="password"
            />
            <Field
              label="Timeout (ms)"
              name="embedding_timeout_ms"
              value={String(formValues?.embedding_timeout_ms ?? 10000)}
              placeholder="10000"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("embedding_timeout_ms", Number(value))}
            />
            <Field
              label="Dimensions"
              name="embedding_dimensions"
              value={String(formValues?.embedding_dimensions ?? 1536)}
              placeholder="1536"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("embedding_dimensions", Number(value))}
            />
            <Field
              label="Batch size"
              name="embedding_batch_size"
              value={String(formValues?.embedding_batch_size ?? 16)}
              placeholder="16"
              disabled={busy}
              type="number"
              onChange={(value) => updateField("embedding_batch_size", Number(value))}
            />
            <label className="flex h-10 items-center gap-2 self-end rounded-md border border-[#cfd8dd] px-3 text-sm font-medium text-[#3a4a53]">
              <input
                name="embedding_tls_verify"
                type="checkbox"
                checked={formValues?.embedding_tls_verify ?? true}
                onChange={(event) => updateField("embedding_tls_verify", event.target.checked)}
                disabled={busy}
              />
              Verify TLS
            </label>
          </div>
          <div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="min-h-5 text-sm text-[#62717a]" role="status">
              {testMessage}
            </p>
            <Button
              type="button"
              variant="secondary"
              onClick={(event) => submitForTest(event.currentTarget.form, testEmbedding)}
              disabled={testEmbedding.isPending || busy}
            >
              {testEmbedding.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <PlugZap className="h-4 w-4" aria-hidden="true" />
              )}
              Test connection
            </Button>
          </div>
        </section>

        <div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="min-h-5 text-sm text-[#62717a]" role="status">
            {updateSettings.isSuccess ? "Saved" : message}
          </p>
          <div className="flex shrink-0 gap-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setFormOverride(null);
              }}
              disabled={busy}
            >
              Reset
            </Button>
            <Button type="submit" disabled={busy}>
              {updateSettings.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Save className="h-4 w-4" aria-hidden="true" />
              )}
              Save
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}

function Field({
  label,
  name,
  value,
  placeholder,
  disabled,
  required = true,
  type = "text",
  onChange,
}: {
  label: string;
  name: keyof SettingsProfileIn;
  value: string;
  placeholder: string;
  disabled: boolean;
  required?: boolean;
  type?: string;
  onChange?: (value: string) => void;
}) {
  return (
    <label className="min-w-0 text-sm font-medium text-[#3a4a53]">
      <span className="mb-1.5 block truncate">{label}</span>
      <input
        className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20 disabled:bg-[#f4f7f8]"
        type={type}
        name={name}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        required={required}
        onChange={(event) => onChange?.(event.target.value)}
      />
    </label>
  );
}

function SelectField({
  label,
  name,
  value,
  disabled,
  options,
  onChange,
}: {
  label: string;
  name: keyof SettingsProfileIn;
  value: string;
  disabled: boolean;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <label className="min-w-0 text-sm font-medium text-[#3a4a53]">
      <span className="mb-1.5 block truncate">{label}</span>
      <select
        className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20 disabled:bg-[#f4f7f8]"
        name={name}
        value={value}
        disabled={disabled}
        required
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function CheckboxField({
  label,
  name,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  name: keyof SettingsProfileIn;
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex h-10 items-center gap-2 self-end rounded-md border border-[#cfd8dd] px-3 text-sm font-medium text-[#3a4a53]">
      <input
        name={name}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        disabled={disabled}
      />
      {label}
    </label>
  );
}

function formatCapability(capability: string) {
  return capability === "text" ? "Text" : capability === "vision" ? "Vision" : "Reasoning";
}

function settingsToFormValues(settings: SettingsProfileOut): SettingsProfileIn {
  return {
    provider: settings.provider,
    llm_provider: settings.llm_provider,
    llm_model: settings.llm_model,
    llm_base_url: settings.llm_base_url ?? "",
    llm_timeout_ms: settings.llm_timeout_ms,
    llm_capabilities: settings.llm_capabilities,
    embedding_model: settings.embedding_model,
    storage_backend: settings.storage_backend,
    embedding_provider: settings.embedding_provider,
    embedding_base_url: settings.embedding_base_url ?? "",
    embedding_timeout_ms: settings.embedding_timeout_ms,
    embedding_dimensions: settings.embedding_dimensions,
    embedding_batch_size: settings.embedding_batch_size,
    embedding_tls_verify: settings.embedding_tls_verify,
    mineru_enabled: settings.mineru_enabled,
    mineru_base_url: settings.mineru_base_url ?? "",
    mineru_timeout_ms: settings.mineru_timeout_ms,
    mineru_poll_interval_ms: settings.mineru_poll_interval_ms,
    runtime_mode: settings.runtime_mode,
    vision_model: settings.vision_model ?? "",
    vision_base_url: settings.vision_base_url ?? "",
    vision_timeout_ms: settings.vision_timeout_ms,
    reranker_provider: settings.reranker_provider,
    reranker_model: settings.reranker_model ?? "",
    reranker_base_url: settings.reranker_base_url ?? "",
    reranker_timeout_ms: settings.reranker_timeout_ms,
    pgvector_schema: settings.pgvector_schema,
    pgvector_table_prefix: settings.pgvector_table_prefix,
    neo4j_uri: settings.neo4j_uri ?? "",
    neo4j_username: settings.neo4j_username ?? "",
    parser: settings.parser,
    parse_method: settings.parse_method,
    chunk_token_size: settings.chunk_token_size,
    chunk_overlap_token_size: settings.chunk_overlap_token_size,
    enable_image_processing: settings.enable_image_processing,
    enable_table_processing: settings.enable_table_processing,
    enable_equation_processing: settings.enable_equation_processing,
    context_window: settings.context_window,
    context_mode: settings.context_mode,
    max_context_tokens: settings.max_context_tokens,
    include_headers: settings.include_headers,
    include_captions: settings.include_captions,
    query_mode: settings.query_mode,
    top_k: settings.top_k,
    chunk_top_k: settings.chunk_top_k,
    enable_rerank: settings.enable_rerank,
    cosine_better_than_threshold: settings.cosine_better_than_threshold,
    max_total_tokens: settings.max_total_tokens,
    max_entity_tokens: settings.max_entity_tokens,
    max_relation_tokens: settings.max_relation_tokens,
    enable_llm_cache: settings.enable_llm_cache,
    enable_llm_cache_for_entity_extract: settings.enable_llm_cache_for_entity_extract,
    llm_model_max_async: settings.llm_model_max_async,
    embedding_func_max_async: settings.embedding_func_max_async,
    max_parallel_insert: settings.max_parallel_insert,
  };
}

function getMessage(settingsError: Error | null, mutationError: Error | null) {
  if (mutationError) {
    return mutationError.message;
  }
  if (settingsError instanceof ApiError && settingsError.status === 404) {
    return "No default profile saved";
  }
  if (settingsError) {
    return settingsError.message;
  }
  return "";
}
