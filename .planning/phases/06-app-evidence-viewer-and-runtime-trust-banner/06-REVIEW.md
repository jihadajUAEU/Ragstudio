---
phase: 06-app-evidence-viewer-and-runtime-trust-banner
status: clean
depth: standard
reviewed_at: 2026-05-16T14:32:37Z
files_reviewed: 9
critical: 0
warnings: 0
info: 0
---

# Phase 6 Code Review

## Scope

Reviewed the Phase 6 frontend implementation for the runtime trust chip and
panel, shared focus-trapped dialog, shared evidence viewer, Query source
evidence rows, Chunk Inspector evidence entry points, route-link fallback states,
and related frontend tests.

## Findings

No blocking bugs, security issues, accessibility regressions, or code-quality
issues found.

## Checks Performed

- Confirmed runtime trust state priority covers blocked diagnostics, provider
  failures, active indexing, graph projection pending, degraded checks, and ready
  runtime state.
- Confirmed provider test actions fetch the saved default settings payload before
  testing LLM, embeddings, reranker, and MinerU connections.
- Confirmed the evidence viewer preserves raw JSON while adding readable parser,
  quality, source-location, reranker, graph, metadata, and route-link sections.
- Confirmed missing evidence states are explicit instead of silently hiding
  incomplete provenance.
- Confirmed shared dialog behavior uses `role="dialog"`, `aria-modal`, Escape
  close, focus trapping, scroll lock, and focus restoration.
- `cd frontend && npm run lint` - passed.
- `cd frontend && npm test -- --run app-shell.test.tsx query-page.test.tsx chunk-inspector.test.tsx graph-page.test.tsx settings-page.test.tsx` - passed.
- `cd frontend && npm run build` - passed.

## Residual Risk

Manual browser smoke should still confirm the drawer sizing and header chip feel
right against live diagnostics data in the running app.
