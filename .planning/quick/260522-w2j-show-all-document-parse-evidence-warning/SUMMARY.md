---
status: complete
completed: 2026-05-22
---

# Show All Parse Evidence Warnings Summary

## Completed

- Added an `All warning rows` section to the document parse evidence page with
  search, warning-code filtering, page-size control, and pagination.
- Kept selected-decision warning details scoped to the clicked evidence row.
- Updated the backend parse evidence service to collect warning rows across the
  full document while keeping detailed chunk/block evidence capped to the preview
  response.
- Optimized full-document warning collection to load only chunk id, source
  location, and extraction-quality metadata.

## Verification

- Live API check for `9abdf420-a695-470d-b427-e84df56a52f0` returned
  `warnings=5496`, `decisions=107`, `chunksPreview=200`, and `totals=6149`.
- `$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; python -m pytest backend\tests\test_document_parse_evidence.py`
  passed with 26 tests.
- `cmd /c npm test -- document-evidence-inspector.test.tsx --run` passed with
  12 tests.
- `cmd /c npm run build` passed.
