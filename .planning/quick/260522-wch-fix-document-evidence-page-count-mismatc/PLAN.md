---
status: complete
created: 2026-05-22
---

# Fix Document Evidence Count Mismatch

## Goal

Make document parse evidence counts unambiguous by separating full document
totals, preview-scoped evidence rows, and full warning rows.

## Plan

1. Compare live API counts with rendered UI labels.
2. Rename metrics and tab labels that mix preview decisions with full warning
   rows.
3. Add explicit preview/full wording where detailed rows remain capped.
4. Update focused tests and verify build.
