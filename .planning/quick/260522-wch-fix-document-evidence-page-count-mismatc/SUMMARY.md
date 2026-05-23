---
status: complete
completed: 2026-05-22
---

# Fix Document Evidence Count Mismatch Summary

## Completed

- Renamed summary metrics to distinguish preview-scoped rows from full-document
  totals.
- Added a count-model notice explaining that the left evidence list is a
  normalization-decision preview while the warning table shows all warning rows.
- Changed the left evidence-list warning filter to count only warnings attached
  to preview decisions.
- Renamed quick tabs so decision counts and warning-row counts are not mixed.
- Widened the decision warning filter to avoid truncating the label.

## Verification

- Live API count comparison for `9abdf420-a695-470d-b427-e84df56a52f0`:
  `decisions=107`, `warnings=5496`, `counted=3330`, `audit=2166`,
  `chunksPreview=200`, `totals=6149`.
- Browser screenshot confirmed the corrected labels render.
- `cmd /c npm test -- document-evidence-inspector.test.tsx --run` passed with
  12 tests.
- `cmd /c npm run build` passed.
