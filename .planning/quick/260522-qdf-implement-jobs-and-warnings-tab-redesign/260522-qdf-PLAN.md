# Quick Task 260522-qdf: Implement Jobs and Warnings tab redesign

## Goal

Implement the approved screenshot for the Documents page Jobs & Warnings tab.

## Scope

- Keep work focused in `frontend/src/features/documents/documents-page.tsx`.
- Preserve current upload, document list, job polling, warning inspection, and
  warning repair behavior.
- Reuse the shared `DataTable` and recently added pagination footer.
- Add tests only for the new visible Jobs & Warnings controls and behavior.

## Plan

1. Add Jobs tab state for warning-only filtering and auto-refresh controls.
2. Replace the Jobs tab body with the screenshot structure: metrics row, filter
   toolbar, jobs queue table, and selected-job inspector.
3. Redesign jobs table columns to show job/document/status/progress/stage/logs/
   warnings/actions.
4. Restyle the warning details panel into a selected-job inspector while keeping
   existing warning query, filter, repair, and table behavior.
5. Run focused Vitest, ESLint, and browser checks.
