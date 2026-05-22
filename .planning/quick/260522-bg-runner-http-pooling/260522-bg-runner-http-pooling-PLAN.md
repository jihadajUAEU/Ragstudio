# Quick Task 260522-bg-runner-http-pooling: Centralize background indexing and HTTP pooling

## Goal

Close the gap between the current durable indexing implementation and the requested
Centralized Background Index Task Handler plus shared outbound HTTP connection pooling.

## Current Status

Partially implemented, not complete.

- Durable indexing jobs exist through `JobQueueService`, `IndexJobRunner`, and
  `workers/index_worker.py`.
- Index jobs have leases, heartbeats, stale-lease recovery, retry/resume actions,
  and stage events exposed through `/api/jobs/{job_id}/events`.
- Granular indexing stages already exist for MinerU validation, chunk
  persistence, runtime enrichment, graph enrichment, ready, warnings, and failed
  states.
- A process-lifetime `HttpClientProvider` exists and is attached to FastAPI app
  state.
- Some settings connection tests and the query reranker path use the provider.
- Retry helpers exist in `http_retry.py` and are used by MinerU polling/download
  and reranker requests.

## Missing From The Requested Feature

- There is no general `BackgroundRunnerFactory` or shared runner abstraction for
  background job types.
- `IndexJobRunner` is specific to `index_document`; job leasing, heartbeat, error
  boundary, terminal cleanup, and recovery are not reusable contracts.
- `workers/index_worker.py` claims only `index_document` jobs and directly
  constructs `IndexJobRunner`.
- `JobWorker` remains a separate older job helper with direct commit/progress
  methods and no lease enforcement.
- Upload and reindex routes still perform runtime readiness, sidecar checks,
  duplicate-active-job checks, and job enqueueing directly instead of delegating
  to a runner factory or background-task facade.
- Index job creation is split between `JobQueueService.enqueue_index_document()`
  and `DocumentService` calling `JobWorker.build()`.
- Failed indexing result payloads are shaped in more than one place:
  `JobQueueService._mark_index_document_failed()` and
  `DocumentService._index_failure_result()`.
- Outbound HTTP pooling is incomplete. Several services still create fresh
  `httpx.AsyncClient` instances directly, including domain metadata suggestions,
  embedding/LLM connection fallbacks, provider manifest preview, job quality
  warning vision recovery, LLM reranking, parser normalization vision calls,
  query hypothesis generation, runtime answer generation, and MinerU production
  parsing when no injected client is provided.
- `RerankerService` can use the provider for generic HTTP reranking, but its LLM
  fallback path constructs a default `LLMRerankerService()` that is not
  provider-backed.
- The worker process does not own a process-lifetime `HttpClientProvider`, so
  production indexing paths cannot reuse app-state HTTP clients.
- Retry policy is not centralized. Retries exist in some services, but attempts,
  status handling, logging, and retry scope vary by caller.
- `HttpClientProvider` currently keys only by name and timeout representation; it
  does not centralize limits, proxy settings, TLS settings, authentication,
  telemetry hooks, or named retry policies.

## Parallel Audit Evidence

Two read-only subagents inspected independent scopes.

### Background Runner Audit

- No central factory exists. `index_worker.run_once()` claims only
  `["index_document"]` and directly constructs `IndexJobRunner`.
- `IndexJobRunner.run()` rejects non-`index_document` jobs, so current execution
  is durable but single-purpose.
- Durable pieces are real: `JobQueueService.claim_next()` owns leases and
  attempts, `heartbeat()` refreshes leases, `recover_expired_jobs()` chooses
  `retry_full_index` or `resume_graph_projection`, and `IndexJobRunner` runs an
  external heartbeat task around long indexing work.
- Recovery and rollback are covered by existing tests in
  `test_job_queue_service.py`, `test_index_job_runner.py`, and
  `test_index_worker_recovery.py`.
- `index_progress.py` and `/api/jobs/{job_id}/events` already provide granular
  stage visibility, so completion work should preserve that contract instead of
  replacing it.
- `chunks.py` has no background behavior today; the feature wording should not
  imply chunk search controllers currently manage leases.

### HTTP Pooling Audit

- `HttpClientProvider` pools clients by `(name, timeout)` and is created/closed
  in FastAPI app lifespan.
