---
phase: 01-proof-contract-and-baseline-packet
plan: "01"
subsystem: docs
tags:
  - proof-packet
  - synthetic-fixtures
  - evidence-artifacts
  - manifest
requires: []
provides:
  - Public proof packet root under docs/benchmarks/ragstudio-oss-proof-v1/
  - Synthetic Arabic and English reference-unit fixtures
  - Redacted parser, chunk, retrieval, graph, and reranker evidence artifacts
  - Manifest artifact links and SHA-256 hashes
affects:
  - phase-01-proof-contract-and-baseline-packet
  - phase-02-replay-and-export-tooling
  - phase-03-ragstudio-site-import
tech-stack:
  added: []
  patterns:
    - Manifest-first public proof packet
    - Synthetic static-fixture evidence
    - Redacted artifact export with manifest hash coverage
key-files:
  created:
    - docs/benchmarks/ragstudio-oss-proof-v1/manifest.json
    - docs/benchmarks/ragstudio-oss-proof-v1/fixtures/corpus.synthetic.json
    - docs/benchmarks/ragstudio-oss-proof-v1/fixtures/parser-warnings.synthetic.json
    - docs/benchmarks/ragstudio-oss-proof-v1/fixtures/retrieval-traces.synthetic.json
    - docs/benchmarks/ragstudio-oss-proof-v1/fixtures/graph-reranker.synthetic.json
    - docs/benchmarks/ragstudio-oss-proof-v1/artifacts/parser-quality.export.json
    - docs/benchmarks/ragstudio-oss-proof-v1/artifacts/chunks.export.json
    - docs/benchmarks/ragstudio-oss-proof-v1/artifacts/retrieval-run.export.json
    - docs/benchmarks/ragstudio-oss-proof-v1/artifacts/graph-projection.export.json
    - docs/benchmarks/ragstudio-oss-proof-v1/artifacts/reranker-trace.export.json
  modified: []
key-decisions:
  - "Used a synthetic static-fixture packet so public proof evidence is inspectable without private providers, live backend calls, or restricted corpus text."
  - "Computed SHA-256 hashes in Phase 1 for exported artifacts instead of leaving hash placeholders."
patterns-established:
  - "Manifest entries list every exported artifact and its SHA-256 hash."
  - "Synthetic fixtures reuse existing Ragstudio evidence names such as quality_action_policy, chunk_traces, reranker_traces, and graph_projection_state."
requirements-completed:
  - PROOF-01
  - PROOF-02
duration: 3 min
completed: 2026-05-14
---

# Phase 1 Plan 01: Proof Packet Baseline Summary

**Reviewer-first public proof packet root with synthetic reference fixtures, redacted evidence artifacts, and manifest hash coverage**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-14T09:30:02Z
- **Completed:** 2026-05-14T09:32:47Z
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments

- Created `docs/benchmarks/ragstudio-oss-proof-v1/` with the required reviewer-first folder structure.
- Added safe synthetic Arabic and English reference-unit fixtures with parser quality warnings and quality action policy examples.
- Added five redacted exported evidence artifacts for parser quality, chunks, retrieval, graph projection, and reranker traces.
- Updated the manifest to reference every exported artifact and record current SHA-256 hashes.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create proof packet directory skeleton and manifest shell** - `2c978f3` (feat)
2. **Task 2: Add synthetic corpus and evidence fixtures** - `1b81a7b` (feat)
3. **Task 3: Add redacted exported evidence artifacts and manifest links** - `68d14ba` (feat)

**Plan metadata:** this summary commit records close-out state.

## Files Created/Modified

- `docs/benchmarks/ragstudio-oss-proof-v1/manifest.json` - Packet provenance, folder map, artifact links, redaction policy, exclusions, limitations, and artifact hashes.
- `docs/benchmarks/ragstudio-oss-proof-v1/fixtures/corpus.synthetic.json` - Synthetic multilingual reference-unit corpus.
- `docs/benchmarks/ragstudio-oss-proof-v1/fixtures/parser-warnings.synthetic.json` - Parser-quality warning fixture with `reference_unit_missing_expected_script`.
- `docs/benchmarks/ragstudio-oss-proof-v1/fixtures/retrieval-traces.synthetic.json` - Retrieval trace fixture with `chunk_traces`.
- `docs/benchmarks/ragstudio-oss-proof-v1/fixtures/graph-reranker.synthetic.json` - Graph projection and reranker trace fixture.
- `docs/benchmarks/ragstudio-oss-proof-v1/artifacts/parser-quality.export.json` - Redacted parser-quality export artifact.
- `docs/benchmarks/ragstudio-oss-proof-v1/artifacts/chunks.export.json` - Redacted chunk export artifact.
- `docs/benchmarks/ragstudio-oss-proof-v1/artifacts/retrieval-run.export.json` - Redacted retrieval-run export artifact.
- `docs/benchmarks/ragstudio-oss-proof-v1/artifacts/graph-projection.export.json` - Redacted graph-projection export artifact.
- `docs/benchmarks/ragstudio-oss-proof-v1/artifacts/reranker-trace.export.json` - Redacted reranker-trace export artifact.

## Decisions Made

- Used escaped Unicode for the synthetic Arabic text so the JSON files remain ASCII on disk while still parsing into Arabic text.
- Used current artifact SHA-256 hashes now, because the exported artifacts exist in this plan and no Phase 2 tooling is needed to compute them.

## Deviations from Plan

None - plan executed exactly as written.

---

**Total deviations:** 0 auto-fixed.
**Impact on plan:** No scope creep.

## Issues Encountered

None.

## Verification

- PASS: `test -f docs/benchmarks/ragstudio-oss-proof-v1/manifest.json`
- PASS: `node -e 'for (const f of process.argv.slice(1)) JSON.parse(require("fs").readFileSync(f,"utf8"));' docs/benchmarks/ragstudio-oss-proof-v1/fixtures/*.json docs/benchmarks/ragstudio-oss-proof-v1/artifacts/*.json docs/benchmarks/ragstudio-oss-proof-v1/manifest.json`
- PASS: `rg "reference_unit_missing_expected_script|quality_action_policy|chunk_traces|reranker_traces|graph_projection_state" docs/benchmarks/ragstudio-oss-proof-v1`
- PASS: Manifest SHA-256 values match the current artifact files.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan `01-02` can now define JSON Schemas, the claims registry, and the claims matrix against a real packet root and artifact set. Screenshot signoff remains intentionally deferred to Plan `01-03`.

## Self-Check: PASSED

All planned tasks completed, all acceptance checks passed, and every exported artifact is linked from the manifest.

---
*Phase: 01-proof-contract-and-baseline-packet*
*Completed: 2026-05-14*
