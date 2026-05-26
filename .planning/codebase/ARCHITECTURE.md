# Architecture

**Analysis Date:** 2026-05-14
**Last Updated:** 2026-05-26

## Pattern Overview

**Overall:** Local full-stack RAG proof workbench with FastAPI backend, React
frontend, async indexing worker, PostgreSQL/PGVector metadata store, Neo4j graph
projection, and a three-pillar evidence architecture: domain-aware,
layout-aware, and context-aware retrieval.

**Key Characteristics:**
- API-first backend with route handlers delegating to service classes.
- Strict product runtime policy: PostgreSQL/PGVector plus Neo4j, MinerU strict parsing, and native RAG-Anything runtime.
- Long-running indexing is queued in the database and processed by a separate worker service.
- Frontend is a single-page Studio shell with manual path routing and TanStack Query data fetching.
- Canonical Postgres chunks are the source of truth. Vector rows, native
  RAG-Anything rows, and Neo4j graph records are materialization or projection
  lanes that must bridge back to canonical evidence.
- Retrieval is orchestrated through domain-aware route planning, canonical
  metadata/reference retrieval, vector and native runtime lanes, graph expansion,
  layout-neighbor expansion, context-window expansion, fusion, reranking,
  context assembly, and answer generation.

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

**Analyze With Vision And Contract Preparation:**
1. The documents page can call `apiClient.suggestDomainMetadata()` before upload.
   The request posts the selected file to `/api/domain-profiles/suggest`.
2. `DomainMetadataAiSuggester` samples pages, chooses the active profile's
   vision-capable target when available, and asks the model for domain,
   language/script, layout, parser, quality, retrieval, and reference-contract
   observations.
3. Model output is normalized into `DomainMetadata`, an `analysis_binding`
   containing filename, size, and SHA-256, and a `contract_state` summary.
   Reference observations remain metadata-only unless validation/execution marks
   a contract as verified.
4. Reference contract candidates are accepted only when model-declared identity
   fields match regex named groups, canonical reference templates are valid, and
   sample-page execution produces matched units. Unverified candidates are kept
   as hints and reference-unit chunking is demoted before indexing.
5. The frontend shows the suggested domain and contract state. Upload includes
   the bound `domain_metadata`, `mineru_parse_options`, and `analysis_binding`;
   the backend rejects the upload if the binding no longer matches the file.

**Document Upload And Durable Indexing:**
1. The documents page posts multipart data to `/api/documents`; reindex posts
   `IndexDocumentIn` to `/api/documents/{document_id}/reindex`.
2. `documents.py` parses JSON form fields, runs `compile_index_options()`,
   validates custom JSON, enforces product parser policy, validates executable
   reference contracts, checks runtime health, and verifies the MinerU sidecar.
3. `DocumentService.upload()` writes the artifact through `ArtifactStore`,
   snapshots `Document.index_contract` with parser, domain, vision, reference,
   quality, and retrieval contract state, and queues an `index_document` job.
4. `index_worker.py` claims queued work through `JobQueueService`; `IndexJobRunner`
   holds and heartbeats the lease while `DocumentService.run_index_job()` runs.
5. PDF preflight may inspect sample pages, run OCR cleanup when configured, and
   switch the active artifact only when the cleaned sample satisfies the contract.
6. `IndexLifecycleService` or `ChunkService` calls `DocumentParserService`, which
   runs MinerU strict parsing and emits parser metadata, source locations,
   page/block provenance, parser warnings, layout roles, reading order, and
   artifact references.
7. Non-reference documents pass through modal preprocessing. Verified reference
   contracts enable canonical reference-unit assembly; otherwise chunking uses
   regular semantic/layout splitting while keeping reference hints as metadata.
8. `ChunkSplitter`, relationship builders, quality gates, repair policy, and
   targeted vision recovery attach `domain_metadata`, `reference_metadata`,
   layout metadata, parent/previous/next links, parser warnings,
   `quality_action_policy`, and materialization policy to canonical chunks.
