---
status: complete
completed: 2026-05-22
---

# Fix Frontend TypeScript Build Errors Summary

## Completed

- Wrapped paged API query functions so TanStack Query no longer passes its
  internal query context as API options.
- Fixed graph query typing by using an explicit zero-argument query function.
- Normalized selected warning job state to `undefined` instead of mixing
  `null` and `undefined`.
- Guarded document warning panel stage fallback when a selected job is absent.
- Removed stale fields from a document page test fixture that no longer match
  `DocumentOut`.

## Verification

- `cmd /c npm run build` passed.
- `cmd /c npm test -- document-evidence-page.test.tsx document-evidence-inspector.test.tsx documents-page.test.tsx --run`
  passed with 36 tests.
