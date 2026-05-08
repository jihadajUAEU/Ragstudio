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

  const loadedValues = settingsQuery.data ? settingsToFormValues(settingsQuery.data) : null;
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

  const buildPayload = (form: HTMLFormElement): SettingsProfileIn | null => {
    if (!formValues) {
      return null;
    }
    const formData = new FormData(form);
    const embeddingApiKey = String(formData.get("embedding_api_key") ?? "").trim();
    const llmApiKey = String(formData.get("llm_api_key") ?? "").trim();
    const payload: SettingsProfileIn = {
      ...formValues,
      llm_provider: formValues.llm_provider ?? "openai_compatible",
      llm_capabilities: formValues.llm_capabilities ?? [],
      embedding_provider: formValues.embedding_provider ?? "fallback",
      embedding_tls_verify: formValues.embedding_tls_verify ?? true,
      mineru_enabled: formValues.mineru_enabled ?? false,
    };
    if (embeddingApiKey) {
      payload.embedding_api_key = embeddingApiKey;
    }
    if (llmApiKey) {
      payload.llm_api_key = llmApiKey;
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
            <Field
              label="Storage backend"
              name="storage_backend"
              value={formValues?.storage_backend ?? ""}
              placeholder="local"
              disabled={busy}
              onChange={(value) => updateField("storage_backend", value)}
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
