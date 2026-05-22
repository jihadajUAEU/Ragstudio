<!-- GSD:project-start source:PROJECT.md -->
## Project

**Ragstudio Open-Source Proof System Launch**

Ragstudio is an existing local RAG data-quality workbench for inspecting document
parsing, chunk metadata, runtime retrieval, reranker traces, graph projection, and
quality-gated materialization before bad evidence reaches answers. This project
turns the existing proof machinery into an open-source launch package: a new public
`ragstudio-site` domain with a static proof viewer, replayable proof packet, docs,
screenshots, and claim registry tied back to Ragstudio source artifacts.

The launch should make one public story obvious: RAG failures often start before
retrieval, and Ragstudio makes those failures visible, traceable, and gateable.

**Core Value:** Every public Ragstudio claim must be inspectable from claim text to replayable
evidence, source commit, raw artifact, and known limitation.

### Constraints

- **Security**: Public artifacts must not leak API keys, private endpoints, private
  hostnames, local absolute paths, unpublished model hosts, or private content.
- **Architecture**: Ragstudio remains the proof-packet source of truth; the site
  imports and renders exported proof packets.
- **Deployment**: Public site deploys through Cloudflare Pages Git integration and
  does not count as launched until the new domain is connected.
- **Runtime**: Fresh-checkout proof validation must use `static-fixtures`; live
  capture is optional and must not require private providers.
- **Corpus**: V1 public baseline is a deterministic synthetic
  multilingual/reference-heavy corpus unless a publishability review approves a
  real public corpus.
- **Accessibility**: Implemented public surfaces must meet WCAG 2.2 Level AA.
- **Design**: `DESIGN.md` is the visual source of truth; avoid generic SaaS,
  decorative hero art, dark neon terminals, and card-heavy marketing patterns.
- **Developer Experience**: The first-time proof path should target a 2-5 minute
  trust moment through `./scripts/proof.sh` and the proof viewer.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.12 - Backend API, ingestion, RAG runtime, workers, and tests in `backend/src/ragstudio` and `backend/tests`.
