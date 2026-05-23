import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { AlertCircle, BarChart3, GitCompare, Loader2, RefreshCcw } from "lucide-react";

import { apiClient } from "../../api/client";
import type { RunOut, VariantOut } from "../../api/generated";
import { DataTable } from "../../components/data-table";
import { EmptyState } from "../../components/empty-state";
import { StatusBadge } from "../../components/status-badge";
import { Button } from "../../components/ui/button";
import { toggleId } from "../../lib/utils";

const queryKeys = {
  runs: ["runs"],
  variants: ["variants"],
} as const;

export function ComparisonPage() {
  const runsQuery = useQuery({ queryKey: queryKeys.runs, queryFn: () => apiClient.runs() });
  const variantsQuery = useQuery({ queryKey: queryKeys.variants, queryFn: () => apiClient.variants() });
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [hasEditedSelection, setHasEditedSelection] = useState(false);

  const runs = useMemo(() => runsQuery.data?.items ?? [], [runsQuery.data?.items]);
  const defaultRunIds = useMemo(() => runs.slice(0, 2).map((run) => run.id), [runs]);
  const effectiveSelectedRunIds = hasEditedSelection ? selectedRunIds : defaultRunIds;
  const runsForComparison = effectiveSelectedRunIds
    .map((id) => runs.find((run) => run.id === id))
    .filter((run): run is RunOut => Boolean(run));

  const variantById = useMemo(
    () => new Map((variantsQuery.data?.items ?? []).map((variant) => [variant.id, variant])),
    [variantsQuery.data?.items],
  );

  const runColumns = useMemo<ColumnDef<RunOut>[]>(
    () => [
      {
        id: "selected",
        header: "Compare",
        cell: ({ row }) => (
          <input
            type="checkbox"
            className="h-4 w-4 accent-[#176b87]"
            checked={effectiveSelectedRunIds.includes(row.original.id)}
            onChange={(event) => {
              setHasEditedSelection(true);
              setSelectedRunIds(toggleId(effectiveSelectedRunIds, row.original.id, event.target.checked));
            }}
            aria-label={`Compare run ${row.original.id}`}
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
    [effectiveSelectedRunIds, variantById],
  );

  const refresh = () => {
    void runsQuery.refetch();
    void variantsQuery.refetch();
  };

  const isLoading = runsQuery.isLoading || variantsQuery.isLoading;
  const isFetching = runsQuery.isFetching || variantsQuery.isFetching;
  const error = runsQuery.error?.message ?? variantsQuery.error?.message;

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <section className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium text-[#176b87]">Comparison</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-normal text-[#1f2933]">
            Run comparison
          </h2>
        </div>
        <Button variant="secondary" onClick={refresh} disabled={isFetching}>
          {isFetching ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCcw className="h-4 w-4" aria-hidden="true" />
          )}
          Refresh
        </Button>
      </section>

      {isLoading ? (
        <EmptyState icon={Loader2} title="Loading runs" description="Fetching recorded query and experiment runs." />
      ) : error ? (
        <EmptyState
          icon={AlertCircle}
          title="Runs unavailable"
          description={error}
          action={
            <Button variant="secondary" onClick={refresh}>
              <RefreshCcw className="h-4 w-4" aria-hidden="true" />
              Retry
            </Button>
          }
        />
      ) : (
        <section className="grid gap-4 xl:grid-cols-[minmax(0,0.42fr)_minmax(0,0.58fr)]">
          <div className="min-w-0">
            <div className="mb-3 flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
              <h3 className="truncate text-base font-semibold text-[#1f2933]">Runs</h3>
            </div>
            <DataTable
              columns={runColumns}
              data={runs}
              emptyTitle="No runs"
              emptyDescription="Query and experiment runs will appear here."
            />
          </div>

          <div className="min-w-0">
            <div className="mb-3 flex items-center gap-2">
              <GitCompare className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
              <h3 className="truncate text-base font-semibold text-[#1f2933]">Answers, sources, and traces</h3>
            </div>
            {runsForComparison.length ? (
              <div className="grid gap-4 lg:grid-cols-2">
                {runsForComparison.map((run) => (
                  <RunComparisonCard
                    key={run.id}
                    run={run}
                    variant={variantById.get(run.variant_id)}
                  />
                ))}
              </div>
            ) : (
              <EmptyState
                icon={GitCompare}
                title="No runs selected"
                description="Select runs to compare answer quality, source coverage, and trace status."
              />
            )}
          </div>
        </section>
      )}
    </div>
  );
}

function RunComparisonCard({ run, variant }: { run: RunOut; variant?: VariantOut }) {
  return (
    <article className="min-w-0 rounded-md border border-[#d6dde1] bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="line-clamp-2 text-sm font-semibold text-[#1f2933]">{run.query}</h4>
          <p className="mt-1 truncate text-xs text-[#62717a]">{variant?.name ?? run.variant_id}</p>
        </div>
        <StatusBadge status={run.status} className="shrink-0" />
      </div>
      {run.error ? (
        <p className="mt-3 rounded-md border border-[#e19a9a] bg-[#fff0f0] p-3 text-sm text-[#8c2525]">
          {run.error}
        </p>
      ) : (
        <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-[#24313a]">
          {run.answer || "No answer returned."}
        </p>
      )}
      <div className="mt-4 grid gap-3">
        <JsonPanel title="Sources" items={run.sources} />
        <JsonPanel title="Traces" items={run.chunk_traces} />
        <JsonPanel title="Timings" items={[run.timings]} />
      </div>
    </article>
  );
}

function JsonPanel({ title, items }: { title: string; items: Record<string, unknown>[] }) {
  return (
    <details className="rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3">
      <summary className="cursor-pointer text-xs font-semibold uppercase text-[#62717a]">
        {title} ({items.length})
      </summary>
      {items.length ? (
        <div className="mt-2 max-h-56 space-y-2 overflow-auto">
          {items.map((item, index) => (
            <pre key={`${title}-${index}`} className="whitespace-pre-wrap break-words text-xs leading-5 text-[#3a4a53]">
              {JSON.stringify(item, null, 2)}
            </pre>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-sm text-[#62717a]">None returned.</p>
      )}
    </details>
  );
}
