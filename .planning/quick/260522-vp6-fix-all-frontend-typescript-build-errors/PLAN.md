---
status: complete
created: 2026-05-22
---

# Fix Frontend TypeScript Build Errors

## Goal

Make `frontend` pass `npm run build` by fixing the current TypeScript errors
without changing unrelated runtime behavior.

## Plan

1. Capture the current TypeScript error set.
2. Fix stale TanStack Query call sites that pass API functions directly.
3. Fix document page type drift from nullable job/document fixtures.
4. Re-run focused tests where touched and then the full frontend build.
