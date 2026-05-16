---
phase: 06-app-evidence-viewer-and-runtime-trust-banner
plan: "02"
subsystem: ui
tags: [react, evidence-viewer, query, traces, accessibility]
requires:
  - phase: 06-app-evidence-viewer-and-runtime-trust-banner
    provides: 06-01 shared focus-trapped dialog primitive
provides:
  - Shared normalized Evidence Viewer drawer/sheet
  - Query readable source rows with Inspect evidence actions
  - Query source normalizer for loose source payloads and run-level reranker fallback
affects: [query, evidence-viewer, chunk-inspector]
tech-stack:
  added: []
  patterns: [normalized evidence model, readable source row before raw JSON fallback]
key-files:
  created:
    - frontend/src/features/evidence/evidence-viewer.tsx
  modified:
    - frontend/src/features/query/query-page.tsx
    - frontend/tests/query-page.test.tsx
key-decisions:
  - Raw Sources JSON remains visible after readable source rows.
  - Query source payloads are normalized defensively from loose records.
  - Unmatched reranker traces show the run-level fallback note rather than implying source-specific ranking.
patterns-established:
  - Evidence surfaces use one `NormalizedEvidence` input and shared `EvidenceViewer` component.
  - Missing evidence fields are displayed as explicit operational states.
requirements-completed:
  - APP-UI-01
duration: 5 min
completed: 2026-05-16
---

# Phase 06 Plan 02: Query Evidence Viewer Summary

**Shared Evidence Viewer drawer plus readable Query source rows with raw JSON fallback preserved**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-16T14:20:00Z
- **Completed:** 2026-05-16T14:24:49Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Created `EvidenceViewer` with the normalized evidence model, accessible `Evidence details` title, Summary-first layout, expandable detail sections, and bounded raw JSON.
- Added readable Query source rows with stable ids, document/source-location context, parser/quality badges, and explicit `Inspect evidence` actions.
- Preserved the existing raw `Sources` JSON panel as the debugging fallback.
- Added source normalizers that safely read loose Query source records and attach run-level reranker fallback context when no exact trace match exists.
- Added tests for source rows, selected source id, parser warnings, quality policy, source location, missing states, reranker fallback note, Escape close, and focus restoration.

## Task Commits

Each task was committed atomically:

1. **Task 1: Build shared evidence viewer and normalized evidence model** - `c3f8ab1` (`feat(06-02): add shared evidence viewer`)
2. **Task 2: Add Query source rows and evidence adapter** - `4473a36` (`feat(06-02): add query evidence rows`)
3. **Task 3: Cover Query evidence missing states and focus behavior** - `00f86eb` (`test(06-02): cover query evidence viewer`)

**Plan metadata:** this summary commit.

## Files Created/Modified

- `frontend/src/features/evidence/evidence-viewer.tsx` - Shared evidence drawer/sheet, normalized evidence types, summary/detail sections, route actions, and raw JSON fallback.
- `frontend/src/features/query/query-page.tsx` - Query source row rendering, source normalizer, reranker fallback summary, and Evidence Viewer integration.
- `frontend/tests/query-page.test.tsx` - Regression coverage for source rows, drawer behavior, missing-state honesty, reranker fallback, and focus close.

## Decisions Made

- The Query evidence viewer opens from an explicit `Inspect evidence` button; the source row and raw JSON remain separate.
- The run-level reranker fallback note is intentionally visible only after opening the Reranker evidence section.
- Route actions are included in the shared viewer now, with unavailable labels when context is missing; Plan 03 will expand graph/link behavior.

## Deviations from Plan

None - plan executed exactly as written.

---

**Total deviations:** 0 auto-fixed.
**Impact on plan:** Query evidence inspection is complete and ready for Chunk Inspector reuse in Plan 03.

## Issues Encountered

- The test assertion for the reranker fallback note needed to expand the `Reranker` detail section, matching the design contract that only Summary opens by default.

## Verification

- `cd frontend && npm test -- --run query-page.test.tsx` - passed
- `cd frontend && npm run build` - passed
- `gsd-sdk query verify.key-links .../06-02-PLAN.md` - passed

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for `06-03`: the shared viewer and Query adapter are in place, so Chunk Inspector can reuse `NormalizedEvidence` and the viewer can gain graph diagnostics/link polish.

---
*Phase: 06-app-evidence-viewer-and-runtime-trust-banner*
*Completed: 2026-05-16*
