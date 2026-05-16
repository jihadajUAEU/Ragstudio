---
status: investigating
trigger: "Graph page/API reports `Graph projection is not ready. Latest graph projection is pending` after documents finish indexing."
created: 2026-05-15T19:53:35Z
updated: 2026-05-15T20:00:30Z
---

## Current Focus
<!-- OVERWRITE on each update - reflects NOW -->

hypothesis: Confirmed. Index jobs were being persisted as succeeded while their graph projection record was still pending, so the worker lease check later failed and rolled back graph materialization.
test: Added `test_index_job_runner_materializes_pending_projection_before_succeeding_job`.
expecting: The test should fail before the fix with `JobLeaseLostError`, then pass after keeping the job running until graph materialization finishes.
next_action: Complete final user report; no further live repair needed.

## Symptoms
<!-- Written during gathering, then IMMUTABLE -->

expected: A completed indexed document should have a non-pending graph projection record, or a completed job should explicitly report graph materialization failed/skipped.
actual: `/api/graph` returns a relationship-metadata fallback warning because the latest graph projection is pending.
errors: `Graph projection is not ready; showing relationship metadata fallback graph. Latest graph projection is pending.`
reproduction: In the live local Ragstudio stack, open Graph or call `/api/graph` after recent document indexing completes.
started: Observed after recent document reindexing and graph enrichment work.

## Eliminated
<!-- APPEND only - prevents re-investigating -->

## Evidence
<!-- APPEND only - facts discovered -->

- timestamp: 2026-05-15T19:53:35Z
  checked: Live `/api/diagnostics`, `/api/graph`, `graph_projection_records`, `jobs`, and worker logs.
  found: Diagnostics reports `graph_projection: pending`; all graph projection records are pending with 0 nodes and 0 edges; succeeded index jobs still store `graph_materialization.status=pending`; worker logs show `JobLeaseLostError` after graph-enrichment jobs.
  implication: The graph warning is not a frontend display issue. The durable graph projection never completed even though index jobs were marked succeeded.
- timestamp: 2026-05-15T19:58:30Z
  checked: Regression test around normal `IndexJobRunner` graph materialization with an active worker lease.
  found: The new test failed before the fix with `JobLeaseLostError`, then passed after moving `document.status/job.status=succeeded` until after graph materialization and final lease validation.
  implication: The root cause is the normal index-job terminal-state ordering, not Neo4j connectivity or graph rendering.
- timestamp: 2026-05-15T20:00:30Z
  checked: Live backend/worker restart, manual graph rematerialization calls, diagnostics, graph API, and Compose health.
  found: All four pending document projections were replayed successfully; diagnostics now reports `graph_projection=succeeded` with no warnings; `/api/graph` returns 500 nodes and 1000 edges with no fallback detail; all Compose services are healthy.
  implication: The current user-visible graph warning is resolved in the live stack.

## Resolution
<!-- OVERWRITE as understanding evolves -->

root_cause: `DocumentService._index_document_for_job()` committed a succeeded job before graph materialization finished; later lease validation requires the DB job row to still be running, so it raised `JobLeaseLostError` and rolled back graph projection updates.
fix: Keep the document/job in running state until graph materialization, warning recording, and final lease validation are complete, then mark them succeeded.
verification: `test_index_job_runner_materializes_pending_projection_before_succeeding_job` now passes; full `test_index_worker_recovery.py`, adjacent MinerU graph-warning tests, Ruff checks, and live diagnostics/graph API pass.
files_changed: ["backend/src/ragstudio/services/document_service.py", "backend/tests/test_index_worker_recovery.py"]
