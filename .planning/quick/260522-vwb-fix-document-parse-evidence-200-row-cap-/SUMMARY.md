---
status: complete
completed: 2026-05-22
---

# Fix Document Parse Evidence 200 Row Cap Summary

## Completed

- Added parse evidence `totals.chunks` so the API reports the full materialized
  document chunk count separately from capped proof preview rows.
- Updated the document evidence UI metrics to show the full chunk total when
  available.
- Kept detailed chunks, parser blocks, warnings, and decisions capped at 200
  source chunks to avoid returning a very large proof payload in one response.
- Preserved the proof limitation message that states how many detailed chunks
  are omitted from the preview.

## Verification

- Live API check for `9abdf420-a695-470d-b427-e84df56a52f0` returned
  `totals.chunks=6149` and `preview.chunks=200`.
- `$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; python -m pytest backend\tests\test_document_parse_evidence.py`
  passed with 25 tests.
- `cmd /c npm test -- document-evidence-inspector.test.tsx --run` passed with
  11 tests.
- `cmd /c npm run build` passed.