9. `ChunkPersistenceService` persists canonical chunks in Postgres. Vector
   materialization, native RAG-Anything ingestion, and Neo4j graph projection run
   only when quality and materialization policy allow them; those outputs remain
   rebuildable lanes, not the source of truth.
10. Job stage events record MinerU validation, chunk persistence, search
    readiness, runtime enrichment, graph enrichment, ready/warning/failed state,
    parser quality, repair details, warning counts, index quality, graph
    materialization, and the final document contract state.

**Query Execution And Evidence Assembly:**
1. The query page posts to `/api/query`; `QueryService` validates document scope,
   variant/runtime settings, active profile health, and query parameters.
2. `RetrievalOrchestrator` loads domain metadata for the selected documents and
   runs query hypothesis. The hypothesis service can use verified document
   reference contracts to parse references, detect scripts, identify target
   terms, and preserve uncertainty in traces.
3. Domain query expansion and `plan_for_query()` produce intent, expanded terms,
   retrieval passes, graph-context needs, and candidate limits.
4. `RetrievalRouteInput` and `RetrievalRoutePlanner` combine document scope,
   domain classification, quality policy, materialization policy, runtime
   readiness, graph readiness, and reranker readiness into lane decisions.
5. The orchestrator executes allowed canonical, lexical/reference, metadata,
   vector, and native runtime lanes with strict document-scope propagation.
   Reference prefilters and query reference normalization consume only verified
   document contracts.
6. Layout-neighbor expansion adds same-page, same-reference, same-layout-group,
   and reading-order neighbors when layout metadata and policy allow it.
7. Context-window expansion adds bounded parent, sibling, previous, and next
   evidence around retrieved seeds.
8. Seed fusion chooses high-confidence canonical seeds for graph expansion.
   Graph candidates hydrate back to canonical chunks before final fusion.
9. Final fusion preserves lane membership and score basis, optional reranking
   records rank deltas, parser-quality warnings remain visible, and diversity
   selection limits redundant evidence.
10. `ContextAssemblyService` preserves direct evidence, injects breadcrumbs and
    layout summaries, includes needed neighbors within budget, and records
    dropped or truncated evidence reasons.
11. Query hypothesis verification and grounding validation run against final
    evidence before answer generation. A `Run` row stores the answer, sources,
    chunk traces, route-plan traces, reranker traces, timings, token metadata,
    validation trace, and any error state.

**Pipeline Timeline, Evidence UI, And Proof Data:**
1. `/api/documents/{document_id}/pipeline-timeline` aggregates `Document`,
   `Job`, `Chunk`, `IndexRecord`, and `GraphProjectionRecord` rows into a
   backend-owned stage flow.
2. Timeline stages include upload, vision, contract proposal/execution/
   verification, canonical-units enabled, queue/worker, MinerU parsing and
   validation, chunk persistence, quality gates, search readiness, runtime
   enrichment, graph enrichment, materialization, ready/warnings/failed, and
   proof readiness.
3. `/api/documents/{document_id}/parse-evidence` exposes parser quality,
   warnings, chunk previews, source locations, and sanitized evidence details
   for the document evidence UI.
4. Query pathway and evidence UI render backend traces for the three pillars;
   React may choose icons and layout, but it does not invent stage vocabulary or
   proof claims.
5. Proof packet export consumes canonical Postgres evidence, trace payloads,
   claims, redaction results, raw artifacts, and known limitations. Public proof
   viewers import static proof packets; they do not become the source of truth.

**Settings And Provider Sync:**
1. Settings UI calls `/api/settings/default` and provider test endpoints.
2. `SettingsService`, runtime health, reranker connection services, and provider
   connection services validate runtime profiles and provider reachability.
3. `ProviderManifestService.preview()` converts a remote manifest into a
   settings patch for reasoning, embeddings, MinerU, vision, and reranker
   sections while keeping provider vocabulary explicit.

