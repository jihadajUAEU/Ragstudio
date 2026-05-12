---
phase: follow-up-ragstudio-review
reviewed: 2026-05-12T04:58:25Z
depth: standard
files_reviewed: 34
files_reviewed_list:
  - backend/src/ragstudio/db/engine.py
  - backend/src/ragstudio/db/models.py
  - backend/src/ragstudio/schemas/chunks.py
  - backend/src/ragstudio/schemas/common.py
  - backend/src/ragstudio/services/chunk_persistence_service.py
  - backend/src/ragstudio/services/chunk_service.py
  - backend/src/ragstudio/services/domain_metadata_quality_gate.py
  - backend/src/ragstudio/services/document_service.py
  - backend/src/ragstudio/services/graph_service.py
  - backend/src/ragstudio/services/hybrid_chunk_search.py
  - backend/src/ragstudio/services/index_artifact_cleanup.py
  - backend/src/ragstudio/services/index_job_runner.py
  - backend/src/ragstudio/services/index_lifecycle_service.py
  - backend/src/ragstudio/services/index_quality_gate.py
  - backend/src/ragstudio/services/index_stage_scheduler.py
  - backend/src/ragstudio/services/job_queue_service.py
  - backend/src/ragstudio/services/job_worker.py
  - backend/src/ragstudio/services/native_raganything_adapter.py
  - backend/src/ragstudio/services/query_service.py
  - backend/src/ragstudio/services/retrieval_orchestrator.py
  - backend/src/ragstudio/workers/index_worker.py
  - backend/tests/test_chunk_persistence_service.py
  - backend/tests/test_hybrid_chunk_search_arabic.py
  - backend/tests/test_index_lifecycle_service.py
  - backend/tests/test_job_queue_service.py
  - docs/superpowers/specs/2026-05-12-metadata-aware-index-quality-gate.md
  - e2e/studio.spec.ts
  - frontend/src/components/app-shell.tsx
  - frontend/src/features/dashboard/dashboard-page.tsx
  - frontend/src/features/graph/graph-page.tsx
  - frontend/src/features/settings/settings-page.tsx
  - frontend/tests/app-shell.test.tsx
  - frontend/tests/dashboard-page.test.tsx
  - frontend/tests/graph-page.test.tsx
  - frontend/tests/settings-page.test.tsx
findings:
  critical: 5
  warning: 1
  info: 0
  total: 6
status: issues_found
---

# Phase follow-up-ragstudio-review: Code Review Report

**Reviewed:** 2026-05-12T04:58:25Z
**Depth:** standard
**Files Reviewed:** 34
**Status:** issues_found

## Summary

This is a follow-up review of the change set originally presented as a dirty worktree at `dbbf779`. During review the worktree became clean at `df68035` (`feat: enhance dashboard and settings functionality`), so this report reviews the same changes as `dbbf779..HEAD`. I did not edit source files; only this review artifact was updated.

The previous blocker around marking runtime indexing succeeded with zero quality-approved chunks appears fixed: `IndexLifecycleService` now fails the runtime `IndexRecord`, skips graph projection, and the new backend tests cover both preparsed and native cleanup paths. Arabic exact-search blocking for quarantined chunks is also covered.

Remaining blockers are mostly unchanged from the prior report: durable job/document terminal state, existing-database active-job uniqueness, document delete races, and native file path leakage are still present. I also found an incomplete runtime cleanup path in the new lifecycle change.

Tests run:

- `.venv/bin/python -m pytest backend/tests/test_chunk_persistence_service.py::test_chunk_output_does_not_rehydrate_blocked_exact_arabic_metadata backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_index_lifecycle_service.py::test_lifecycle_marks_runtime_failed_when_all_references_are_quarantined backend/tests/test_index_lifecycle_service.py::test_lifecycle_cleans_nonpreparsed_native_index_when_quality_blocks_all backend/tests/test_job_queue_service.py::test_recover_expired_running_job_fails_after_max_attempts` -> 7 passed.
- `npm test -- --run tests/dashboard-page.test.tsx tests/graph-page.test.tsx tests/settings-page.test.tsx tests/app-shell.test.tsx` -> 4 files / 17 tests passed.
- `npm run build` -> passed. Vite emitted only the existing large chunk warning.

Playwright e2e was not run because no dev server was started for this read-only follow-up review.

## Critical Issues

### CR-01: [BLOCKER] Runtime failure paths can leave partial native indexes for failed documents

**File:** `backend/src/ragstudio/services/index_lifecycle_service.py:249`

