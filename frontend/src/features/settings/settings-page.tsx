import { type ChangeEvent, type FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, PlugZap, RefreshCcw, RotateCcw, Save, Settings } from "lucide-react";

import { ApiError, apiClient } from "../../api/client";
import type {
  MinerUConnectionTestOut,
  SettingsProfileIn,
  SettingsProfileOut,
} from "../../api/generated";
import { Button } from "../../components/ui/button";

const queryKeys = {
  settings: ["settings", "default"],
  defaults: ["defaults"],
} as const;

type SecretFieldName =
  | "embedding_api_key"
  | "llm_api_key"
  | "vision_api_key"
  | "reranker_api_key"
  | "neo4j_password";

type SecretValues = Record<SecretFieldName, string>;
type NumberFieldName = Extract<
  keyof SettingsProfileIn,
  | "vision_timeout_ms"
  | "reranker_timeout_ms"
  | "llm_timeout_ms"
  | "mineru_timeout_ms"
  | "mineru_poll_interval_ms"
  | "mineru_max_concurrent_files"
  | "chunk_token_size"
  | "chunk_overlap_token_size"
  | "context_window"
  | "max_context_tokens"
  | "top_k"
  | "chunk_top_k"
  | "cosine_better_than_threshold"
  | "max_total_tokens"
  | "max_entity_tokens"
  | "max_relation_tokens"
  | "llm_model_max_async"
  | "embedding_func_max_async"
  | "max_parallel_insert"
  | "embedding_timeout_ms"
  | "embedding_dimensions"
  | "embedding_batch_size"
>;
type NumberDrafts = Partial<Record<NumberFieldName, string>>;
type NumberConstraints = { min: number; max?: number; step?: number | "any" };

const blankSecretValues = (): SecretValues => ({
  embedding_api_key: "",
  llm_api_key: "",
  vision_api_key: "",
  reranker_api_key: "",
  neo4j_password: "",
});

