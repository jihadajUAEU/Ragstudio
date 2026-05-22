---
status: complete
completed_at: "2026-05-22"
---

# Quick Task Summary

Implemented a first complete pass for centralized background runner dispatch and
shared outbound HTTP client pooling.

## Completed

- Added `BackgroundRunnerFactory` with an explicit durable runner contract and
  `index_document` dispatch.
- Updated the worker loop to claim factory-registered job types and construct
  runners through the factory.
- Added a worker-owned process-lifetime `HttpClientProvider` so indexing outside
  the FastAPI app can reuse outbound clients.
- Threaded `HttpClientProvider` through document upload/reindex validation,
  indexing, query orchestration, settings provider preview, domain metadata AI
  suggestions, job quality repair, LLM reranking, runtime answer generation,
  query hypothesis generation, MinerU parsing, and targeted vision recovery.
- Preserved request-scoped auth headers; shared clients do not store provider
  keys.
- Kept compatibility with tests and injected fake MinerU clients that do not
  accept an `http_client` constructor argument.
- Added regression tests for the background runner factory, provider-backed
  provider manifest preview, and provider-backed LLM reranking.
- Requested independent code review and fixed both Important findings:
  `HttpClientProvider` now reaches `ChunkSplitter` / `MinerUContentNormalizer`
  for indexing-time vision recovery, and `RetrievalOrchestrator` passes the
  provider to its default `RerankerService`.
- Added regression tests for provider threading through `ChunkSplitter` and
  direct `RetrievalOrchestrator` construction.

## Verified

- `python -m compileall -q backend\src\ragstudio`
- `PYTHONPATH=backend/src python -m pytest backend/tests/test_background_runner_factory.py backend/tests/test_index_worker_recovery.py backend/tests/test_http_client_provider.py backend/tests/test_provider_manifest_service.py backend/tests/test_llm_reranker_service.py backend/tests/test_reranker_service.py backend/tests/test_query_hypothesis_service.py backend/tests/test_runtime_answer_service.py backend/tests/test_settings.py -q`
- `PYTHONPATH=backend/src python -m pytest backend/tests/test_mineru_reindex_jobs.py::test_mineru_strict_blocks_when_sidecar_is_local_only backend/tests/test_documents.py backend/tests/test_jobs.py backend/tests/test_mineru_client.py -q`
- `PYTHONPATH=backend/src python -m pytest backend/tests/test_chunk_splitter.py::test_chunk_splitter_threads_http_client_provider_to_content_normalizer backend/tests/test_retrieval_orchestrator.py::test_retrieval_orchestrator_threads_http_client_provider_to_default_reranker backend/tests/test_background_runner_factory.py backend/tests/test_index_worker_recovery.py backend/tests/test_http_client_provider.py backend/tests/test_provider_manifest_service.py backend/tests/test_llm_reranker_service.py backend/tests/test_reranker_service.py backend/tests/test_query_hypothesis_service.py backend/tests/test_runtime_answer_service.py backend/tests/test_settings.py -q`
