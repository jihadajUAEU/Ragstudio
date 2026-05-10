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
  AlertTriangle,
  BrainCircuit,
  Database,
  FileText,
  GitBranch,
  Info,
  Loader2,
  MessageSquareText,
  RefreshCcw,
  Search,
  SlidersHorizontal,
} from "lucide-react";

import { apiClient } from "../../api/client";
import type { RuntimeHealthCheck } from "../../api/generated";
import { EmptyState } from "../../components/empty-state";
import { Button } from "../../components/ui/button";
import { formatCount } from "../../lib/utils";

type PipelineNodeData = {
  label: string;
  detail: string;
  metric: string;
  tone: "input" | "process" | "output";
};

const queryKeys = {
  documents: ["documents"],
  variants: ["variants"],
  runs: ["runs"],
  graph: ["graph"],
  diagnostics: ["diagnostics"],
} as const;

const nodeTypes = { pipelineStage: PipelineStageNode };

export function PipelineBuilder() {
  const documentsQuery = useQuery({ queryKey: queryKeys.documents, queryFn: apiClient.documents });
  const variantsQuery = useQuery({ queryKey: queryKeys.variants, queryFn: apiClient.variants });
  const runsQuery = useQuery({ queryKey: queryKeys.runs, queryFn: apiClient.runs });
  const graphQuery = useQuery({ queryKey: queryKeys.graph, queryFn: apiClient.graph });
  const diagnosticsQuery = useQuery({
    queryKey: queryKeys.diagnostics,
    queryFn: apiClient.diagnostics,
  });
  const stageDiagnostics = useMemo(
    () => getStageDiagnostics(diagnosticsQuery.data?.checks ?? [], diagnosticsQuery.data?.warnings ?? []),
    [diagnosticsQuery.data?.checks, diagnosticsQuery.data?.warnings],
  );

  const nodes = useMemo<Node<PipelineNodeData>[]>(
    () => [
      stage("documents", "Documents", "Upload source files", formatCount(documentsQuery.data?.total), 0, 0, "input"),
      stage("chunking", "Chunking", "Index document chunks", "Searchable spans", 260, 0, "process"),
      stage(
        "variants",
        "Variants",
        "Tune retrieval and generation",
        formatCount(variantsQuery.data?.total),
        520,
        -86,
        "process",
      ),
      stage("retrieval", "Retrieval", "Rank matching chunks", "Top-k trace", 520, 86, "process"),
      stage("generation", "Generation", "Compose grounded answer", formatCount(runsQuery.data?.total), 780, 0, "process"),
      stage(
        "graph",
        "Graph",
        "Inspect entities and edges",
        `${formatCount(graphQuery.data?.nodes.length)} nodes`,
        1040,
        -86,
        "output",
      ),
      stage("answer", "Answer", "Sources, traces, timings", "Run result", 1040, 86, "output"),
    ],
    [documentsQuery.data?.total, graphQuery.data?.nodes.length, runsQuery.data?.total, variantsQuery.data?.total],
  );

  const edges = useMemo<Edge[]>(
    () => [
      edge("documents", "chunking", "parse"),
      edge("chunking", "retrieval", "embed/search"),
      edge("variants", "retrieval", "params"),
      edge("retrieval", "generation", "context"),
      edge("generation", "answer", "ground"),
      edge("chunking", "graph", "entities"),
      edge("graph", "answer", "evidence"),
    ],
    [],
  );

  const isRefreshing =
    documentsQuery.isFetching ||
    variantsQuery.isFetching ||
    runsQuery.isFetching ||
    graphQuery.isFetching ||
    diagnosticsQuery.isFetching;
  const hasError =
    documentsQuery.isError ||
    variantsQuery.isError ||
    runsQuery.isError ||
    graphQuery.isError ||
    diagnosticsQuery.isError;

  const refresh = () => {
    void documentsQuery.refetch();
    void variantsQuery.refetch();
    void runsQuery.refetch();
    void graphQuery.refetch();
    void diagnosticsQuery.refetch();
  };

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <section className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium text-[#176b87]">Pipeline Status</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-normal text-[#1f2933]">
            RAG flow from source files to grounded answers
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[#62717a]">
            The canvas reflects live counts and runtime health for each stage. Configuration and
            execution still happen from Documents, Settings, Variants, and Query.
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

      {hasError ? (
        <EmptyState
          icon={AlertCircle}
          title="Pipeline data unavailable"
          description="One or more pipeline status requests failed. The flow remains available for orientation."
          action={
            <Button variant="secondary" onClick={refresh}>
              <RefreshCcw className="h-4 w-4" aria-hidden="true" />
              Retry
            </Button>
          }
        />
      ) : null}

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-h-[560px] overflow-hidden rounded-md border border-[#d6dde1] bg-white">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            fitView
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            minZoom={0.55}
            maxZoom={1.25}
            aria-label="RAG pipeline flow"
          >
            <Background color="#d7e0e4" gap={20} />
            <MiniMap pannable zoomable nodeStrokeWidth={3} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>

        <aside className="rounded-md border border-[#d6dde1] bg-white p-4">
          <div className="mb-4 flex items-center gap-2">
            <GitBranch className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
            <h3 className="truncate text-base font-semibold text-[#1f2933]">Stage checklist</h3>
          </div>
          <div className="space-y-3">
            <StageCheck
              icon={FileText}
              label="Documents"
              value={formatCount(documentsQuery.data?.total)}
              diagnostic={stageDiagnostics.documents}
            />
            <StageCheck icon={Database} label="Chunks" value="Index per document" diagnostic={stageDiagnostics.chunks} />
            <StageCheck
              icon={SlidersHorizontal}
              label="Variants"
              value={formatCount(variantsQuery.data?.total)}
              diagnostic={stageDiagnostics.variants}
            />
            <StageCheck icon={Search} label="Retrieval" value="Scoped search" diagnostic={stageDiagnostics.retrieval} />
            <StageCheck
              icon={BrainCircuit}
              label="Generation"
              value={formatCount(runsQuery.data?.total)}
              diagnostic={stageDiagnostics.generation}
            />
            <StageCheck
              icon={MessageSquareText}
              label="Answers"
              value="Sources and traces"
              diagnostic={stageDiagnostics.answers}
            />
            <StageCheck
              icon={GitBranch}
              label="Graph"
              value={`${formatCount(graphQuery.data?.edges.length)} edges`}
              diagnostic={stageDiagnostics.graph}
            />
          </div>
          <div className="mt-4 grid gap-2">
            <StageAction href="/documents" label="Open Documents" />
            <StageAction href="/chunks" label="Open Chunks" />
            <StageAction href="/settings" label="Open Settings" />
            <StageAction href="/variants" label="Open Variants" />
            <StageAction href="/query" label="Open Query" />
            <StageAction href="/graph" label="Open Graph" />
            <StageAction href="/diagnostics" label="Open Diagnostics" />
          </div>
          <div className="mt-4 rounded-md border border-[#cfe3ea] bg-[#f5fafb] p-3 text-sm leading-6 text-[#3a4a53]">
            <div className="mb-1 flex items-center gap-2 font-semibold text-[#1f2933]">
              <Info className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
              Read-only map
            </div>
            This page is implemented as a status view. Use the stage actions to edit stages, inspect
            graph evidence, rerun work, or recover failures.
          </div>
        </aside>
      </section>
    </div>
  );
}

function PipelineStageNode({ data }: NodeProps<Node<PipelineNodeData>>) {
  return (
    <div
      className="min-w-52 rounded-md border bg-white px-4 py-3 shadow-sm"
      data-tone={data.tone}
      style={{
        borderColor:
          data.tone === "input" ? "#8bb9c6" : data.tone === "output" ? "#9fba8f" : "#d6dde1",
      }}
    >
      <Handle type="target" position={Position.Left} className="!bg-[#176b87]" />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-[#1f2933]">{data.label}</p>
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-[#62717a]">{data.detail}</p>
        </div>
        <span className="shrink-0 rounded-md bg-[#eef4f6] px-2 py-1 text-xs font-medium text-[#174657]">
          {data.metric}
        </span>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-[#176b87]" />
    </div>
  );
}

function StageCheck({
  icon: Icon,
  label,
  value,
  diagnostic,
}: {
  icon: typeof FileText;
  label: string;
  value: string;
  diagnostic?: string;
}) {
  return (
    <div className="rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3" aria-label={`${label} stage`}>
      <div className="flex items-center gap-3">
        <Icon className="h-4 w-4 shrink-0 text-[#176b87]" aria-hidden="true" />
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-[#24313a]">{label}</p>
          <p className="truncate text-xs text-[#62717a]">{value}</p>
        </div>
      </div>
      {diagnostic ? (
        <p className="mt-2 flex gap-2 rounded-md border border-[#e5c36b] bg-[#fff8e6] px-2 py-1.5 text-xs leading-5 text-[#705300]">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#8c6500]" aria-hidden="true" />
          <span className="line-clamp-2" title={diagnostic}>
            {diagnostic}
          </span>
        </p>
      ) : null}
    </div>
  );
}

function StageAction({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      className="inline-flex h-9 items-center justify-center rounded-md border border-[#d6dde1] bg-white px-3 text-sm font-medium text-[#24313a] hover:bg-[#edf3f5]"
    >
      {label}
    </a>
  );
}

function getStageDiagnostics(checks: RuntimeHealthCheck[], warnings: string[]) {
  const alerts = [
    ...checks
      .filter((check) => check.severity === "blocking" || check.status === "failed")
      .map((check) => ({
        text: check.detail || check.remediation || `${check.name} reported ${check.status}.`,
        haystack: `${check.name} ${check.detail} ${check.remediation ?? ""}`.toLowerCase(),
      })),
    ...warnings.map((warning) => ({ text: warning, haystack: warning.toLowerCase() })),
  ];

  return {
    documents: firstMatching(alerts, ["profile", "setting", "runtime mode"]),
    chunks: firstMatching(alerts, ["index", "chunk", "embed", "pgvector", "raganything", "lightrag"]),
    variants: firstMatching(alerts, ["variant", "profile", "provider", "setting"]),
    retrieval: firstMatching(alerts, ["query", "retrieval", "scoped", "pgvector", "lightrag", "raganything"]),
    generation: firstMatching(alerts, ["query", "generation", "provider", "raganything"]),
    answers: firstMatching(alerts, ["query", "answer", "sources", "scoped"]),
    graph: firstMatching(alerts, ["graph", "neo4j", "relationship"]),
  };
}

function firstMatching(alerts: Array<{ text: string; haystack: string }>, keywords: string[]) {
  return alerts.find((alert) => keywords.some((keyword) => alert.haystack.includes(keyword)))?.text;
}

function stage(
  id: string,
  label: string,
  detail: string,
  metric: string,
  x: number,
  y: number,
  tone: PipelineNodeData["tone"],
): Node<PipelineNodeData> {
  return {
    id,
    type: "pipelineStage",
    position: { x, y },
    data: { label, detail, metric, tone },
  };
}

function edge(source: string, target: string, label: string): Edge {
  return {
    id: `${source}-${target}`,
    source,
    target,
    label,
    animated: true,
    style: { stroke: "#176b87", strokeWidth: 2 },
    labelStyle: { fill: "#3a4a53", fontSize: 12, fontWeight: 600 },
  };
}
