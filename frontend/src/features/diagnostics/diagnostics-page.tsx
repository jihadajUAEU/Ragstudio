import { useMemo, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { AlertCircle, AlertTriangle, CheckCircle2, Loader2, RefreshCcw, ServerCog, XCircle } from "lucide-react";

import { apiClient } from "../../api/client";
import type { RuntimeHealthCheck, RuntimeOverallStatus } from "../../api/generated";
import { DataTable } from "../../components/data-table";
import { EmptyState } from "../../components/empty-state";
import { Button } from "../../components/ui/button";

const queryKeys = {
  diagnostics: ["diagnostics"],
} as const;

interface CapabilityRow {
  name: string;
  enabled: boolean;
}

interface DependencyRow {
  name: string;
  value: unknown;
}

export function DiagnosticsPage() {
  const diagnosticsQuery = useQuery({
    queryKey: queryKeys.diagnostics,
    queryFn: apiClient.diagnostics,
  });

  const capabilityRows = useMemo<CapabilityRow[]>(
    () =>
      Object.entries(diagnosticsQuery.data?.capabilities ?? {}).map(([name, enabled]) => ({
        name,
        enabled,
      })),
    [diagnosticsQuery.data?.capabilities],
  );

  const dependencyRows = useMemo<DependencyRow[]>(
    () =>
      Object.entries(diagnosticsQuery.data?.dependency_status ?? {}).map(([name, value]) => ({
        name,
        value,
      })),
    [diagnosticsQuery.data?.dependency_status],
  );

  const capabilityColumns = useMemo<ColumnDef<CapabilityRow>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Capability",
        cell: ({ row }) => <span className="truncate font-medium">{humanize(row.original.name)}</span>,
      },
      {
        accessorKey: "enabled",
        header: "Status",
        cell: ({ row }) => (
          <span
            className={
              row.original.enabled
                ? "inline-flex items-center gap-2 rounded-md bg-[#ecf8f0] px-2 py-1 text-xs font-medium text-[#24563a]"
                : "inline-flex items-center gap-2 rounded-md bg-[#f1f3f4] px-2 py-1 text-xs font-medium text-[#5b656b]"
            }
          >
            {row.original.enabled ? (
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {row.original.enabled ? "Ready" : "Unavailable"}
          </span>
        ),
      },
    ],
    [],
  );

  const dependencyColumns = useMemo<ColumnDef<DependencyRow>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Dependency",
        cell: ({ row }) => <span className="truncate font-medium">{humanize(row.original.name)}</span>,
      },
      {
        accessorKey: "value",
        header: "Status",
        cell: ({ row }) => <StatusValue value={row.original.value} />,
      },
    ],
    [],
  );

  const checkColumns = useMemo<ColumnDef<RuntimeHealthCheck>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Check",
        cell: ({ row }) => <span className="truncate font-medium">{humanize(row.original.name)}</span>,
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <CheckStatus check={row.original} />,
      },
      {
        accessorKey: "severity",
        header: "Severity",
        cell: ({ row }) => <span className="truncate">{titleCase(row.original.severity)}</span>,
      },
      {
        accessorKey: "detail",
        header: "Detail",
        cell: ({ row }) => (
          <span className="line-clamp-2" title={row.original.detail}>
            {row.original.detail}
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
          <p className="text-sm font-medium text-[#176b87]">Diagnostics</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-normal text-[#1f2933]">
            Capabilities and dependency status
          </h2>
        </div>
        <Button
          variant="secondary"
          onClick={() => void diagnosticsQuery.refetch()}
          disabled={diagnosticsQuery.isFetching}
        >
          {diagnosticsQuery.isFetching ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCcw className="h-4 w-4" aria-hidden="true" />
          )}
          Refresh
        </Button>
      </section>

      {diagnosticsQuery.isLoading ? (
        <EmptyState icon={Loader2} title="Loading diagnostics" description="Fetching service capabilities and dependencies." />
      ) : diagnosticsQuery.isError ? (
        <EmptyState
          icon={AlertCircle}
          title="Diagnostics unavailable"
          description={diagnosticsQuery.error.message}
          action={
            <Button variant="secondary" onClick={() => void diagnosticsQuery.refetch()}>
              <RefreshCcw className="h-4 w-4" aria-hidden="true" />
              Retry
            </Button>
          }
        />
      ) : diagnosticsQuery.data ? (
        <>
          <section className="grid gap-4 sm:grid-cols-3">
            <Metric
              icon={ServerCog}
              label="Overall status"
              value={<OverallStatusBadge status={diagnosticsQuery.data.overall_status} />}
              detail={titleCase(diagnosticsQuery.data.runtime_mode)}
            />
            <Metric
              icon={CheckCircle2}
              label="Checks"
              value={String(diagnosticsQuery.data.checks.length)}
              detail={`${dependencyRows.length} dependency keys`}
            />
            <Metric
              icon={AlertTriangle}
              label="Warnings"
              value={String(diagnosticsQuery.data.warnings.length)}
              detail="Active notices"
            />
          </section>

          {diagnosticsQuery.data.warnings.length ? (
            <section className="rounded-md border border-[#e5c36b] bg-[#fff8e6] p-4">
              <div className="flex gap-3">
                <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-[#8c6500]" aria-hidden="true" />
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold text-[#5f4600]">Warnings</h3>
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

          <section className="grid gap-4 xl:grid-cols-2">
            <Panel title="Capabilities">
              <DataTable
                columns={capabilityColumns}
                data={capabilityRows}
                emptyTitle="No capabilities"
                emptyDescription="Capability flags will appear when the backend reports them."
              />
            </Panel>
            <Panel title="Dependencies">
              <DataTable
                columns={dependencyColumns}
                data={dependencyRows}
                emptyTitle="No dependencies"
                emptyDescription="Dependency statuses will appear when the backend reports them."
              />
            </Panel>
          </section>

          <Panel title="Runtime checks">
            <DataTable
              columns={checkColumns}
              data={diagnosticsQuery.data.checks}
              emptyTitle="No runtime checks"
              emptyDescription="Runtime health checks will appear when the backend reports them."
            />
          </Panel>

          <details className="rounded-md border border-[#d6dde1] bg-white p-4">
            <summary className="cursor-pointer text-sm font-semibold text-[#1f2933]">Raw diagnostics</summary>
            <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-md bg-[#f8fafb] p-3 text-xs leading-5 text-[#3a4a53]">
              {JSON.stringify(diagnosticsQuery.data, null, 2)}
            </pre>
          </details>
        </>
      ) : null}
    </div>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: typeof ServerCog;
  label: string;
  value: ReactNode;
  detail: string;
}) {
  return (
    <div className="rounded-md border border-[#d6dde1] bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold uppercase text-[#6f7f87]">{label}</p>
          <p className="mt-2 truncate text-2xl font-semibold text-[#1f2933]">{value}</p>
        </div>
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-[#e8f1f4] text-[#176b87]">
          <Icon className="h-5 w-5" aria-hidden="true" />
        </div>
      </div>
      <p className="mt-3 truncate text-sm text-[#62717a]">{detail}</p>
    </div>
  );
}

function OverallStatusBadge({ status }: { status: RuntimeOverallStatus }) {
  const isReady = status === "ready";
  const isWarning = status === "degraded" || status === "fallback";
  return (
    <span
      className={
        isReady
          ? "inline-flex items-center gap-2 rounded-md bg-[#ecf8f0] px-2 py-1 text-xs font-medium text-[#24563a]"
          : isWarning
            ? "inline-flex items-center gap-2 rounded-md bg-[#fff8e6] px-2 py-1 text-xs font-medium text-[#8c6500]"
            : "inline-flex items-center gap-2 rounded-md bg-[#fff0f0] px-2 py-1 text-xs font-medium text-[#8c2525]"
      }
    >
      {isReady ? (
        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
      ) : isWarning ? (
        <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
      ) : (
        <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
      )}
      {titleCase(status)}
    </span>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="min-w-0">
      <div className="mb-3 flex items-center gap-2">
        <ServerCog className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
        <h3 className="truncate text-base font-semibold text-[#1f2933]">{title}</h3>
      </div>
      {children}
    </section>
  );
}

function StatusValue({ value }: { value: unknown }) {
  if (typeof value === "boolean") {
    return value ? (
      <span className="inline-flex items-center gap-2 rounded-md bg-[#ecf8f0] px-2 py-1 text-xs font-medium text-[#24563a]">
        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
        Ready
      </span>
    ) : (
      <span className="inline-flex items-center gap-2 rounded-md bg-[#fff0f0] px-2 py-1 text-xs font-medium text-[#8c2525]">
        <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
        Missing
      </span>
    );
  }

  if (typeof value === "string" || typeof value === "number") {
    return <span className="truncate">{String(value)}</span>;
  }

  return (
    <code className="block max-w-sm truncate text-xs text-[#62717a]">
      {JSON.stringify(value)}
    </code>
  );
}

function CheckStatus({ check }: { check: RuntimeHealthCheck }) {
  const isReady = check.status === "ok";
  const isWarning = check.status === "warning" || check.status === "skipped";
  return (
    <span
      className={
        isReady
          ? "inline-flex items-center gap-2 rounded-md bg-[#ecf8f0] px-2 py-1 text-xs font-medium text-[#24563a]"
          : isWarning
            ? "inline-flex items-center gap-2 rounded-md bg-[#fff8e6] px-2 py-1 text-xs font-medium text-[#8c6500]"
            : "inline-flex items-center gap-2 rounded-md bg-[#fff0f0] px-2 py-1 text-xs font-medium text-[#8c2525]"
      }
    >
      {isReady ? (
        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
      ) : isWarning ? (
        <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
      ) : (
        <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
      )}
      {titleCase(check.status)}
    </span>
  );
}

function titleCase(value: string) {
  return humanize(value).replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function humanize(value: string) {
  return value.replace(/[_-]+/g, " ");
}
