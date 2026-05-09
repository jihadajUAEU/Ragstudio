import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  CircleDot,
  GitBranch,
  Loader2,
  Network,
  RefreshCcw,
} from "lucide-react";

import { apiClient } from "../../api/client";
import { EmptyState } from "../../components/empty-state";
import { Button } from "../../components/ui/button";
import { formatCount } from "../../lib/utils";

const queryKeys = {
  graph: ["graph"],
  diagnostics: ["diagnostics"],
} as const;

export function GraphPage() {
  const graphQuery = useQuery({ queryKey: queryKeys.graph, queryFn: apiClient.graph });
  const diagnosticsQuery = useQuery({ queryKey: queryKeys.diagnostics, queryFn: apiClient.diagnostics });
  const nodes = graphQuery.data?.nodes ?? [];
  const edges = graphQuery.data?.edges ?? [];
  const graphAvailable = diagnosticsQuery.data?.capabilities.graph ?? true;
  const graphUnavailableDetail =
    diagnosticsQuery.data?.warnings.find((warning) => warning.toLowerCase().includes("graph")) ??
    diagnosticsQuery.data?.checks.find((check) => check.name === "runtime_mode")?.detail ??
    "Graph capability is disabled by the active runtime profile.";

  const previewNodes = nodes.slice(0, 50);
  const previewEdges = edges.slice(0, 50);

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <section className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium text-[#176b87]">Graph</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-normal text-[#1f2933]">
            Nodes, edges, and graph payload details
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[#62717a]">
            Reads `/api/graph` directly and exposes the returned shape for debugging graph-backed
            retrieval.
          </p>
        </div>
        <Button variant="secondary" onClick={() => void graphQuery.refetch()} disabled={graphQuery.isFetching}>
          {graphQuery.isFetching ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCcw className="h-4 w-4" aria-hidden="true" />
          )}
          Refresh
        </Button>
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        <Metric icon={CircleDot} label="Nodes" value={formatCount(nodes.length)} />
        <Metric icon={GitBranch} label="Edges" value={formatCount(edges.length)} />
      </section>

      {graphQuery.isLoading || diagnosticsQuery.isLoading ? (
        <EmptyState icon={Loader2} title="Loading graph" description="Fetching graph data." />
      ) : graphQuery.isError ? (
        <EmptyState
          icon={AlertCircle}
          title="Graph unavailable"
          description={graphQuery.error.message}
          action={
            <Button variant="secondary" onClick={() => void graphQuery.refetch()}>
              <RefreshCcw className="h-4 w-4" aria-hidden="true" />
              Retry
            </Button>
          }
        />
      ) : !graphAvailable ? (
        <EmptyState
          icon={AlertCircle}
          title="Graph unavailable"
          description={graphUnavailableDetail}
          action={
            <Button variant="secondary" onClick={() => void diagnosticsQuery.refetch()}>
              <RefreshCcw className="h-4 w-4" aria-hidden="true" />
              Refresh diagnostics
            </Button>
          }
        />
      ) : nodes.length === 0 && edges.length === 0 ? (
        <EmptyState
          icon={Network}
          title="Graph is empty"
          description="The backend returned no nodes or edges yet."
        />
      ) : (
        <section className="grid gap-4 xl:grid-cols-2">
          <GraphList title="Nodes" items={previewNodes} total={nodes.length} />
          <GraphList title="Edges" items={previewEdges} total={edges.length} />
        </section>
      )}
    </div>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof CircleDot;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-md border border-[#d6dde1] bg-white p-4">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-[#e7f1f4] text-[#176b87]">
          <Icon className="h-5 w-5" aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm text-[#62717a]">{label}</p>
          <p className="truncate text-2xl font-semibold text-[#1f2933]">{value}</p>
        </div>
      </div>
    </div>
  );
}

function GraphList({
  title,
  items,
  total,
}: {
  title: string;
  items: Record<string, unknown>[];
  total: number;
}) {
  return (
    <div className="min-w-0 rounded-md border border-[#d6dde1] bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="truncate text-base font-semibold text-[#1f2933]">{title}</h3>
        <span className="shrink-0 text-xs text-[#62717a]">
          Showing {formatCount(items.length)} of {formatCount(total)}
        </span>
      </div>
      <div className="max-h-[560px] space-y-2 overflow-auto pr-1">
        {items.map((item, index) => (
          <pre
            key={`${title}-${index}`}
            className="whitespace-pre-wrap break-words rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3 text-xs leading-5 text-[#3a4a53]"
          >
            {JSON.stringify(item, null, 2)}
          </pre>
        ))}
      </div>
    </div>
  );
}
