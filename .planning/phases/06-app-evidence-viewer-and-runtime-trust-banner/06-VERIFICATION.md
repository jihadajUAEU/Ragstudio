---
phase: 06-app-evidence-viewer-and-runtime-trust-banner
status: passed
verified_at: 2026-05-16T14:32:37Z
requirements:
  - APP-UI-01
  - APP-UI-02
automated_checks: passed
human_verification: optional_visual_smoke
---

# Phase 6 Verification: App Evidence Viewer and Runtime Trust Banner

## Verdict

Passed. Phase 6 achieves its goal: Ragstudio operators now have a compact
runtime trust status in the shell and a shared in-app evidence viewer for Query
source evidence and Chunk Inspector results.

## Requirement Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| APP-UI-01 | passed | Query results render readable source rows with `Inspect evidence`, and Chunk Inspector rows open the same `Evidence details` drawer with chunk text, source location, parser warnings, quality status, reranker context, graph context, metadata, route links, and raw JSON fallback. |
| APP-UI-02 | passed | AppShell renders the runtime trust chip on every Studio route. The panel groups Backend/API, Worker/jobs, Postgres/PGVector, Neo4j/graph projection, MinerU/parser, LLM, Embeddings, and Reranker readiness from diagnostics and supports refresh, Diagnostics navigation, and explicit provider tests. |

## Must-Have Verification

- Plan `06-01` status mapping priority is implemented and tested: `Blocked`,
  `Provider issue`, `Indexing`, `Graph pending`, `Degraded`, and `Ready`.
- Diagnostics polling uses `refetchInterval: 30000` and does not call provider
  test APIs unless a provider test button is clicked.
- Provider tests fetch the saved default settings payload before testing LLM,
  embeddings, reranker, or MinerU.
- Shared `FocusTrapDialog` provides `role="dialog"`, `aria-modal`, Escape close,
  focus trapping, body scroll lock, overlay close, and focus restoration.
- Shared `EvidenceViewer` renders a summary first, keeps detail/raw sections
  expandable, bounds raw JSON overflow, and renders all payload values as React
  text or JSON.
- Query keeps the raw `Sources` JSON panel while adding readable source rows.
- Chunk Inspector preserves existing chunk cards, retrieval explain details,
  source-location JSON, and metadata JSON while adding `Inspect evidence`.
- Missing evidence states are explicit: parser warnings, quality policy, source
  location, graph context, and document links show recorded/unavailable text.
- Route actions only link to existing Studio surfaces and show unavailable
  labels when context is missing.

## Automated Checks

- PASS: `gsd-sdk query phase-plan-index 06` shows all three plans have summaries
  and no incomplete plans remain.
- PASS: `gsd-sdk query verify.key-links` passed for Plans `06-02` and `06-03`
  during execution.
- PASS: `cd frontend && npm run lint`.
- PASS: `cd frontend && npm test -- --run app-shell.test.tsx query-page.test.tsx chunk-inspector.test.tsx graph-page.test.tsx settings-page.test.tsx` passed with 5 files and 43 tests.
- PASS: `cd frontend && npm run build`.
- PASS: `gsd-sdk query verify.schema-drift 06` reported no schema drift.

## Non-Blocking Workflow Warnings

- `gsd-sdk query verify.codebase-drift` reported structural drift from older
  unmapped repository files and recommended `/gsd-map-codebase --paths ...`.
  The execute-phase workflow treats this as non-blocking and it is not caused by
  the Phase 6 UI changes.

## Residual Risk

Manual visual smoke in a browser should confirm the drawer sizing and runtime
trust chip feel right against live diagnostics data. Automated accessibility,
focus, lint, test, build, and schema gates are passing.
