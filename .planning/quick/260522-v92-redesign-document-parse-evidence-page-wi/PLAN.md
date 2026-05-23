---
status: complete
created: 2026-05-22
---

# Redesign Document Parse Evidence Page

## Goal

Implement the approved document parse evidence mock: compact document summary,
metrics, search/filter controls, paginated evidence decision list, selected
evidence detail, and cleaner proof/artifact/redaction panels.

## Plan

1. Preserve the existing parse evidence API contract.
2. Add client-side search, filters, tabs, and pagination over normalization
   decisions.
3. Rework proof metadata so redactions are searchable and bounded.
4. Update focused component tests.
5. Validate with Vitest and browser screenshot review.
