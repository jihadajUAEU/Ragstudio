---
phase: 02
slug: replay-and-export-tooling
status: complete
created: 2026-05-14
---

# Phase 2 Pattern Map: Replay and Export Tooling

## Implementation Style

Phase 2 should add a focused backend package under
`backend/src/ragstudio/proof_packet/`. This matches the repo's existing Python
3.12 backend layout while keeping proof validation independent from FastAPI,
database sessions, Docker, providers, and frontend runtime.

Use small modules with clear responsibilities:

- `models.py` for result, finding, summary, and artifact-result shapes.
- `errors.py` for stable error-code constants and recovery guidance.
- `manifest.py` for packet-root path resolution, JSON loading, SHA-256 hashing,
  and export-manifest helpers.
- `redaction.py` for fail-closed public-leak rules.
- `validator.py` for orchestrating schema, manifest, artifact, claim, screenshot,
  redaction, and metadata checks.
- `cli.py` for argument parsing and human/JSON output.

Prefer standard-library `pathlib`, `hashlib`, `json`, `dataclasses`, and
`argparse`, plus `jsonschema.Draft202012Validator` for canonical JSON Schema
2020-12 validation.

## Existing Code To Mirror

### Static Proof Contract Tests

`backend/tests/test_proof_packet_contract.py` is the closest source of truth. It
already checks:

- manifest path coverage and artifact hash verification;
- JSON Schema 2020-12 and strict schema files;
- proven, roadmap, and disabled claim honesty;
- screenshot signoff metadata;
- redaction/public-safety deny patterns;
- public docs boundaries.

Phase 2 should move this behavior into reusable validator APIs and add new tests
that call the validator instead of duplicating all validation logic in tests.

### Backend Package Conventions

Backend code lives in `backend/src/ragstudio/` with snake_case module names and
pytest coverage in `backend/tests/test_*.py`. Ruff uses a 100-character line
limit and selects `E`, `F`, `I`, `B`, `UP`, and `RUF` rules.

No Phase 2 validator code should import app/server modules, database models,
runtime providers, Docker helpers, or frontend code. The only packet input
should be an explicit packet root.

### Script Pattern

Developer shell entrypoints live under `scripts/`. `scripts/proof.sh` should be a
thin wrapper only:

- change to the repository root;
- prefer `.venv/bin/python` when present, otherwise use `python3`;
- set `PYTHONPATH=backend/src`;
- run `python -m ragstudio.proof_packet.cli "$@"`.

Avoid implementing validation logic in Bash.

## Public Packet Shape

The default packet root is:

`docs/benchmarks/ragstudio-oss-proof-v1/`

Important packet files:

- `manifest.json`
- `schemas/manifest.schema.json`
- `schemas/claim.schema.json`
- `schemas/artifact.schema.json`
- `schemas/screenshot-signoff.schema.json`
- `schemas/validation-result.schema.json`
- `claims/claims.registry.json`
- `claims/claims.matrix.md`
- `screenshots/signoff.json`
- `fixtures/*.json`
- `artifacts/*.json`
- `docs/QUICKSTART.md`
- `docs/REDACTION.md`
- `docs/COMPATIBILITY.md`

Phase 2 may add `docs/REPLAY.md` and `docs/ERRORS.md`.

## Validation Patterns

### Paths

Resolve all manifest-referenced paths relative to the supplied packet root.
Reject absolute paths and paths containing `..` before reading file contents.
Validation must not read outside the packet root.

### JSON And Schema

Use structured JSON parsing and `jsonschema.Draft202012Validator`. Report parse
and schema failures as structured findings with code, path, message, and recovery
text.

### Hashes

Recompute SHA-256 for every manifest artifact hash entry. Hash failures should
identify the exact artifact path and expected/actual mismatch.

### Claims

For `proven` claims, every evidence item must be public, redacted, and point at
a manifest artifact. `roadmap` and `disabled` claims must remain visible and
must not count as proven evidence.

### Redaction

Scan text-like `.json` and `.md` packet files for fail-closed public-leak
patterns: API keys, bearer tokens, common cloud/GitHub/Slack/Google tokens,
private hosts/IPs, localhost, local absolute paths, and `file://`. Screenshot
pixel contents remain manual signoff territory; Phase 2 validates signoff
metadata and hashes only.

### Output

Use `schemas/validation-result.schema.json` as the compact `--json` anchor.
Human output should summarize status, packet path, errors, warnings, and recovery
pointers without dumping every file by default. Verbose output may include
per-rule detail.

## Test Patterns

Add focused tests in `backend/tests/test_proof_packet_validator.py`:

- validate the real default packet;
- copy the packet to `tmp_path` and mutate one field/file per failure test;
- call Python APIs for validator behavior;
- call `scripts/proof.sh` through subprocess only for command/exit-code/output
  coverage;
- keep tests static-fixture only, with no Docker, providers, backend server, or
  secrets.

Recommended focused command:

```bash
.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py backend/tests/test_proof_packet_validator.py -q
```

## Plan Implications

Plan 01 should build the validator package and core tests.
Plan 02 should add the script, CLI output, export-manifest helper, and docs.
Plan 03 should broaden failure-path and strict-mode coverage, then harden any
edge cases found by those tests.