- TypeScript - Frontend app, generated API bindings, Vitest tests, and Playwright E2E tests in `frontend/src`, `frontend/tests`, and `e2e`.
- Bash - Developer scripts in `scripts/`.
- JSON/YAML/TOML - Project configuration in `frontend/package.json`, `docker-compose.yml`, `pyproject.toml`, and `backend/pyproject.toml`.
## Runtime
- Backend runs on Python `>=3.12,<3.15` using FastAPI and Uvicorn.
- Frontend Docker image uses Node 24 via `frontend/Dockerfile`.
- Local development runs through Docker Compose in `docker-compose.yml`.
- Python packages install from `backend/pyproject.toml` and root `pyproject.toml`.
- Frontend packages install with npm from `frontend/package-lock.json`.
- Runtime Python dependency versions are constrained through `constraints/runtime-latest.txt`.
## Frameworks
- FastAPI - HTTP API in `backend/src/ragstudio/app.py` and `backend/src/ragstudio/api/routes/`.
- SQLAlchemy async ORM - PostgreSQL metadata models and sessions in `backend/src/ragstudio/db/`.
- Pydantic and pydantic-settings - API schemas and environment-backed settings in `backend/src/ragstudio/schemas/` and `backend/src/ragstudio/config.py`.
- React - UI screens in `frontend/src/features/`.
- Vite - Dev server, proxying, and build in `frontend/vite.config.ts`.
- TanStack Query - API fetching/caching through feature pages and `frontend/src/lib/query-client.ts`.
- TanStack Table - Data tables, notably `frontend/src/components/data-table.tsx`.
- Tailwind CSS v4 - Utility styling via `frontend/src/styles.css` and `@tailwindcss/vite`.
- React Flow - Pipeline and graph visualization via `@xyflow/react`.
- pytest and pytest-asyncio - Backend tests under `backend/tests`.
- Ruff and Pyright - Backend lint/type checks configured in root `pyproject.toml`.
- Vitest, Testing Library, and jsdom - Frontend unit/component tests under `frontend/tests`.
- Playwright - E2E tests under `e2e`.
## Key Dependencies
- `raganything[all]` - Native RAG-Anything integration and runtime dependency.
- `lightrag` - Imported by runtime smoke checks and native runtime setup.
- `torch`, `mineru`, `paddleocr`, `paddlex`, `PyMuPDF` - Heavy document parsing/OCR/runtime stack validated by `scripts/runtime_import_smoke.py`.
- `asyncpg`, `pgvector`, `neo4j` - Storage and graph dependencies.
- `httpx` - Outbound calls to MinerU, provider manifests, embedding/LLM/reranker endpoints.
- `@tanstack/react-query` - Main async state pattern.
- `@tanstack/react-table` - Reusable table behavior.
- `@xyflow/react` - Visual graph/pipeline surfaces.
- `lucide-react` - Shared icon set.
- `class-variance-authority`, `clsx`, `tailwind-merge` - Component class composition.
## Configuration
- Backend settings use `RAGSTUDIO_` environment variables via `AppSettings` in `backend/src/ragstudio/config.py`.
- Important settings include database URL, Neo4j URI, data directory, runtime working directory, pgvector schema/table prefix, and allowed reranker hosts.
- Frontend API base is controlled by `VITE_API_BASE_URL`; dev proxy target uses `VITE_API_PROXY_TARGET`.
- `backend/Dockerfile` installs native dependencies, patches the PaddleX wheel, installs backend dev dependencies, and runs `scripts/runtime_import_smoke.py`.
- `frontend/Dockerfile` runs `npm ci` and starts the Vite dev server.
- `scripts/generate-openapi.sh` emits an OpenAPI schema from `create_app()`.
## Platform Requirements
- Docker Desktop or Docker Engine is required for `./scripts/setup.sh`, `./scripts/dev.sh`, and `./scripts/test-all.sh`.
- Backend tests require PostgreSQL; `backend/tests/conftest.py` creates per-test databases from `RAGSTUDIO_TEST_DATABASE_URL` or default settings.
- Frontend commands must be run from `frontend/`, not the repo root.
- Current deployable unit is Docker Compose with `backend`, `worker`, `frontend`, `postgres`, and `neo4j`.
- Local exposed dev ports are frontend `127.0.0.1:5173`, backend `127.0.0.1:8000`, Postgres `55432`, and Neo4j HTTP/Bolt `57474`/`57687`.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- Backend Python modules use snake_case, for example `runtime_health_service.py`.
- Backend tests use `test_*.py`.
- Frontend feature files use kebab-case, for example `documents-page.tsx`.
- Shared React components use kebab-case filenames with PascalCase exported functions.
- Python functions/methods use snake_case.
- Python classes use PascalCase and service classes are usually named `{Domain}Service`.
- TypeScript functions and variables use camelCase.
- React components use PascalCase function exports.
- Python constants use UPPER_SNAKE_CASE, for example `DEFAULT_PARSER_MODE`.
- TypeScript constants use camelCase for local values and UPPER_SNAKE_CASE only when representing fixed global values.
- IDs and payload keys generally mirror API schema field names.
- Pydantic models use PascalCase with suffixes like `In`, `Out`, `Page`, or `Profile`.
- TypeScript relies heavily on OpenAPI-generated types imported from `frontend/src/api/generated.ts`.
## Code Style
- Ruff configured in root `pyproject.toml`.
- Line length is 100.
- Target Python version is 3.12.
- Ruff lint selects `E`, `F`, `I`, `B`, `UP`, and `RUF`, with FastAPI `Depends(...)` defaults intentionally ignored through `B008`.
- Pyright is configured in root `pyproject.toml`.
- Type checking mode is `basic`.
- Backend source is included; backend tests are excluded.
- ESLint flat config in `frontend/eslint.config.js`.
- React Hooks rules are enabled.
- No separate Prettier config was found; follow existing file style.
## Import Organization
- No TypeScript source alias is configured in `frontend/tsconfig.json`; imports use relative paths.
- Python package import root is `ragstudio`.
## Error Handling
- API routes catch expected service errors and raise `HTTPException`.
- Services raise domain-specific errors where useful, for example `ActiveIndexJobError`, `RuntimeUnavailableError`, and `QueryResourceNotFoundError`.
- Long-running worker errors are caught, logged, and translated into failed job state.
- Query failures are often persisted on `Run` rows with `error` and `error_type` rather than raised to the client.
- `ApiError` in `frontend/src/api/client.ts` normalizes failed API responses.
- Feature pages use TanStack Query and mutation state to show loading/error UI locally.
- API invalidation happens through `useQueryClient()` after mutations.
## Logging
- Logging is configured by `configure_logging()` during app creation.
- Worker logs exceptions with worker ID and job ID in `index_worker.py`.
- Job-level user-visible logs are persisted in `Job.logs`.
- No dedicated logging framework was found.
- UI state and API errors are displayed through page components.
## Comments
- Comments are sparse and usually explain policy or exceptional behavior.
- Examples include lint-ignore rationale in `pyproject.toml` and dependency/runtime notes in `backend/Dockerfile`.
- Prefer comments for why a safety gate exists, not for restating simple code.
## Function Design
- Service classes group domain behavior and accept dependencies in constructors.
- Async functions dominate API, DB, provider, and runtime paths.
- Helper functions often live below route/service methods in the same file.
- Pydantic validation and SQLAlchemy persistence are kept close to service boundaries.
- Feature pages are large but internally organized with local helper components.
- Components are function components.
- State is local React state plus TanStack Query for server state.
- Shared primitives are intentionally small: `Button`, `DataTable`, `EmptyState`, `StatusBadge`.
## Module Design
- New user-visible behavior usually spans schemas, routes, services, tests, and sometimes DB model/column compatibility updates.
- Runtime configuration changes often require updates in `models.py`, `engine.py`, `schemas/settings.py`, settings service, connection tests, and frontend settings UI.
- Storage compatibility is handled by `init_db()` plus `_ensure_runtime_columns()` rather than migration files.
- `frontend/src/App.tsx` owns path selection and page mounting.
- `frontend/src/lib/routes.ts` owns nav metadata.
- `frontend/src/api/client.ts` is the single API call surface.
- Feature pages tend to own their specific presentational helpers.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Pattern Overview
- API-first backend with route handlers delegating to service classes.
- Strict product runtime policy: PostgreSQL/PGVector plus Neo4j, MinerU strict parsing, and native RAG-Anything runtime.
- Long-running indexing is queued in the database and processed by a separate worker service.
- Frontend is a single-page Studio shell with manual path routing and TanStack Query data fetching.
- Retrieval is orchestrated through domain-aware route planning, canonical
  metadata/reference retrieval, vector retrieval, native runtime retrieval,
  layout-neighbor expansion, context-window expansion, graph expansion, fusion,
  reranking, context assembly, and answer generation.