**Issue:** The new cleanup only runs in some failure paths. If the strict/preparsed runtime branch writes native chunks and then canonical persistence fails, the catch block only calls cleanup when `runtime_chunks is not None`, which is false for the preparsed path. If the runtime branch itself is reported as `skipped`, the branch at line 257 marks the `IndexRecord` failed but never deletes possible partial native writes. A failed document can therefore leave native vector data behind and later surface through unscoped native retrieval.

**Fix:**
```python
async def cleanup_runtime_index_best_effort() -> None:
    try:
        await runtime.delete_document_index(document.id)
    except Exception:
        logger.exception("Failed to clean runtime index for %s", document.id)

try:
    branch_results = await IndexStageScheduler(max_parallel_branches=2).run(...)
except Exception:
    await cleanup_runtime_index_best_effort()
    await self._mark_graph_projection_skipped(projection_record.id, reason)
    raise

if runtime_result.status == "skipped":
    await cleanup_runtime_index_best_effort()
    await self._mark_runtime_index_failed(document.id, profile.id, reason)
```

Add regressions for a preparsed runtime write followed by canonical persistence failure, and for a runtime branch exception after a partial write.

### CR-02: [BLOCKER] Exhausted durable jobs still leave the document non-terminal

**File:** `backend/src/ragstudio/services/job_queue_service.py:137`

**Issue:** `recover_expired_jobs()` marks an exhausted `index_document` job failed, but it never updates the matching `Document` row. `mark_failed()` has the same gap at line 108. The new targeted test still only asserts the job state, so a document can remain `running` after the durable job is terminally failed.

**Fix:**
```python
if job.type == "index_document" and job.target_id:
    document = await self.session.get(Document, job.target_id, with_for_update=True)
    if document is not None:
        document.status = StageStatus.FAILED.value
        document.indexing_stage = {
            "stage": "failed",
            "status": "failed",
            "detail": log,
        }
```

Cover both max-attempt recovery and worker-level `mark_failed()` with assertions on `Document.status`.

### CR-03: [BLOCKER] Existing PostgreSQL databases still do not receive the active-job uniqueness guard

**File:** `backend/src/ragstudio/db/engine.py:212`

**Issue:** The model defines partial unique index `uq_active_index_document_job`, but `_ensure_job_runtime_indexes()` only creates non-unique claim/lease indexes for existing databases. A database initialized before the model change can still enqueue duplicate ready/running `index_document` jobs for the same document.

**Fix:**
```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_index_document_job
ON jobs (target_id)
WHERE type = 'index_document'
  AND status IN ('ready', 'running')
  AND target_id IS NOT NULL;
```

Resolve duplicate active rows before creating the index, and extend the DB initialization test to assert the partial unique index exists.

### CR-04: [BLOCKER] Document deletion still races active indexing workers

**File:** `backend/src/ragstudio/services/document_service.py:143`

**Issue:** `delete_document()` deletes graph rows, jobs, index records, the artifact, and the document without taking the document workflow lock or rejecting a ready/running indexing job. A worker that already claimed the job can keep writing runtime/graph state after the user was told the document was deleted.

**Fix:**
```python
await self.lock_document_workflow(document_id)
if await self.active_index_job(document_id) is not None:
    raise ActiveIndexJobError("Document has an active indexing job")
```

If delete-during-indexing is required, add an explicit cancel state that workers observe before runtime and graph writes.

### CR-05: [BLOCKER] Native scoped retrieval still exposes raw file paths

**File:** `backend/src/ragstudio/services/native_raganything_adapter.py:657`

**Issue:** `_native_sources_from_proxy()` forwards `row.get("file_path")` into `source_location`. Canonical chunk persistence scrubs path-like metadata, but native scoped query responses can still leak server filesystem paths to API/UI consumers.

**Fix:**
```python
source_location = {
    key: value
    for key, value in row.items()
    if key in {"page", "page_idx", "reference"} and value is not None
}
```

Add a native-adapter regression with an absolute path row and assert no absolute path appears in `sources`.

## Warnings

### WR-01: [WARNING] Relationship metadata fallback graph still collapses nodes across documents

**File:** `backend/src/ragstudio/services/graph_service.py:137`

**Issue:** The fallback graph deduplicates nodes by raw `source`/`target` and edges by `source-target-type`. Two documents with the same relationship ids merge into one node/edge set and keep whichever document was seen first, so fallback graph data is not document-isolated.

**Fix:** Key fallback nodes and edges by `(document_id, source)` / `(document_id, target)` and include `document_id` in `edge_id`. Add a two-document regression with identical relationship ids and assert document-scoped nodes are not merged.

---

_Reviewed: 2026-05-12T04:58:25Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
