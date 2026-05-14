---
phase: 02
slug: replay-and-export-tooling
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-14
---

# Phase 02 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x |
| **Config file** | `pyproject.toml`, `backend/pyproject.toml` |
| **Quick run command** | `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py backend/tests/test_proof_packet_validator.py -q` |
| **Full suite command** | `scripts/test-all.sh` |
| **Estimated runtime** | ~1-3 seconds for focused proof-packet tests |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py backend/tests/test_proof_packet_validator.py -q`
- **After every plan wave:** Run the focused proof-packet tests plus `.venv/bin/python -m ruff check backend/src/ragstudio/proof_packet backend/tests/test_proof_packet_validator.py`
- **Before `$gsd-verify-work`:** Focused proof-packet tests must be green; run `scripts/test-all.sh` when Docker services are available.
- **Max feedback latency:** ~3 seconds for the focused proof-packet tests.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | VAL-02 | T-02-01 / T-02-02 | Invalid schemas, missing paths, broken hashes, and stale/invalid packet metadata produce structured failures. | unit/contract | `.venv/bin/python -m pytest backend/tests/test_proof_packet_validator.py -q` | W0 | pending |
| 02-01-02 | 01 | 1 | VAL-03 | T-02-03 | Public-leak patterns fail closed with `REDACTION_LEAK`. | unit/contract | `.venv/bin/python -m pytest backend/tests/test_proof_packet_validator.py -q` | W0 | pending |
| 02-01-03 | 01 | 1 | VAL-04 | T-02-04 | Validation result carries stable error/warning codes and summary booleans. | unit/contract | `.venv/bin/python -m pytest backend/tests/test_proof_packet_validator.py -q` | W0 | pending |
| 02-02-01 | 02 | 1 | VAL-01 | T-02-05 | `./scripts/proof.sh` validates default packet without Docker, secrets, live providers, backend, or private files. | CLI | `.venv/bin/python -m pytest backend/tests/test_proof_packet_validator.py -q` | W0 | pending |
| 02-02-02 | 02 | 1 | VAL-04 | T-02-04 | `--json` emits compact machine-readable output; verbose mode carries detailed diagnostics. | CLI | `.venv/bin/python -m pytest backend/tests/test_proof_packet_validator.py -q` | W0 | pending |
| 02-02-03 | 02 | 1 | VAL-05 | T-02-06 | Export manifest helper records source commit/tag, packet hash, artifact hashes, validation status, and timestamps. | unit/contract | `.venv/bin/python -m pytest backend/tests/test_proof_packet_validator.py -q` | W0 | pending |
| 02-02-04 | 02 | 1 | DOCS-01, DOCS-02, DOCS-04 | T-02-07 | QUICKSTART, REPLAY, and ERRORS docs describe command path, static-fixture boundary, and error recovery. | docs/assertion | `.venv/bin/python -m pytest backend/tests/test_proof_packet_validator.py -q` | W0 | pending |
| 02-03-01 | 03 | 1 | VAL-07 | T-02-01 / T-02-03 / T-02-05 | Success and common failure paths are covered with temp packet fixtures and strict mode behavior. | unit/CLI | `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py backend/tests/test_proof_packet_validator.py -q` | W0 | pending |

*Status: pending - green - red - flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_proof_packet_validator.py` - success path and representative schema/hash/redaction/claim/CLI failure-path tests.
- [ ] `backend/src/ragstudio/proof_packet/` - reusable validator package that tests can call.
- [ ] `scripts/proof.sh` - command entrypoint used by CLI tests.

---

## Manual-Only Verifications

All Phase 2 behaviors should have automated verification. Screenshot image contents remain governed by Phase 1 human signoff metadata and are validated here through signoff/hash checks only.

---

## Validation Sign-Off

- [ ] All tasks have automated verification or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 3s for focused proof-packet tests
- [ ] `nyquist_compliant: true` set in frontmatter after implementation

**Approval:** pending
