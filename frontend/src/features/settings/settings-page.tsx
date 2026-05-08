import { type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RotateCcw, Save, Settings } from "lucide-react";

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

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    updateSettings.mutate({
      provider: String(formData.get("provider") ?? ""),
      llm_model: String(formData.get("llm_model") ?? ""),
      embedding_model: String(formData.get("embedding_model") ?? ""),
      storage_backend: String(formData.get("storage_backend") ?? ""),
    });
  };

  const message = getMessage(settingsQuery.error, updateSettings.error);
  const defaults: SettingsProfileIn = {
    provider: settingsQuery.data?.provider ?? "",
    llm_model: settingsQuery.data?.llm_model ?? "",
    embedding_model: settingsQuery.data?.embedding_model ?? "",
    storage_backend: settingsQuery.data?.storage_backend ?? "",
  };

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

      <form
        key={JSON.stringify(defaults)}
        onSubmit={submit}
        className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5"
      >
        <div className="mb-5 flex items-center gap-2">
          <Settings className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
          <h3 className="truncate text-base font-semibold text-[#1f2933]">Default settings</h3>
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
            label="Embedding model"
            name="embedding_model"
            defaultValue={defaults.embedding_model}
            placeholder="text-embedding-3-small"
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
}: {
  label: string;
  name: keyof SettingsProfileIn;
  defaultValue: string;
  placeholder: string;
  disabled: boolean;
}) {
  return (
    <label className="min-w-0 text-sm font-medium text-[#3a4a53]">
      <span className="mb-1.5 block truncate">{label}</span>
      <input
        className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20 disabled:bg-[#f4f7f8]"
        name={name}
        defaultValue={defaultValue}
        placeholder={placeholder}
        disabled={disabled}
        required
      />
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
