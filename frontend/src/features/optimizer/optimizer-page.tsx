import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { AlertCircle, Loader2, RefreshCcw, Sparkles, Target, Trophy } from "lucide-react";

import { apiClient } from "../../api/client";
import type { OptimizerCandidateSummary, RunOut, VariantOut } from "../../api/generated";
import { DataTable } from "../../components/data-table";
import { EmptyState } from "../../components/empty-state";
import { StatusBadge } from "../../components/status-badge";
import { Button } from "../../components/ui/button";
import { formatCount } from "../../lib/utils";

const queryKeys = {
  runs: ["runs"],
  variants: ["variants"],
} as const;

export function OptimizerPage() {
  const runsQuery = useQuery({ queryKey: queryKeys.runs, queryFn: apiClient.runs });
  const variantsQuery = useQuery({ queryKey: queryKeys.variants, queryFn: apiClient.variants });
  const [experimentId, setExperimentId] = useState("");
  const [objectiveText, setObjectiveText] = useState("{\n  \"metric\": \"total\"\n}");
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [formError, setFormError] = useState("");

  const optimize = useMutation({
    mutationFn: apiClient.optimize,
    onSuccess: () => setFormError(""),
  });

  const variantById = useMemo(
    () => new Map((variantsQuery.data?.items ?? []).map((variant) => [variant.id, variant])),
    [variantsQuery.data?.items],
  );
  const selectedRuns = (runsQuery.data?.items ?? []).filter((run) => selectedRunIds.includes(run.id));

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const objective = parseObject(objectiveText);
    if (!objective.ok) {
      setFormError(objective.message);
      return;
    }
    if (!experimentId.trim()) {
      setFormError("Enter an experiment id.");
      return;
    }
    optimize.mutate({ experiment_id: experimentId.trim(), objective: objective.value });
  };

  const runColumns = useMemo<ColumnDef<RunOut>[]>(
    () => [
      {
        id: "selected",
        header: "Review",
        cell: ({ row }) => (
          <input
            type="checkbox"
            className="h-4 w-4 accent-[#176b87]"
            checked={selectedRunIds.includes(row.original.id)}
            onChange={(event) =>
              setSelectedRunIds((ids) => toggleId(ids, row.original.id, event.target.checked))
            }
            aria-label={`Review run ${row.original.id}`}
          />
        ),
      },
      {
        accessorKey: "query",
        header: "Query",
        cell: ({ row }) => <span className="line-clamp-2">{row.original.query}</span>,
      },
      {
        accessorKey: "variant_id",
        header: "Variant",
        cell: ({ row }) => (
          <span className="truncate">
            {variantById.get(row.original.variant_id)?.name ?? row.original.variant_id}
          </span>
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
    ],
    [selectedRunIds, variantById],
  );

  const candidateColumns = useMemo<ColumnDef<OptimizerCandidateSummary>[]>(
    () => [
      {
        accessorKey: "variant_id",
        header: "Variant",
        cell: ({ row }) => (
          <span className="truncate">
            {variantById.get(row.original.variant_id)?.name ?? row.original.variant_id}
          </span>
        ),
      },
      {
        accessorKey: "run_count",
        header: "Runs",
      },
      {
        accessorKey: "average_score",
        header: "Average",
        cell: ({ row }) => <span className="font-medium">{row.original.average_score}</span>,
      },
      {
        accessorKey: "best_run_score",
        header: "Best",
        cell: ({ row }) => <span>{row.original.best_run_score ?? "n/a"}</span>,
      },
    ],
    [variantById],
  );

  const refresh = () => {
    void runsQuery.refetch();
    void variantsQuery.refetch();
  };

  const isLoading = runsQuery.isLoading || variantsQuery.isLoading;
  const error = runsQuery.error?.message ?? variantsQuery.error?.message;

  return (
    <div className="mx-auto grid max-w-7xl gap-6 xl:grid-cols-[minmax(340px,0.38fr)_minmax(0,0.62fr)]">
      <form onSubmit={submit} className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
        <div className="mb-5 flex items-center gap-2">
          <Target className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
          <h2 className="truncate text-base font-semibold text-[#1f2933]">Optimizer</h2>
        </div>

        <label className="block text-sm font-medium text-[#3a4a53]">
          <span className="mb-1.5 block truncate">Experiment ID</span>
          <input
            type="text"
            value={experimentId}
            onChange={(event) => setExperimentId(event.target.value)}
            className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20"
            disabled={optimize.isPending}
          />
        </label>

        <label className="mt-4 block text-sm font-medium text-[#3a4a53]">
          <span className="mb-1.5 block truncate">Objective JSON</span>
          <textarea
            value={objectiveText}
            onChange={(event) => setObjectiveText(event.target.value)}
            className="min-h-28 w-full resize-y rounded-md border border-[#cfd8dd] bg-white px-3 py-2 font-mono text-xs text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20"
            disabled={optimize.isPending}
          />
        </label>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <Metric label="Recorded runs" value={formatCount(runsQuery.data?.total)} />
          <Metric label="Review set" value={formatCount(selectedRuns.length)} />
        </div>

        <div className="mt-4 flex items-center justify-between gap-3">
          <p className="min-h-5 min-w-0 flex-1 truncate text-sm text-[#62717a]" role="status">
            {formError || optimize.error?.message || (optimize.isSuccess ? "Recommendation ready" : "")}
          </p>
          <Button type="submit" disabled={optimize.isPending || !experimentId.trim()}>
            {optimize.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Sparkles className="h-4 w-4" aria-hidden="true" />
            )}
            Recommend
          </Button>
        </div>
      </form>

      <section className="min-w-0 space-y-4">
        {isLoading ? (
          <EmptyState icon={Loader2} title="Loading runs" description="Fetching run history and variants." />
        ) : error ? (
          <EmptyState
            icon={AlertCircle}
            title="Optimizer inputs unavailable"
            description={error}
            action={
              <Button variant="secondary" onClick={refresh}>
                <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                Retry
              </Button>
            }
          />
        ) : optimize.data ? (
          <>
            <article className="rounded-md border border-[#d6dde1] bg-white p-4">
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-[#ecf8f0] text-[#24563a]">
                  <Trophy className="h-5 w-5" aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-semibold uppercase text-[#6f7f87]">Selected variant</p>
                  <h3 className="mt-1 truncate text-lg font-semibold text-[#1f2933]">
                    {selectedVariantName(optimize.data.selected_variant_id, variantById)}
                  </h3>
                  <p className="mt-2 text-sm leading-6 text-[#3a4a53]">{optimize.data.explanation}</p>
                </div>
              </div>
            </article>
            <DataTable
              columns={candidateColumns}
              data={optimize.data.candidate_summaries}
              emptyTitle="No candidate summaries"
              emptyDescription="Optimizer candidate scores will appear here when runs are available."
            />
            <JsonDetails title="Recommendation details" value={optimize.data} />
          </>
        ) : (
          <EmptyState
            icon={Target}
            title="No recommendation"
            description="Run the optimizer against an experiment to select the strongest variant."
          />
        )}

        <div>
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="truncate text-base font-semibold text-[#1f2933]">Runs for review</h3>
            <Button variant="secondary" size="sm" onClick={refresh} disabled={runsQuery.isFetching}>
              <RefreshCcw className="h-4 w-4" aria-hidden="true" />
              Refresh
            </Button>
          </div>
          <DataTable
            columns={runColumns}
            data={runsQuery.data?.items ?? []}
            emptyTitle="No runs"
            emptyDescription="Experiment runs will appear after evaluations complete."
          />
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3">
      <p className="truncate text-xs font-semibold uppercase text-[#6f7f87]">{label}</p>
      <p className="mt-1 truncate text-lg font-semibold text-[#1f2933]">{value}</p>
    </div>
  );
}

function JsonDetails({ title, value }: { title: string; value: unknown }) {
  return (
    <details className="rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3">
      <summary className="cursor-pointer text-xs font-semibold uppercase text-[#62717a]">{title}</summary>
      <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-[#3a4a53]">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

function selectedVariantName(id: string | null, variants: Map<string, VariantOut>) {
  if (!id) {
    return "No variant selected";
  }
  return variants.get(id)?.name ?? id;
}

function toggleId(ids: string[], id: string, checked: boolean) {
  if (checked) {
    return ids.includes(id) ? ids : [...ids, id];
  }
  return ids.filter((existingId) => existingId !== id);
}

function parseObject(text: string): { ok: true; value: Record<string, unknown> } | { ok: false; message: string } {
  try {
    const parsed: unknown = JSON.parse(text || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, message: "Objective must be a JSON object." };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch {
    return { ok: false, message: "Objective JSON is malformed." };
  }
}
