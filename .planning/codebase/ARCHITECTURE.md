# Architecture

**Analysis Date:** 2026-05-14

## Pattern Overview

**Overall:** Local full-stack RAG workbench with FastAPI backend, React frontend, async indexing worker, PostgreSQL/PGVector metadata store, and Neo4j graph projection.

**Key Characteristics:**
- API-first backend with route handlers delegating to service classes.
- Strict product runtime policy: PostgreSQL/PGVector plus Neo4j, MinerU strict parsing, and native RAG-Anything runtime.
- Long-running indexing is queued in the database and processed by a separate worker service.
- Frontend is a single-page Studio shell with manual path routing and TanStack Query data fetching.
- Retrieval is orchestrated through native runtime, metadata retrieval, graph expansion, fusion, reranking, context assembly, and answer generation.

## Layers

**API Layer:**
- Purpose: Validate HTTP payloads, translate domain errors into HTTP responses, and call services.
- Contains: `backend/src/ragstudio/api/routes/*.py`.
- Depends on: Pydantic schemas, async DB session dependency, service classes.
- Used by: Frontend API client and external/local callers.

**Schema Layer:**
- Purpose: Define request/response contracts and runtime/profile objects.
- Contains: `backend/src/ragstudio/schemas/*.py` and generated frontend bindings in `frontend/src/api/generated.ts`.
- Depends on: Pydantic backend-side, OpenAPI TypeScript generation frontend-side.
- Used by: API routes, services, tests, frontend API client.

**Service Layer:**
- Purpose: Own business behavior for documents, chunks, indexing, runtime settings, retrieval, graph projection, experiments, optimizer, and diagnostics.
- Contains: `backend/src/ragstudio/services/*.py`.
- Depends on: DB models/session, runtime adapters, provider clients, quality gates, artifact store.
- Used by: API routes and worker.

**Data Layer:**
- Purpose: Persist documents, chunks, jobs, runs, settings, graph projection records, experiments, and scores.
- Contains: `backend/src/ragstudio/db/models.py`, `engine.py`, and repository helpers.
- Depends on: SQLAlchemy async ORM, PostgreSQL, PGVector, JSONB where available.
- Used by: Service layer and tests.

**Worker Layer:**
- Purpose: Claim and execute queued document indexing jobs outside the API request lifecycle.
- Contains: `backend/src/ragstudio/workers/index_worker.py`, `index_job_runner.py`, and `job_queue_service.py`.
- Depends on: PostgreSQL job leases, runtime profile readiness, document indexing services.
- Used by: Docker Compose `worker` service.

**Frontend Layer:**
- Purpose: Operator-facing UI for upload, pipeline status, chunk inspection, querying, evaluation, experiments, graph, diagnostics, variants, optimizer, and settings.
- Contains: `frontend/src/App.tsx`, `frontend/src/components/`, and `frontend/src/features/`.
- Depends on: React, TanStack Query, generated API types, Vite proxy.
- Used by: Browser users on the local dev/frontend endpoint.

## Data Flow

**Document Upload and Indexing:**
1. User submits a file from `frontend/src/features/documents/documents-page.tsx`.
2. `frontend/src/api/client.ts` posts multipart data to `/api/documents`.
3. `documents.py` validates parser mode, domain metadata, runtime readiness, and MinerU sidecar readiness.
4. `DocumentService.upload()` writes the artifact through `ArtifactStore`, creates a `Document`, and queues an `index_document` job.
5. `index_worker.py` claims the job through `JobQueueService`.
6. `IndexJobRunner` calls `DocumentService.run_index_job()`.
7. Parsing, chunk persistence, quality gating, vector materialization, and graph projection update chunks, index records, graph projection records, and job result metadata.

**Query Execution:**
1. User submits a query from `frontend/src/features/query/query-page.tsx`.
2. `apiClient.query()` posts to `/api/query`.
3. `QueryService` validates variants/documents, resolves the active runtime profile, checks runtime health, and builds query config.
4. `RetrievalOrchestrator` runs native retrieval and metadata retrieval, expands graph candidates, fuses/reranks evidence, assembles context, and asks the answer service.
5. A `Run` row stores answer, sources, chunk traces, reranker traces, timings, token metadata, and any error state.