## Layers
- Purpose: Validate HTTP payloads, translate domain errors into HTTP responses, and call services.
- Contains: `backend/src/ragstudio/api/routes/*.py`.
- Depends on: Pydantic schemas, async DB session dependency, service classes.
- Used by: Frontend API client and external/local callers.
- Purpose: Define request/response contracts and runtime/profile objects.
- Contains: `backend/src/ragstudio/schemas/*.py` and generated frontend bindings in `frontend/src/api/generated.ts`.
- Depends on: Pydantic backend-side, OpenAPI TypeScript generation frontend-side.
- Used by: API routes, services, tests, frontend API client.
- Purpose: Own business behavior for documents, chunks, indexing, runtime settings, retrieval, graph projection, experiments, optimizer, and diagnostics.
- Contains: `backend/src/ragstudio/services/*.py`.
- Depends on: DB models/session, runtime adapters, provider clients, quality gates, artifact store.
- Used by: API routes and worker.
- Purpose: Persist documents, chunks, jobs, runs, settings, graph projection records, experiments, and scores.
- Contains: `backend/src/ragstudio/db/models.py`, `engine.py`, and repository helpers.
- Depends on: SQLAlchemy async ORM, PostgreSQL, PGVector, JSONB where available.
- Used by: Service layer and tests.
- Purpose: Claim and execute queued document indexing jobs outside the API request lifecycle.
- Contains: `backend/src/ragstudio/workers/index_worker.py`, `index_job_runner.py`, and `job_queue_service.py`.
- Depends on: PostgreSQL job leases, runtime profile readiness, document indexing services.
- Used by: Docker Compose `worker` service.
- Purpose: Operator-facing UI for upload, pipeline status, chunk inspection, querying, evaluation, experiments, graph, diagnostics, variants, optimizer, and settings.
- Contains: `frontend/src/App.tsx`, `frontend/src/components/`, and `frontend/src/features/`.
- Depends on: React, TanStack Query, generated API types, Vite proxy.
- Used by: Browser users on the local dev/frontend endpoint.
## Data Flow
- Upload/reindex creates a durable `index_document` job.
- The worker runs MinerU strict parsing, normalizes parser output, applies
  domain metadata, and creates canonical chunks with source location,
  provenance, quality policy, materialization policy, layout metadata, and
  context metadata.
- Chunk persistence stores canonical evidence in Postgres. PGVector and native
  runtime storage are materialization lanes; Neo4j is a rebuildable graph
  projection, not the source of truth.
- Query execution builds a `RetrievalRouteRequest` from document scope, query
  understanding, domain metadata, quality/materialization policy, runtime
  readiness, graph readiness, and reranker readiness.
- `RetrievalRoutePlanner` decides which lanes run, skip, or degrade.
- `RetrievalOrchestrator` gathers candidates across planned canonical,
  lexical/reference, vector, native runtime, graph, layout-neighbor, and
  context-window lanes, then fuses, reranks, assembles final context, and writes
  traceable run evidence.