- Provider-backed paths currently include settings embedding, LLM, reranker, and
  MinerU connection tests plus the query route's generic `RerankerService`.
- Production and model-backed paths still creating direct clients include
  `DocumentParserService`'s MinerU indexing client, `ProviderManifestService`,
  `LLMRerankerService`, `QueryHypothesisService`, `RuntimeAnswerService`,
  `DomainMetadataAISuggester`, parser-normalization vision recovery, and
  job-quality-warning AI repair.
- `retry_async_http()` uses exponential backoff for transient statuses
  `{408, 429, 500, 502, 503, 504}` and connect/read/timeout failures.
- Retry usage is uneven: MinerU polling/download, embedding connection tests, LLM
  connection tests, and generic HTTP reranker use it; direct LLM, vision,
  manifest, and answer-generation paths do not.

## Implementation Plan

1. Add focused failing tests for the architecture contract.
   - `BackgroundRunnerFactory` can build an index runner with lease ownership,
     heartbeat, stale-lease recovery, rollback-on-error, and terminal cleanup.
   - Non-index job helpers cannot bypass lease checks when updating durable job
     status.
   - Named outbound clients are reused for MinerU, LLM, embedding, reranker, and
     provider manifest calls.
   - Transient HTTP failures use one standard retry policy and non-transient
     failures do not retry.

2. Extract a reusable background runner layer.
   - Introduce `BackgroundRunnerFactory`, `BackgroundJobRunner`, and a small
     `BackgroundJobHandler` protocol.
   - Move lease acquisition, heartbeat scheduling, lease validation, rollback
     handling, failed-job marking, and terminal lease cleanup out of
     `IndexJobRunner`.
   - Keep `IndexJobRunner` as the `index_document` handler that owns only
     document indexing and graph-resume semantics.

3. Route job execution through the factory.
   - Update `workers/index_worker.py` to claim jobs and dispatch through the
     factory.
   - Either retire or adapt `JobWorker` so route/controller code cannot create
     unleased background mutations for long-running jobs.
   - Keep document advisory locks and active-job uniqueness in the service
     boundary.

4. Preserve and extend pipeline visibility.
   - Keep `index_progress.py` as the indexing stage source of truth.
   - Ensure runner-level failures append stage events with `failed` and keep
     MinerU, chunk persistence, runtime enrichment, graph projection, warning,
     and recovery details visible through the existing jobs API/SSE endpoint.
   - Add tests that expired jobs retain enough stage state to choose
     `retry_full_index` vs `resume_graph_projection`.

5. Upgrade HTTP client infrastructure.
   - Extend `HttpClientProvider` with named client configuration for timeouts,
     connection limits, proxy/TLS options, and an explicit `request_with_retry`
     helper or companion `HttpRetryPolicy`.
   - Wire app-level provider into settings routes, query routes, runtime answer,
     query hypothesis, provider manifests, LLM reranker, domain metadata AI,
     parser normalization, job quality recovery, and production MinerU parsing.
   - Keep test injection simple by allowing service constructors to accept either
     a concrete client or the provider.

6. Verify narrowly, then broaden.
   - Backend unit tests for `JobQueueService`, new runner factory, index worker
     recovery, HTTP provider, MinerU client, reranker service, settings
     connection services, and route job status.
   - Run the durable indexing slice first, then the HTTP service slice.
   - Only run full proof validation after implementation changes stabilize.

## Validation Targets

- `python -m pytest backend/tests/test_job_queue_service.py backend/tests/test_index_job_runner.py backend/tests/test_index_worker_recovery.py -q`
- `python -m pytest backend/tests/test_http_client_provider.py backend/tests/test_mineru_client.py backend/tests/test_reranker_service.py backend/tests/test_settings.py -q`
- `python -m pytest backend/tests/test_documents.py backend/tests/test_jobs.py -q`
- `./scripts/proof.sh --strict --json` after the final behavior change if public
  proof claims are touched.

## Risk Notes

- The runner extraction must not hold long database transactions during runtime
  storage or graph operations; the current lifecycle intentionally commits before
  native runtime work to avoid lock contention.
- Shared clients must not leak auth headers between providers. Authentication
  should stay request-scoped unless a named client is deliberately bound to a
  single trusted provider.
- Production MinerU parsing already supports status callbacks; preserve that
  path so the UI does not regress to generic processing.
