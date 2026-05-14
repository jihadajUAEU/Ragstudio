---
phase: 02-replay-and-export-tooling
plan: "02"
subsystem: cli-docs
tags:
  - proof.sh
  - cli
  - replay
  - export-manifest
requires:
  - 02-01
provides:
  - Fresh-checkout proof command
  - Human and compact JSON validation output
  - Static export manifest metadata helper
  - Replay and error recovery documentation
affects:
  - phase-02-replay-and-export-tooling
  - phase-03-ragstudio-site-import
tech-stack:
  added: []
  patterns:
    - Thin Bash wrapper over Python module
    - Strict JSON automation mode
    - Static fixture replay boundary
key-files:
  created:
    - scripts/proof.sh
    - backend/src/ragstudio/proof_packet/cli.py
    - docs/benchmarks/ragstudio-oss-proof-v1/docs/REPLAY.md
    - docs/benchmarks/ragstudio-oss-proof-v1/docs/ERRORS.md
  modified:
    - backend/src/ragstudio/proof_packet/manifest.py
    - backend/tests/test_proof_packet_validator.py
    - docs/benchmarks/ragstudio-oss-proof-v1/docs/QUICKSTART.md
requirements-completed:
  - VAL-01
  - VAL-04
  - VAL-05
  - DOCS-01
  - DOCS-02
  - DOCS-04
duration: 15 min
completed: 2026-05-14
---

# Phase 2 Plan 02: Proof Command And Replay Docs Summary

Added the public `./scripts/proof.sh` command, CLI output modes, static export
manifest helper, and proof replay documentation.

## Accomplishments

- Added executable `scripts/proof.sh` as a thin wrapper over `python -m ragstudio.proof_packet.cli`.
- Implemented `--packet`, `--json`, `--strict`, `--verbose`, and `--export-manifest` CLI behavior.
- Added compact JSON output for automation and readable human output for first-time evaluators.
- Added static export manifest metadata generation for packet hash, artifact hashes, source commit, validation status, and timestamps.
- Updated QUICKSTART and added REPLAY and ERRORS docs.

## Verification

- PASS: `./scripts/proof.sh`
- PASS: `./scripts/proof.sh --strict --json | .venv/bin/python -m json.tool >/dev/null`
- PASS: `.venv/bin/python -m pytest backend/tests/test_proof_packet_validator.py -q`
- PASS: `rg './scripts/proof.sh|--strict --json|PACKET_NOT_FOUND|HASH_MISMATCH|REDACTION_LEAK|static fixture' docs/benchmarks/ragstudio-oss-proof-v1/docs`

## Deviations

- The export manifest helper is exposed as `--export-manifest` for direct inspection, while keeping the primary CLI focused on validation.

## Self-Check: PASSED

The no-Docker proof replay path and automation JSON contract are implemented and tested.
