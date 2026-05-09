import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
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

type GraphNodeData = {
  label: string;
  type: string;
  detail: string;
};

const nodeTypes = { graphEntity: GraphEntityNode };

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
  const visualGraph = useMemo(() => buildVisualGraph(previewNodes, previewEdges), [previewNodes, previewEdges]);

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
        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="h-[560px] overflow-hidden rounded-md border border-[#d6dde1] bg-white">
            <ReactFlow
              nodes={visualGraph.nodes}
              edges={visualGraph.edges}
              nodeTypes={nodeTypes}
              fitView
              nodesDraggable
              nodesConnectable={false}
              minZoom={0.35}
              maxZoom={1.6}
              aria-label="Graph relationship map"
            >
              <Background color="#d7e0e4" gap={20} />
              <MiniMap pannable zoomable nodeStrokeWidth={3} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
          <div className="grid min-w-0 gap-4">
            <GraphList title="Nodes" items={previewNodes} total={nodes.length} />
            <GraphList title="Edges" items={previewEdges} total={edges.length} />
          </div>
        </section>
      )}
    </div>
  );
}

function GraphEntityNode({ data }: NodeProps<Node<GraphNodeData>>) {
  return (
    <div className="min-w-48 max-w-64 rounded-md border border-[#c9d6dc] bg-white px-3 py-2 shadow-sm">
      <Handle type="target" position={Position.Left} className="!bg-[#176b87]" />
      <p className="truncate text-sm font-semibold text-[#1f2933]">{data.label}</p>
      <p className="mt-1 truncate text-xs font-medium text-[#176b87]">{data.type}</p>
      {data.detail ? <p className="mt-1 line-clamp-2 text-xs leading-5 text-[#62717a]">{data.detail}</p> : null}
      <Handle type="source" position={Position.Right} className="!bg-[#176b87]" />
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

function buildVisualGraph(
  rawNodes: Record<string, unknown>[],
  rawEdges: Record<string, unknown>[],
): { nodes: Node<GraphNodeData>[]; edges: Edge[] } {
  const graphNodes = rawNodes.map((item, index) => {
    const id = graphId(item, index);
    return {
      id,
      type: "graphEntity",
      position: graphPosition(index, rawNodes.length),
      data: {
        label: graphLabel(item, id),
        type: graphType(item, "entity"),
        detail: graphDetail(item),
      },
    };
  });
  const nodeIds = new Set(graphNodes.map((node) => node.id));
  const graphEdges = rawEdges.flatMap<Edge>((item, index) => {
    const source = graphEndpoint(item, ["source", "source_id", "from", "start"]);
    const target = graphEndpoint(item, ["target", "target_id", "to", "end"]);
    if (!source || !target || !nodeIds.has(source) || !nodeIds.has(target)) {
      return [];
    }
    return [
      {
        id: String(item.id ?? item.edge_id ?? `${source}-${target}-${index}`),
        source,
        target,
        label: graphType(item, "relates"),
        animated: false,
        style: { stroke: "#176b87", strokeWidth: 2 },
        labelStyle: { fill: "#3a4a53", fontSize: 12, fontWeight: 600 },
      },
    ];
  });
  return { nodes: graphNodes, edges: graphEdges };
}

function graphId(item: Record<string, unknown>, index: number): string {
  return String(item.id ?? item.node_id ?? item.name ?? item.label ?? `node-${index + 1}`);
}

function graphLabel(item: Record<string, unknown>, fallback: string): string {
  const properties = graphProperties(item);
  return String(
    item.label ??
      item.name ??
      item.title ??
      item.text ??
      properties.label ??
      properties.name ??
      properties.title ??
      properties.text ??
      fallback,
  );
}

function graphType(item: Record<string, unknown>, fallback: string): string {
  const labels = item.labels;
  const properties = graphProperties(item);
  const firstLabel = Array.isArray(labels) && labels.length > 0 ? labels[0] : null;
  return String(
    item.type ??
      item.kind ??
      item.label_type ??
      item.relationship ??
      properties.type ??
      properties.kind ??
      firstLabel ??
      fallback,
  );
}

function graphDetail(item: Record<string, unknown>): string {
  const properties = graphProperties(item);
  const page = item.page ?? item.page_idx ?? item.page_start ?? properties.page ?? properties.page_idx;
  const document =
    item.document_id ?? item.document ?? item.source_document ?? properties.document_id;
  return [document ? `document ${String(document)}` : null, page != null ? `page ${String(page)}` : null]
    .filter(Boolean)
    .join(" · ");
}

function graphProperties(item: Record<string, unknown>): Record<string, unknown> {
  const properties = item.properties;
  return typeof properties === "object" && properties !== null && !Array.isArray(properties)
    ? (properties as Record<string, unknown>)
    : {};
}

function graphEndpoint(item: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = item[key];
    if (typeof value === "string" && value) {
      return value;
    }
  }
  return null;
}

function graphPosition(index: number, total: number): { x: number; y: number } {
  const columns = Math.max(1, Math.ceil(Math.sqrt(total)));
  const column = index % columns;
  const row = Math.floor(index / columns);
  return { x: column * 260, y: row * 150 };
}
