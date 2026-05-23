---
status: complete
completed: 2026-05-22
---

# Summary

Fixed the inflated document job warning count shown when parser warning counts
are present in both `parser_quality.warning_counts` and
`parser_quality_details.groups`.

## Changes

- Updated the document job warning count helper to use the largest available
  warning source instead of summing duplicate parser warning summaries.
- Added a regression test covering the duplicate-count shape that previously
  rendered `5695` instead of `2847`.

## Validation

- `cmd /c npm test -- documents-page.test.tsx --run`
