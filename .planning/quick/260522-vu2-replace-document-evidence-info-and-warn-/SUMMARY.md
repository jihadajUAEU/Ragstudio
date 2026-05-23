---
status: complete
completed: 2026-05-22
---

# Replace Evidence Info And Warn Badges Summary

## Completed

- Replaced text-only evidence rail `info` and `warn` badges with compact icons.
- Added accessible labels and browser tooltips for no-warning, audit-info, and
  counted-warning states.

## Verification

- `cmd /c npm test -- document-evidence-inspector.test.tsx --run` passed.
- `cmd /c npm run build` passed.
