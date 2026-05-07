import { useMemo } from "react";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  AlertTriangle,
  Database,
  FileText,
  GitBranch,
  Loader2,
  PlayCircle,
  RefreshCcw,
  Server,
  SlidersHorizontal,
} from "lucide-react";

import { apiClient } from "../../api/client";
import type { DocumentOut, JobOut, RunOut, VariantOut } from "../../api/generated";
import { DataTable } from "../../components/data-table";
import { EmptyState } from "../../components/empty-state";
import { StatusBadge } from "../../components/status-badge";
import { Button } from "../../components/ui/button";
import { formatCount, titleCase } from "../../lib/utils";

const queryKeys = {
  health: ["health"],
  documents: ["documents"],
  jobs: ["jobs"],
  variants: ["variants"],
  runs: ["runs"],
  diagnostics: ["diagnostics"],
  graph: ["graph"],
} as const;

export function DashboardPage() {
  const healthQuery = useQuery({ queryKey: queryKeys.health, queryFn: apiClient.health });
  const documentsQuery = useQuery({ queryKey: queryKeys.documents, queryFn: apiClient.documents });
  const jobsQuery = useQuery({ queryKey: queryKeys.jobs, queryFn: apiClient.jobs });
  const variantsQuery = useQuery({ queryKey: queryKeys.variants, queryFn: apiClient.variants });
  const runsQuery = useQuery({ queryKey: queryKeys.runs, queryFn: apiClient.runs });
  const diagnosticsQuery = useQuery({
    queryKey: queryKeys.diagnostics,
    queryFn: apiClient.diagnostics,
  });
  const graphQuery = useQuery({ queryKey: queryKeys.graph, queryFn: apiClient.graph });

  const isRefreshing =
    healthQuery.isFetching ||
    documentsQuery.isFetching ||
    jobsQuery.isFetching ||
    variantsQuery.isFetching ||
    runsQuery.isFetching ||
    diagnosticsQuery.isFetching ||
    graphQuery.isFetching;

  const refresh = () => {
    void healthQuery.refetch();
    void documentsQuery.refetch();
    void jobsQuery.refetch();
    void variantsQuery.refetch();
    void runsQuery.refetch();
    void diagnosticsQuery.refetch();
    void graphQuery.refetch();
  };

  const documentColumns = useMemo<ColumnDef<DocumentOut>[]>(
    () => [
      {
        accessorKey: "filename",
        header: "Document",
        cell: ({ row }) => (
          <div className="min-w-0">
            <p className="truncate font-medium">{row.original.filename}</p>
            <p className="truncate text-xs text-[#6f7f87]">{row.original.content_type}</p>
          </div>
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: "sha256",
        header: "SHA",
        cell: ({ row }) => (
          <code className="block truncate text-xs text-[#62717a]">
            {row.original.sha256.slice(0, 16)}
          </code>
        ),
      },
    ],
    [],
  );

  const jobColumns = useMemo<ColumnDef<JobOut>[]>(
    () => [
      {
        accessorKey: "type",
        header: "Job",
        cell: ({ row }) => <span className="truncate font-medium">{titleCase(row.original.type)}</span>,
      },
      {
        accessorKey: "progress",
        header: "Progress",
        cell: ({ row }) => (
          <div className="flex min-w-24 items-center gap-2">
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-[#e6ecef]">
              <div
                className="h-full rounded-full bg-[#176b87]"
                style={{ width: `${Math.min(row.original.progress, 100)}%` }}
              />
            </div>
            <span className="w-9 text-right text-xs text-[#62717a]">{row.original.progress}%</span>
          </div>
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
    ],
    [],
  );

  const runColumns = useMemo<ColumnDef<RunOut>[]>(
    () => [
      {
        accessorKey: "query",
        header: "Query",
        cell: ({ row }) => <span className="line-clamp-2">{row.original.query}</span>,
      },
      {
        accessorKey: "variant_id",
        header: "Variant",
        cell: ({ row }) => (
          <code className="block truncate text-xs text-[#62717a]">
            {row.original.variant_id.slice(0, 12)}
          </code>
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
    ],
    [],
  );

  const variantColumns = useMemo<ColumnDef<VariantOut>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Variant",
        cell: ({ row }) => <span className="truncate font-medium">{row.original.name}</span>,
      },
      {
        accessorKey: "preset",
        header: "Preset",
        cell: ({ row }) => <span className="truncate">{titleCase(row.original.preset)}</span>,
      },
      {
        accessorKey: "parameters",
        header: "Parameters",
        cell: ({ row }) => (
          <span className="text-xs text-[#62717a]">
            {formatCount(Object.keys(row.original.parameters).length)}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <section className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium text-[#176b87]">Workbench overview</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-normal text-[#1f2933]">
            Pipeline, retrieval, and evaluation state
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[#62717a]">
            Monitor ingestion, query runs, variants, graph readiness, and local dependencies from a
            single operational surface.
          </p>
        </div>
        <Button variant="secondary" onClick={refresh} disabled={isRefreshing}>
          {isRefreshing ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCcw className="h-4 w-4" aria-hidden="true" />
          )}
          Refresh
        </Button>
      </section>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={Server}
          label="API service"
          value={healthQuery.data?.status === "ok" ? "Online" : "Unavailable"}
          detail={healthQuery.data?.service ?? "Waiting for backend"}
          tone={healthQuery.data?.status === "ok" ? "good" : "muted"}
        />
        <MetricCard
          icon={FileText}
          label="Documents"
          value={formatCount(documentsQuery.data?.total)}
          detail="Uploaded source files"
        />
        <MetricCard
          icon={PlayCircle}
          label="Runs"
          value={formatCount(runsQuery.data?.total)}
          detail="Recorded query executions"
        />
        <MetricCard
          icon={GitBranch}
          label="Graph"
          value={formatCount(graphQuery.data?.nodes.length)}
          detail={`${formatCount(graphQuery.data?.edges.length)} edges indexed`}
        />
      </section>

      {diagnosticsQuery.data?.warnings.length ? (
        <section className="rounded-md border border-[#e5c36b] bg-[#fff8e6] p-4">
          <div className="flex gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-[#8c6500]" aria-hidden="true" />
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-[#5f4600]">Diagnostics warnings</h3>
              <ul className="mt-2 space-y-1 text-sm leading-6 text-[#705300]">
                {diagnosticsQuery.data.warnings.map((warning) => (
                  <li key={warning} className="break-words">
                    {warning}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      ) : null}

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(360px,0.75fr)]">
        <Panel title="Documents" icon={FileText}>
          <DataTable
            columns={documentColumns}
            data={documentsQuery.data?.items ?? []}
            emptyTitle="No documents indexed"
            emptyDescription="Uploaded files and their ingestion status will appear here."
          />
        </Panel>

        <Panel title="Jobs" icon={Database}>
          <DataTable
            columns={jobColumns}
            data={jobsQuery.data?.items ?? []}
            emptyTitle="No jobs running"
            emptyDescription="Ingestion and indexing jobs will be listed as work starts."
          />
        </Panel>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <Panel title="Variants" icon={SlidersHorizontal}>
          <DataTable
            columns={variantColumns}
            data={variantsQuery.data?.items ?? []}
            emptyTitle="No variants configured"
            emptyDescription="Retrieval and generation variants will appear after they are created."
          />
        </Panel>

        <Panel title="Recent Runs" icon={PlayCircle}>
          <DataTable
            columns={runColumns}
            data={runsQuery.data?.items ?? []}
            emptyTitle="No query runs"
            emptyDescription="Queries executed through the studio will be shown here."
          />
        </Panel>
      </section>

      {healthQuery.isError ? (
        <EmptyState
          icon={Server}
          title="Backend is not reachable"
          description="Start the FastAPI service and refresh this dashboard to load live studio state."
        />
      ) : null}
    </div>
  );
}

function MetricCard({
  icon: Icon,
  label,
  value,
  detail,
  tone = "neutral",
}: {
  icon: typeof Server;
  label: string;
  value: string;
  detail: string;
  tone?: "neutral" | "good" | "muted";
}) {
  const toneClass = {
    neutral: "bg-[#e8f1f4] text-[#176b87]",
    good: "bg-[#ecf8f0] text-[#24563a]",
    muted: "bg-[#f1f3f4] text-[#5b656b]",
  }[tone];

  return (
    <div className="rounded-md border border-[#d6dde1] bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold uppercase text-[#6f7f87]">{label}</p>
          <p className="mt-2 truncate text-2xl font-semibold text-[#1f2933]">{value}</p>
        </div>
        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-md ${toneClass}`}>
          <Icon className="h-5 w-5" aria-hidden="true" />
        </div>
      </div>
      <p className="mt-3 truncate text-sm text-[#62717a]">{detail}</p>
    </div>
  );
}

function Panel({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: typeof FileText;
  children: ReactNode;
}) {
  return (
    <section className="min-w-0">
      <div className="mb-3 flex items-center gap-2">
        <Icon className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
        <h3 className="truncate text-base font-semibold text-[#1f2933]">{title}</h3>
      </div>
      {children}
    </section>
  );
}
