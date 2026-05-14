---
phase: 02
slug: replay-and-export-tooling
status: complete
researched_at: 2026-05-14
requirements:
  - VAL-01
  - VAL-02
  - VAL-03
  - VAL-04
  - VAL-05
  - VAL-07
  - DOCS-01
  - DOCS-02
  - DOCS-04
---

# Phase 2 Research: Replay and Export Tooling

## Objective

Plan a fresh-checkout proof validator and `./scripts/proof.sh` path for
`docs/benchmarks/ragstudio-oss-proof-v1/`. The implementation must validate the
Phase 1 static proof packet without Docker, secrets, live providers, a running
backend, or private files.

## Key Findings

### Use Python Module Plus Thin Bash Wrapper

The repo already uses Python 3.12 for backend code and pytest for backend tests.
Phase 2 should add a small package under `backend/src/ragstudio/proof_packet/`
and expose it through `python -m ragstudio.proof_packet.cli` or an equivalent
module entrypoint. `scripts/proof.sh` should only:

- `cd` to the repository root,
- choose an available Python interpreter, preferring `.venv/bin/python` when it
  exists,
- set `PYTHONPATH=backend/src` for fresh checkouts,
- pass arguments through to the Python module.

This keeps the user-facing command simple while avoiding JSON/schema/hash logic
in Bash.

### Reuse Existing Proof Contract Coverage

`backend/tests/test_proof_packet_contract.py` already captures the important
Phase 1 invariants:

- manifest path coverage,
- artifact hash verification,
- schema strictness,
- claim count/status honesty,
- proven-claim evidence requirements,
- screenshot signoff,
- redaction/public-safety pattern checks,
- docs/compatibility boundaries.

Phase 2 should convert these test-only assertions into reusable validator
functions, then update the tests to exercise the validator rather than duplicate
the validator logic.

### JSON Schema Validation Dependency

The current dependencies include Pydantic but do not include `jsonschema` or
`referencing`. Phase 2 needs JSON Schema 2020-12 validation for packet schemas.
There are two viable approaches:

1. Add `jsonschema>=4` to backend/root dependencies and use
   `jsonschema.Draft202012Validator`.
2. Implement only bespoke structural checks.

Use option 1. The phase requirement explicitly calls for canonical JSON Schema
2020-12 validation. A maintained library is safer and clearer than recreating
schema semantics.

### Output Contract Should Follow `validation-result.schema.json`

The packet already contains
`docs/benchmarks/ragstudio-oss-proof-v1/schemas/validation-result.schema.json`.
Use it as the compatibility anchor for `--json` output, with any minimal
backward-compatible extensions added deliberately if implementation needs them.

The compact result should include:

- `validation_id`,
- `packet_id`,
- `status` (`passed`, `failed`, or `blocked`),
- `validated_at`,
- `validator_version`,
- `summary` booleans,
- `errors`,
- `warnings`,
- `artifact_results`.

Verbose output can include additional implementation-side detail, but compact
`--json` should stay stable for Phase 3 import.

### Error Code Families

Structured errors should be stable enough for docs and future site import. A
small code family is enough for Phase 2:

- `PACKET_NOT_FOUND`
- `JSON_PARSE_ERROR`
- `SCHEMA_INVALID`
- `MANIFEST_PATH_MISSING`
- `HASH_MISMATCH`
- `REDACTION_LEAK`
- `CLAIM_EVIDENCE_INVALID`
- `CLAIM_COUNTS_MISMATCH`
- `SCREENSHOT_SIGNOFF_INVALID`
- `STALE_SOURCE_COMMIT`
- `EXPORT_MANIFEST_INVALID`

Every error should include a `path` and recovery text suitable for
`docs/ERRORS.md`.

### Redaction Checks Must Be Fail-Closed

Phase 1 locked the public-safety list. Phase 2 should enforce it directly:

- API-key patterns,
- bearer tokens,
- common cloud/GitHub/Slack/Google token patterns,
- private hosts and private IP ranges,
- localhost and `file://`,
- local absolute paths such as `/Users/...`, `/home/...`, and `C:\Users\...`,
- unpublished model endpoint hints if they appear as private host patterns.

The existing Phase 1 test intentionally scans text-like files only (`.json`,
`.md`). Phase 2 should do the same for initial validation and rely on screenshot
signoff for image contents. Screenshots are validated through metadata and hash
coverage, not OCR.

### Export Manifest Boundary

Phase 2 requirements include export manifest recording (`VAL-05`). Since the
baseline packet already has `manifest.json`, the practical Phase 2 boundary is:

- validate current manifest completeness and hash coverage;
- add a local export/manifest-generation helper that can recompute packet hashes
  and write or verify manifest status for future packets;
