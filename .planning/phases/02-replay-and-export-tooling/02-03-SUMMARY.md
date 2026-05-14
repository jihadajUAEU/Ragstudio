---
phase: 02-replay-and-export-tooling
plan: "03"
subsystem: tests
tags:
  - failure-paths
  - strict-mode
  - cli-contract
  - docs-contract
requires:
  - 02-01
  - 02-02
provides:
  - Representative validator failure-path coverage
  - CLI exit-code and JSON output coverage
  - Error documentation coverage against exported code set
  - Green Phase 2 validation strategy
affects:
  - phase-02-replay-and-export-tooling
  - phase-03-ragstudio-site-import
tech-stack:
  added: []
  patterns:
    - Temporary packet copy mutation tests
    - Strict-mode warning failure tests
    - Docs/code error-code cross-check
key-files:
  created: []
  modified:
    - backend/tests/test_proof_packet_validator.py
    - backend/src/ragstudio/proof_packet/cli.py
    - backend/src/ragstudio/proof_packet/errors.py
    - backend/src/ragstudio/proof_packet/manifest.py
    - backend/src/ragstudio/proof_packet/redaction.py
    - backend/src/ragstudio/proof_packet/validator.py
    - docs/benchmarks/ragstudio-oss-proof-v1/docs/ERRORS.md
    - .planning/phases/02-replay-and-export-tooling/02-VALIDATION.md
requirements-completed:
  - VAL-01
  - VAL-02
  - VAL-03
  - VAL-04
  - VAL-05
  - VAL-07
  - DOCS-04
duration: 12 min
completed: 2026-05-14
---

# Phase 2 Plan 03: Failure-Path Hardening Summary

Hardened the validator and CLI with temp-packet mutation coverage and final docs
alignment.

## Accomplishments

- Added tests for `PACKET_NOT_FOUND`, `JSON_PARSE_ERROR`, `SCHEMA_INVALID`, `MANIFEST_PATH_MISSING`, `HASH_MISMATCH`, `REDACTION_LEAK`, `CLAIM_EVIDENCE_INVALID`, `CLAIM_COUNTS_MISMATCH`, `SCREENSHOT_SIGNOFF_INVALID`, `STALE_SOURCE_COMMIT`, and `EXPORT_MANIFEST_INVALID`.
- Added CLI subprocess coverage for no-arg success, `--packet`, compact JSON, invalid packet failure, strict mode, and verbose recovery output.
- Added docs/code coverage that verifies ERRORS.md documents every exported stable error code.
- Marked Phase 2 validation strategy complete and Nyquist-compliant.

## Verification

- PASS: `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py backend/tests/test_proof_packet_validator.py -q`
- PASS: `./scripts/proof.sh`
- PASS: `./scripts/proof.sh --strict --json | .venv/bin/python -m json.tool >/dev/null`
- PASS: `.venv/bin/python -m ruff check backend/src/ragstudio/proof_packet backend/tests/test_proof_packet_validator.py backend/tests/test_proof_packet_contract.py`
- PASS: `rg 'PACKET_NOT_FOUND|JSON_PARSE_ERROR|SCHEMA_INVALID|MANIFEST_PATH_MISSING|HASH_MISMATCH|REDACTION_LEAK|CLAIM_EVIDENCE_INVALID|CLAIM_COUNTS_MISMATCH|SCREENSHOT_SIGNOFF_INVALID|STALE_SOURCE_COMMIT|EXPORT_MANIFEST_INVALID' docs/benchmarks/ragstudio-oss-proof-v1/docs/ERRORS.md`

## Deviations

- None affecting scope. The final implementation keeps site import validation deferred to Phase 3.

## Self-Check: PASSED

Success, failure, strict, verbose, JSON, and docs contracts are covered and green.
