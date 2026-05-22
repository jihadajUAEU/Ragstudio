# Proof Manifest Hash Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore strict proof-packet validation for the committed three-pillar retrieval architecture proof artifact.

**Architecture:** This is a proof metadata repair, not a runtime behavior change. The retrieval export artifact is already committed and redaction/schema checks pass; the manifest must record the artifact's current SHA-256 so the proof validator can verify packet integrity.

**Tech Stack:** JSON proof manifest, Python SHA-256 verification, `ragstudio.proof_packet.cli`, pytest, Ruff, Git.

---

## File Structure

- Modify: `docs/benchmarks/ragstudio-oss-proof-v1/manifest.json`
  - Responsibility: store the canonical SHA-256 hash for `artifacts/retrieval-run.export.json`.
- Reference only: `docs/benchmarks/ragstudio-oss-proof-v1/artifacts/retrieval-run.export.json`
  - Responsibility: committed proof artifact whose actual SHA-256 is `0b83f358b0146e21ecc6710edb8f4eedafda3577ee3cd9272bb66ff97fb2332a`.
- Create: `docs/superpowers/plans/2026-05-22-proof-manifest-hash-refresh.md`
  - Responsibility: record this execution-ready plan.

### Task 1: Refresh Retrieval Proof Artifact Hash

**Files:**
- Modify: `docs/benchmarks/ragstudio-oss-proof-v1/manifest.json:102-105`
- Reference: `docs/benchmarks/ragstudio-oss-proof-v1/artifacts/retrieval-run.export.json`

- [ ] **Step 1: Confirm the current retrieval artifact hash**

  Run:

  ```powershell
  @'
  import hashlib
  from pathlib import Path
  path = Path("docs/benchmarks/ragstudio-oss-proof-v1/artifacts/retrieval-run.export.json")
  print(hashlib.sha256(path.read_bytes()).hexdigest())
  '@ | python -
  ```

  Expected output:

  ```text
  0b83f358b0146e21ecc6710edb8f4eedafda3577ee3cd9272bb66ff97fb2332a
  ```

- [ ] **Step 2: Update the manifest hash**

  Change `docs/benchmarks/ragstudio-oss-proof-v1/manifest.json` so this block:

  ```json
  "artifacts/retrieval-run.export.json": {
    "algorithm": "sha256",
    "value": "1d7ef7fb0322997e057116ebecf929b9f6cb5272bda2073c56a14d67f9b1019e",
    "redaction_status": "passed"
  }
  ```

  becomes:

  ```json
  "artifacts/retrieval-run.export.json": {
    "algorithm": "sha256",
    "value": "0b83f358b0146e21ecc6710edb8f4eedafda3577ee3cd9272bb66ff97fb2332a",
    "redaction_status": "passed"
  }
  ```

- [ ] **Step 3: Run strict proof validation**

  Run:

  ```powershell
  $env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
  uv run python -m ragstudio.proof_packet.cli --packet docs/benchmarks/ragstudio-oss-proof-v1 --strict --json
  ```

  Expected result:

  ```json
  "status": "passed"
  ```

  Expected summary values:

  ```json
  "claims_valid": true,
  "hashes_valid": true,
  "redaction_valid": true,
  "schema_valid": true
  ```

- [ ] **Step 4: Re-run focused architecture validation**

  Run:

  ```powershell
  $env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
  uv run pytest backend/tests/test_domain_classifier.py backend/tests/test_domain_query_expansion_service.py backend/tests/test_domain_profile_registry.py backend/tests/test_retrieval_route_input.py backend/tests/test_retrieval_route_planner.py backend/tests/test_layout_neighbor_service.py backend/tests/test_context_window_service.py backend/tests/test_context_assembly_service.py backend/tests/test_retrieval_orchestrator.py backend/tests/test_vector_retrieval_service.py backend/tests/test_vector_candidate_repository.py backend/tests/test_native_raganything_adapter.py -q
  ```

  Expected output:

  ```text
  170 passed
  ```

- [ ] **Step 5: Run lint**

  Run:

  ```powershell
  uv run ruff check backend/src/ragstudio backend/tests
  ```

  Expected output:

  ```text
  All checks passed!
  ```

- [ ] **Step 6: Commit and push**

  Run:

  ```powershell
  git add docs/benchmarks/ragstudio-oss-proof-v1/manifest.json docs/superpowers/plans/2026-05-22-proof-manifest-hash-refresh.md
  git commit -m "docs: refresh retrieval proof artifact hash"
  git push origin main
  ```

  Expected result:

  ```text
  main pushed to origin with strict proof validation restored.
  ```

## Self-Review

- Spec coverage: The plan covers the stale retrieval proof hash, strict proof validation, focused architecture tests, lint, commit, and push.
- Placeholder scan: No placeholder steps are present.
- Type consistency: No runtime type or API changes are introduced.
