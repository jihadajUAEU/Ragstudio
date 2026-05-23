---
status: complete
completed: 2026-05-22
---

# Fix Counted Warning Tab Mismatch Summary

## Completed

- Changed left evidence-list tabs from full warning-row counts to preview
  decision counts.
- Added counted/audit filtering to the full `All warning rows` table, where the
  full warning-row counts belong.
- Added a regression test proving one preview decision can contain multiple
  counted warning rows without inflating the preview decision tab.

## Verification

- Browser screenshot confirmed the left rail now shows `Preview counted
  decisions 12`, not `Warning counted 3330`.
- `cmd /c npm test -- document-evidence-inspector.test.tsx --run` passed with
  13 tests.
- `cmd /c npm run build` passed.
