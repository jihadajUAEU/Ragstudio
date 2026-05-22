# Three-Pillar UI Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Ragstudio's domain-aware, layout-aware, and context-aware retrieval architecture fully visible and usable in the application UI, not only present in backend traces and proof artifacts.

**Architecture:** Preserve the backend as the source of truth for retrieval traces, lane results, context windows, reranker rank changes, and assembly decisions. Add a small frontend normalization layer that converts permissive `Record<string, unknown>` trace payloads into stable UI summaries, then reuse those summaries in Query, Evidence, Chunk, and Pipeline surfaces. Backend diagnostics should expose the new three-pillar stages so existing `pathway_diagnostics` consumers remain aligned with the richer `chunk_traces`.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, pytest, TypeScript, React, TanStack Query, Vitest, Testing Library, React Flow, Tailwind CSS v4.

---

## Scope Check

This plan is one coherent UI observability project. It touches one backend diagnostics service and four frontend surfaces:

- Query pathway drawer
- Query result card and evidence drawer
- Chunk inspector evidence drawer
- Pipeline status canvas

It does not change retrieval behavior, ranking, chunk persistence, or proof packet generation. Those are already implemented. This plan makes the implemented architecture inspectable by users.

## File Structure

- Modify `backend/src/ragstudio/services/query_pathway_diagnostics_service.py`
  - Add pathway diagnostic rows for retrieval route plan, lane results, layout neighbor expansion, context window, and reranker.
- Modify `backend/tests/test_query_pathway_diagnostics_service.py`
  - Prove new diagnostics are produced and missing traces stay safe.
- Create `frontend/src/features/query/three-pillar-trace.ts`
  - Normalize raw `RunOut.chunk_traces`, `RunOut.reranker_traces`, source metadata, and timings into UI-safe summaries.
- Create `frontend/tests/three-pillar-trace.test.ts`
  - Prove route, lane, layout, context, assembly, and reranker summaries are derived from realistic traces.
- Modify `frontend/src/features/query/query-pathway-viewer.tsx`
  - Add first-class sections for route plan, lanes, layout neighbors, context window, context assembly, and reranker rank changes.
- Modify `frontend/tests/query-page.test.tsx`
  - Prove the Query pathway drawer renders the new architecture sections.
- Modify `frontend/src/features/query/query-page.tsx`
  - Add a compact architecture summary on each run result and pass normalized architecture summaries into evidence rows.
- Modify `frontend/src/features/evidence/evidence-viewer.tsx`
  - Add domain, layout, context, assembly, and reranker rank sections.
- Modify `frontend/src/features/chunks/chunk-inspector.tsx`
  - Surface layout/context/materialization fields in chunk previews and evidence details.
- Modify `frontend/tests/chunk-inspector.test.tsx` if present; otherwise create `frontend/tests/chunk-inspector-three-pillar.test.tsx`
  - Prove chunk UI exposes layout/context metadata outside raw JSON.
- Modify `frontend/src/features/pipeline/pipeline-builder.tsx`
  - Replace the coarse retrieval node with the actual three-pillar flow.
- Create or modify `frontend/tests/pipeline-builder.test.tsx`
  - Prove pipeline stage labels include the three-pillar architecture.
- Modify `docs/user-guide.md` and `docs/workflows.md`
  - Explain where users inspect route plan, layout neighbors, context window, assembly drops, and rank deltas.

## Target UI Features

- Route Plan panel: domain profile, layout hint, materialization hint, source of truth, direct evidence requirement, graph context requirement.
- Lane Results table: metadata, lexical, vector, runtime, graph, layout, context window, reranker status, reason, candidate count, latency, partial, timeout.
- Layout Neighbor panel: layout group IDs, reading-order neighbor flag, layout summaries, canonical chunk IDs.
- Context Window panel: parent, sibling, previous, next, linked/reading-order relationship reasons.
- Context Assembly panel: included count, dropped count, evidence IDs, grounding status, breadcrumbs/layout visibility, dropped reasons.
- Reranker Rank Delta table: candidate ID, rank before, rank after, delta, provider/model/status when available.
- Evidence Drawer architecture sections: domain/materialization, layout chain, context chain, assembly status, source-specific reranker.
- Chunk Inspector metadata summary: layout group, layout role, reading order, parent/previous/next chunk IDs, materialization policy.
- Pipeline canvas: Domain Resolver, Quality/Materialization Gate, Route Planner, Layout Neighbor Expansion, Context Window, Reranker, Context Assembly.

---

### Task 1: Backend Pathway Diagnostics For Three-Pillar Stages

**Files:**
- Modify: `backend/tests/test_query_pathway_diagnostics_service.py`
- Modify: `backend/src/ragstudio/services/query_pathway_diagnostics_service.py`

- [ ] **Step 1: Write the failing backend diagnostics test**

Add this test to `backend/tests/test_query_pathway_diagnostics_service.py` after `test_builds_complete_fast_mode_pathway_diagnostics`:

```python
def test_builds_three_pillar_architecture_diagnostics():
    rows = QueryPathwayDiagnosticsService().build(
        status="succeeded",
        error=None,
        error_type=None,
        timings={
            "route_plan_ms": 1.2,
            "layout_neighbor_ms": 2.4,
            "context_window_ms": 2.8,
            "context_assembly_ms": 0.8,
            "rerank_ms": 4.0,
        },
        chunk_traces=[
            {
                "stage": "retrieval_route_plan",
                "domain_profile_id": "reference_heavy",
                "layout_hint": "reference",
                "materialization_hint": "graph",
                "source_of_truth": "postgres_canonical_evidence",
                "direct_evidence_required": True,
                "graph_context_required": True,
            },
            {
                "stage": "retrieval_lane_result",
                "lane": "metadata",
                "status": "ran",
                "reason": "metadata_lane_completed",
                "candidate_count": 1,
                "latency_ms": 2.1,
                "timed_out": False,
                "partial": False,
            },
            {
                "stage": "layout_neighbor_expansion",
                "status": "ran",
                "reason": "same_page_reference_layout_group_or_reading_order_neighbors",
                "candidate_count": 1,
                "layout_group_ids": ["table-srg-001"],
                "reading_order_neighbors": True,
            },
            {
                "stage": "retrieval_lane_result",
                "lane": "context_window",
                "status": "ran",
                "reason": "adjacent_parent_sibling_context_window",
                "candidate_count": 4,
                "relationship_reasons": {
                    "chunk-parent": "parent_context",
                    "chunk-prev": "reading_order_adjacent_and_linked_context",
                },
            },
            {
                "stage": "retrieval_lane_result",
                "lane": "reranker",
                "status": "ran",
                "reason": "reranker_completed",
                "candidate_count": 2,
                "rank_deltas": {
                    "chunk-a": {"before": 2, "after": 1},
                    "chunk-b": {"before": 1, "after": 2},
                },
            },
            {
                "stage": "context_assembly",
                "included_candidates": 1,
                "dropped_candidates": 1,
                "assembled_context": {
                    "evidence_ids": ["metadata:chunk-a"],
                    "grounding_status": "grounded",
                    "breadcrumbs_visible": True,
                    "layout_summary_visible": True,
                },
                "dropped_reasons": {
                    "vector:chunk-b": "lower_rank_supporting_context",
                },
            },
        ],
        sources=[],
        token_metadata={},
        query_config={"response_mode": "fast"},
    )

    assert [row["stage"] for row in rows][:5] == [
        "retrieval_route_plan",
        "retrieval_lanes",
        "layout_neighbor_expansion",
        "context_window",
        "reranker",
    ]
    assert row_for(rows, "retrieval_route_plan")["output"] == (
        "domain: reference_heavy; layout: reference; materialization: graph; "
        "source: postgres_canonical_evidence"
    )
    assert row_for(rows, "retrieval_lanes")["output"] == "metadata ran: 1 candidates"
    assert row_for(rows, "layout_neighbor_expansion")["output"] == (
        "1 candidates; layout groups: table-srg-001; reading order neighbors: yes"
    )
    assert row_for(rows, "context_window")["output"] == (
        "4 candidates; parent_context: 1; reading_order_adjacent_and_linked_context: 1"
    )
    assert row_for(rows, "reranker")["output"] == "2 candidates; rank changes: 2"
    assert row_for(rows, "context_assembly")["output"] == (
        "included: 1; dropped: 1; evidence: metadata:chunk-a; grounding: grounded"
    )
```

