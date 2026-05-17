# Query Pathway Performance Diagnostics Design

Date: 2026-05-17
Status: Design approved for user review

## Context

Ragstudio already has a Query page `View pathway` drawer. It currently shows these
sections:

- Summary
- Timeline
- Planner
- Retrieval
- Answer
- Raw

The current timeline is useful, but it does not fully answer the user's operating
question: for a slow query, what happened in each stage, what came out of that
stage, why did it take that long, and what should be checked next?

The goal for this phase is visibility first. No query behavior should change in
this design. The system should explain the existing run clearly enough that later
performance tuning is based on real stage evidence instead of guesses.

## Goals

- Keep the existing `View pathway` button and right-side drawer pattern.
- Make the pathway modal primarily timeline-based.
- Show each query stage from step 1 to step n with:
  - input
  - action
  - output
  - status
  - time taken
  - budget or timeout
  - diagnosis
  - suggested action
- Preserve raw run data for deeper debugging.
- Make slow-stage diagnosis understandable without reading raw JSON.
- Support both fast mode and full answer mode.

## Non-Goals

- Do not change retrieval, planning, graph, rerank, or answer behavior.
- Do not add automatic budget tuning.
- Do not add Settings controls for budgets.
- Do not add parallel or deferred stage classification.
- Do not add a database migration.
- Do not create a second modal.

## User Experience

The `View pathway` drawer should change from six sections:

- Summary
- Timeline
- Planner
- Retrieval
- Answer
- Raw

to three sections:

- Summary
- Timeline
- Raw

The Summary section stays compact. It should show run status, total time, answer
mode, top reference, top source, and error if any.

The Timeline section becomes the main view. Each row represents one query stage
and includes the stage input, action, output, status, elapsed time, budget,
diagnosis, and suggested action.

The Raw section remains collapsible and shows the underlying `timings`,
`chunk_traces`, and `token_metadata` for advanced inspection.

## Timeline Stages

The first version should normalize these stages when data is available:

1. Planner
2. LLM planning
3. Metadata retrieval
4. Native retrieval
5. Seed fusion
6. Graph expansion
7. Graph hydration
8. Final fusion
9. Hypothesis verification
10. Context assembly
11. Answer generation
12. Grounding validation

Missing stages should render as `skipped` or `unknown`, not crash the drawer.

## Diagnostic Row Shape

The backend should produce normalized diagnostic rows so the frontend does less
trace-specific interpretation.

Suggested shape:

```json
{
  "stage": "llm_planning",
  "label": "LLM planning",
  "input": "query + selected document metadata",
  "action": "Generate target terms and possible references",
  "output": "target_terms: offering, sacrifice, eid; possible_references: book:13:hadith:25",
  "status": "success",
  "time_ms": 1543,
  "budget_ms": 5000,
  "diagnosis": "Healthy. Used 31% of budget.",
  "suggested_action": "None"
}
```

The row should be display-ready but still structured enough for future UI
formatting. `time_ms` and `budget_ms` should remain numeric when known.

## Backend Design

Add a focused diagnostics builder, for example
`QueryPathwayDiagnosticsService`.

Inputs:

- run timings
- chunk traces
- sources
- token metadata
- query config
- run status and error fields

Output:

- ordered diagnostic rows
- optional summary values if useful

The service should use existing `timings`, `chunk_traces`, `sources`, and
`token_metadata`; it should not require new persistence tables.

It can be wired in one of two ways:

- Preferable: add an optional response field to `RunOut`, such as
  `pathway_diagnostics`, and populate it when serializing runs.
- Acceptable fallback: place the normalized rows in `token_metadata` under a
  clearly named key if a schema change is too wide.

The preferred option is cleaner because it keeps diagnostics separate from model
token metadata.

## Frontend Design

Keep `QueryPathwayViewer` as the drawer component.

Simplify its content:

- Render Summary from run fields and diagnostics summary.
- Render Timeline from normalized diagnostic rows.
- Render Raw from existing run details.

The component should still tolerate old runs that do not have
`pathway_diagnostics`. In that case, it can fall back to the current local
builder logic or show a minimal timeline with raw data available.

Timeline rows should be readable in the drawer:

- first line: step number, stage label, status, time, budget
- detail blocks: input, action, output, diagnosis, suggested action
- long text should wrap cleanly
- missing values should show `not recorded`

## Status Mapping

Use a small, consistent status vocabulary:

- `success`: completed normally
- `warning`: timeout, fallback, degraded, near budget, or partial result
- `failed`: stage error or failed run stage
- `skipped`: intentionally not run
- `unknown`: trace or timing is missing

The UI can continue mapping these to the existing status pill colors.

## Diagnosis Rules

The first version should use simple deterministic rules:

- Healthy: stage succeeded and used less than 80 percent of its budget.
- Near budget: stage succeeded but used 80 percent or more of its budget.
- Timed out: trace or timing records timeout.
- Degraded: trace records fallback, degradation, or partial result.
- Skipped: trace records skipped or config disabled the stage.
- Missing trace: expected timing or output is not recorded.

Examples:

- `LLM planning`: `1543 ms / 5000 ms` -> `Healthy. Used 31% of budget.`
- `Native retrieval`: timeout at `2500 ms` -> `Timed out; metadata fallback used.`
- `Answer generation`: `3001 ms / 3000 ms` -> `Timed out; evidence-first answer used.`
- `Graph expansion`: disabled -> `Skipped by query configuration.`

Suggested actions should be short and practical. Examples:

- `None`
- `Use full mode if natural LLM wording is required.`
- `Check native runtime latency.`
- `Use exact reference query when known.`
- `Disable graph for fast mode if graph context is not needed.`
- `Increase planner timeout only if plans are frequently missing.`

## Stage Output Requirements

The `output` field is first-class. It should summarize what the stage produced,
not only whether it succeeded.

Examples:

- LLM planning output: target terms and possible references.
- Metadata retrieval output: pass names and candidate counts.
- Native retrieval output: candidate count or timeout/error reason.
- Fusion output: final candidate count and top reference if available.
- Hypothesis verification output: confirmed, rejected, and not-found references.
- Context assembly output: included/dropped evidence counts.
- Answer generation output: LLM answer status or evidence-first fallback reason.
- Grounding validation output: grounded status, cited labels, or failures.

## Error Handling

- Missing diagnostics should not block the query response.
- Diagnostics generation should be best-effort and should not change run status.
- If diagnostics fail, the UI should still show Summary and Raw.
- Old runs without normalized diagnostics must remain viewable.

## Testing

Backend tests:

- Builds a complete diagnostic timeline from representative successful fast-mode
  run data.
- Marks answer timeout as warning with `answer_budget_ms`.
- Marks native timeout/degraded status as warning with output and suggestion.
- Shows planner target terms and possible references in output.
- Handles missing traces without exceptions.
- Does not alter query run status or answer content.

Frontend tests:

- `View pathway` still opens an accessible drawer.
- Drawer shows `Summary`, `Timeline`, and `Raw`.
- Drawer no longer depends on separate `Planner`, `Retrieval`, and `Answer`
  sections.
- Timeline row shows input, action, output, status, time, budget, diagnosis, and
  suggested action.
- Old-run fallback remains readable when normalized diagnostics are missing.

## Acceptance Criteria

- A slow fast-mode query clearly identifies whether the bottleneck was planner,
  metadata, native retrieval, graph, answer generation, or grounding.
- The modal shows the output of every recorded stage.
- The modal structure is simplified to `Summary / Timeline / Raw`.
- Raw traces remain available.
- Existing evidence modal behavior is unaffected.
- No retrieval or answer behavior changes in this phase.
