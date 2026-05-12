---
phase: post-merge-ragstudio-review
reviewed: 2026-05-12T04:02:15Z
depth: standard
files_reviewed: 28
files_reviewed_list:
  - backend/src/ragstudio/db/engine.py
  - backend/src/ragstudio/db/models.py
  - backend/src/ragstudio/services/chunk_persistence_service.py
  - backend/src/ragstudio/services/chunk_service.py
  - backend/src/ragstudio/services/domain_metadata_quality_gate.py
  - backend/src/ragstudio/services/document_service.py
  - backend/src/ragstudio/services/graph_materialization_service.py
  - backend/src/ragstudio/services/graph_projection_runner.py
  - backend/src/ragstudio/services/graph_service.py
  - backend/src/ragstudio/services/hybrid_chunk_search.py
  - backend/src/ragstudio/services/index_job_runner.py
  - backend/src/ragstudio/services/index_lifecycle_service.py
  - backend/src/ragstudio/services/job_queue_service.py
  - backend/src/ragstudio/services/native_raganything_adapter.py
  - backend/src/ragstudio/services/query_service.py
  - backend/src/ragstudio/services/retrieval_orchestrator.py
  - backend/src/ragstudio/workers/index_worker.py
  - backend/tests/test_chunk_service_arabic_search.py
  - backend/tests/test_db_engine.py
  - backend/tests/test_domain_metadata_quality_gate.py
  - backend/tests/test_documents.py
  - backend/tests/test_durable_ingestion_stages.py
  - backend/tests/test_index_lifecycle_service.py
  - backend/tests/test_index_quality_gate.py
  - backend/tests/test_index_worker_recovery.py
  - backend/tests/test_job_queue_service.py
  - backend/tests/test_native_raganything_adapter.py
  - backend/tests/test_retrieval_orchestrator.py
findings:
  critical: 4
  warning: 2
  info: 0
  total: 6
status: issues_found
---

# Phase post-merge-ragstudio-review: Code Review Report

**Reviewed:** 2026-05-12T04:02:15Z
**Depth:** standard
**Files Reviewed:** 28
**Status:** issues_found

## Summary

Targeted post-merge review covered durable indexing jobs, runtime index lifecycle, graph projection/fallback graph handling, scoped retrieval orchestration, Arabic lexical/search quality gates, and the directly related tests. The current worktree already had tracked source changes before this review; this report evaluates that current state and only updates this review artifact.

I did not complete a whole-repository audit. Residual risk remains in untouched UI/API paths and broader runtime-provider code.

Tests run:

- `uv run pytest ...` was attempted but skipped because `uv` is not installed in this environment.
- `.venv/bin/python -m pytest backend/tests/test_job_queue_service.py backend/tests/test_db_engine.py backend/tests/test_native_raganything_adapter.py backend/tests/test_retrieval_orchestrator.py` -> 75 passed.
- `.venv/bin/python -m pytest backend/tests/test_durable_ingestion_stages.py backend/tests/test_index_worker_recovery.py backend/tests/test_index_lifecycle_service.py::test_lifecycle_preserves_runtime_index_when_strict_mineru_parse_fails backend/tests/test_index_lifecycle_service.py::test_graph_projection_runner_preserves_old_projection_when_replacement_skips backend/tests/test_documents.py::test_reindex_document_concurrent_requests_create_one_active_job` -> 9 passed.

## Critical Issues

### CR-01: [BLOCKER] Runtime index can be marked succeeded after indexing zero quality-approved chunks

**File:** `backend/src/ragstudio/services/index_lifecycle_service.py:209`

**Issue:** `enrich_runtime()` deletes the existing runtime index and returns `[]` when every parsed chunk is blocked by `quality_action_policy.index_vector=false`. The later count check accepts `runtime_chunk_count == expected_runtime_chunk_count == 0` and marks the runtime `IndexRecord` succeeded with `len(chunks)` at line 293. Query degradation then treats this document as runtime-ready, so selected-document queries can skip metadata fallback even though no vector/native chunks exist.