- [ ] **Step 2: Run the backend test and verify it fails**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run pytest backend/tests/test_query_pathway_diagnostics_service.py::test_builds_three_pillar_architecture_diagnostics -q
```

Expected: FAIL because `retrieval_route_plan`, `retrieval_lanes`, `layout_neighbor_expansion`, `context_window`, and `reranker` rows are not emitted before the older planner row.

- [ ] **Step 3: Implement backend diagnostic rows**

In `backend/src/ragstudio/services/query_pathway_diagnostics_service.py`, change the `return [` block in `QueryPathwayDiagnosticsService.build()` to begin with the new rows:

```python
        return [
            _retrieval_route_plan(context),
            _retrieval_lanes(context),
            _layout_neighbor_expansion(context),
            _context_window(context),
            _reranker(context),
            _planner(context),
            _llm_planning(context),
            _metadata_retrieval(context),
            _native_retrieval(context),
            _seed_fusion(context),
            _graph_expansion(context),
            _graph_hydration(context),
            _final_fusion(context),
            _hypothesis_verification(context),
            _context_assembly(context),
            _answer_generation(context),
            _grounding_validation(context),
        ]
```

Add these helper functions above `_planner()`:

```python
def _retrieval_route_plan(context: _DiagnosticContext) -> dict[str, Any]:
    trace = context.trace("retrieval_route_plan")
    output = _join_parts(
        [
            _field("domain", _text(trace, "domain_profile_id") or _text(trace, "domain_id")),
            _field("layout", _text(trace, "layout_hint")),
            _field("materialization", _text(trace, "materialization_hint")),
            _field("source", _text(trace, "source_of_truth")),
        ]
    )
    return _row(
        "retrieval_route_plan",
        "Retrieval route plan",
        "query + domain metadata + runtime profile",
        "Resolve the retrieval route across domain, layout, and context lanes",
        output or "not recorded",
        _status_from_text(_text(trace, "status") or ("success" if trace else None)),
        _number(context.timings, "route_plan_ms"),
        None,
        trace_present=trace is not None,
    )


def _retrieval_lanes(context: _DiagnosticContext) -> dict[str, Any]:
    lane_traces = _lane_traces(context)
    output = "; ".join(
        f"{_text(trace, 'lane') or 'lane'} {_text(trace, 'status') or 'unknown'}: "
        f"{int(_number(trace, 'candidate_count') or 0)} candidates"
        for trace in lane_traces
        if _text(trace, "lane") not in {"context_window", "reranker"}
    )
    visible_lane_count = sum(
        1 for trace in lane_traces if _text(trace, "lane") not in {"context_window", "reranker"}
    )
    return _row(
        "retrieval_lanes",
        "Retrieval lanes",
        "route plan + selected documents",
        "Run planned canonical, metadata, vector, runtime, and graph lanes",
        output or "no retrieval lanes recorded",
        "success" if visible_lane_count else "unknown",
        _number(context.timings, "retrieval_ms"),
        None,
        trace_present=visible_lane_count > 0,
    )


def _layout_neighbor_expansion(context: _DiagnosticContext) -> dict[str, Any]:
    trace = context.trace("layout_neighbor_expansion")
    layout_groups = _string_list(trace.get("layout_group_ids") if trace else None)
    reading_order = "yes" if trace and trace.get("reading_order_neighbors") is True else "no"
    output = _join_parts(
        [
            _field("candidates", int(_number(trace, "candidate_count") or 0) if trace else None),
            _field("layout groups", ", ".join(layout_groups) if layout_groups else None),
            _field("reading order neighbors", reading_order if trace else None),
        ]
    )
    return _row(
        "layout_neighbor_expansion",
        "Layout neighbor expansion",
        "seed evidence + source layout metadata",
        "Add same-page, same-layout-group, and reading-order neighbors",
        output or "not recorded",
        _status_from_text(_text(trace, "status") or ("success" if trace else None)),
        _number(context.timings, "layout_neighbor_ms"),
        None,
        trace_present=trace is not None,
    )


def _context_window(context: _DiagnosticContext) -> dict[str, Any]:
    trace = _lane_trace(context, "context_window")
    reasons = _reason_counts(_record(trace.get("relationship_reasons") if trace else None))
    reason_text = "; ".join(f"{key}: {value}" for key, value in reasons.items())
    output = _join_parts(
        [
            _field("candidates", int(_number(trace, "candidate_count") or 0) if trace else None),
            reason_text,
        ]
    )
    return _row(
        "context_window",
        "Context window",
        "direct evidence + chunk relationships",
        "Hydrate parent, sibling, previous, next, and linked context",
        output or "not recorded",
        _status_from_text(_text(trace, "status") or ("success" if trace else None)),
        _number(context.timings, "context_window_ms"),
        None,
        trace_present=trace is not None,
    )


def _reranker(context: _DiagnosticContext) -> dict[str, Any]:
    trace = _lane_trace(context, "reranker")
    rank_deltas = _record(trace.get("rank_deltas") if trace else None) or {}
    output = _join_parts(
        [
            _field("candidates", int(_number(trace, "candidate_count") or 0) if trace else None),
            _field("rank changes", len(rank_deltas) if trace else None),
        ]
    )
    return _row(
        "reranker",
        "Reranker",
        "fused evidence candidates",
        "Reorder evidence candidates and record rank deltas",
        output or "not recorded",
        _status_from_text(_text(trace, "status") or ("success" if trace else None)),
        _number(trace, "latency_ms") or _number(context.timings, "rerank_ms"),
        None,
        trace_present=trace is not None,
    )
```

Add these helper functions near the existing `_record`, `_text`, and `_number` helpers:

```python
def _lane_traces(context: _DiagnosticContext) -> list[dict[str, Any]]:
    return [
        trace
        for trace in context.traces
        if isinstance(trace, dict) and trace.get("stage") == "retrieval_lane_result"
    ]


def _lane_trace(context: _DiagnosticContext, lane: str) -> dict[str, Any] | None:
    return next((trace for trace in _lane_traces(context) if trace.get("lane") == lane), None)


def _reason_counts(reasons: dict[str, Any] | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not reasons:
        return counts
    for reason in reasons.values():
        key = str(reason).strip()
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts
```

- [ ] **Step 4: Run backend diagnostics tests**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run pytest backend/tests/test_query_pathway_diagnostics_service.py -q
```

Expected: PASS. Update the existing `assert len(rows) == 12` in `test_build_handles_missing_traces_without_failing` to `assert len(rows) == 17` because five new diagnostic rows are always returned with `unknown` status when traces are missing.

- [ ] **Step 5: Commit backend diagnostics**

```powershell
git add backend/src/ragstudio/services/query_pathway_diagnostics_service.py backend/tests/test_query_pathway_diagnostics_service.py
git commit -m "feat: expose three-pillar pathway diagnostics"
```

---

### Task 2: Shared Frontend Trace Normalizer

**Files:**
- Create: `frontend/src/features/query/three-pillar-trace.ts`
- Create: `frontend/tests/three-pillar-trace.test.ts`

- [ ] **Step 1: Write the failing frontend normalizer test**

Create `frontend/tests/three-pillar-trace.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import type { RunOut } from "../src/api/generated";
import { buildThreePillarTrace } from "../src/features/query/three-pillar-trace";

const run: RunOut = {
  id: "run-1",
  variant_id: "variant-1",
  experiment_id: null,
  query: "Which reference was blocked?",
  status: "succeeded",
  answer: "answer",
  sources: [
    {
      id: "source-1",
      chunk_id: "chunk-a",
      metadata: {
        domain_metadata: { domain: "hadith" },
        layout_group_id: "table-srg-001",
        layout_role: "table_cell",
        reading_order: 12,
        parent_chunk_id: "chunk-parent",
        previous_chunk_id: "chunk-prev",
        next_chunk_id: "chunk-next",
        quality_action_policy: "materialize",
        materialization_hint: "graph",
      },
    },
  ],
  chunk_traces: [
    {
      stage: "retrieval_route_plan",
      domain_profile_id: "reference_heavy",
      layout_hint: "reference",
      materialization_hint: "graph",
      source_of_truth: "postgres_canonical_evidence",
      direct_evidence_required: true,
      graph_context_required: true,
    },
    {
      stage: "retrieval_lane_result",
      lane: "metadata",
      status: "ran",
      reason: "metadata_lane_completed",
      candidate_count: 1,
      latency_ms: 2.1,
      timed_out: false,
      partial: false,
      canonical_chunk_ids: ["chunk-a"],
    },
    {
      stage: "layout_neighbor_expansion",
      status: "ran",
      reason: "same_page_reference_layout_group_or_reading_order_neighbors",
      candidate_count: 1,
      layout_group_ids: ["table-srg-001"],
      reading_order_neighbors: true,
      canonical_chunk_ids: ["chunk-b"],
    },
    {
      stage: "retrieval_lane_result",
      lane: "context_window",
      status: "ran",
      reason: "adjacent_parent_sibling_context_window",
      candidate_count: 4,
      relationship_reasons: {
        "chunk-parent": "parent_context",
        "chunk-prev": "reading_order_adjacent_and_linked_context",
      },
    },
    {
      stage: "retrieval_lane_result",
      lane: "reranker",
      status: "ran",
      reason: "reranker_completed",
      candidate_count: 2,
      rank_deltas: {
        "chunk-a": { before: 2, after: 1 },
        "chunk-b": { before: 1, after: 2 },
      },
    },
    {
      stage: "context_assembly",
      included_candidates: 1,
      dropped_candidates: 1,
      assembled_context: {
        evidence_ids: ["metadata:chunk-a"],
        grounding_status: "grounded",
        breadcrumbs_visible: true,
        layout_summary_visible: true,
      },
      dropped_reasons: { "vector:chunk-b": "lower_rank_supporting_context" },
    },
  ],
  timings: { total_ms: 21, rerank_ms: 4 },
  error: null,
  runtime_profile_id: "default",
  document_ids: ["doc-1"],
  query_config: {},
  reranker_traces: [{ status: "succeeded", provider: "generic_http", model: "rerank-model" }],
  token_metadata: {},
  error_type: null,
};

describe("buildThreePillarTrace", () => {
  it("summarizes route, lanes, layout, context, assembly, and reranker rank deltas", () => {
    const summary = buildThreePillarTrace(run);

    expect(summary.route.domainProfileId).toBe("reference_heavy");
    expect(summary.route.materializationHint).toBe("graph");
    expect(summary.lanes.map((lane) => lane.lane)).toEqual(["metadata", "context_window", "reranker"]);
    expect(summary.layout.layoutGroupIds).toEqual(["table-srg-001"]);
    expect(summary.layout.readingOrderNeighbors).toBe(true);
    expect(summary.context.relationshipReasons).toEqual([
      { chunkId: "chunk-parent", reason: "parent_context" },
      { chunkId: "chunk-prev", reason: "reading_order_adjacent_and_linked_context" },
    ]);
    expect(summary.assembly.evidenceIds).toEqual(["metadata:chunk-a"]);
    expect(summary.assembly.droppedReasons).toEqual([
      { candidateId: "vector:chunk-b", reason: "lower_rank_supporting_context" },
    ]);
    expect(summary.reranker.rankDeltas).toEqual([
      { candidateId: "chunk-a", before: 2, after: 1, delta: 1 },
      { candidateId: "chunk-b", before: 1, after: 2, delta: -1 },
    ]);
    expect(summary.sources[0].layout.readingOrder).toBe("12");
    expect(summary.sources[0].context.parentChunkId).toBe("chunk-parent");
  });
});
```

- [ ] **Step 2: Run the failing frontend normalizer test**

Run:

```powershell
Set-Location frontend
npm test -- three-pillar-trace.test.ts --run
```

Expected: FAIL because `three-pillar-trace.ts` does not exist.

- [ ] **Step 3: Implement the normalizer**

Create `frontend/src/features/query/three-pillar-trace.ts`:

```typescript
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

  return {
    route: {
      domainProfileId: textValue(routeTrace?.domain_profile_id) ?? textValue(routeTrace?.domain_id) ?? "not recorded",
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
      evidenceIds: stringArray(recordValue(assemblyTrace?.assembled_context)?.evidence_ids),
      groundingStatus: textValue(recordValue(assemblyTrace?.assembled_context)?.grounding_status) ?? "not recorded",
      breadcrumbsVisible: recordValue(assemblyTrace?.assembled_context)?.breadcrumbs_visible === true,
      layoutSummaryVisible: recordValue(assemblyTrace?.assembled_context)?.layout_summary_visible === true,
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
      rankDeltas: objectEntries(rerankerLaneTrace?.rank_deltas)
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

function sourceArchitectureSummary(source: Record<string, unknown>, index: number): SourceArchitectureSummary {
  const metadata = recordValue(source.metadata) ?? recordValue(source.metadata_json) ?? {};
  const domainMetadata = recordValue(metadata.domain_metadata);
  return {
    sourceId: textValue(source.id) ?? textValue(source.chunk_id) ?? `source-${index + 1}`,
    domain: {
      domain: textValue(domainMetadata?.domain) ?? textValue(metadata.domain) ?? "not recorded",
      materializationHint: textValue(metadata.materialization_hint) ?? "not recorded",
      qualityPolicy: textValue(metadata.quality_action_policy) ?? textValue(source.quality_action_policy) ?? "not recorded",
    },
    layout: {
      layoutGroupId: textValue(metadata.layout_group_id) ?? "not recorded",
      layoutRole: textValue(metadata.layout_role) ?? "not recorded",
      readingOrder: numberValue(metadata.reading_order)?.toString() ?? textValue(metadata.reading_order) ?? "not recorded",
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
```

- [ ] **Step 4: Run the normalizer test**

Run:

```powershell
Set-Location frontend
npm test -- three-pillar-trace.test.ts --run
```

Expected: PASS.

- [ ] **Step 5: Commit the normalizer**

```powershell
git add frontend/src/features/query/three-pillar-trace.ts frontend/tests/three-pillar-trace.test.ts
git commit -m "feat: normalize three-pillar retrieval traces"
```

---

### Task 3: Query Pathway Drawer Architecture Sections

**Files:**
- Modify: `frontend/src/features/query/query-pathway-viewer.tsx`
- Modify: `frontend/tests/query-page.test.tsx`

- [ ] **Step 1: Write the failing Query pathway UI test**

In `frontend/tests/query-page.test.tsx`, extend the mocked run in `it("opens query pathway details with stage status, results, and timings", ...)` by adding these traces before the existing `planner` trace:

```typescript
{
  stage: "retrieval_route_plan",
  domain_profile_id: "reference_heavy",
  layout_hint: "reference",
  materialization_hint: "graph",
  source_of_truth: "postgres_canonical_evidence",
  direct_evidence_required: true,
  graph_context_required: true,
},
{
  stage: "retrieval_lane_result",
  lane: "metadata",
  status: "ran",
  reason: "metadata_lane_completed",
  candidate_count: 1,
  latency_ms: 2.1,
},
{
  stage: "layout_neighbor_expansion",
  status: "ran",
  reason: "same_page_reference_layout_group_or_reading_order_neighbors",
  candidate_count: 1,
  layout_group_ids: ["table-srg-001"],
  reading_order_neighbors: true,
},
{
  stage: "retrieval_lane_result",
  lane: "context_window",
  status: "ran",
  reason: "adjacent_parent_sibling_context_window",
  candidate_count: 4,
  relationship_reasons: { "chunk-parent": "parent_context" },
},
{
  stage: "retrieval_lane_result",
  lane: "reranker",
  status: "ran",
  reason: "reranker_completed",
  candidate_count: 2,
  rank_deltas: { "chunk-25": { before: 2, after: 1 } },
},
```

Then add these assertions after the drawer opens:

```typescript
expect(screen.getByText("Route plan", { selector: "summary" })).toBeVisible();
expect(screen.getByText("Lane results", { selector: "summary" })).toBeVisible();
expect(screen.getByText("Layout neighbors", { selector: "summary" })).toBeVisible();
expect(screen.getByText("Context window", { selector: "summary" })).toBeVisible();
expect(screen.getByText("Reranker rank changes", { selector: "summary" })).toBeVisible();
fireEvent.click(screen.getByText("Route plan", { selector: "summary" }));
expect(screen.getByText("reference_heavy")).toBeVisible();
expect(screen.getByText("postgres_canonical_evidence")).toBeVisible();
fireEvent.click(screen.getByText("Lane results", { selector: "summary" }));
expect(screen.getByText("metadata")).toBeVisible();
expect(screen.getByText("metadata_lane_completed")).toBeVisible();
fireEvent.click(screen.getByText("Layout neighbors", { selector: "summary" }));
expect(screen.getByText("table-srg-001")).toBeVisible();
fireEvent.click(screen.getByText("Context window", { selector: "summary" }));
expect(screen.getByText("parent_context")).toBeVisible();
fireEvent.click(screen.getByText("Reranker rank changes", { selector: "summary" }));
expect(screen.getByText("chunk-25")).toBeVisible();
expect(screen.getByText("2 -> 1")).toBeVisible();
```

- [ ] **Step 2: Run the failing Query pathway UI test**

Run:

```powershell
Set-Location frontend
npm test -- query-page.test.ts --run
```

Expected: FAIL because the new sections are not rendered.

- [ ] **Step 3: Render architecture sections in the drawer**

Modify `frontend/src/features/query/query-pathway-viewer.tsx`:

```typescript
import { buildThreePillarTrace, type ThreePillarTraceSummary } from "./three-pillar-trace";
```

Inside `buildPathway(run)`, create the architecture summary:

```typescript
  const architecture = buildThreePillarTrace(run);
```

Return it:

```typescript
  return {
    steps,
    topReference,
    topSource: textValue(topSource?.chunk_id) ?? textValue(topSource?.id) ?? "not recorded",
    architecture,
  };
```

In the drawer body, insert these sections between `Summary` and `Timeline`:

```tsx
<PathwaySection title="Route plan">
  <ArchitectureRoute route={pathway.architecture.route} />
</PathwaySection>
<PathwaySection title="Lane results">
  <LaneResults lanes={pathway.architecture.lanes} />
</PathwaySection>
<PathwaySection title="Layout neighbors">
  <LayoutNeighbors layout={pathway.architecture.layout} />
</PathwaySection>
<PathwaySection title="Context window">
  <ContextWindowDetails context={pathway.architecture.context} />
</PathwaySection>
<PathwaySection title="Context assembly">
  <ContextAssemblyDetails assembly={pathway.architecture.assembly} />
</PathwaySection>
<PathwaySection title="Reranker rank changes">
  <RerankerRankChanges reranker={pathway.architecture.reranker} />
</PathwaySection>
```

Add these components below `Timeline`:

```tsx
function ArchitectureRoute({ route }: { route: ThreePillarTraceSummary["route"] }) {
  return (
    <>
      <KeyValue label="Domain profile" value={route.domainProfileId} />
      <KeyValue label="Layout hint" value={route.layoutHint} />
      <KeyValue label="Materialization" value={route.materializationHint} />
      <KeyValue label="Source of truth" value={route.sourceOfTruth} />
      <KeyValue label="Direct evidence" value={route.directEvidenceRequired ? "required" : "not required"} />
      <KeyValue label="Graph context" value={route.graphContextRequired ? "required" : "not required"} />
    </>
  );
}

function LaneResults({ lanes }: { lanes: ThreePillarTraceSummary["lanes"] }) {
  if (!lanes.length) {
    return <MissingValue>No lane traces recorded</MissingValue>;
  }
  return (
    <div className="grid gap-2 sm:col-span-2">
      {lanes.map((lane) => (
        <div key={`${lane.lane}-${lane.reason}`} className="rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3">
          <div className="grid gap-2 sm:grid-cols-4">
            <KeyValue label="Lane" value={lane.lane} />
            <KeyValue label="Status" value={lane.status} />
            <KeyValue label="Candidates" value={lane.candidateCount === null ? "not recorded" : String(lane.candidateCount)} />
            <KeyValue label="Latency" value={formatMs(lane.latencyMs ?? undefined)} />
          </div>
          <p className="mt-2 break-words text-xs text-[#62717a]">{lane.reason}</p>
        </div>
      ))}
    </div>
  );
}

function LayoutNeighbors({ layout }: { layout: ThreePillarTraceSummary["layout"] }) {
  return (
    <>
      <KeyValue label="Status" value={layout.status} />
      <KeyValue label="Reason" value={layout.reason} />
      <KeyValue label="Candidates" value={layout.candidateCount === null ? "not recorded" : String(layout.candidateCount)} />
      <KeyValue label="Reading order" value={layout.readingOrderNeighbors ? "yes" : "no"} />
      <ListValue label="Layout groups" values={layout.layoutGroupIds} />
      <ListValue label="Canonical chunks" values={layout.canonicalChunkIds} />
    </>
  );
}

function ContextWindowDetails({ context }: { context: ThreePillarTraceSummary["context"] }) {
  return (
    <>
      <KeyValue label="Status" value={context.status} />
      <KeyValue label="Reason" value={context.reason} />
      <KeyValue label="Candidates" value={context.candidateCount === null ? "not recorded" : String(context.candidateCount)} />
      <ListValue
        label="Relationship reasons"
        values={context.relationshipReasons.map((item) => `${item.chunkId}: ${item.reason}`)}
      />
    </>
  );
}

function ContextAssemblyDetails({ assembly }: { assembly: ThreePillarTraceSummary["assembly"] }) {
  return (
    <>
      <KeyValue label="Included" value={assembly.includedCandidates === null ? "not recorded" : String(assembly.includedCandidates)} />
      <KeyValue label="Dropped" value={assembly.droppedCandidates === null ? "not recorded" : String(assembly.droppedCandidates)} />
      <KeyValue label="Grounding" value={assembly.groundingStatus} />
      <KeyValue label="Breadcrumbs" value={assembly.breadcrumbsVisible ? "visible" : "not recorded"} />
      <ListValue label="Evidence ids" values={assembly.evidenceIds} />
      <ListValue
        label="Dropped reasons"
        values={assembly.droppedReasons.map((item) => `${item.candidateId}: ${item.reason}`)}
      />
    </>
  );
}

function RerankerRankChanges({ reranker }: { reranker: ThreePillarTraceSummary["reranker"] }) {
  if (!reranker.rankDeltas.length) {
    return <MissingValue>No rank deltas recorded</MissingValue>;
  }
  return (
    <div className="grid gap-2 sm:col-span-2">
      {reranker.rankDeltas.map((delta) => (
        <div key={delta.candidateId} className="grid gap-2 rounded-md bg-[#f8fafb] px-3 py-2 sm:grid-cols-3">
          <KeyValue label="Candidate" value={delta.candidateId} />
          <KeyValue label="Rank" value={`${delta.before} -> ${delta.after}`} />
          <KeyValue label="Delta" value={String(delta.delta)} />
        </div>
      ))}
    </div>
  );
}

function ListValue({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="min-w-0 rounded-md bg-[#f8fafb] px-3 py-2 sm:col-span-2">
      <p className="text-xs font-semibold text-[#62717a]">{label}</p>
      <p className="mt-1 break-words text-sm text-[#24313a]">{values.length ? values.join(", ") : "not recorded"}</p>
    </div>
  );
}

function MissingValue({ children }: { children: ReactNode }) {
  return <p className="text-sm text-[#62717a] sm:col-span-2">{children}</p>;
}
```

- [ ] **Step 4: Run Query pathway UI tests**

Run:

```powershell
Set-Location frontend
npm test -- query-page.test.ts three-pillar-trace.test.ts --run
```

Expected: PASS.

- [ ] **Step 5: Commit Query pathway UI**

```powershell
git add frontend/src/features/query/query-pathway-viewer.tsx frontend/tests/query-page.test.tsx
git commit -m "feat: show three-pillar query pathway details"
```

---

### Task 4: Query Result Architecture Summary

**Files:**
- Modify: `frontend/src/features/query/query-page.tsx`
- Modify: `frontend/tests/query-page.test.tsx`

- [ ] **Step 1: Write the failing Query result summary test**

Add this test to `frontend/tests/query-page.test.tsx`:

```typescript
it("summarizes the three-pillar route on the query result card", async () => {
  vi.mocked(apiClient.query).mockResolvedValue({
    runs: [
      {
        id: "run-1",
        variant_id: "variant-1",
        experiment_id: null,
        query: "alpha",
        status: "succeeded",
        answer: "answer",
        sources: [],
        chunk_traces: [
          {
            stage: "retrieval_route_plan",
            domain_profile_id: "reference_heavy",
            layout_hint: "reference",
            materialization_hint: "graph",
            source_of_truth: "postgres_canonical_evidence",
          },
          {
            stage: "layout_neighbor_expansion",
            status: "ran",
            candidate_count: 2,
            reading_order_neighbors: true,
          },
          {
            stage: "retrieval_lane_result",
            lane: "context_window",
            status: "ran",
            candidate_count: 4,
          },
          {
            stage: "context_assembly",
            included_candidates: 2,
            dropped_candidates: 1,
            assembled_context: { grounding_status: "grounded" },
          },
        ],
        timings: {},
        error: null,
        runtime_profile_id: "profile-1",
        document_ids: ["doc-1"],
        query_config: {},
        reranker_traces: [],
        token_metadata: {},
        error_type: null,
      },
    ],
  });
  renderQueryPage();

  fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
    target: { value: "alpha" },
  });
  fireEvent.click(await screen.findByText("source.txt"));
  fireEvent.click((await screen.findAllByText("Balanced"))[0]);
  fireEvent.click(screen.getByRole("button", { name: "Run" }));

  expect(await screen.findByText("Architecture trace")).toBeVisible();
  expect(screen.getByText("reference_heavy")).toBeVisible();
  expect(screen.getByText("layout 2")).toBeVisible();
  expect(screen.getByText("context 4")).toBeVisible();
  expect(screen.getByText("grounded")).toBeVisible();
});
```

- [ ] **Step 2: Run the failing Query result summary test**

Run:

```powershell
Set-Location frontend
npm test -- query-page.test.ts --run
```

Expected: FAIL because the card does not show `Architecture trace`.

- [ ] **Step 3: Render the compact architecture card**

In `frontend/src/features/query/query-page.tsx`, import the normalizer:

```typescript
import { buildThreePillarTrace, type ThreePillarTraceSummary } from "./three-pillar-trace";
```

Inside `RunResult`, compute the summary:

```typescript
  const architecture = useMemo(() => buildThreePillarTrace(run), [run]);
```

Render this immediately after `<RerankerSummary traces={run.reranker_traces} />`:

```tsx
<ArchitectureTraceSummary architecture={architecture} />
```

Add this component near `RerankerSummary`:

```tsx
function ArchitectureTraceSummary({ architecture }: { architecture: ThreePillarTraceSummary }) {
  const layoutCount = architecture.layout.candidateCount ?? 0;
  const contextCount = architecture.context.candidateCount ?? 0;
  return (
    <div className="mt-3 rounded-md border border-[#dce5e8] bg-[#f8fafb] p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-semibold text-[#1f2933]">Architecture trace</h4>
        <Badge>{architecture.route.domainProfileId}</Badge>
        <Badge>{architecture.route.materializationHint}</Badge>
        <Badge>layout {layoutCount}</Badge>
        <Badge>context {contextCount}</Badge>
        <Badge>{architecture.assembly.groundingStatus}</Badge>
      </div>
      <p className="text-xs leading-5 text-[#62717a]">
        {architecture.route.sourceOfTruth} / {architecture.layout.reason} / {architecture.context.reason}
      </p>
    </div>
  );
}
```

- [ ] **Step 4: Run Query result tests**

Run:

```powershell
Set-Location frontend
npm test -- query-page.test.ts --run
```

Expected: PASS.

- [ ] **Step 5: Commit Query result summary**

```powershell
git add frontend/src/features/query/query-page.tsx frontend/tests/query-page.test.tsx
git commit -m "feat: summarize retrieval architecture on query results"
```

---

### Task 5: Evidence Drawer Domain, Layout, Context, And Assembly Sections

**Files:**
- Modify: `frontend/src/features/evidence/evidence-viewer.tsx`
- Modify: `frontend/src/features/query/query-page.tsx`
- Modify: `frontend/tests/query-page.test.tsx`

- [ ] **Step 1: Write the failing evidence drawer test**

Add this assertion block to `it("renders readable source rows and opens the evidence viewer", ...)` after opening `Evidence details`. Update the mocked source metadata in that test to include the fields shown below:

```typescript
metadata: {
  domain_metadata: { domain: "hadith" },
  materialization_hint: "graph",
  layout_group_id: "table-srg-001",
  layout_role: "table_cell",
  reading_order: 12,
  parent_chunk_id: "chunk-parent",
  previous_chunk_id: "chunk-prev",
  next_chunk_id: "chunk-next",
},
```

Add these assertions:

```typescript
fireEvent.click(screen.getByText("Domain and materialization", { selector: "summary" }));
expect(screen.getByText("hadith")).toBeVisible();
expect(screen.getByText("graph")).toBeVisible();
fireEvent.click(screen.getByText("Layout chain", { selector: "summary" }));
expect(screen.getByText("table-srg-001")).toBeVisible();
expect(screen.getByText("table_cell")).toBeVisible();
expect(screen.getByText("12")).toBeVisible();
fireEvent.click(screen.getByText("Context chain", { selector: "summary" }));
expect(screen.getByText("chunk-parent")).toBeVisible();
expect(screen.getByText("chunk-prev")).toBeVisible();
expect(screen.getByText("chunk-next")).toBeVisible();
```

- [ ] **Step 2: Run the failing evidence drawer test**

Run:

```powershell
Set-Location frontend
npm test -- query-page.test.ts --run
```

Expected: FAIL because the evidence drawer has no `Domain and materialization`, `Layout chain`, or `Context chain` sections.

- [ ] **Step 3: Extend evidence types and rendering**

In `frontend/src/features/evidence/evidence-viewer.tsx`, extend `NormalizedEvidence`:

```typescript
  architecture?: {
    domain?: {
      domain: string;
      materializationHint: string;
      qualityPolicy: string;
    };
    layout?: {
      layoutGroupId: string;
      layoutRole: string;
      readingOrder: string;
    };
    context?: {
      parentChunkId: string;
      previousChunkId: string;
      nextChunkId: string;
    };
    assembly?: {
      groundingStatus: string;
      evidenceIds: string[];
      droppedReasons: string[];
    };
  };
```

Insert these sections after `Parser quality`:

```tsx
<EvidenceSection title="Domain and materialization">
  <ArchitectureKeyValues
    values={[
      ["Domain", evidence.architecture?.domain?.domain],
      ["Materialization", evidence.architecture?.domain?.materializationHint],
      ["Quality policy", evidence.architecture?.domain?.qualityPolicy],
    ]}
  />
</EvidenceSection>
<EvidenceSection title="Layout chain">
  <ArchitectureKeyValues
    values={[
      ["Layout group", evidence.architecture?.layout?.layoutGroupId],
      ["Layout role", evidence.architecture?.layout?.layoutRole],
      ["Reading order", evidence.architecture?.layout?.readingOrder],
    ]}
  />
</EvidenceSection>
<EvidenceSection title="Context chain">
  <ArchitectureKeyValues
    values={[
      ["Parent", evidence.architecture?.context?.parentChunkId],
      ["Previous", evidence.architecture?.context?.previousChunkId],
      ["Next", evidence.architecture?.context?.nextChunkId],
    ]}
  />
</EvidenceSection>
{evidence.architecture?.assembly ? (
  <EvidenceSection title="Context assembly">
    <ArchitectureKeyValues
      values={[
        ["Grounding", evidence.architecture.assembly.groundingStatus],
        ["Evidence ids", evidence.architecture.assembly.evidenceIds.join(", ")],
        ["Dropped", evidence.architecture.assembly.droppedReasons.join(", ")],
      ]}
    />
  </EvidenceSection>
) : null}
```

Add this helper below `SummaryGrid`:

```tsx
function ArchitectureKeyValues({ values }: { values: Array<[string, string | undefined]> }) {
  const visibleValues = values.map(([label, value]) => [label, value || "not recorded"] as const);
  return (
    <div className="grid gap-2 text-sm sm:grid-cols-2">
      {visibleValues.map(([label, value]) => (
        <KeyValue key={label} label={label} value={value} />
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Populate architecture summaries from Query sources**

In `frontend/src/features/query/query-page.tsx`, inside `RunResult`, pass architecture into normalization:

```typescript
  const readableSources = useMemo(
    () => run.sources.map((source, index) => normalizeQuerySource(source, index, run, architecture)),
    [architecture, run],
  );
```

Change the `normalizeQuerySource` signature:

```typescript
function normalizeQuerySource(
  source: Record<string, unknown>,
  index: number,
  run: RunOut,
  architecture: ThreePillarTraceSummary,
): NormalizedEvidence {
```

Before the return, add:

```typescript
  const sourceArchitecture = architecture.sources.find((item) => item.sourceId === sourceId);
```

Inside the returned object, add:

```typescript
    architecture: sourceArchitecture
      ? {
          domain: sourceArchitecture.domain,
          layout: sourceArchitecture.layout,
          context: sourceArchitecture.context,
          assembly: {
            groundingStatus: architecture.assembly.groundingStatus,
            evidenceIds: architecture.assembly.evidenceIds,
            droppedReasons: architecture.assembly.droppedReasons.map(
              (item) => `${item.candidateId}: ${item.reason}`,
            ),
          },
        }
      : undefined,
```

- [ ] **Step 5: Run evidence drawer tests**

Run:

```powershell
Set-Location frontend
npm test -- query-page.test.ts --run
```

Expected: PASS.

- [ ] **Step 6: Commit evidence drawer architecture sections**

```powershell
git add frontend/src/features/evidence/evidence-viewer.tsx frontend/src/features/query/query-page.tsx frontend/tests/query-page.test.tsx
git commit -m "feat: show architecture metadata in evidence details"
```

---

### Task 6: Chunk Inspector Layout And Context Metadata

**Files:**
- Modify: `frontend/src/features/chunks/chunk-inspector.tsx`
- Create: `frontend/tests/chunk-inspector-three-pillar.test.tsx` if no focused chunk inspector test exists

- [ ] **Step 1: Write the failing chunk inspector test**

Create `frontend/tests/chunk-inspector-three-pillar.test.tsx`:

```typescript
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../src/api/client";
import { ChunkInspector } from "../src/features/chunks/chunk-inspector";

vi.mock("../src/api/client", () => ({
  DEFAULT_PARSER_MODE: "mineru_strict",
  apiClient: {
    documents: vi.fn(),
    domainProfiles: vi.fn(),
    searchChunks: vi.fn(),
    createDocumentReindexJob: vi.fn(),
  },
}));

function renderChunkInspector() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ChunkInspector />
    </QueryClientProvider>,
  );
}

describe("ChunkInspector three-pillar metadata", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-1",
          filename: "source.txt",
          content_type: "text/plain",
          status: "succeeded",
          sha256: "sha",
        },
      ],
      total: 1,
    });
    vi.mocked(apiClient.domainProfiles).mockResolvedValue({ items: [] });
    vi.mocked(apiClient.searchChunks).mockResolvedValue({
      items: [
        {
          id: "chunk-1",
          document_id: "doc-1",
          runtime_profile_id: "default",
          text: "Evidence text",
          source_location: { page_start: 1, page_end: 1 },
          metadata: {
            score: 0.91,
            domain_metadata: { domain: "hadith" },
            quality_action_policy: "materialize",
            materialization_hint: "graph",
            layout_group_id: "table-srg-001",
            layout_role: "table_cell",
            reading_order: 12,
            parent_chunk_id: "chunk-parent",
            previous_chunk_id: "chunk-prev",
            next_chunk_id: "chunk-next",
          },
          content_type: "text",
          relationship_refs: {},
        },
      ],
      total: 1,
    });
  });

  it("shows layout and context metadata outside raw JSON", async () => {
    renderChunkInspector();

    fireEvent.change(await screen.findByPlaceholderText("12:13"), { target: { value: "alpha" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(apiClient.searchChunks).toHaveBeenCalled());
    fireEvent.click(await screen.findByRole("button", { name: "Preview" }));

    expect(screen.getByText("Layout group")).toBeVisible();
    expect(screen.getByText("table-srg-001")).toBeVisible();
    expect(screen.getByText("Reading order")).toBeVisible();
    expect(screen.getByText("12")).toBeVisible();
    expect(screen.getByText("Parent")).toBeVisible();
    expect(screen.getByText("chunk-parent")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Inspect" }));
    fireEvent.click(await screen.findByText("Context chain", { selector: "summary" }));
    expect(screen.getAllByText("chunk-next").length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run the failing chunk inspector test**

Run:

```powershell
Set-Location frontend
npm test -- chunk-inspector-three-pillar.test.tsx --run
```

Expected: FAIL until chunk metadata summary and evidence architecture fields are rendered.

- [ ] **Step 3: Add layout/context fields to `MetadataSummary`**

In `frontend/src/features/chunks/chunk-inspector.tsx`, modify `MetadataSummary`:

```tsx
function MetadataSummary({ chunk }: { chunk: ChunkOut }) {
  return (
    <div className="rounded-md border border-[#dce5e8] bg-white p-3 text-xs text-[#3a4a53]">
      <div className="grid gap-2 sm:grid-cols-2">
        <SummaryLine label="Profile" value={chunk.runtime_profile_id ?? "n/a"} />
        <SummaryLine label="Content" value={chunk.content_type} />
        <SummaryLine label="Snapshot" value={metadataValue(chunk.metadata, ["mirrored_snapshot"], "false")} />
        <SummaryLine label="Domain" value={metadataValue(chunk.metadata, ["domain_metadata", "domain"], "generic")} />
        <SummaryLine label="Materialization" value={metadataValue(chunk.metadata, ["materialization_hint"], "not recorded")} />
        <SummaryLine label="Layout group" value={metadataValue(chunk.metadata, ["layout_group_id"], "not recorded")} />
        <SummaryLine label="Layout role" value={metadataValue(chunk.metadata, ["layout_role"], "not recorded")} />
        <SummaryLine label="Reading order" value={metadataValue(chunk.metadata, ["reading_order"], "not recorded")} />
        <SummaryLine label="Parent" value={metadataValue(chunk.metadata, ["parent_chunk_id"], "not recorded")} />
        <SummaryLine label="Previous" value={metadataValue(chunk.metadata, ["previous_chunk_id"], "not recorded")} />
        <SummaryLine label="Next" value={metadataValue(chunk.metadata, ["next_chunk_id"], "not recorded")} />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Populate evidence architecture from chunks**

In `normalizeChunkEvidence`, add this object to the returned `NormalizedEvidence`:

```typescript
    architecture: {
      domain: {
        domain: metadataValue(chunk.metadata, ["domain_metadata", "domain"], "not recorded"),
        materializationHint: metadataValue(chunk.metadata, ["materialization_hint"], "not recorded"),
        qualityPolicy: metadataValue(chunk.metadata, ["quality_action_policy"], "not recorded"),
      },
      layout: {
        layoutGroupId: metadataValue(chunk.metadata, ["layout_group_id"], "not recorded"),
        layoutRole: metadataValue(chunk.metadata, ["layout_role"], "not recorded"),
        readingOrder: metadataValue(chunk.metadata, ["reading_order"], "not recorded"),
      },
      context: {
        parentChunkId: metadataValue(chunk.metadata, ["parent_chunk_id"], "not recorded"),
        previousChunkId: metadataValue(chunk.metadata, ["previous_chunk_id"], "not recorded"),
        nextChunkId: metadataValue(chunk.metadata, ["next_chunk_id"], "not recorded"),
      },
    },
```

- [ ] **Step 5: Run chunk inspector tests**

Run:

```powershell
Set-Location frontend
npm test -- chunk-inspector-three-pillar.test.tsx --run
```

Expected: PASS.

- [ ] **Step 6: Commit chunk inspector metadata**

```powershell
git add frontend/src/features/chunks/chunk-inspector.tsx frontend/tests/chunk-inspector-three-pillar.test.tsx
git commit -m "feat: surface layout and context metadata in chunks"
```

---

### Task 7: Pipeline Canvas Three-Pillar Architecture Map

**Files:**
- Modify: `frontend/src/features/pipeline/pipeline-builder.tsx`
- Create: `frontend/tests/pipeline-builder.test.tsx` if absent

- [ ] **Step 1: Write the failing pipeline test**

Create `frontend/tests/pipeline-builder.test.tsx`:

```typescript
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../src/api/client";
import { PipelineBuilder } from "../src/features/pipeline/pipeline-builder";

vi.mock("@xyflow/react", () => ({
  Background: () => <div>Background</div>,
  Controls: () => <div>Controls</div>,
  Handle: () => null,
  MiniMap: () => <div>MiniMap</div>,
  Position: { Left: "left", Right: "right" },
  ReactFlow: ({ nodes }: { nodes: Array<{ data: { label: string; detail: string } }> }) => (
    <div aria-label="RAG pipeline flow">
      {nodes.map((node) => (
        <section key={node.data.label}>
          <h3>{node.data.label}</h3>
          <p>{node.data.detail}</p>
        </section>
      ))}
    </div>
  ),
}));

vi.mock("../src/api/client", () => ({
  apiClient: {
    documents: vi.fn(),
    variants: vi.fn(),
    runs: vi.fn(),
    graph: vi.fn(),
    diagnostics: vi.fn(),
  },
}));

function renderPipeline() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <PipelineBuilder />
    </QueryClientProvider>,
  );
}

describe("PipelineBuilder", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.documents).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.variants).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.runs).mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0, has_more: false });
    vi.mocked(apiClient.graph).mockResolvedValue({ nodes: [], edges: [] });
    vi.mocked(apiClient.diagnostics).mockResolvedValue({
      capabilities: {},
      dependency_status: {},
      warnings: [],
      runtime_mode: "runtime",
      overall_status: "ready",
      checks: [],
    });
  });

  it("shows the three-pillar retrieval architecture as first-class stages", async () => {
    renderPipeline();

    expect(await screen.findByText("Domain resolver")).toBeVisible();
    expect(screen.getByText("Quality gate")).toBeVisible();
    expect(screen.getByText("Route planner")).toBeVisible();
    expect(screen.getByText("Layout neighbors")).toBeVisible();
    expect(screen.getByText("Context window")).toBeVisible();
    expect(screen.getByText("Context assembly")).toBeVisible();
  });
});
```

- [ ] **Step 2: Run the failing pipeline test**

Run:

```powershell
Set-Location frontend
npm test -- pipeline-builder.test.tsx --run
```

Expected: FAIL because the current canvas only has coarse stages.

- [ ] **Step 3: Replace coarse retrieval node with three-pillar nodes**

In `frontend/src/features/pipeline/pipeline-builder.tsx`, update the `nodes` list so the core flow includes these stages:

```typescript
      stage("documents", "Documents", "Upload source files", formatCount(documentsQuery.data?.total), 0, 0, "input"),
      stage("chunking", "Chunking", "Parse and mirror chunks", "Searchable spans", 240, 0, "process"),
      stage("domain", "Domain resolver", "Classify domain and reference style", "Profile route", 500, -150, "process"),
      stage("quality", "Quality gate", "Apply parser and materialization policy", "Safe lanes", 500, 0, "process"),
      stage("route", "Route planner", "Plan metadata, vector, runtime, graph lanes", "Lane plan", 760, 0, "process"),
      stage("layout", "Layout neighbors", "Expand page, group, and reading-order context", "Layout trace", 1020, -110, "process"),
      stage("context", "Context window", "Hydrate parent, sibling, previous, and next chunks", "Context trace", 1020, 110, "process"),
      stage("reranker", "Reranker", "Record rank deltas and degraded status", "Rank trace", 1280, -110, "process"),
      stage("assembly", "Context assembly", "Preserve evidence and record dropped context", "Grounded context", 1280, 110, "process"),
      stage("answer", "Answer", "Sources, traces, timings", "Run result", 1540, 0, "output"),
      stage(
        "graph",
        "Graph",
        "Inspect entities and edges",
        `${formatCount(graphQuery.data?.nodes.length)} nodes`,
        760,
        180,
        "output",
      ),
