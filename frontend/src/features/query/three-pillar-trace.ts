import type { RunOut } from "../../api/generated";

export interface ThreePillarTraceSummary {
  route: RoutePlanSummary;
  lanes: LaneSummary[];
  layout: LayoutSummary;
  context: ContextWindowSummary;
  assembly: ContextAssemblySummary;
  reranker: RerankerTraceSummary;
  sources: SourceArchitectureSummary[];
}

export interface RoutePlanSummary {
  domainProfileId: string;
  layoutHint: string;
  materializationHint: string;
  sourceOfTruth: string;
  directEvidenceRequired: boolean;
  graphContextRequired: boolean;
  raw?: Record<string, unknown>;
}

export interface LaneSummary {
  lane: string;
  status: string;
  reason: string;
  candidateCount: number | null;
  latencyMs: number | null;
  timedOut: boolean;
  partial: boolean;
  canonicalChunkIds: string[];
  raw: Record<string, unknown>;
}

export interface LayoutSummary {
  status: string;
  reason: string;
  candidateCount: number | null;
  layoutGroupIds: string[];
  readingOrderNeighbors: boolean;
  canonicalChunkIds: string[];
  layoutSummaries: Array<{ chunkId: string; summary: string }>;
  raw?: Record<string, unknown>;
}

export interface ContextWindowSummary {
  status: string;
  reason: string;
  candidateCount: number | null;
  relationshipReasons: Array<{ chunkId: string; reason: string }>;
  raw?: Record<string, unknown>;
}

export interface ContextAssemblySummary {
  includedCandidates: number | null;
  droppedCandidates: number | null;
  evidenceIds: string[];
  groundingStatus: string;
  breadcrumbsVisible: boolean;
  layoutSummaryVisible: boolean;
  droppedReasons: Array<{ candidateId: string; reason: string }>;
  raw?: Record<string, unknown>;
}

export interface RerankerTraceSummary {
  status: string;
  provider: string;
  model: string;
  candidateCount: number | null;
  rankDeltas: Array<{ candidateId: string; before: number; after: number; delta: number }>;
  raw?: Record<string, unknown>;
}

export interface SourceArchitectureSummary {
  sourceId: string;
  domain: {
    domain: string;
    materializationHint: string;
    qualityPolicy: string;
  };
  layout: {
    layoutGroupId: string;
    layoutRole: string;
    readingOrder: string;
  };
  context: {
    parentChunkId: string;
    previousChunkId: string;
    nextChunkId: string;
  };
}

