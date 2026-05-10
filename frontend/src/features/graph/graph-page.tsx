import { useMemo, useState } from "react";
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
  Filter,
  GitBranch,
  Loader2,
  Network,
  RefreshCcw,
  Search,
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

type GraphFilters = {
  nodeType: string;
  edgeType: string;
  documentId: string;
  searchText: string;
};

type GraphFilterOptions = {
  nodeTypes: string[];
  edgeTypes: string[];
  documentIds: string[];
};

const nodeTypes = { graphEntity: GraphEntityNode };

const emptyGraphItems: Record<string, unknown>[] = [];

const emptyFilters: GraphFilters = {
  nodeType: "",
  edgeType: "",
  documentId: "",
  searchText: "",
};

export function GraphPage() {
  const [filters, setFilters] = useState<GraphFilters>(emptyFilters);
  const graphQuery = useQuery({ queryKey: queryKeys.graph, queryFn: apiClient.graph });
  const diagnosticsQuery = useQuery({ queryKey: queryKeys.diagnostics, queryFn: apiClient.diagnostics });
  const nodes = graphQuery.data?.nodes ?? emptyGraphItems;
  const edges = graphQuery.data?.edges ?? emptyGraphItems;
  const hasGraphData = nodes.length > 0 || edges.length > 0;
  const filterOptions = useMemo(() => buildGraphFilterOptions(nodes, edges), [nodes, edges]);
  const filteredGraph = useMemo(() => filterGraphData(nodes, edges, filters), [nodes, edges, filters]);
  const hasActiveFilters = hasGraphFilters(filters);
  const graphAvailable = diagnosticsQuery.data?.capabilities.graph ?? true;
  const graphUnavailableDetail =
    diagnosticsQuery.data?.warnings.find((warning) => warning.toLowerCase().includes("graph")) ??
    diagnosticsQuery.data?.checks.find((check) => check.name === "runtime_mode")?.detail ??
    "Graph capability is disabled by the active runtime profile.";

  const previewNodes = filteredGraph.nodes.slice(0, 50);
  const previewEdges = filteredGraph.edges.slice(0, 50);
  const visualGraph = useMemo(() => buildVisualGraph(previewNodes, previewEdges), [previewNodes, previewEdges]);
  const filteredResultEmpty = hasGraphData && filteredGraph.nodes.length === 0 && filteredGraph.edges.length === 0;

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
        <Metric
          icon={CircleDot}
          label={hasActiveFilters ? "Visible nodes" : "Nodes"}
          value={formatCount(hasGraphData ? filteredGraph.nodes.length : nodes.length)}
          detail={hasActiveFilters ? `${formatCount(nodes.length)} total` : undefined}
        />
        <Metric
          icon={GitBranch}
          label={hasActiveFilters ? "Visible edges" : "Edges"}
          value={formatCount(hasGraphData ? filteredGraph.edges.length : edges.length)}
          detail={hasActiveFilters ? `${formatCount(edges.length)} total` : undefined}
        />
      </section>

      {graphQuery.data?.detail ? (
        <div className="rounded-md border border-[#f4c95d] bg-[#fff8e1] px-3 py-2 text-sm text-[#6d5700]">
          {graphQuery.data.detail}
        </div>
      ) : null}

      {nodes.length > previewNodes.length || edges.length > previewEdges.length ? (
        <div className="rounded-md border border-[#d6dde1] bg-[#f7fafb] px-3 py-2 text-sm text-[#3a4a53]">
          Showing {visualGraph.nodes.length} of {nodes.length} nodes and {visualGraph.edges.length} of{" "}
          {edges.length} edges in the visual preview.
        </div>
      ) : null}

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
      ) : !graphAvailable && !hasGraphData ? (
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
      ) : !hasGraphData ? (
        <EmptyState
          icon={Network}
          title="Graph is empty"
          description="The backend returned no nodes or edges yet."
        />
      ) : (
        <section className="grid gap-4">
          <GraphFiltersPanel
            filters={filters}
            options={filterOptions}
            onChange={setFilters}
            onReset={() => setFilters(emptyFilters)}
          />
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <div className="h-[560px] overflow-hidden rounded-md border border-[#d6dde1] bg-white">
              {filteredResultEmpty ? (
                <div className="flex h-full items-center justify-center p-6">
                  <EmptyState
                    icon={Filter}
                    title="No graph matches"
                    description="Adjust the filters to explore a different slice of the graph."
                  />
                </div>
              ) : (
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
              )}
            </div>
            <div className="grid min-w-0 gap-4">
              <GraphList title="Nodes" items={previewNodes} total={filteredGraph.nodes.length} />
              <GraphList title="Edges" items={previewEdges} total={filteredGraph.edges.length} />
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

function GraphFiltersPanel({
  filters,
  options,
  onChange,
  onReset,
}: {
  filters: GraphFilters;
  options: GraphFilterOptions;
  onChange: (filters: GraphFilters) => void;
  onReset: () => void;
}) {
  const active = hasGraphFilters(filters);

  return (
    <div className="rounded-md border border-[#d6dde1] bg-white p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
        <FilterSelect
          label="Node type"
          value={filters.nodeType}
          options={options.nodeTypes}
          placeholder="All node types"
          onChange={(nodeType) => onChange({ ...filters, nodeType })}
        />
        <FilterSelect
          label="Edge type"
          value={filters.edgeType}
          options={options.edgeTypes}
          placeholder="All edge types"
          onChange={(edgeType) => onChange({ ...filters, edgeType })}
        />
        <FilterSelect
          label="Document id"
          value={filters.documentId}
          options={options.documentIds}
          placeholder="All documents"
          onChange={(documentId) => onChange({ ...filters, documentId })}
        />
        <label className="min-w-0 flex-1 text-sm font-medium text-[#3a4a53]">
          Page or reference
          <div className="mt-1 flex h-10 items-center gap-2 rounded-md border border-[#d6dde1] bg-white px-3 focus-within:ring-2 focus-within:ring-[#176b87]">
            <Search className="h-4 w-4 shrink-0 text-[#6f7f87]" aria-hidden="true" />
            <input
              value={filters.searchText}
              onChange={(event) => onChange({ ...filters, searchText: event.target.value })}
              placeholder="Label, id, page, ref"
              className="min-w-0 flex-1 bg-transparent text-sm text-[#24313a] outline-none placeholder:text-[#8c9aa1]"
            />
          </div>
        </label>
        <Button variant="secondary" onClick={onReset} disabled={!active}>
          Reset
        </Button>
      </div>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  placeholder: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="min-w-0 flex-1 text-sm font-medium text-[#3a4a53]">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 h-10 w-full rounded-md border border-[#d6dde1] bg-white px-3 text-sm text-[#24313a] outline-none focus:ring-2 focus:ring-[#176b87]"
      >
        <option value="">{placeholder}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
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
  detail,
}: {
  icon: typeof CircleDot;
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="rounded-md border border-[#d6dde1] bg-white p-4">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-[#e7f1f4] text-[#176b87]">
          <Icon className="h-5 w-5" aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm text-[#62717a]">{label}</p>
          <div className="flex flex-wrap items-baseline gap-x-2">
            <p className="truncate text-2xl font-semibold text-[#1f2933]">{value}</p>
            {detail ? <p className="truncate text-xs text-[#6f7f87]">{detail}</p> : null}
          </div>
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
        {items.length === 0 ? (
          <p className="rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3 text-sm text-[#62717a]">
            No matching {title.toLowerCase()}.
          </p>
        ) : (
          items.map((item, index) => (
            <pre
              key={`${title}-${index}`}
              className="whitespace-pre-wrap break-words rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3 text-xs leading-5 text-[#3a4a53]"
            >
              {JSON.stringify(item, null, 2)}
            </pre>
          ))
        )}
      </div>
    </div>
  );
}

function buildGraphFilterOptions(
  rawNodes: Record<string, unknown>[],
  rawEdges: Record<string, unknown>[],
): GraphFilterOptions {
  return {
    nodeTypes: uniqueSorted(rawNodes.map((item) => graphType(item, "entity"))),
    edgeTypes: uniqueSorted(rawEdges.map((item) => graphType(item, "relates"))),
    documentIds: uniqueSorted([...rawNodes, ...rawEdges].flatMap((item) => graphDocumentIds(item))),
  };
}

function filterGraphData(
  rawNodes: Record<string, unknown>[],
  rawEdges: Record<string, unknown>[],
  filters: GraphFilters,
): { nodes: Record<string, unknown>[]; edges: Record<string, unknown>[] } {
  if (!hasGraphFilters(filters)) {
    return { nodes: rawNodes, edges: rawEdges };
  }

  const nodeEntries = rawNodes.map((node, index) => ({ node, id: graphId(node, index) }));
  const nodesById = new Map(nodeEntries.map((entry) => [entry.id, entry.node]));
  const visibleNodeIds = new Set<string>();
  const hasNodeScopedFilter = Boolean(filters.nodeType || filters.documentId || filters.searchText.trim());
  const normalizedSearch = filters.searchText.trim().toLowerCase();

  for (const entry of nodeEntries) {
    if (nodeMatchesFilters(entry.node, filters, normalizedSearch)) {
      visibleNodeIds.add(entry.id);
    }
  }

  const edgeEntries = rawEdges.map((edge) => ({
    edge,
    source: graphEndpoint(edge, ["source", "source_id", "from", "start"]),
    target: graphEndpoint(edge, ["target", "target_id", "to", "end"]),
  }));
  const matchingEdgeEntries = edgeEntries.filter((entry) => {
    if (!entry.source || !entry.target) {
      return false;
    }
    return edgeMatchesFilters(entry.edge, filters, normalizedSearch);
  });

  if (!hasNodeScopedFilter) {
    for (const entry of matchingEdgeEntries) {
      const source = entry.source;
      const target = entry.target;
      if (source && nodesById.has(source)) {
        visibleNodeIds.add(source);
      }
      if (target && nodesById.has(target)) {
        visibleNodeIds.add(target);
      }
    }
  } else {
    for (const entry of matchingEdgeEntries) {
      if (filters.nodeType) {
        continue;
      }
      if (entry.source && nodesById.has(entry.source)) {
        visibleNodeIds.add(entry.source);
      }
      if (entry.target && nodesById.has(entry.target)) {
        visibleNodeIds.add(entry.target);
      }
    }
  }

  const filteredNodes = nodeEntries
    .filter((entry) => visibleNodeIds.has(entry.id))
    .map((entry) => entry.node);
  const filteredEdges = edgeEntries
    .filter((entry) => {
      if (!entry.source || !entry.target) {
        return false;
      }
      if (!visibleNodeIds.has(entry.source) || !visibleNodeIds.has(entry.target)) {
        return false;
      }
      if (edgeScopedFiltersActive(filters)) {
        return edgeMatchesFilters(entry.edge, filters, normalizedSearch);
      }
      return true;
    })
    .map((entry) => entry.edge);

  return { nodes: filteredNodes, edges: filteredEdges };
}

function nodeMatchesFilters(
  item: Record<string, unknown>,
  filters: GraphFilters,
  normalizedSearch: string,
): boolean {
  if (filters.nodeType && graphType(item, "entity") !== filters.nodeType) {
    return false;
  }
  if (filters.documentId && !graphDocumentIds(item).includes(filters.documentId)) {
    return false;
  }
  if (normalizedSearch && !graphSearchText(item).includes(normalizedSearch)) {
    return false;
  }
  return true;
}

function edgeMatchesFilters(
  item: Record<string, unknown>,
  filters: GraphFilters,
  normalizedSearch: string,
): boolean {
  if (filters.edgeType && graphType(item, "relates") !== filters.edgeType) {
    return false;
  }
  if (filters.documentId && !graphDocumentIds(item).includes(filters.documentId)) {
    return false;
  }
  if (normalizedSearch && !graphSearchText(item).includes(normalizedSearch)) {
    return false;
  }
  return true;
}

function hasGraphFilters(filters: GraphFilters): boolean {
  return Boolean(filters.nodeType || filters.edgeType || filters.documentId || filters.searchText.trim());
}

function edgeScopedFiltersActive(filters: GraphFilters): boolean {
  return Boolean(filters.edgeType || filters.documentId || filters.searchText.trim());
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

function graphDocumentIds(item: Record<string, unknown>): string[] {
  const properties = graphProperties(item);
  return uniqueSorted([
    ...valueStrings(item.document_id),
    ...valueStrings(item.document_ids),
    ...valueStrings(item.document),
    ...valueStrings(item.source_document),
    ...valueStrings(properties.document_id),
    ...valueStrings(properties.document_ids),
    ...valueStrings(properties.document),
    ...valueStrings(properties.source_document),
  ]);
}

function graphSearchText(item: Record<string, unknown>): string {
  const properties = graphProperties(item);
  return uniqueSorted([
    ...valueStrings(item.id),
    ...valueStrings(item.node_id),
    ...valueStrings(item.edge_id),
    ...valueStrings(item.label),
    ...valueStrings(item.labels),
    ...valueStrings(item.name),
    ...valueStrings(item.title),
    ...valueStrings(item.text),
    ...valueStrings(item.type),
    ...valueStrings(item.kind),
    ...valueStrings(item.relationship),
    ...valueStrings(item.page),
    ...valueStrings(item.page_idx),
    ...valueStrings(item.page_start),
    ...valueStrings(item.page_end),
    ...valueStrings(item.reference),
    ...valueStrings(item.ref),
    ...valueStrings(properties.label),
    ...valueStrings(properties.labels),
    ...valueStrings(properties.name),
    ...valueStrings(properties.title),
    ...valueStrings(properties.text),
    ...valueStrings(properties.type),
    ...valueStrings(properties.kind),
    ...valueStrings(properties.page),
    ...valueStrings(properties.page_idx),
    ...valueStrings(properties.page_start),
    ...valueStrings(properties.page_end),
    ...valueStrings(properties.reference),
    ...valueStrings(properties.ref),
    ...graphDocumentIds(item),
    graphType(item, "entity"),
    graphDetail(item),
  ])
    .join(" ")
    .toLowerCase();
}

function graphProperties(item: Record<string, unknown>): Record<string, unknown> {
  const properties = item.properties;
  return typeof properties === "object" && properties !== null && !Array.isArray(properties)
    ? (properties as Record<string, unknown>)
    : {};
}

function graphEndpoint(item: Record<string, unknown>, keys: string[]): string | null {
  const properties = graphProperties(item);
  for (const key of keys) {
    const value = item[key];
    if (typeof value === "string" && value) {
      return value;
    }
    const propertyValue = properties[key];
    if (typeof propertyValue === "string" && propertyValue) {
      return propertyValue;
    }
  }
  return null;
}

function uniqueSorted(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean))).sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }),
  );
}

function valueStrings(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.flatMap((item) => valueStrings(item));
  }
  if (typeof value === "string") {
    return value ? [value] : [];
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return [String(value)];
  }
  return [];
}

function graphPosition(index: number, total: number): { x: number; y: number } {
  const columns = Math.max(1, Math.ceil(Math.sqrt(total)));
  const column = index % columns;
  const row = Math.floor(index / columns);
  return { x: column * 260, y: row * 150 };
}
