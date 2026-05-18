---
quick_id: 260518-spb
status: complete
completed_at: "2026-05-18T19:10:22+04:00"
task: "Implement semantic page-boundary paragraph stitching"
---

# Summary

Added conservative MinerU normalization stitching for adjacent paragraph/text blocks
that span consecutive PDF pages and appear to be one sentence split by a page
break. The merged block records `semantic_stitch`, `page_start`, `page_end`,
`stitched_pages`, and source summaries for proof/evidence inspection.

## Verification

- `PYTHONPATH=E:\repos\Ragstudio\backend\src python -m pytest backend/tests/test_parser_normalization.py -q`
- `D:\python312\Scripts\ruff.exe check backend/src/ragstudio/services/parser_normalization.py backend/tests/test_parser_normalization.py`