## Key Abstractions
- Purpose: Central product runtime configuration for LLM, embeddings, MinerU, reranking, storage, parser, chunking, and query behavior.
- Examples: `SettingsProfile` in `db/models.py`, runtime schemas in `schemas/runtime.py` and `schemas/settings.py`.
- Pattern: Persisted DB model plus Pydantic view models.
- Purpose: Decide whether parsed units are safe for vector indexing and graph projection.
- Examples: `DomainMetadataQualityGate`, `quality_action_policy`, `IndexQualityGate`, `VectorIndexPolicy`.
- Pattern: Metadata-derived policy attached to chunks and consumed by indexing/graph services.
- Purpose: Resolve domain-aware retrieval behavior.
- Examples: `DomainClassifier`, `DomainProfileRegistry`, `DomainLexicalRegistry`, `RetrievalRouteInput`.
- Pattern: Domain metadata becomes executable retrieval profile, materialization
  hint, lexical/query expansion, and route-planner input.
- Purpose: Preserve layout-aware retrieval behavior.
- Examples: `LayoutNeighborService`, native bridge metadata, `source_location`,
  `layout_group_id`, `layout_role`, `reading_order`, `block_index`.
- Pattern: Persisted canonical chunk metadata seeds layout-neighbor candidates
  and proof traces.
- Purpose: Preserve context-aware retrieval behavior.
- Examples: `ContextWindowService`, `ContextAssemblyService`, `evidence_context`,
  `parent_chunk_id`, `previous_chunk_id`, `next_chunk_id`.
- Pattern: Retrieval expands bounded neighbors and final context records
  breadcrumbs, layout summaries, direct evidence preservation, and dropped or
  truncated evidence reasons.
- Purpose: Isolate native RAG-Anything and LightRAG behavior behind an adapter protocol.
- Examples: `RuntimeAdapter` protocol and `NativeRAGAnythingAdapter`.
- Pattern: Factory plus protocol, with runtime import checks.
- Purpose: Make indexing resumable and prevent duplicate active jobs.
- Examples: `JobQueueService`, `IndexJobRunner`, `index_worker.py`.
- Pattern: Database-backed claim, heartbeat, lease expiry, and recovery.
- Purpose: Each major Studio workflow is a feature module.
- Examples: `DocumentsPage`, `ChunkInspector`, `QueryPage`, `SettingsPage`, `GraphPage`.
- Pattern: Top-level page component plus local helper components and TanStack Query hooks.
## Entry Points
- Location: `backend/src/ragstudio/app.py`.
- Trigger: Uvicorn command in `backend/Dockerfile` or package script `ragstudio`.
- Responsibilities: Configure logging, settings, DB engine/session factory, route registration, frontend static mount.
- Location: `backend/src/ragstudio/workers/index_worker.py`.
- Trigger: Docker Compose `worker` command.
- Responsibilities: Poll, claim, heartbeat, run, and recover `index_document` jobs.
- Location: `frontend/src/main.tsx` and `frontend/src/App.tsx`.
- Trigger: Vite dev server.
- Responsibilities: Provide React Query context, route to feature pages, render `AppShell`.
- Location: `scripts/setup.sh`, `scripts/dev.sh`, `scripts/test-all.sh`.
- Trigger: Manual shell commands.
- Responsibilities: Build images, run compose stack, execute validation.
## Error Handling
- Readiness or product policy violations usually become `409` or `422`.
- Missing resources become `404`.
- Query runtime failures are persisted as failed `Run` records instead of always surfacing as HTTP failures.
- Worker errors roll back and then mark jobs failed through `JobQueueService`.
## Cross-Cutting Concerns
- Configured in `backend/src/ragstudio/logging.py`.
- Worker logs exceptions and job IDs.
- Pydantic validates API payloads.
- `metadata_json_schema.py` validates custom domain metadata.
- `runtime_policy.py` enforces product-only runtime/parser/storage settings.
- PostgreSQL advisory locks protect document workflows.
- Job leases and heartbeats protect long-running indexing.
- Unique partial index prevents duplicate active index jobs for one document.
- Runtime health, job logs, parser quality details, index quality reports, chunk traces, reranker traces, timings, and graph diagnostics are first-class persisted outputs.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

- `.codex/skills/rag-pipeline-auditor/SKILL.md` - use for parse-to-proof RAG
  pipeline audits, public proof claims, quality gates, indexing, graph,
  reranking, and trace UI changes.
- `.codex/skills/chunk-query-retrieval-auditor/SKILL.md` - use for chunk
  search, query planning, lane execution, retrieval traces, fusion, reranking,
  graph expansion, layout-neighbor expansion, context-window expansion, and
  context assembly changes.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
