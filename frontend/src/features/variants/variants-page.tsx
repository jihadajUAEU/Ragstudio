import { useCallback, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  AlertCircle,
  GitCompare,
  Loader2,
  Pencil,
  Plus,
  RefreshCcw,
  SlidersHorizontal,
  Trash2,
} from "lucide-react";

import { apiClient } from "../../api/client";
import type { VariantIn, VariantOut, VariantPreset, VariantUpdate } from "../../api/generated";
import { DataTable } from "../../components/data-table";
import { EmptyState } from "../../components/empty-state";
import { Button } from "../../components/ui/button";
import { titleCase } from "../../lib/utils";

const queryKeys = {
  variants: ["variants"],
} as const;

const presetDefaults: Record<VariantPreset, Record<string, unknown>> = {
  balanced: { top_k: 5, temperature: 0.2, enable_rerank: true },
  precise: { top_k: 3, temperature: 0.1, enable_rerank: true },
  broad: { top_k: 12, temperature: 0.3, enable_rerank: true },
  fast: { top_k: 4, temperature: 0.0, enable_rerank: false },
};

const defaultPreset: VariantPreset = "balanced";

function presetParametersText(preset: VariantPreset) {
  return JSON.stringify(presetDefaults[preset], null, 2);
}

export function VariantsPage() {
  const queryClient = useQueryClient();
  const variantsQuery = useQuery({ queryKey: queryKeys.variants, queryFn: () => apiClient.variants() });
  const [name, setName] = useState("");
  const [preset, setPreset] = useState<VariantPreset>(defaultPreset);
  const [parametersText, setParametersText] = useState(presetParametersText(defaultPreset));
  const [formError, setFormError] = useState("");
  const [editingVariant, setEditingVariant] = useState<VariantOut | null>(null);

  const resetForm = () => {
    setName("");
    setPreset(defaultPreset);
    setParametersText(presetParametersText(defaultPreset));
    setFormError("");
    setEditingVariant(null);
  };

  const createVariant = useMutation({
    mutationFn: apiClient.createVariant,
    onSuccess: () => {
      resetForm();
      void queryClient.invalidateQueries({ queryKey: queryKeys.variants });
    },
  });

  const updateVariant = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: VariantUpdate }) =>
      apiClient.updateVariant(id, payload),
    onSuccess: () => {
      resetForm();
      void queryClient.invalidateQueries({ queryKey: queryKeys.variants });
    },
  });

  const deleteVariant = useMutation({
    mutationFn: (variant: VariantOut) => apiClient.deleteVariant(variant.id),
    onSuccess: (_data, variant) => {
      if (editingVariant?.id === variant.id) {
        resetForm();
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.variants });
    },
  });

  const isSaving = createVariant.isPending || updateVariant.isPending;

  const startEditing = useCallback((variant: VariantOut) => {
    setEditingVariant(variant);
    setName(variant.name);
    setPreset(variant.preset);
    setParametersText(JSON.stringify(variant.parameters, null, 2));
    setFormError("");
    createVariant.reset();
    updateVariant.reset();
  }, [createVariant, updateVariant]);

  const handlePresetChange = (nextPreset: VariantPreset) => {
    setPreset(nextPreset);
    setParametersText(presetParametersText(nextPreset));
    setFormError("");
    createVariant.reset();
    updateVariant.reset();
  };

  const requestDelete = useCallback((variant: VariantOut) => {
    const confirmed = window.confirm(
      `Delete variant ${variant.name}? This cannot be undone.`,
    );
    if (!confirmed) {
      return;
    }
    deleteVariant.mutate(variant);
  }, [deleteVariant]);

  const variantColumns = useMemo<ColumnDef<VariantOut>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Variant",
        cell: ({ row }) => (
          <div className="min-w-0">
            <p className="truncate font-medium">{row.original.name}</p>
            <code className="block truncate text-xs text-[#62717a]">{row.original.id}</code>
          </div>
        ),
      },
      {
        accessorKey: "preset",
        header: "Preset",
        cell: ({ row }) => <span className="truncate">{titleCase(row.original.preset)}</span>,
      },
      {
        accessorKey: "parameters",
        header: "Parameters",
        cell: ({ row }) => <ParameterList parameters={row.original.parameters} />,
      },
      {
        id: "actions",
        header: "Actions",
        cell: ({ row }) => (
          <div className="flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Edit variant ${row.original.name}`}
              onClick={() => startEditing(row.original)}
              disabled={isSaving || deleteVariant.isPending}
            >
              <Pencil className="h-4 w-4" aria-hidden="true" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Delete variant ${row.original.name}`}
              onClick={() => requestDelete(row.original)}
              disabled={isSaving || deleteVariant.isPending}
            >
              {deleteVariant.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              )}
            </Button>
          </div>
        ),
      },
    ],
    [deleteVariant, isSaving, requestDelete, startEditing],
  );

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    let parameters: VariantIn["parameters"];

    try {
      const parsed = JSON.parse(parametersText) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        setFormError("Parameters must be a JSON object");
        return;
      }
      parameters = parsed as VariantIn["parameters"];
    } catch {
      setFormError("Parameters must be valid JSON");
      return;
    }

    setFormError("");
    if (editingVariant) {
      updateVariant.mutate({ id: editingVariant.id, payload: { name, preset, parameters } });
      return;
    }
    createVariant.mutate({ name, preset, parameters });
  };

  const formTitle = editingVariant ? "Edit variant" : "Create variant";
  const mutationError = editingVariant ? updateVariant.error?.message : createVariant.error?.message;
  const saveSuccess = editingVariant
    ? updateVariant.isSuccess
      ? "Updated"
      : ""
    : createVariant.isSuccess
      ? "Created"
      : "";

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <section className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium text-[#176b87]">Variants</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-normal text-[#1f2933]">
            Retrieval and generation variants
          </h2>
        </div>
        <Button
          variant="secondary"
          onClick={() => void variantsQuery.refetch()}
          disabled={variantsQuery.isFetching}
        >
          {variantsQuery.isFetching ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCcw className="h-4 w-4" aria-hidden="true" />
          )}
          Refresh
        </Button>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(320px,0.45fr)_minmax(0,0.55fr)]">
        <form
          onSubmit={submit}
          className="min-w-0 rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5"
        >
          <div className="mb-5 flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
            <h3 className="truncate text-base font-semibold text-[#1f2933]">{formTitle}</h3>
          </div>

          <div className="grid gap-4">
            <label className="min-w-0 text-sm font-medium text-[#3a4a53]">
              <span className="mb-1.5 block truncate">Name</span>
              <input
                className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20 disabled:bg-[#f4f7f8]"
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={isSaving}
                required
              />
            </label>

            <label className="min-w-0 text-sm font-medium text-[#3a4a53]">
              <span className="mb-1.5 block truncate">Preset</span>
              <select
                className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20 disabled:bg-[#f4f7f8]"
                value={preset}
                onChange={(event) => handlePresetChange(event.target.value as VariantPreset)}
                disabled={isSaving}
              >
                <option value="balanced">Balanced</option>
                <option value="precise">Precise</option>
                <option value="broad">Broad</option>
                <option value="fast">Fast</option>
              </select>
            </label>

            <label className="min-w-0 text-sm font-medium text-[#3a4a53]">
              <span className="mb-1.5 block truncate">Parameters</span>
              <textarea
                className="min-h-40 w-full resize-y rounded-md border border-[#cfd8dd] bg-white px-3 py-2 font-mono text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20 disabled:bg-[#f4f7f8]"
                value={parametersText}
                onChange={(event) => setParametersText(event.target.value)}
                disabled={isSaving}
                spellCheck={false}
              />
            </label>
          </div>

          <div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="min-h-5 text-sm text-[#62717a]" role="status">
              {formError || mutationError || saveSuccess || deleteVariant.error?.message || ""}
            </p>
            <div className="flex items-center justify-end gap-2">
              {editingVariant ? (
                <Button type="button" variant="secondary" onClick={resetForm} disabled={isSaving}>
                  Cancel
                </Button>
              ) : null}
              <Button type="submit" disabled={isSaving}>
                {isSaving ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : editingVariant ? (
                  <Pencil className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <Plus className="h-4 w-4" aria-hidden="true" />
                )}
                {editingVariant ? "Update" : "Create"}
              </Button>
            </div>
          </div>
        </form>

        <section className="min-w-0">
          <div className="mb-3 flex items-center gap-2">
            <GitCompare className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
            <h3 className="truncate text-base font-semibold text-[#1f2933]">Variant matrix</h3>
          </div>
          {variantsQuery.isLoading ? (
            <EmptyState
              icon={Loader2}
              title="Loading variants"
              description="Fetching variant matrix."
            />
          ) : variantsQuery.isError ? (
            <EmptyState
              icon={AlertCircle}
              title="Variants unavailable"
              description={variantsQuery.error.message}
              action={
                <Button variant="secondary" onClick={() => void variantsQuery.refetch()}>
                  <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                  Retry
                </Button>
              }
            />
          ) : (
            <DataTable
              columns={variantColumns}
              data={variantsQuery.data?.items ?? []}
              emptyTitle="No variants"
              emptyDescription="Created variants will appear here."
            />
          )}
        </section>
      </section>
    </div>
  );
}

function ParameterList({ parameters }: { parameters: Record<string, unknown> }) {
  const entries = Object.entries(parameters);

  if (entries.length === 0) {
    return <span className="text-xs text-[#62717a]">None</span>;
  }

  return (
    <div className="flex max-w-full flex-wrap gap-1.5">
      {entries.map(([key, value]) => (
        <span
          key={key}
          className="inline-flex max-w-full items-center gap-1 rounded-md border border-[#d6dde1] bg-[#f7fafb] px-2 py-1 text-xs text-[#3a4a53]"
        >
          <span className="truncate font-medium">{key}</span>
          <span className="truncate text-[#62717a]">{formatValue(value)}</span>
        </span>
      ))}
    </div>
  );
}

function formatValue(value: unknown) {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}
