---
status: complete
completed: 2026-05-22
---

# Group Duplicate Selected Decision Warnings Summary

## Completed

- Confirmed selected chunk `7fca71cf-8db4-4249-857f-d5af65926b5f` has three
  raw warning rows attached to one normalization decision.
- Grouped selected decision summary warnings by warning code, action, block type,
  counting status, and normalized severity.
- Added a row-count label, for example `3 rows`, so repeated raw rows do not
  print as duplicate cards in the selected summary.
- Preserved raw row-level warning display in the full warning table.

## Verification

- Browser screenshot confirmed grouped selected warning rows.
- `cmd /c npm test -- document-evidence-inspector.test.tsx --run` passed with
  14 tests.
- `cmd /c npm run build` passed.
