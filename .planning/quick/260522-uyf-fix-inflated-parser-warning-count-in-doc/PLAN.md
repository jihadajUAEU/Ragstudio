---
status: in_progress
created: 2026-05-22
---

# Fix Inflated Parser Warning Count In Doc

## Root Cause

The documents page warning badge adds job warning message count, parser quality
detail group totals, and persisted parser quality warning counts. The parser
quality detail groups and persisted warning counts represent the same counted
parser warnings, so jobs with both payload fields show an inflated total.

## Plan

1. Add a focused frontend regression test for duplicate parser warning count
   sources.
2. Update the warning-count helper to choose the strongest available warning
   count instead of summing duplicate sources.
3. Run the focused documents page test.
