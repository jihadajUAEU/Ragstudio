---
phase: 06-app-evidence-viewer-and-runtime-trust-banner
plan: "01"
subsystem: ui
tags: [react, tanstack-query, diagnostics, accessibility, runtime-trust]
requires:
  - phase: 06-app-evidence-viewer-and-runtime-trust-banner
    provides: approved SPEC, CONTEXT, UI-SPEC, RESEARCH, and PATTERNS for Phase 6
provides:
  - Shared focus-trapped dialog shell for Phase 6 modal surfaces
  - Runtime trust chip in the Studio shell
  - Runtime trust detail panel with diagnostics refresh, navigation, and provider tests
affects: [app-shell, diagnostics, settings, evidence-viewer]
tech-stack:
  added: []
  patterns: [shared focus trap dialog, diagnostics polling query, provider test action state]
key-files:
  created:
    - frontend/src/components/focus-trap-dialog.tsx
    - frontend/src/components/runtime-trust.tsx
  modified:
    - frontend/src/components/app-shell.tsx
    - frontend/tests/app-shell.test.tsx
key-decisions:
  - Runtime trust polling calls diagnostics only every 30 seconds.
  - Provider tests fetch and use the saved default settings profile at click time.
  - Runtime trust and mobile navigation share one focus-trapped dialog primitive.
patterns-established:
  - Modal surfaces restore focus to the trigger and lock background scroll while open.
  - Runtime trust status is derived in one exported frontend mapper before rendering.
requirements-completed:
  - APP-UI-02
duration: 5 min
completed: 2026-05-16
---

# Phase 06 Plan 01: Runtime Trust Shell Summary

**Studio-wide runtime trust chip with diagnostics polling, accessible detail panel, and saved-profile provider tests**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-16T14:14:45Z
- **Completed:** 2026-05-16T14:19:46Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Added a reusable `FocusTrapDialog` that supports `role="dialog"`, `aria-modal`, Escape close, Tab trapping, body scroll lock, and trigger focus restoration.
- Added a compact runtime trust chip to `AppShell`, visible on every Studio route.
- Implemented deterministic status mapping for `Ready`, `Degraded`, `Blocked`, `Indexing`, `Graph pending`, and `Provider issue`.
- Added a `Runtime trust` panel with readiness sections for Backend/API, Worker/jobs, Postgres/PGVector, Neo4j/graph projection, MinerU/parser, LLM, Embeddings, and Reranker.
- Added diagnostics-only 30-second polling plus explicit `Refresh status`, `Open Diagnostics`, and independent provider test actions.

## Task Commits

Each task was committed atomically:

1. **Task 1: Extract shared focus-trapped dialog shell** - `0914278` (`feat(06-01): add shared focus trap dialog`)
2. **Task 2: Add runtime trust chip and deterministic status mapping** - `55e4cc5` (`feat(06-01): add runtime trust chip`)
3. **Task 3: Add diagnostics polling and runtime trust detail panel actions** - `319029b` (`feat(06-01): add runtime trust panel actions`)

**Plan metadata:** this summary commit.

## Files Created/Modified

- `frontend/src/components/focus-trap-dialog.tsx` - Reusable focus-trapped dialog primitive for mobile navigation, runtime trust, and later evidence drawers.
- `frontend/src/components/runtime-trust.tsx` - Runtime trust status derivation, shell chip, detail panel, polling, readiness sections, and provider test actions.
- `frontend/src/components/app-shell.tsx` - Renders runtime trust in the sticky shell header and uses the shared dialog for mobile navigation.
- `frontend/tests/app-shell.test.tsx` - Covers mobile nav focus behavior, status priority, diagnostics polling, panel sections/actions, provider tests, and Escape focus restoration.

## Decisions Made

- Provider tests intentionally use the saved default settings profile from `apiClient.defaultSettings()` and do not inspect unsaved Settings form drafts.
- The chip opens a panel instead of navigating directly; the panel owns the explicit `Open Diagnostics` route action.
- Diagnostics load failure maps to `Blocked` and includes the API error text in the accessible chip label.

## Deviations from Plan

None - plan executed exactly as written.

---

**Total deviations:** 0 auto-fixed.
**Impact on plan:** The runtime trust shell is ready for the shared Evidence Viewer to reuse the dialog pattern.

## Issues Encountered

- Focus restoration test required focusing the trust chip before simulating Escape, matching keyboard-trigger behavior in jsdom.

## Verification

- `cd frontend && npm test -- --run app-shell.test.tsx` - passed
- `cd frontend && npm test -- --run app-shell.test.tsx settings-page.test.tsx` - passed
- `cd frontend && npm run build` - passed

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for `06-02`: the shared focus-trap primitive and runtime trust patterns are available for the Evidence Viewer and Query source inspection.

---
*Phase: 06-app-evidence-viewer-and-runtime-trust-banner*
*Completed: 2026-05-16*