```

Update `edges`:

```typescript
      edge("documents", "chunking", "parse"),
      edge("chunking", "domain", "metadata"),
      edge("domain", "quality", "policy"),
      edge("quality", "route", "lanes"),
      edge("route", "layout", "layout"),
      edge("route", "context", "context"),
      edge("route", "graph", "graph"),
      edge("layout", "reranker", "candidates"),
      edge("context", "assembly", "neighbors"),
      edge("reranker", "assembly", "ranked"),
      edge("assembly", "answer", "ground"),
      edge("graph", "answer", "evidence"),
```

Update the stage checklist labels to include:

```tsx
<StageCheck icon={Search} label="Domain resolver" value="Profile route" diagnostic={stageDiagnostics.retrieval} />
<StageCheck icon={AlertTriangle} label="Quality gate" value="Materialization policy" diagnostic={stageDiagnostics.chunks} />
<StageCheck icon={GitBranch} label="Route planner" value="Lane plan" diagnostic={stageDiagnostics.retrieval} />
<StageCheck icon={FileText} label="Layout neighbors" value="Reading-order trace" diagnostic={stageDiagnostics.retrieval} />
<StageCheck icon={Database} label="Context window" value="Parent and sibling context" diagnostic={stageDiagnostics.retrieval} />
<StageCheck icon={SlidersHorizontal} label="Context assembly" value="Dropped reasons" diagnostic={stageDiagnostics.answers} />
```

- [ ] **Step 4: Run pipeline tests**

Run:

```powershell
Set-Location frontend
npm test -- pipeline-builder.test.tsx --run
```

Expected: PASS.

- [ ] **Step 5: Commit pipeline map**

```powershell
git add frontend/src/features/pipeline/pipeline-builder.tsx frontend/tests/pipeline-builder.test.tsx
git commit -m "feat: map three-pillar architecture in pipeline view"
```

---

### Task 8: Documentation Updates

**Files:**
- Modify: `docs/user-guide.md`
- Modify: `docs/workflows.md`

- [ ] **Step 1: Update user guide with architecture inspection workflow**

In `docs/user-guide.md`, add this section after the Query workflow section:

```markdown
## Inspecting Three-Pillar Retrieval

