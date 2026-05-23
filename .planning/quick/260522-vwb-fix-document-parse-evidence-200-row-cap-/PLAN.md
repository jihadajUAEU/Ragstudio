---
status: complete
created: 2026-05-22
---

# Fix Document Parse Evidence 200 Row Cap

## Goal

Make the document parse evidence page report the real document chunk total even
when detailed proof rows remain capped for response size.

## Plan

1. Confirm the backend source of the `200` chunk count.
2. Add an explicit totals contract to parse evidence.
3. Use total chunk count for the UI metric card.
4. Keep detailed proof rows capped and clearly marked as a preview.
5. Add regression tests and verify build.