- keep live capture optional/out of scope.

The helper should not depend on providers or a running backend. It can operate
on static packet roots.

## Recommended Implementation Shape

### Package Layout

```text
backend/src/ragstudio/proof_packet/
  __init__.py
  cli.py
  errors.py
  models.py
  redaction.py
  validator.py
  manifest.py
```

- `models.py`: dataclasses or Pydantic models for findings, summary, artifact
  results, and validation result.
- `errors.py`: stable code constants and recovery strings.
- `redaction.py`: public-leak regex rules and scan helpers.
- `manifest.py`: load JSON, resolve paths, hash files, export manifest helpers.
- `validator.py`: orchestration of schema/hash/redaction/claims/screenshot
  validation.
- `cli.py`: argument parsing and output formatting.

### Script Shape

`scripts/proof.sh` should support:

- no args: validate `docs/benchmarks/ragstudio-oss-proof-v1/` with readable
  output;
- `--packet <path>`: validate another packet root;
- `--json`: compact machine-readable result;
- `--strict`: warnings become failures;
- `--verbose`: detailed diagnostics for humans or debugging.

Recommended automation command:

```bash
./scripts/proof.sh --strict --json
```

### Documentation Shape

Phase 2 should update or add:

- `docs/benchmarks/ragstudio-oss-proof-v1/docs/QUICKSTART.md` with the
  2-5 minute no-arg command path;
- `docs/benchmarks/ragstudio-oss-proof-v1/docs/REPLAY.md` explaining static
  fixture validation and explicitly labeling live capture/export as optional or
  future;
- `docs/benchmarks/ragstudio-oss-proof-v1/docs/ERRORS.md` mapping error codes to
  recovery guidance.

## Validation Architecture

### Test Infrastructure

- Framework: pytest.
- Existing fast command:
  `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py -q`
- Phase 2 focused command should become:
  `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py backend/tests/test_proof_packet_validator.py -q`
- Full project validation remains `scripts/test-all.sh`, but that command is
  Docker-heavy and is not part of the first-time proof path.

### Required Test Coverage

1. Happy path: default packet validates successfully through Python API.
2. CLI happy path: `./scripts/proof.sh` exits 0 and prints readable pass summary.
3. JSON output: `./scripts/proof.sh --json` parses and conforms to the validation
   result shape.
4. Strict mode: a warning fixture fails when `--strict` is set.
5. Missing artifact: validator reports `MANIFEST_PATH_MISSING`.
6. Hash mismatch: validator reports `HASH_MISMATCH`.
7. Schema invalid: validator reports `SCHEMA_INVALID`.
8. Redaction leak: validator reports `REDACTION_LEAK`.
9. Claim evidence invalid: proven claim without valid public artifact evidence
   fails.
10. Export manifest helper: recomputes hashes/source metadata and records
    validation status without live providers.

### Nyquist Mapping

- `VAL-01`: CLI no-arg proof path and no Docker/provider/backend dependencies.
- `VAL-02`: schema, missing path, hash, stale metadata tests.
- `VAL-03`: redaction leak tests.
- `VAL-04`: readable output and compact JSON output tests.
- `VAL-05`: manifest/export helper tests.
- `VAL-07`: success and representative failure-path tests.
- `DOCS-01`: QUICKSTART command and 2-5 minute language check.
- `DOCS-02`: REPLAY static-fixture/live-capture boundary check.
- `DOCS-04`: ERRORS code/recovery table check.

## Risks And Landmines

- Avoid making `./scripts/proof.sh` depend on Docker, Postgres, Neo4j, frontend
  build, provider env vars, or a running backend.
- Avoid hardcoding only the current default packet path inside validator logic;
  the CLI default can use that path, but validator APIs must accept a packet
  root.
- Avoid duplicating validation behavior in tests. Tests should call validator
  APIs and mutate temporary packet copies for failure cases.
- Avoid over-expanding into Phase 3 import or Phase 4 viewer work.
- Treat screenshot contents as manual-signoff territory unless a later phase adds
  OCR/image scanning; Phase 2 can verify signoff metadata and hashes.

## Planning Implications

Three executable plan slices fit the roadmap:

1. Core validator package: schema/path/hash/redaction/claim/signoff validation
   and result models.
2. CLI/export/docs: `scripts/proof.sh`, compact JSON output, readable summary,
   export manifest helper, QUICKSTART/REPLAY/ERRORS docs.
3. Failure-path tests and hardening: representative temp-packet failures,
   strict-mode behavior, docs assertions, and command-level tests.

Each plan must include a `<threat_model>` block because security enforcement is
enabled.

