# Quick Task 260522-ouk: Add shared DataTable pagination components for all tables

## Goal

Add a reusable pagination surface to the shared `DataTable` component so feature
pages can use one consistent table footer instead of hand-rolling per-page
pagination controls.

## Scope

- Extend `frontend/src/components/data-table.tsx` with optional controlled
  pagination props.
- Keep pagination optional so existing table callers continue to work.
- Wire the Documents and Jobs tables through the shared pagination contract as
  the first implementation.
- Add focused frontend tests for the shared component and existing documents
  page behavior.

## Plan

1. Add a `DataTablePagination` type and footer rendering to `DataTable`.
2. Keep the component controlled: pages own current page, page size, total count,
   and data slicing or server-backed query behavior.
3. Add shared footer affordances: range text, first/previous/next/last buttons,
   optional page size selector, and accessible labels.
4. Update the Documents page to slice filtered Documents and Jobs rows and pass
   pagination metadata into `DataTable`.
5. Reset table page to 1 when filters change.
6. Run focused table and documents page tests plus lint on changed files.