**Settings and Provider Sync:**
1. Settings UI calls `/api/settings/default` and test endpoints.
2. `SettingsService` and provider connection services validate runtime profiles and provider reachability.
3. `ProviderManifestService.preview()` converts a remote manifest into a settings patch, including reasoning, embeddings, MinerU, and reranker sections.

## Key Abstractions

**Runtime Profile:**
- Purpose: Central product runtime configuration for LLM, embeddings, MinerU, reranking, storage, parser, chunking, and query behavior.
- Examples: `SettingsProfile` in `db/models.py`, runtime schemas in `schemas/runtime.py` and `schemas/settings.py`.
- Pattern: Persisted DB model plus Pydantic view models.

**Quality Policy:**
- Purpose: Decide whether parsed units are safe for vector indexing and graph projection.
- Examples: `DomainMetadataQualityGate`, `quality_action_policy`, `IndexQualityGate`, `VectorIndexPolicy`.
- Pattern: Metadata-derived policy attached to chunks and consumed by indexing/graph services.

**Runtime Adapter:**
- Purpose: Isolate native RAG-Anything and LightRAG behavior behind an adapter protocol.
- Examples: `RuntimeAdapter` protocol and `NativeRAGAnythingAdapter`.
- Pattern: Factory plus protocol, with runtime import checks.

**Job Lease:**
- Purpose: Make indexing resumable and prevent duplicate active jobs.
- Examples: `JobQueueService`, `IndexJobRunner`, `index_worker.py`.
- Pattern: Database-backed claim, heartbeat, lease expiry, and recovery.

**Frontend Feature Page:**
- Purpose: Each major Studio workflow is a feature module.
- Examples: `DocumentsPage`, `ChunkInspector`, `QueryPage`, `SettingsPage`, `GraphPage`.
- Pattern: Top-level page component plus local helper components and TanStack Query hooks.

## Entry Points

**Backend API:**
- Location: `backend/src/ragstudio/app.py`.
- Trigger: Uvicorn command in `backend/Dockerfile` or package script `ragstudio`.
- Responsibilities: Configure logging, settings, DB engine/session factory, route registration, frontend static mount.

**Index Worker:**
- Location: `backend/src/ragstudio/workers/index_worker.py`.
- Trigger: Docker Compose `worker` command.
- Responsibilities: Poll, claim, heartbeat, run, and recover `index_document` jobs.

**Frontend App:**
- Location: `frontend/src/main.tsx` and `frontend/src/App.tsx`.
- Trigger: Vite dev server.
- Responsibilities: Provide React Query context, route to feature pages, render `AppShell`.

**Developer Scripts:**
- Location: `scripts/setup.sh`, `scripts/dev.sh`, `scripts/test-all.sh`.
- Trigger: Manual shell commands.
- Responsibilities: Build images, run compose stack, execute validation.

## Error Handling

**Strategy:** Domain services raise typed errors or `RuntimeError`; API routes translate expected failures to HTTP status codes.

**Patterns:**
- Readiness or product policy violations usually become `409` or `422`.
- Missing resources become `404`.
- Query runtime failures are persisted as failed `Run` records instead of always surfacing as HTTP failures.
- Worker errors roll back and then mark jobs failed through `JobQueueService`.

## Cross-Cutting Concerns

**Logging:**
- Configured in `backend/src/ragstudio/logging.py`.
- Worker logs exceptions and job IDs.

**Validation:**
- Pydantic validates API payloads.
- `metadata_json_schema.py` validates custom domain metadata.
- `runtime_policy.py` enforces product-only runtime/parser/storage settings.

**Concurrency:**
- PostgreSQL advisory locks protect document workflows.
- Job leases and heartbeats protect long-running indexing.
- Unique partial index prevents duplicate active index jobs for one document.

**Observability:**
- Runtime health, job logs, parser quality details, index quality reports, chunk traces, reranker traces, timings, and graph diagnostics are first-class persisted outputs.

---
*Architecture analysis: 2026-05-14*
*Update when major patterns change*