After running a query, each result includes an **Architecture trace** summary and a **View pathway** action.

Use **Architecture trace** to confirm the resolved domain profile, materialization hint, layout expansion count, context window count, and final grounding status.

Use **View pathway** for the full operator audit:

- **Route plan** shows domain profile, layout hint, materialization hint, source of truth, direct evidence requirement, and graph context requirement.
- **Lane results** shows each retrieval lane, status, reason, candidate count, latency, timeout, and partial-result state.
- **Layout neighbors** shows layout group IDs, reading-order expansion, canonical neighbor chunks, and layout summaries.
- **Context window** shows parent, sibling, previous, next, and linked context relationships.
- **Context assembly** shows included evidence, dropped evidence, drop reasons, grounding status, breadcrumbs, and layout-summary visibility.
- **Reranker rank changes** shows before/after ranks for candidates when rank deltas are recorded.

Use **Inspect evidence** from a source row or chunk row to inspect the same architecture from the evidence perspective: domain/materialization, layout chain, context chain, graph relationships, parser quality, and source location.
```

- [ ] **Step 2: Update workflows with validation commands**

In `docs/workflows.md`, add this section under local validation:

````markdown
## Three-Pillar UI Observability Validation

Run the focused backend diagnostics test:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run pytest backend/tests/test_query_pathway_diagnostics_service.py -q
```