## Key Abstractions

**Runtime Profile:**
- Purpose: Central product runtime configuration for LLM, embeddings, MinerU, reranking, storage, parser, chunking, and query behavior.
- Examples: `SettingsProfile` in `db/models.py`, runtime schemas in `schemas/runtime.py` and `schemas/settings.py`.
- Pattern: Persisted DB model plus Pydantic view models.

**Quality Policy:**
- Purpose: Decide whether parsed units are safe for vector indexing and graph projection.
- Examples: `DomainMetadataQualityGate`, `quality_action_policy`, `IndexQualityGate`, `VectorIndexPolicy`.
- Pattern: Metadata-derived policy attached to chunks and consumed by indexing/graph services.

**Executable Reference Contract:**
- Purpose: Prove that a document-specific reference system is executable before
  it controls chunking, exact reference search, graph identity, or query
  reference normalization.
- Examples: `domain_metadata_contract_compiler.py`,
  `reference_contract_validator.py`, `reference_contract_execution.py`,
  `reference_metadata.py`, `reference_query_parser.py`.
- Pattern: The model proposes metadata, Ragstudio validates regex safety,
  checks model-declared identity fields against regex named groups, executes the
  candidate against sample pages, stores the verified contract on the document,
  then enables canonical reference units. Unverified `reference_schema` and
  `domain_structure` remain hints for display/retrieval context only.

**Domain-Aware Evidence:**
- Purpose: Resolve document and query behavior through profiles, contracts, and
  policies rather than hardcoded domain branches.
- Examples: `DomainClassifier`, `DomainProfileRegistry`,
  `DomainLexicalRegistry`, `retrieval_route_input.py`,
  `retrieval_route_planner.py`, `domain_metadata_contract_compiler.py`.
- Pattern: Domain metadata becomes an executable retrieval profile,
  materialization hint, lexical/query expansion input, and route-planner signal.
  Document-specific reference identity comes only from verified executable
  contracts.

**Layout-Aware Evidence:**
- Purpose: Preserve visual and parser provenance so chunks and retrieval results
  can explain where evidence came from and what physical context surrounds it.
- Examples: `source_location`, parser provenance blocks, `layout_group_id`,
  `layout_role`, `reading_order`, `block_index`, `LayoutNeighborService`, native
  bridge metadata, parser warning details.
- Pattern: Parsing and chunking keep page, block, bbox, reading-order, layout
  role, preview/artifact, and warning metadata on canonical chunks. Retrieval can
  expand same-page, same-reference, same-layout-group, table/caption, and
  reading-order neighbors when metadata and policy allow it.

**Context-Aware Evidence:**
- Purpose: Preserve parent, sibling, reference, graph, and final-prompt context
  so answer evidence is understandable without flattening the document.
- Examples: `ContextWindowService`, `ContextAssemblyService`,
  `evidence_context`, `parent_chunk_id`, `previous_chunk_id`, `next_chunk_id`,
  graph-seeded canonical hydration, breadcrumbs, dropped/truncated evidence
  reasons.
- Pattern: Retrieval expands bounded parent/sibling/previous/next context,
  hydrates runtime or graph candidates back to canonical chunks, dedupes by
  canonical identity, and assembles final context with breadcrumbs, direct
  evidence preservation, layout summaries, and visible drop reasons.

**Retrieval Route Planner:**
- Purpose: Turn upstream domain, layout, context, quality, materialization, and
  readiness signals into explicit lane decisions.
- Examples: `RetrievalRouteInput`, `RetrievalRoutePlanner`,
  `RetrievalOrchestrator`, lane traces, route-plan diagnostics.
- Pattern: The planner decides whether canonical, lexical/reference, metadata,
  vector, native runtime, graph, layout-neighbor, context-window, and reranker
  lanes run, skip, or degrade. Every skipped or degraded lane needs a traceable
  reason.

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
