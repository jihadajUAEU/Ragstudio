import { type FormEvent, type MouseEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, PlugZap, RotateCcw, Save, Settings } from "lucide-react";

import { ApiError, apiClient } from "../../api/client";
import type { SettingsProfileIn } from "../../api/generated";
import { Button } from "../../components/ui/button";

const queryKeys = {
  settings: ["settings", "default"],
} as const;

export function SettingsPage() {
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({
    queryKey: queryKeys.settings,
    queryFn: apiClient.defaultSettings,
    retry: (failureCount, error) =>
      error instanceof ApiError && error.status === 404 ? false : failureCount < 2,
  });

  const updateSettings = useMutation({
    mutationFn: apiClient.updateDefaultSettings,
    onSuccess: (settings) => {
      queryClient.setQueryData(queryKeys.settings, settings);
    },
  });
  const testEmbedding = useMutation({
    mutationFn: apiClient.testEmbeddingSettings,
  });
  const testMinerU = useMutation({
    mutationFn: apiClient.testMinerUSettings,
  });

  const buildPayload = (form: HTMLFormElement): SettingsProfileIn => {
    const formData = new FormData(form);
    const apiKey = String(formData.get("embedding_api_key") ?? "").trim();
    const payload: SettingsProfileIn = {
      provider: String(formData.get("provider") ?? ""),
      llm_model: String(formData.get("llm_model") ?? ""),
      embedding_model: String(formData.get("embedding_model") ?? ""),
      storage_backend: String(formData.get("storage_backend") ?? ""),
      embedding_provider: String(formData.get("embedding_provider") ?? "fallback") as
        | "fallback"
        | "vllm_openai",
      embedding_base_url: String(formData.get("embedding_base_url") ?? ""),
      embedding_timeout_ms: Number(formData.get("embedding_timeout_ms") ?? 10000),
      embedding_dimensions: Number(formData.get("embedding_dimensions") ?? 1536),
      embedding_batch_size: Number(formData.get("embedding_batch_size") ?? 16),
      embedding_tls_verify: formData.get("embedding_tls_verify") === "on",
      mineru_enabled: formData.get("mineru_enabled") === "on",
      mineru_base_url: String(formData.get("mineru_base_url") ?? ""),
      mineru_timeout_ms: Number(formData.get("mineru_timeout_ms") ?? 1800000),
      mineru_poll_interval_ms: Number(formData.get("mineru_poll_interval_ms") ?? 1000),
    };
    if (apiKey) {
      payload.embedding_api_key = apiKey;
    }
    return payload;
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    updateSettings.mutate(buildPayload(event.currentTarget));
  };

  const submitForTest = (event: MouseEvent<HTMLButtonElement>) => {
    const form = event.currentTarget.form;
    if (form?.reportValidity()) {
      testEmbedding.mutate(buildPayload(form));
    }
  };
  const submitMinerUForTest = (event: MouseEvent<HTMLButtonElement>) => {
    const form = event.currentTarget.form;
    if (form?.reportValidity()) {
      testMinerU.mutate(buildPayload(form));
    }
  };

  const message = getMessage(settingsQuery.error, updateSettings.error);
  const defaults: SettingsProfileIn = {
    provider: settingsQuery.data?.provider ?? "",
    llm_model: settingsQuery.data?.llm_model ?? "",
    embedding_model: settingsQuery.data?.embedding_model ?? "",
    storage_backend: settingsQuery.data?.storage_backend ?? "",
    embedding_provider: settingsQuery.data?.embedding_provider ?? "fallback",
    embedding_base_url: settingsQuery.data?.embedding_base_url ?? "",
    embedding_timeout_ms: settingsQuery.data?.embedding_timeout_ms ?? 10000,
    embedding_dimensions: settingsQuery.data?.embedding_dimensions ?? 1536,
    embedding_batch_size: settingsQuery.data?.embedding_batch_size ?? 16,
    embedding_tls_verify: settingsQuery.data?.embedding_tls_verify ?? true,
    mineru_enabled: settingsQuery.data?.mineru_enabled ?? false,
    mineru_base_url: settingsQuery.data?.mineru_base_url ?? "",
    mineru_timeout_ms: settingsQuery.data?.mineru_timeout_ms ?? 1800000,
    mineru_poll_interval_ms: settingsQuery.data?.mineru_poll_interval_ms ?? 1000,
  };
  const testMessage = testEmbedding.error
    ? testEmbedding.error.message
    : testEmbedding.data
      ? `${testEmbedding.data.ok ? "Connected" : "Failed"}: ${testEmbedding.data.detail}${
          testEmbedding.data.dimensions ? ` (${testEmbedding.data.dimensions} dims)` : ""
        }`
      : settingsQuery.data?.has_embedding_api_key
        ? "Saved API key present"
        : "";
  const mineruTestMessage = testMinerU.error
    ? testMinerU.error.message
    : testMinerU.data
      ? `${testMinerU.data.ok ? "Connected" : "Failed"}: ${testMinerU.data.detail}`
      : "";

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

      <form key={JSON.stringify(defaults)} onSubmit={submit} className="flex flex-col gap-4">
        <section className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
          <div className="mb-5 flex items-center gap-2">
            <Settings className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
            <h3 className="truncate text-base font-semibold text-[#1f2933]">Runtime profile</h3>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Provider"
              name="provider"
              defaultValue={defaults.provider}
              placeholder="openai"
              disabled={updateSettings.isPending}
            />
            <Field
              label="LLM model"
              name="llm_model"
              defaultValue={defaults.llm_model}
              placeholder="gpt-4.1-mini"
              disabled={updateSettings.isPending}
            />
            <Field
              label="Storage backend"
              name="storage_backend"
              defaultValue={defaults.storage_backend}
              placeholder="local"
              disabled={updateSettings.isPending}
            />
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
                defaultChecked={defaults.mineru_enabled ?? false}
                disabled={updateSettings.isPending}
              />
              Enable MinerU
            </label>
            <Field
              label="MinerU base URL"
              name="mineru_base_url"
              defaultValue={defaults.mineru_base_url ?? ""}
              placeholder="http://127.0.0.1:8765"
              disabled={updateSettings.isPending}
              required={false}
            />
            <Field
              label="MinerU timeout (ms)"
              name="mineru_timeout_ms"
              defaultValue={String(defaults.mineru_timeout_ms ?? 1800000)}
              placeholder="1800000"
              disabled={updateSettings.isPending}
              type="number"
            />
            <Field
              label="MinerU poll interval (ms)"
              name="mineru_poll_interval_ms"
              defaultValue={String(defaults.mineru_poll_interval_ms ?? 1000)}
              placeholder="1000"
              disabled={updateSettings.isPending}
              type="number"
            />
          </div>
          <div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="min-h-5 text-sm text-[#62717a]" role="status">
              {mineruTestMessage}
            </p>
            <Button
              type="button"
              variant="secondary"
              onClick={submitMinerUForTest}
              disabled={testMinerU.isPending || updateSettings.isPending}
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
              defaultValue={defaults.embedding_provider ?? "fallback"}
              disabled={updateSettings.isPending}
              options={[
                { value: "fallback", label: "Local fallback" },
                { value: "vllm_openai", label: "vLLM / OpenAI-compatible" },
              ]}
            />
            <Field
              label="Embedding model"
              name="embedding_model"
              defaultValue={defaults.embedding_model}
              placeholder="Qwen/Qwen3-Embedding-8B"
              disabled={updateSettings.isPending}
            />
            <Field
              label="Base URL"
              name="embedding_base_url"
              defaultValue={defaults.embedding_base_url ?? ""}
              placeholder="http://127.0.0.1:8001/v1"
              disabled={updateSettings.isPending}
              required={false}
            />
            <Field
              label="API key"
              name="embedding_api_key"
              defaultValue=""
              placeholder={settingsQuery.data?.has_embedding_api_key ? "Saved key present" : "optional"}
              disabled={updateSettings.isPending}
              required={false}
              type="password"
            />
            <Field
              label="Timeout (ms)"
              name="embedding_timeout_ms"
              defaultValue={String(defaults.embedding_timeout_ms ?? 10000)}
              placeholder="10000"
              disabled={updateSettings.isPending}
              type="number"
            />
            <Field
              label="Dimensions"
              name="embedding_dimensions"
              defaultValue={String(defaults.embedding_dimensions ?? 1536)}
              placeholder="1536"
              disabled={updateSettings.isPending}
              type="number"
            />
            <Field
              label="Batch size"
              name="embedding_batch_size"
              defaultValue={String(defaults.embedding_batch_size ?? 16)}
              placeholder="16"
              disabled={updateSettings.isPending}
              type="number"
            />
            <label className="flex h-10 items-center gap-2 self-end rounded-md border border-[#cfd8dd] px-3 text-sm font-medium text-[#3a4a53]">
              <input
                name="embedding_tls_verify"
                type="checkbox"
                defaultChecked={defaults.embedding_tls_verify ?? true}
                disabled={updateSettings.isPending}
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
              onClick={submitForTest}
              disabled={testEmbedding.isPending || updateSettings.isPending}
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
            <Button type="reset" variant="secondary" disabled={updateSettings.isPending}>
              Reset
            </Button>
            <Button type="submit" disabled={updateSettings.isPending}>
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
  defaultValue,
  placeholder,
  disabled,
  required = true,
  type = "text",
}: {
  label: string;
  name: keyof SettingsProfileIn;
  defaultValue: string;
  placeholder: string;
  disabled: boolean;
  required?: boolean;
  type?: string;
}) {
  return (
    <label className="min-w-0 text-sm font-medium text-[#3a4a53]">
      <span className="mb-1.5 block truncate">{label}</span>
      <input
        className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20 disabled:bg-[#f4f7f8]"
        type={type}
        name={name}
        defaultValue={defaultValue}
        placeholder={placeholder}
        disabled={disabled}
        required={required}
      />
    </label>
  );
}

function SelectField({
  label,
  name,
  defaultValue,
  disabled,
  options,
}: {
  label: string;
  name: keyof SettingsProfileIn;
  defaultValue: string;
  disabled: boolean;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <label className="min-w-0 text-sm font-medium text-[#3a4a53]">
      <span className="mb-1.5 block truncate">{label}</span>
      <select
        className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20 disabled:bg-[#f4f7f8]"
        name={name}
        defaultValue={defaultValue}
        disabled={disabled}
        required
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