Run the focused frontend UI tests:

```powershell
Set-Location frontend
npm test -- three-pillar-trace.test.ts query-page.test.ts chunk-inspector-three-pillar.test.tsx pipeline-builder.test.tsx --run
```

Run frontend build before merging:

```powershell
Set-Location frontend
npm run build
```
````

- [ ] **Step 3: Run documentation grep checks**

Run:

```powershell
rg -n "Route plan|Lane results|Layout neighbors|Context window|Context assembly|Reranker rank changes" docs/user-guide.md docs/workflows.md
```

Expected: all six feature names appear in docs.

- [ ] **Step 4: Commit docs**

```powershell
git add docs/user-guide.md docs/workflows.md
git commit -m "docs: document three-pillar UI observability"
```

---

### Task 9: Final Verification And Integration Commit

**Files:**
- No new files unless previous tasks require test snapshot updates.

- [ ] **Step 1: Run focused backend tests**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run pytest backend/tests/test_query_pathway_diagnostics_service.py backend/tests/test_retrieval_orchestrator.py backend/tests/test_context_window_service.py backend/tests/test_layout_neighbor_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Run focused frontend tests**

Run:

```powershell
Set-Location frontend
npm test -- three-pillar-trace.test.ts query-page.test.ts chunk-inspector-three-pillar.test.tsx pipeline-builder.test.tsx --run
```