const DEFAULT_MANIFEST_URL = "https://updates.jihadaj.com/providers.json";
const DEFAULT_MINERU_TIMEOUT_MS = 14_400_000;
const MIN_RUNTIME_TIMEOUT_MS = 100;
const MAX_RUNTIME_TIMEOUT_MS = 1_800_000;
const NUMBER_CONSTRAINTS: Record<NumberFieldName, NumberConstraints> = {
  vision_timeout_ms: { min: MIN_RUNTIME_TIMEOUT_MS, max: MAX_RUNTIME_TIMEOUT_MS },
  reranker_timeout_ms: { min: MIN_RUNTIME_TIMEOUT_MS, max: MAX_RUNTIME_TIMEOUT_MS },
  llm_timeout_ms: { min: MIN_RUNTIME_TIMEOUT_MS, max: MAX_RUNTIME_TIMEOUT_MS },
  mineru_timeout_ms: { min: 1, max: DEFAULT_MINERU_TIMEOUT_MS },
  mineru_poll_interval_ms: { min: 100, max: 60_000 },
  mineru_max_concurrent_files: { min: 1, max: 8 },
  chunk_token_size: { min: 1, max: 128_000 },
  chunk_overlap_token_size: { min: 0, max: 128_000 },
  context_window: { min: 0, max: 100 },
  max_context_tokens: { min: 1, max: 1_000_000 },
  top_k: { min: 1, max: 1_000 },
  chunk_top_k: { min: 1, max: 1_000 },
  cosine_better_than_threshold: { min: 0, max: 1, step: 0.01 },
  max_total_tokens: { min: 1, max: 1_000_000 },
  max_entity_tokens: { min: 1, max: 1_000_000 },
  max_relation_tokens: { min: 1, max: 1_000_000 },
  llm_model_max_async: { min: 1, max: 256 },
  embedding_func_max_async: { min: 1, max: 256 },
  max_parallel_insert: { min: 1, max: 64 },
  embedding_timeout_ms: { min: MIN_RUNTIME_TIMEOUT_MS, max: MAX_RUNTIME_TIMEOUT_MS },
  embedding_dimensions: { min: 1, max: 1_000_000 },
  embedding_batch_size: { min: 1, max: 10_000 },
};
const DEFAULT_FORM_VALUES: SettingsProfileIn = {
  provider: "openai-compatible",
  llm_provider: "openai_compatible",
  llm_model: "gpt-4o-mini",
  llm_base_url: "",
  llm_timeout_ms: 10000,
  llm_capabilities: [],
  embedding_model: "Qwen/Qwen3-Embedding-8B",
  storage_backend: "postgres_pgvector_neo4j",
  embedding_provider: "vllm_openai",
  embedding_base_url: "",
  embedding_timeout_ms: 10000,
  embedding_dimensions: 1536,
  embedding_batch_size: 16,
  embedding_tls_verify: true,
  mineru_enabled: false,
  mineru_base_url: "",
  mineru_timeout_ms: DEFAULT_MINERU_TIMEOUT_MS,
  mineru_poll_interval_ms: 1_000,
  mineru_require_hpc: true,
  mineru_backend: "pipeline",
  mineru_device: "cuda:0",
  mineru_lang: "",
  mineru_formula: true,
  mineru_table: true,
  mineru_source: "",
  mineru_max_concurrent_files: 1,
  runtime_mode: "runtime",
  vision_model: "",
  vision_base_url: "",
  vision_timeout_ms: 10000,
  reranker_provider: "disabled",
  reranker_fallback_provider: "disabled",
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
  const [secretValues, setSecretValues] = useState<SecretValues>(() => blankSecretValues());
  const [numberDrafts, setNumberDrafts] = useState<NumberDrafts>({});
  const [manifestUrl, setManifestUrl] = useState(DEFAULT_MANIFEST_URL);
  const [syncMessage, setSyncMessage] = useState("");

  const settingsQuery = useQuery({
    queryKey: queryKeys.settings,
    queryFn: apiClient.defaultSettings,
    retry: (failureCount, error) =>
      error instanceof ApiError && error.status === 404 ? false : failureCount < 2,
  });
  const defaultsQuery = useQuery({
    queryKey: queryKeys.defaults,
    queryFn: apiClient.defaults,
    staleTime: 60_000,
  });

  const settingsMissing =
    settingsQuery.error instanceof ApiError && settingsQuery.error.status === 404;
  const runtimeDefaults = defaultsQuery.data?.runtime ?? DEFAULT_FORM_VALUES;
  const loadedValues = settingsQuery.data
    ? settingsToFormValues(settingsQuery.data)
    : settingsMissing
      ? { ...DEFAULT_FORM_VALUES, ...runtimeDefaults }
      : null;
  const formValues = formOverride ?? loadedValues;

  const updateSettings = useMutation({
    mutationFn: apiClient.updateDefaultSettings,
    onSuccess: (settings) => {
      queryClient.setQueryData(queryKeys.settings, settings);
      setFormOverride(settingsToFormValues(settings));
      setSecretValues(blankSecretValues());
      setNumberDrafts({});
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
  const testReranker = useMutation({
    mutationFn: apiClient.testRerankerSettings,
  });
  const testMinerU = useMutation({
    mutationFn: apiClient.testMinerUSettings,
  });

  const updateField = <K extends keyof SettingsProfileIn>(key: K, value: SettingsProfileIn[K]) => {
    setFormOverride((current) => (formValues ? { ...formValues, ...current, [key]: value } : current));
  };

  const updateNumberField = (key: NumberFieldName, rawValue: string) => {
    setNumberDrafts((current) => ({ ...current, [key]: rawValue }));
    if (rawValue.trim() === "") {
      return;
    }
    const parsed = Number(rawValue);
    if (!Number.isFinite(parsed)) {
      return;
    }
    setFormOverride((current) =>
      formValues ? { ...formValues, ...current, [key]: parsed } : current,
    );
  };

  const commitNumberField = (key: NumberFieldName, fallback: number) => {
    const rawValue = numberDrafts[key];
    if (rawValue == null) {
      return;
    }
    const parsed = Number(rawValue);
    if (rawValue.trim() === "" || !Number.isFinite(parsed)) {
      setNumberDrafts((current) => withoutNumberDraft(current, key));
      return;
    }
    const constrained = constrainNumber(parsed, NUMBER_CONSTRAINTS[key]);
    setFormOverride((current) =>
      formValues ? { ...formValues, ...current, [key]: constrained } : current,
    );
    setNumberDrafts((current) => ({ ...withoutNumberDraft(current, key), [key]: String(constrained) }));
    if (constrained === (formValues?.[key] ?? fallback)) {
      setNumberDrafts((current) => withoutNumberDraft(current, key));
    }
  };

  const numberValue = (key: NumberFieldName, fallback: number) =>
    numberDrafts[key] ?? String(formValues?.[key] ?? fallback);

  const updateSecretField = (key: SecretFieldName, value: string) => {
    setSecretValues((current) => ({ ...current, [key]: value }));
  };

  const updateRuntimeMode = (value: SettingsProfileIn["runtime_mode"]) => {
    setFormOverride((current) => {
      if (!formValues) {
        return current;
      }
      return { ...formValues, ...current, runtime_mode: value, storage_backend: "postgres_pgvector_neo4j" };
    });
  };

  const updateStorageBackend = (value: SettingsProfileIn["storage_backend"]) => {
    setFormOverride((current) => {
      if (!formValues) {
        return current;
      }
      return { ...formValues, ...current, storage_backend: value, runtime_mode: "runtime" };
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
      llm_timeout_ms: constrainNumber(
        formValues.llm_timeout_ms ?? runtimeDefaults.llm_timeout_ms,
        NUMBER_CONSTRAINTS.llm_timeout_ms,
      ),
      embedding_provider: formValues.embedding_provider ?? "vllm_openai",
      embedding_timeout_ms: constrainNumber(
        formValues.embedding_timeout_ms ?? runtimeDefaults.embedding_timeout_ms,
        NUMBER_CONSTRAINTS.embedding_timeout_ms,
      ),
      embedding_dimensions: constrainNumber(
        formValues.embedding_dimensions ?? runtimeDefaults.embedding_dimensions,
        NUMBER_CONSTRAINTS.embedding_dimensions,
      ),
      embedding_batch_size: constrainNumber(
        formValues.embedding_batch_size ?? runtimeDefaults.embedding_batch_size,
        NUMBER_CONSTRAINTS.embedding_batch_size,
      ),
      embedding_tls_verify: formValues.embedding_tls_verify ?? true,
      mineru_enabled: formValues.mineru_enabled ?? false,
      mineru_timeout_ms: constrainNumber(
        formValues.mineru_timeout_ms ?? runtimeDefaults.mineru_timeout_ms,
        NUMBER_CONSTRAINTS.mineru_timeout_ms,
      ),
      mineru_poll_interval_ms: constrainNumber(
        formValues.mineru_poll_interval_ms ?? runtimeDefaults.mineru_poll_interval_ms,
        NUMBER_CONSTRAINTS.mineru_poll_interval_ms,
      ),
      mineru_require_hpc: formValues.mineru_require_hpc ?? true,
      mineru_backend: formValues.mineru_backend || "pipeline",
      mineru_device: formValues.mineru_device || "cuda:0",
      mineru_lang: formValues.mineru_lang || null,
      mineru_formula: formValues.mineru_formula ?? true,
      mineru_table: formValues.mineru_table ?? true,
      mineru_source: formValues.mineru_source || null,
      mineru_max_concurrent_files: constrainNumber(
        formValues.mineru_max_concurrent_files ?? runtimeDefaults.mineru_max_concurrent_files,
        NUMBER_CONSTRAINTS.mineru_max_concurrent_files,
      ),
      runtime_mode: formValues.runtime_mode ?? "runtime",
      storage_backend: formValues.storage_backend ?? "postgres_pgvector_neo4j",
      vision_timeout_ms: constrainNumber(
        formValues.vision_timeout_ms ?? runtimeDefaults.vision_timeout_ms,
        NUMBER_CONSTRAINTS.vision_timeout_ms,
      ),
      reranker_provider: formValues.reranker_provider ?? "disabled",
      reranker_fallback_provider: formValues.reranker_fallback_provider ?? "disabled",
      reranker_timeout_ms: constrainNumber(
        formValues.reranker_timeout_ms ?? runtimeDefaults.reranker_timeout_ms,
        NUMBER_CONSTRAINTS.reranker_timeout_ms,
      ),
      pgvector_schema: formValues.pgvector_schema ?? "public",
      pgvector_table_prefix: formValues.pgvector_table_prefix ?? "ragstudio",
      parser: formValues.parser ?? "mineru",
      parse_method: formValues.parse_method ?? "auto",
      chunk_token_size: constrainNumber(
        formValues.chunk_token_size ?? runtimeDefaults.chunk_token_size,
        NUMBER_CONSTRAINTS.chunk_token_size,
      ),
      chunk_overlap_token_size: constrainNumber(
        formValues.chunk_overlap_token_size ?? runtimeDefaults.chunk_overlap_token_size,
        NUMBER_CONSTRAINTS.chunk_overlap_token_size,
      ),
      enable_image_processing: formValues.enable_image_processing ?? true,
      enable_table_processing: formValues.enable_table_processing ?? true,
      enable_equation_processing: formValues.enable_equation_processing ?? true,
      context_window: constrainNumber(
        formValues.context_window ?? runtimeDefaults.context_window,
        NUMBER_CONSTRAINTS.context_window,
      ),
      context_mode: formValues.context_mode ?? "page",
      max_context_tokens: constrainNumber(
        formValues.max_context_tokens ?? runtimeDefaults.max_context_tokens,
        NUMBER_CONSTRAINTS.max_context_tokens,
      ),
      include_headers: formValues.include_headers ?? true,
      include_captions: formValues.include_captions ?? true,
      query_mode: formValues.query_mode ?? "mix",
      top_k: constrainNumber(formValues.top_k ?? runtimeDefaults.top_k, NUMBER_CONSTRAINTS.top_k),
      chunk_top_k: constrainNumber(
        formValues.chunk_top_k ?? runtimeDefaults.chunk_top_k,
        NUMBER_CONSTRAINTS.chunk_top_k,
      ),
      enable_rerank: formValues.enable_rerank ?? true,
      cosine_better_than_threshold: constrainNumber(
        formValues.cosine_better_than_threshold
          ?? runtimeDefaults.cosine_better_than_threshold,
        NUMBER_CONSTRAINTS.cosine_better_than_threshold,
      ),
      max_total_tokens: constrainNumber(
        formValues.max_total_tokens ?? runtimeDefaults.max_total_tokens,
        NUMBER_CONSTRAINTS.max_total_tokens,
      ),
      max_entity_tokens: constrainNumber(
        formValues.max_entity_tokens ?? runtimeDefaults.max_entity_tokens,
        NUMBER_CONSTRAINTS.max_entity_tokens,
      ),
      max_relation_tokens: constrainNumber(
        formValues.max_relation_tokens ?? runtimeDefaults.max_relation_tokens,
        NUMBER_CONSTRAINTS.max_relation_tokens,
      ),
      enable_llm_cache: formValues.enable_llm_cache ?? true,
      enable_llm_cache_for_entity_extract: formValues.enable_llm_cache_for_entity_extract ?? true,
      llm_model_max_async: constrainNumber(
        formValues.llm_model_max_async ?? runtimeDefaults.llm_model_max_async,
        NUMBER_CONSTRAINTS.llm_model_max_async,
      ),
      embedding_func_max_async: constrainNumber(
        formValues.embedding_func_max_async ?? runtimeDefaults.embedding_func_max_async,
        NUMBER_CONSTRAINTS.embedding_func_max_async,
      ),
      max_parallel_insert: constrainNumber(
        formValues.max_parallel_insert ?? runtimeDefaults.max_parallel_insert,
        NUMBER_CONSTRAINTS.max_parallel_insert,
      ),
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
    if (!event.currentTarget.reportValidity()) {
      return;
    }
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
    mutation: typeof testEmbedding | typeof testLlm | typeof testReranker | typeof testMinerU,
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
  const rerankerUsesLlm =
    formValues?.reranker_provider === "llm" || formValues?.reranker_fallback_provider === "llm";
  const rerankerTestMessage = testReranker.error
    ? testReranker.error.message
    : testReranker.data
      ? `${testReranker.data.ok ? "Connected" : "Failed"}: ${testReranker.data.detail}`
      : settingsQuery.data?.has_reranker_api_key
        ? "Saved API key present"
        : rerankerUsesLlm && settingsQuery.data?.has_llm_api_key
          ? "Saved LLM API key present"
        : "";
  const mineruOptimizationMessage = testMinerU.data
    ? missingMinerUOptimizationDetail(
        testMinerU.data.detail,
        mineruReportedOptimization(testMinerU.data),
      )
    : "";
  const mineruTestMessage = testMinerU.error
    ? testMinerU.error.message
    : testMinerU.data
      ? `${testMinerU.data.ok ? "Connected" : "Failed"}: ${testMinerU.data.detail}${
          mineruOptimizationMessage ? ` ${mineruOptimizationMessage}` : ""
        }`
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
          onClick={() => {
            setSecretValues(blankSecretValues());
            void settingsQuery.refetch();
          }}
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
              value={formValues?.runtime_mode ?? "runtime"}
              disabled={busy}
              onChange={(value) => updateRuntimeMode(value as SettingsProfileIn["runtime_mode"])}
              options={[
                { value: "runtime", label: "Native runtime" },
              ]}
            />
            <SelectField
              label="Storage backend"
              name="storage_backend"
              value={formValues?.storage_backend ?? "postgres_pgvector_neo4j"}
              disabled={busy}
              onChange={(value) => updateStorageBackend(value as SettingsProfileIn["storage_backend"])}
              options={[
                { value: "postgres_pgvector_neo4j", label: "Postgres + PGVector + Neo4j" },
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
              value={secretValues.neo4j_password}
              placeholder={settingsQuery.data?.has_neo4j_password ? "Saved password present" : "optional"}
              disabled={busy}
              required={false}
              type="password"
              onChange={(value) => updateSecretField("neo4j_password", value)}
            />
          </div>
          {formValues?.runtime_mode === "runtime" ? (
            <p className="mt-4 rounded-md border border-[#f0d68a] bg-[#fff8e6] px-3 py-2 text-sm text-[#7a5b00]" role="status">
              Native runtime uses RAG-Anything, PGVector, and Neo4j when dependencies are healthy.
            </p>
          ) : null}
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
              value={secretValues.vision_api_key}
              placeholder={settingsQuery.data?.has_vision_api_key ? "Saved key present" : "optional"}
              disabled={busy}
              required={false}
              type="password"
              onChange={(value) => updateSecretField("vision_api_key", value)}
            />
            <Field
              label="Vision timeout (ms)"
              name="vision_timeout_ms"
              value={numberValue("vision_timeout_ms", runtimeDefaults.vision_timeout_ms)}
              placeholder="10000"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.vision_timeout_ms}
              onChange={(value) => updateNumberField("vision_timeout_ms", value)}
              onBlur={() => commitNumberField("vision_timeout_ms", runtimeDefaults.vision_timeout_ms)}
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
                { value: "llm", label: "Existing LLM" },
              ]}
            />
            <SelectField
              label="Reranker fallback"
              name="reranker_fallback_provider"
              value={formValues?.reranker_fallback_provider ?? "disabled"}
              disabled={busy}
              onChange={(value) =>
                updateField(
                  "reranker_fallback_provider",
                  value as SettingsProfileIn["reranker_fallback_provider"],
                )
              }
              options={[
                { value: "disabled", label: "Disabled" },
                { value: "llm", label: "Existing LLM" },
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
              value={secretValues.reranker_api_key}
              placeholder={settingsQuery.data?.has_reranker_api_key ? "Saved key present" : "optional"}
              disabled={busy}
              required={false}
              type="password"
              onChange={(value) => updateSecretField("reranker_api_key", value)}
            />
            <Field
              label="Reranker timeout (ms)"
              name="reranker_timeout_ms"
              value={numberValue("reranker_timeout_ms", runtimeDefaults.reranker_timeout_ms)}
              placeholder="10000"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.reranker_timeout_ms}
              onChange={(value) => updateNumberField("reranker_timeout_ms", value)}
              onBlur={() => commitNumberField("reranker_timeout_ms", runtimeDefaults.reranker_timeout_ms)}
            />
          </div>
          <div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="min-h-5 text-sm text-[#62717a]" role="status">
              {rerankerTestMessage}
            </p>
            <Button
              type="button"
              variant="secondary"
              onClick={(event) => submitForTest(event.currentTarget.form, testReranker)}
              disabled={testReranker.isPending || busy}
            >
              {testReranker.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <PlugZap className="h-4 w-4" aria-hidden="true" />
              )}
              Test Reranker
            </Button>
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
              value={secretValues.llm_api_key}
              placeholder={settingsQuery.data?.has_llm_api_key ? "Saved key present" : "optional"}
              disabled={busy}
              required={false}
              type="password"
              onChange={(value) => updateSecretField("llm_api_key", value)}
            />
            <Field
              label="LLM timeout (ms)"
              name="llm_timeout_ms"
              value={numberValue("llm_timeout_ms", runtimeDefaults.llm_timeout_ms)}
              placeholder="10000"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.llm_timeout_ms}
              onChange={(value) => updateNumberField("llm_timeout_ms", value)}
              onBlur={() => commitNumberField("llm_timeout_ms", runtimeDefaults.llm_timeout_ms)}
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
              value={numberValue("mineru_timeout_ms", runtimeDefaults.mineru_timeout_ms)}
              placeholder={String(DEFAULT_MINERU_TIMEOUT_MS)}
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.mineru_timeout_ms}
              onChange={(value) => updateNumberField("mineru_timeout_ms", value)}
              onBlur={() => commitNumberField("mineru_timeout_ms", runtimeDefaults.mineru_timeout_ms)}
            />
            <Field
              label="MinerU poll interval (ms)"
              name="mineru_poll_interval_ms"
              value={numberValue(
                "mineru_poll_interval_ms",
                runtimeDefaults.mineru_poll_interval_ms,
              )}
              placeholder="1000"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.mineru_poll_interval_ms}
              onChange={(value) => updateNumberField("mineru_poll_interval_ms", value)}
              onBlur={() => commitNumberField(
                "mineru_poll_interval_ms",
                runtimeDefaults.mineru_poll_interval_ms,
              )}
            />
            <CheckboxField
              label="Require HPC MinerU coordinator"
              name="mineru_require_hpc"
              checked={formValues?.mineru_require_hpc ?? true}
              disabled={busy}
              onChange={(checked) => updateField("mineru_require_hpc", checked)}
            />
            <Field
              label="MinerU backend"
              name="mineru_backend"
              value={formValues?.mineru_backend ?? "pipeline"}
              placeholder="pipeline"
              disabled={busy}
              onChange={(value) => updateField("mineru_backend", value)}
            />
            <Field
              label="MinerU device"
              name="mineru_device"
              value={formValues?.mineru_device ?? "cuda:0"}
              placeholder="cuda:0"
              disabled={busy}
              onChange={(value) => updateField("mineru_device", value)}
            />
            <Field
              label="MinerU language"
              name="mineru_lang"
              value={formValues?.mineru_lang ?? ""}
              placeholder="arabic"
              disabled={busy}
              required={false}
              onChange={(value) => updateField("mineru_lang", value)}
            />
            <Field
              label="MinerU source"
              name="mineru_source"
              value={formValues?.mineru_source ?? ""}
              placeholder="huggingface"
              disabled={busy}
              required={false}
              onChange={(value) => updateField("mineru_source", value)}
            />
            <Field
              label="MinerU max concurrent files"
              name="mineru_max_concurrent_files"
              value={numberValue(
                "mineru_max_concurrent_files",
                runtimeDefaults.mineru_max_concurrent_files,
              )}
              placeholder="1"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.mineru_max_concurrent_files}
              onChange={(value) => updateNumberField("mineru_max_concurrent_files", value)}
              onBlur={() => commitNumberField(
                "mineru_max_concurrent_files",
                runtimeDefaults.mineru_max_concurrent_files,
              )}
            />
            <CheckboxField
              label="Parse formulas"
              name="mineru_formula"
              checked={formValues?.mineru_formula ?? true}
              disabled={busy}
              onChange={(checked) => updateField("mineru_formula", checked)}
            />
            <CheckboxField
              label="Parse tables"
              name="mineru_table"
              checked={formValues?.mineru_table ?? true}
              disabled={busy}
              onChange={(checked) => updateField("mineru_table", checked)}
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
              value={numberValue("chunk_token_size", runtimeDefaults.chunk_token_size)}
              placeholder="1200"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.chunk_token_size}
              onChange={(value) => updateNumberField("chunk_token_size", value)}
              onBlur={() => commitNumberField("chunk_token_size", runtimeDefaults.chunk_token_size)}
            />
            <Field
              label="Chunk overlap tokens"
              name="chunk_overlap_token_size"
              value={numberValue(
                "chunk_overlap_token_size",
                runtimeDefaults.chunk_overlap_token_size,
              )}
              placeholder="100"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.chunk_overlap_token_size}
              onChange={(value) => updateNumberField("chunk_overlap_token_size", value)}
              onBlur={() => commitNumberField(
                "chunk_overlap_token_size",
                runtimeDefaults.chunk_overlap_token_size,
              )}
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
              value={numberValue("context_window", runtimeDefaults.context_window)}
              placeholder="1"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.context_window}
              onChange={(value) => updateNumberField("context_window", value)}
              onBlur={() => commitNumberField("context_window", runtimeDefaults.context_window)}
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
              value={numberValue("max_context_tokens", runtimeDefaults.max_context_tokens)}
              placeholder="2000"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.max_context_tokens}
              onChange={(value) => updateNumberField("max_context_tokens", value)}
              onBlur={() => commitNumberField("max_context_tokens", runtimeDefaults.max_context_tokens)}
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
              value={numberValue("top_k", runtimeDefaults.top_k)}
              placeholder="40"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.top_k}
              onChange={(value) => updateNumberField("top_k", value)}
              onBlur={() => commitNumberField("top_k", runtimeDefaults.top_k)}
            />
            <Field
              label="Chunk top K"
              name="chunk_top_k"
              value={numberValue("chunk_top_k", runtimeDefaults.chunk_top_k)}
              placeholder="20"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.chunk_top_k}
              onChange={(value) => updateNumberField("chunk_top_k", value)}
              onBlur={() => commitNumberField("chunk_top_k", runtimeDefaults.chunk_top_k)}
            />
            <Field
              label="Cosine threshold"
              name="cosine_better_than_threshold"
              value={numberValue(
                "cosine_better_than_threshold",
                runtimeDefaults.cosine_better_than_threshold,
              )}
              placeholder="0.2"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.cosine_better_than_threshold}
              onChange={(value) => updateNumberField("cosine_better_than_threshold", value)}
              onBlur={() => commitNumberField(
                "cosine_better_than_threshold",
                runtimeDefaults.cosine_better_than_threshold,
              )}
            />
            <Field
              label="Max total tokens"
              name="max_total_tokens"
              value={numberValue("max_total_tokens", runtimeDefaults.max_total_tokens)}
              placeholder="30000"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.max_total_tokens}
              onChange={(value) => updateNumberField("max_total_tokens", value)}
              onBlur={() => commitNumberField("max_total_tokens", runtimeDefaults.max_total_tokens)}
            />
            <Field
              label="Max entity tokens"
              name="max_entity_tokens"
              value={numberValue("max_entity_tokens", runtimeDefaults.max_entity_tokens)}
              placeholder="6000"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.max_entity_tokens}
              onChange={(value) => updateNumberField("max_entity_tokens", value)}
              onBlur={() => commitNumberField("max_entity_tokens", runtimeDefaults.max_entity_tokens)}
            />
            <Field
              label="Max relation tokens"
              name="max_relation_tokens"
              value={numberValue("max_relation_tokens", runtimeDefaults.max_relation_tokens)}
              placeholder="8000"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.max_relation_tokens}
              onChange={(value) => updateNumberField("max_relation_tokens", value)}
              onBlur={() => commitNumberField(
                "max_relation_tokens",
                runtimeDefaults.max_relation_tokens,
              )}
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
              value={numberValue("llm_model_max_async", runtimeDefaults.llm_model_max_async)}
              placeholder="4"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.llm_model_max_async}
              onChange={(value) => updateNumberField("llm_model_max_async", value)}
              onBlur={() => commitNumberField(
                "llm_model_max_async",
                runtimeDefaults.llm_model_max_async,
              )}
            />
            <Field
              label="Embedding max async"
              name="embedding_func_max_async"
              value={numberValue(
                "embedding_func_max_async",
                runtimeDefaults.embedding_func_max_async,
              )}
              placeholder="8"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.embedding_func_max_async}
              onChange={(value) => updateNumberField("embedding_func_max_async", value)}
              onBlur={() => commitNumberField(
                "embedding_func_max_async",
                runtimeDefaults.embedding_func_max_async,
              )}
            />
            <Field
              label="Max parallel insert"
              name="max_parallel_insert"
              value={numberValue("max_parallel_insert", runtimeDefaults.max_parallel_insert)}
              placeholder="2"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.max_parallel_insert}
              onChange={(value) => updateNumberField("max_parallel_insert", value)}
              onBlur={() => commitNumberField(
                "max_parallel_insert",
                runtimeDefaults.max_parallel_insert,
              )}
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
              value={formValues?.embedding_provider ?? "vllm_openai"}
              disabled={busy}
              onChange={(value) =>
                updateField("embedding_provider", value as "vllm_openai")
              }
              options={[
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
              value={secretValues.embedding_api_key}
              placeholder={settingsQuery.data?.has_embedding_api_key ? "Saved key present" : "optional"}
              disabled={busy}
              required={false}
              type="password"
              onChange={(value) => updateSecretField("embedding_api_key", value)}
            />
            <Field
              label="Timeout (ms)"
              name="embedding_timeout_ms"
              value={numberValue("embedding_timeout_ms", runtimeDefaults.embedding_timeout_ms)}
              placeholder="10000"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.embedding_timeout_ms}
              onChange={(value) => updateNumberField("embedding_timeout_ms", value)}
              onBlur={() => commitNumberField(
                "embedding_timeout_ms",
                runtimeDefaults.embedding_timeout_ms,
              )}
            />
            <Field
              label="Dimensions"
              name="embedding_dimensions"
              value={numberValue("embedding_dimensions", runtimeDefaults.embedding_dimensions)}
              placeholder="1536"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.embedding_dimensions}
              onChange={(value) => updateNumberField("embedding_dimensions", value)}
              onBlur={() => commitNumberField(
                "embedding_dimensions",
                runtimeDefaults.embedding_dimensions,
              )}
            />
            <Field
              label="Batch size"
              name="embedding_batch_size"
              value={numberValue("embedding_batch_size", runtimeDefaults.embedding_batch_size)}
              placeholder="16"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.embedding_batch_size}
              onChange={(value) => updateNumberField("embedding_batch_size", value)}
              onBlur={() => commitNumberField(
                "embedding_batch_size",
                runtimeDefaults.embedding_batch_size,
              )}
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
                setSecretValues(blankSecretValues());
                setNumberDrafts({});
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
  onBlur,
  min,
  max,
  step,
}: {
  label: string;
  name: keyof SettingsProfileIn;
  value: string;
  placeholder: string;
  disabled: boolean;
  required?: boolean;
  type?: string;
  onChange?: (value: string) => void;
  onBlur?: () => void;
  min?: number;
  max?: number;
  step?: number | "any";
}) {
  const valueProps = onChange
    ? {
        value,
        onChange: (event: ChangeEvent<HTMLInputElement>) => onChange(event.target.value),
      }
    : { defaultValue: value };

  return (
    <label className="min-w-0 text-sm font-medium text-[#3a4a53]">
      <span className="mb-1.5 block truncate">{label}</span>
      <input
        className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20 disabled:bg-[#f4f7f8]"
        type={type}
        name={name}
        {...valueProps}
        placeholder={placeholder}
        disabled={disabled}
        required={required}
        min={min}
        max={max}
        step={step}
        onBlur={onBlur}
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
    mineru_require_hpc: settings.mineru_require_hpc,
    mineru_backend: settings.mineru_backend,
    mineru_device: settings.mineru_device,
    mineru_lang: settings.mineru_lang ?? "",
    mineru_formula: settings.mineru_formula,
    mineru_table: settings.mineru_table,
    mineru_source: settings.mineru_source ?? "",
    mineru_max_concurrent_files: settings.mineru_max_concurrent_files,
    runtime_mode: settings.runtime_mode,
    vision_model: settings.vision_model ?? "",
    vision_base_url: settings.vision_base_url ?? "",
    vision_timeout_ms: settings.vision_timeout_ms,
    reranker_provider: settings.reranker_provider,
    reranker_fallback_provider: settings.reranker_fallback_provider ?? "disabled",
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

function mineruReportedOptimization(
  data: MinerUConnectionTestOut,
): Record<string, unknown> {
  const optimization = data.optimization;
  if (isRecord(optimization.reported)) {
    return optimization.reported;
  }
  if (isFlatMinerUOptimization(optimization)) {
    return optimization;
  }
  return {};
}

function missingMinerUOptimizationDetail(
  detail: string,
  optimization: Record<string, unknown>,
): string {
  const tokens = [
    optimization.backend ? `backend=${String(optimization.backend)}` : "",
    optimization.device ? `device=${String(optimization.device)}` : "",
    optimization.max_concurrent_files
      ? `maxConcurrentFiles=${String(optimization.max_concurrent_files)}`
      : "",
  ].filter(Boolean);
  return tokens.filter((token) => !detail.includes(token)).join("; ");
}

function isFlatMinerUOptimization(
  value: MinerUConnectionTestOut["optimization"],
): value is MinerUConnectionTestOut["optimization"] & Record<string, unknown> {
  return Boolean(value.backend || value.device || value.max_concurrent_files);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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

function constrainNumber(value: number, constraints: NumberConstraints): number {
  const minConstrained = Math.max(value, constraints.min);
  return constraints.max == null ? minConstrained : Math.min(minConstrained, constraints.max);
}

function withoutNumberDraft(drafts: NumberDrafts, key: NumberFieldName): NumberDrafts {
  const next = { ...drafts };
  delete next[key];
  return next;
}
