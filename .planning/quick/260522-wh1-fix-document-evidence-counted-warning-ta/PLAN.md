---
status: complete
created: 2026-05-22
---

# Fix Counted Warning Tab Mismatch

## Goal

Stop the left evidence-list tabs from showing full warning-row counts when they
filter preview decision rows.

## Plan

1. Compute preview decision counts separately from all warning-row counts.
2. Rename left quick tabs to make their preview-decision scope explicit.
3. Add counted/audit filtering to the full warning-row table.
4. Update focused tests and verify build.
