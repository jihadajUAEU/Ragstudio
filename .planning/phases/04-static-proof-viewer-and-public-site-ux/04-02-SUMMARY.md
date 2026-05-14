---
phase: 04-static-proof-viewer-and-public-site-ux
plan: "02"
status: completed
completed: 2026-05-14
site_root: /Users/meet/Documents/ragstudio-site
---

# Plan 04-02 Summary

## Outcome

Added deep-linkable claim dossiers and evidence panels so visitors can inspect
what each public claim is based on before trusting the site copy.

## Implemented

- Added `claim-<claim id>` sections for all imported claims.
- Rendered limitations, proof summaries, missing evidence, disabled reasons,
  requirements to prove, source paths, and proof metadata.
- Grouped evidence under the UI-SPEC labels: `Parser warning/unit`,
  `Chunk/source`, `Retrieval trace`, `Graph/reranker`, `Screenshot`, and
  `Raw artifact`.
- Added static artifact links under `/proof/ragstudio-oss-proof-v1/...`.
- Added explicit `Not available in this static build.` fallback text for
  artifact paths that are referenced but not copied into the static bundle.
- Added pre-filled GitHub feedback issue links containing claim id, artifact
  path, packet id, validation id, source commit, and viewer hash context.

## Verification

- `cd /Users/meet/Documents/ragstudio-site && npm test` - passed
- `cd /Users/meet/Documents/ragstudio-site && npm run check:static && npm run lint && npm test && npm run build` - passed

