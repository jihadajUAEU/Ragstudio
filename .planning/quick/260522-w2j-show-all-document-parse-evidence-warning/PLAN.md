---
status: complete
created: 2026-05-22
---

# Show All Parse Evidence Warnings

## Goal

Expose warning rows as their own searchable, paginated evidence view instead of
requiring users to infer warning coverage from normalization decision rows.

## Plan

1. Confirm the current decision count and warning-row count.
2. Add a paginated all-warnings panel to the evidence page.
3. Keep selected-decision warning details unchanged.
4. Add focused frontend coverage and run build/tests.
