---
status: complete
created: 2026-05-22
---

# Group Duplicate Selected Decision Warnings

## Goal

Make the selected decision summary readable by grouping repeated warning rows
with the same code/message/action while preserving raw warning rows in the full
warning table.

## Plan

1. Confirm why the selected warning appears multiple times.
2. Group selected summary warnings by display identity.
3. Show repeated row count when a group has multiple raw rows.
4. Add focused test coverage and verify build.