Expected: PASS.

- [ ] **Step 3: Run frontend lint and build**

Run:

```powershell
Set-Location frontend
npm run lint
npm run build
```

Expected: both commands pass.

- [ ] **Step 4: Run backend lint**

Run:

```powershell
uv run ruff check backend/src/ragstudio backend/tests
```

Expected: `All checks passed!`

- [ ] **Step 5: Validate proof packet still passes**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run python -m ragstudio.proof_packet.cli --packet docs/benchmarks/ragstudio-oss-proof-v1 --strict --json
```

Expected: JSON output includes `"status": "passed"`.

- [ ] **Step 6: Manual UI smoke**

Start the development stack the same way the project normally does:

```powershell
bash scripts/dev.sh
```

Open the frontend at `http://127.0.0.1:5173` and verify:

- Query result card shows `Architecture trace`.
- Query pathway drawer shows Route plan, Lane results, Layout neighbors, Context window, Context assembly, and Reranker rank changes.
- Evidence drawer shows Domain and materialization, Layout chain, and Context chain.
- Chunk inspector preview shows layout group, layout role, reading order, parent, previous, and next.
- Pipeline page shows Domain resolver, Quality gate, Route planner, Layout neighbors, Context window, and Context assembly.

- [ ] **Step 7: Final commit if verification caused follow-up edits**

