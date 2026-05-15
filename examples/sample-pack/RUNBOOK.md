# Sample Pack Runbook

Use this runbook to verify the sample pack in a live Ragstudio app.

```bash
export RAGSTUDIO_FRONTEND_URL="${RAGSTUDIO_FRONTEND_URL:-http://127.0.0.1:5173}"
```

Open `$RAGSTUDIO_FRONTEND_URL` in a browser.

## App Flow

1. Open Documents.
2. Upload the files in `documents/`.
3. Attach the matching JSON files in `metadata/` when upload or reindex metadata is available.
4. Wait for indexing. If a job fails or stays pending, capture that state as a limitation.
5. Open Pipeline and inspect parser warnings for `ocr-stress`.
6. Open Chunks and inspect metadata for at least one exact-reference chunk.
7. Open Query and run an exact-reference question from `evaluations/sample-pack-evaluation-set.json`.
8. Open Query and run a `should_not_answer` question from the same evaluation set.
9. Open Graph when graph projection is available and inspect citation relationships for `legal-opinion` or `scientific-article`.
10. Open Evaluation, Variants, Experiments, Comparison, and Optimizer when those flows are configured.
11. Capture screenshots only after checking they contain no private endpoint, private hostname, token, local path, or unpublished model/provider detail.
12. Update `screenshots/signoff.json` with the approval state for every screenshot.

## Screenshot Targets

- Documents page with uploaded sample documents.
- Pipeline or job warning view for the OCR stress document.
- Chunk inspector showing reference metadata and quality action policy.
- Query trace for an exact-reference answer.
- Query trace for a should-not-answer case.
- Graph page showing legal or scientific citation relationships when available.
- Evaluation or Comparison page showing sample-pack runs when available.

## Limitation Rule

If a surface is unavailable, broken, or not configured, record the limitation. Do not mark it as proof.