**Fix:**
```python
if chunks and not runtime_adapter_chunks:
    reason = "No chunks passed the runtime materialization quality gate."
    await self._mark_runtime_index_failed(document.id, profile.id, reason)
    projection_record = await self._mark_graph_projection_skipped(projection_record.id, reason)
    return IndexLifecycleResult(...)

await self._mark_runtime_index_succeeded(
    document.id,
    profile.id,
    len(runtime_adapter_chunks),
)
```

Add a regression where all chunks are quarantined and assert the index record is failed/degraded, graph projection is skipped, and `QueryService._index_degradation()` returns metadata fallback.

### CR-02: [BLOCKER] Exhausted durable jobs leave the document stuck in running state

**File:** `backend/src/ragstudio/services/job_queue_service.py:120`

**Issue:** `recover_expired_jobs()` marks a max-attempts `index_document` job failed at lines 137-143, but it never updates the associated `Document` row. The same gap exists in `mark_failed()`. A worker that dies repeatedly can leave `documents.status` and `indexing_stage` reporting running/progress while the durable job is terminally failed.

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

Cover both lease-exhaustion recovery and runner-level failure with tests that assert the `Document` row is terminally failed.

### CR-03: [BLOCKER] Existing PostgreSQL databases never receive the active-job uniqueness guard

**File:** `backend/src/ragstudio/db/engine.py:212`

**Issue:** `Job.__table_args__` defines `uq_active_index_document_job` for one active `index_document` job per document (`backend/src/ragstudio/db/models.py:189`), but `_ensure_job_runtime_indexes()` only creates non-unique claim/lease indexes. Existing Postgres installations initialized before this model change will not get the partial unique index, so concurrent reindex requests can still create duplicate ready/running jobs for the same document.

**Fix:**
```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_index_document_job
ON jobs (target_id)
WHERE type = 'index_document'
  AND status IN ('ready', 'running')
  AND target_id IS NOT NULL;
```

Before creating the index, resolve existing duplicate active rows deterministically. Extend `test_init_db_adds_durable_job_worker_columns` to inspect indexes and assert the partial unique index exists.

### CR-04: [BLOCKER] Deleting a document can race with an active indexing worker

**File:** `backend/src/ragstudio/services/document_service.py:143`

**Issue:** `delete_document()` deletes active `index_document` jobs, index records, the artifact, and the document without taking the document workflow advisory lock or rejecting a ready/running job. A worker that already claimed the job can continue with an in-memory `Job` and artifact path while deletion removes the database rows underneath it, leading to lost terminal status, stale graph/runtime writes, or failures after the user was told the document was deleted.

**Fix:**
```python
await self.lock_document_workflow(document_id)
if await self.active_index_job(document_id) is not None:
    raise ActiveIndexJobError("Document has an active indexing job")
```

If deletion during indexing must be supported, add an explicit cancel state and make workers observe cancellation before runtime/graph writes. Add a regression with a running leased job where delete returns conflict and leaves the document/job/artifact intact.

## Warnings

### WR-01: [WARNING] Relationship metadata fallback graph collapses nodes across documents

**File:** `backend/src/ragstudio/services/graph_service.py:137`

**Issue:** The fallback graph deduplicates nodes by raw `source`/`target` and edges by `source-target-type`. If two documents use the same relationship ids, the graph merges them and keeps the first chunk's `document_id` in properties. That breaks data isolation and produces incorrect fallback graph results when Neo4j projection is unavailable or pending.

**Fix:** Key fallback nodes and edges by `(document_id, source)` / `(document_id, target)` and include `document_id` in `edge_id`. Add a two-document test with identical relationship ids and assert four document-scoped nodes, not two merged nodes.

### WR-02: [WARNING] Native runtime sources can expose raw file paths

**File:** `backend/src/ragstudio/services/native_raganything_adapter.py:637`

**Issue:** `_native_sources_from_proxy()` forwards `row.get("file_path")` into `source_location` at line 661. Canonical chunk persistence scrubs path-like metadata, but native query responses can still expose runtime storage paths directly through retrieval sources.

**Fix:** Omit `file_path` from native source locations or replace it with a safe artifact/document reference such as basename plus document id. Add a native-adapter regression with an absolute path row and assert no absolute path appears in `sources`.

---

_Reviewed: 2026-05-12T04:02:15Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