If any follow-up fixes were made during verification:

```powershell
git add backend frontend docs
git commit -m "fix: complete three-pillar UI observability verification"
```

If no files changed during verification, do not create an empty commit.

---

## Execution Order

1. Task 1: Backend diagnostics first, because `pathway_diagnostics` should match the richer architecture.
2. Task 2: Shared frontend normalizer, because all UI surfaces reuse it.
3. Task 3: Query pathway drawer, because it is the primary architecture inspection surface.
4. Task 4: Query result card, because users need a compact summary before opening details.
5. Task 5: Evidence drawer, because users need source-level architecture details.
6. Task 6: Chunk inspector, because ingestion/retrieval metadata must be inspectable before query time.
7. Task 7: Pipeline map, because the top-level architecture should match actual runtime behavior.
8. Task 8: Docs.
9. Task 9: Full verification.

## Self-Review

- Spec coverage: all missing UI features from the audit are covered: route plan, lane table, layout neighbors, context window, context assembly, reranker rank deltas, evidence drawer sections, chunk inspector metadata, pipeline map, and docs.
- Placeholder scan: no task uses deferred work language; every task names exact files, tests, commands, and expected outputs.
- Type consistency: frontend architecture types are defined in `three-pillar-trace.ts` and reused by Query pathway, Query result, and Evidence viewer tasks. Backend diagnostic stage names match current trace stage names: `retrieval_route_plan`, `retrieval_lane_result`, `layout_neighbor_expansion`, `context_window`, `context_assembly`, and `reranker`.