export function buildThreePillarTrace(run: RunOut): ThreePillarTraceSummary {
  const routeTrace = traceByStage(run.chunk_traces, "retrieval_route_plan");
  const layoutTrace = traceByStage(run.chunk_traces, "layout_neighbor_expansion");
  const contextTrace = laneTrace(run.chunk_traces, "context_window");
  const rerankerLaneTrace = laneTrace(run.chunk_traces, "reranker");
  const assemblyTrace = traceByStage(run.chunk_traces, "context_assembly");
  const firstRerankerTrace = recordValue(run.reranker_traces[0]);
  const assembledContext = recordValue(assemblyTrace?.assembled_context);

  return {
    route: {
      domainProfileId:
        textValue(routeTrace?.domain_profile_id) ?? textValue(routeTrace?.domain_id) ?? "not recorded",
      layoutHint: textValue(routeTrace?.layout_hint) ?? "not recorded",
      materializationHint: textValue(routeTrace?.materialization_hint) ?? "not recorded",
      sourceOfTruth: textValue(routeTrace?.source_of_truth) ?? "not recorded",
      directEvidenceRequired: routeTrace?.direct_evidence_required === true,
      graphContextRequired: routeTrace?.graph_context_required === true,
      raw: routeTrace,
    },
    lanes: run.chunk_traces
      .map(recordValue)
      .filter((trace): trace is Record<string, unknown> => trace?.stage === "retrieval_lane_result")
      .map((trace) => ({
        lane: textValue(trace.lane) ?? "unknown",
        status: textValue(trace.status) ?? "unknown",
        reason: textValue(trace.reason) ?? "not recorded",
        candidateCount: numberValue(trace.candidate_count),
        latencyMs: numberValue(trace.latency_ms),
        timedOut: trace.timed_out === true,
        partial: trace.partial === true,
        canonicalChunkIds: stringArray(trace.canonical_chunk_ids),
        raw: trace,
      })),
    layout: {
      status: textValue(layoutTrace?.status) ?? "unknown",
      reason: textValue(layoutTrace?.reason) ?? "not recorded",
      candidateCount: numberValue(layoutTrace?.candidate_count),
      layoutGroupIds: stringArray(layoutTrace?.layout_group_ids),
      readingOrderNeighbors: layoutTrace?.reading_order_neighbors === true,
      canonicalChunkIds: stringArray(layoutTrace?.canonical_chunk_ids),
      layoutSummaries: objectEntries(layoutTrace?.layout_summaries).map(([chunkId, summary]) => ({
        chunkId,
        summary,
      })),
      raw: layoutTrace,
    },
    context: {
      status: textValue(contextTrace?.status) ?? "unknown",
      reason: textValue(contextTrace?.reason) ?? "not recorded",
      candidateCount: numberValue(contextTrace?.candidate_count),
      relationshipReasons: objectEntries(contextTrace?.relationship_reasons).map(([chunkId, reason]) => ({
        chunkId,
        reason,
      })),
      raw: contextTrace,
    },
    assembly: {
      includedCandidates: numberValue(assemblyTrace?.included_candidates),
      droppedCandidates: numberValue(assemblyTrace?.dropped_candidates),
      evidenceIds: stringArray(assembledContext?.evidence_ids),
      groundingStatus: textValue(assembledContext?.grounding_status) ?? "not recorded",
      breadcrumbsVisible: assembledContext?.breadcrumbs_visible === true,
      layoutSummaryVisible: assembledContext?.layout_summary_visible === true,
      droppedReasons: objectEntries(assemblyTrace?.dropped_reasons).map(([candidateId, reason]) => ({
        candidateId,
        reason,
      })),
      raw: assemblyTrace,
    },
    reranker: {
      status: textValue(rerankerLaneTrace?.status) ?? textValue(firstRerankerTrace?.status) ?? "unknown",
      provider: textValue(firstRerankerTrace?.provider) ?? "not recorded",
      model: textValue(firstRerankerTrace?.model) ?? "not recorded",
      candidateCount: numberValue(rerankerLaneTrace?.candidate_count),
      rankDeltas: recordEntries(rerankerLaneTrace?.rank_deltas)
        .map(([candidateId, value]) => {
          const record = recordValue(value);
          const before = numberValue(record?.before);
          const after = numberValue(record?.after);
          if (before === null || after === null) {
            return null;
          }
          return { candidateId, before, after, delta: before - after };
        })
        .filter((item): item is { candidateId: string; before: number; after: number; delta: number } => item !== null),
      raw: rerankerLaneTrace ?? firstRerankerTrace ?? undefined,
    },
    sources: run.sources.map((source, index) => sourceArchitectureSummary(source, index)),
  };
}

export function traceByStage(traces: Record<string, unknown>[], stage: string) {
  return traces.map(recordValue).find((trace) => trace?.stage === stage);
}

function laneTrace(traces: Record<string, unknown>[], lane: string) {
  return traces
    .map(recordValue)
    .find((trace) => trace?.stage === "retrieval_lane_result" && trace.lane === lane);
}

function sourceArchitectureSummary(
  source: Record<string, unknown>,
  index: number,
): SourceArchitectureSummary {
  const metadata = recordValue(source.metadata) ?? recordValue(source.metadata_json) ?? {};
  const domainMetadata = recordValue(metadata.domain_metadata);
  return {
    sourceId: textValue(source.id) ?? textValue(source.chunk_id) ?? `source-${index + 1}`,
    domain: {
      domain: textValue(domainMetadata?.domain) ?? textValue(metadata.domain) ?? "not recorded",
      materializationHint: textValue(metadata.materialization_hint) ?? "not recorded",
      qualityPolicy:
        textValue(metadata.quality_action_policy) ??
        textValue(source.quality_action_policy) ??
        "not recorded",
    },
    layout: {
      layoutGroupId: textValue(metadata.layout_group_id) ?? "not recorded",
      layoutRole: textValue(metadata.layout_role) ?? "not recorded",
      readingOrder:
        numberValue(metadata.reading_order)?.toString() ??
        textValue(metadata.reading_order) ??
        "not recorded",
    },
    context: {
      parentChunkId: textValue(metadata.parent_chunk_id) ?? "not recorded",
      previousChunkId: textValue(metadata.previous_chunk_id) ?? "not recorded",
      nextChunkId: textValue(metadata.next_chunk_id) ?? "not recorded",
    },
  };
}

function objectEntries(value: unknown): Array<[string, string]> {
  const record = recordValue(value);
  if (!record) {
    return [];
  }
  return Object.entries(record).map(([key, item]) => [key, String(item)]);
}

function recordEntries(value: unknown): Array<[string, unknown]> {
  const record = recordValue(value);
  return record ? Object.entries(record) : [];
}

function stringArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).filter(Boolean);
  }
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  return [];
}

function textValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
