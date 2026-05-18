# Quick Task 260518-spb: Semantic page-boundary stitching

## Goal

Implement conservative paragraph stitching for MinerU blocks that are split only by a PDF page boundary.

## Tasks

1. Add a focused regression in `backend/tests/test_parser_normalization.py` for a paragraph continued from page 1 onto page 2.
2. Update `backend/src/ragstudio/services/parser_normalization.py` with a post-normalization stitch pass that merges eligible adjacent text-like blocks across consecutive pages.
3. Run the focused parser normalization tests and ruff on the touched files.
