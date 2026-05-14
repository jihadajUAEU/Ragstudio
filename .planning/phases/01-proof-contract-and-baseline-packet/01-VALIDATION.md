---
phase: 01
slug: proof-contract-and-baseline-packet
status: verified
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-14
---

# Phase 01 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x |
| **Config file** | `pyproject.toml`, `backend/pyproject.toml` |
| **Quick run command** | `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py -q` |
| **Full suite command** | `scripts/test-all.sh` |
| **Estimated runtime** | ~1 second for proof-packet contract tests |

---

## Sampling Rate

- **After every proof-packet contract change:** Run `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py -q`
- **After every plan wave:** Run `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py -q`
- **Before `$gsd-verify-work`:** Run the quick proof-packet contract test; run `scripts/test-all.sh` when Docker services are available.
- **Max feedback latency:** ~1 second for the Phase 01 contract test.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | PROOF-01 | T-01-03 | Packet root exposes schemas, fixtures, artifacts, screenshots, docs, claims, and manifest-linked paths. | contract | `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py -q` | yes | green |
| 01-01-02 | 01 | 1 | PROOF-02 | T-01-01 | Synthetic corpus and fixtures include required reference-heavy evidence shapes without private corpus data. | contract | `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py -q` | yes | green |
| 01-02-01 | 02 | 1 | PROOF-03 | T-01-05 | JSON Schema files use 2020-12, required fields, and strict `additionalProperties: false` boundaries. | contract | `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py -q` | yes | green |
| 01-02-02 | 02 | 1 | PROOF-04 | T-01-06 | Claim registry records statuses, source metadata, evidence links, code paths, artifact paths, and screenshot arrays. | contract | `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py -q` | yes | green |
| 01-02-03 | 02 | 1 | PROOF-05 | T-01-06 | Every `proven` claim has public redacted artifact evidence and an explanation. | contract | `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py -q` | yes | green |
| 01-02-04 | 02 | 1 | PROOF-06 | T-01-06 | `roadmap` and `disabled` claims remain visible with missing evidence, planned proof path, disabled reason, or requirements to prove. | contract | `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py -q` | yes | green |
| 01-03-01 | 03 | 1 | DOCS-03 | T-01-08 | Claims docs explain `proven`, `roadmap`, and `disabled` statuses and public evidence boundaries. | contract | `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py -q` | yes | green |
| 01-03-02 | 03 | 1 | DOCS-05 | T-01-05 | Compatibility docs record JSON Schema 2020-12, packet version, Docker-free inspection, and secret-free public boundaries. | contract | `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py -q` | yes | green |
| 01-03-03 | 03 | 1 | PROOF-01, PROOF-04, PROOF-06 | T-01-07 | Screenshot signoff is present, approved, hash-covered by the manifest, and not required for proven claims. | contract + human checkpoint | `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py -q` | yes | green |

*Status: pending - green - red - flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Human visual screenshot approval | PROOF-01, DOCS-03 | Image contents cannot be fully proven by text-only contract tests. | Confirm `screenshots/signoff.json` records reviewer, review time, `safe_to_publish: true`, and approved checks; visually inspect `screenshots/documents-page-desktop-empty-state.png` before public release. |

---

## Automated Coverage Summary

| Metric | Count |
|--------|-------|
| Requirements audited | 8 |
| Automated coverage | 8 |
| Manual-only behaviors | 1 |
| Gaps remaining | 0 |

## Validation Audit 2026-05-14

| Metric | Count |
|--------|-------|
| Gaps found | 8 |
| Resolved | 8 |
| Escalated | 0 |

Generated validation coverage:

- `backend/tests/test_proof_packet_contract.py`

Commands run:

- `.venv/bin/python -m ruff check backend/tests/test_proof_packet_contract.py`
- `.venv/bin/python -m pytest backend/tests/test_proof_packet_contract.py -q`

---

## Validation Sign-Off

- [x] All tasks have automated verification or documented manual-only boundaries
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all missing references
- [x] No watch-mode flags
- [x] Feedback latency < 2 seconds for the focused proof-packet contract test
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-05-14
