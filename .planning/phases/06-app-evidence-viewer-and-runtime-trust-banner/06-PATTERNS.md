# Phase 6 - Pattern Map

**Mapped:** 2026-05-16
**Purpose:** Existing analogs and implementation constraints for planning Phase 6.

## Files Likely To Change

| Target | Role | Closest Existing Analog | Pattern To Reuse |
|--------|------|-------------------------|------------------|
| `frontend/src/components/app-shell.tsx` | Runtime trust chip/panel host | Existing mobile navigation dialog in same file | Focus trap, Escape close, body overflow lock, focus restoration, sidebar navigation callbacks. |
| `frontend/src/features/evidence/evidence-viewer.tsx` or equivalent | Shared evidence drawer | `frontend/src/components/app-shell.tsx`, `frontend/src/features/diagnostics/diagnostics-page.tsx` | Dialog shell plus `details/summary` raw JSON sections. |
| `frontend/src/features/query/query-page.tsx` | Query source entry point and adapter | Existing `RunResult`, `RerankerSummary`, `JsonPanel` | Keep raw JSON panels; add readable source rows and inspect action. |
| `frontend/src/features/chunks/chunk-inspector.tsx` | Chunk entry point and adapter | Existing `ChunkCard`, `RetrievalExplainPanel` | Preserve chunk card layout; add explicit `Inspect evidence` button. |
| `frontend/src/features/graph/graph-page.tsx` | Graph unavailable wording source | Existing diagnostics-derived `graphUnavailableDetail` | Reuse warnings/checks logic when graph context is missing. |
| `frontend/src/api/client.ts` | API client calls | Existing settings tests and diagnostics methods | Use existing `diagnostics`, `defaultSettings`, and provider test methods. |
| `frontend/tests/app-shell.test.tsx` | Trust chip/panel tests | Existing AppShell modal focus test | Add diagnostics mocks, fake timers, panel actions, focus restoration. |
| `frontend/tests/query-page.test.tsx` | Query evidence entry tests | Existing QueryPage mock flow | Add source payload fixtures and evidence viewer assertions. |
| `frontend/tests/chunk-inspector.test.tsx` | Chunk evidence entry tests | Existing ChunkInspector search fixture | Add inspect action and missing-state assertions. |

## Concrete Analog Excerpts

### AppShell Modal Behavior

`frontend/src/components/app-shell.tsx` already stores the active element, locks body overflow, focuses the first control, traps Tab, closes on Escape, and restores focus in cleanup. The trust panel/evidence drawer should reuse or extract this behavior.

### Query Result Evidence

`frontend/src/features/query/query-page.tsx` renders `RunResult`, `RerankerSummary`, and raw JSON panels for `Sources`, `Chunk traces`, `Reranker traces`, `Token metadata`, and `Timings`. Add readable source rows near `Sources` without removing raw JSON.

### Chunk Evidence

`frontend/src/features/chunks/chunk-inspector.tsx` renders `ChunkCard`, exact `chunk.text`, `source_location`, full `metadata`, and `RetrievalExplainPanel` with matched references, relationship refs, and signals. The shared viewer should consume this already-visible data through a normalizer.

### Diagnostics And Graph State

`backend/src/ragstudio/services/diagnostics_service.py` includes graph projection state, graph projection detail, stale running jobs, ready index jobs, warnings, runtime checks, and `overall_status`. `frontend/src/features/graph/graph-page.tsx` already derives graph unavailable detail from diagnostics warnings/checks.

### Provider Test Flow

`frontend/src/features/settings/settings-page.tsx` already has mutations for embedding, LLM, reranker, and MinerU tests and message formatting. The trust panel should call the same `apiClient` methods, but with the saved default settings profile only.

## Data Flow Notes

1. `AppShell` mounts diagnostics query and derives one trust label.
2. Trust panel reads the same diagnostics result, plus on-demand default settings for manual provider tests.
3. Query page normalizes selected source + run-level traces into shared evidence.
4. Chunk page normalizes selected `ChunkOut` into shared evidence.
5. Shared evidence viewer renders summary first, details collapsed, raw JSON fallback, and route links.

## Planning Constraints

- No new frontend package.
- No new backend route unless deterministic provider status cannot be expressed from diagnostics in tests.
- Do not remove existing raw JSON panels.
- Do not fetch full graph data on evidence drawer open.
- Do not introduce report/export behavior.
- Every modal/drawer task must include focus restoration and Escape close tests.

## Verification Hooks

- `npm test -- --run app-shell.test.tsx`
- `npm test -- --run query-page.test.tsx`
- `npm test -- --run chunk-inspector.test.tsx`
- `npm test -- --run graph-page.test.tsx settings-page.test.tsx`
- `npm run build`
