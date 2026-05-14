# Codebase Structure

**Analysis Date:** 2026-05-14

## Directory Layout

```text
Ragstudio/
|-- backend/              # FastAPI backend package, Dockerfile, tests
|-- frontend/             # React/Vite frontend package and tests
|-- e2e/                  # Playwright browser tests
|-- scripts/              # Setup, dev, validation, OpenAPI, runtime smoke scripts
|-- docs/                 # User docs, workflow docs, architecture notes, Superpowers plans
|-- samples/              # Quran experiment sample assets and seed scripts
|-- constraints/          # Python runtime dependency constraints
|-- .planning/            # GSD/debug/UI review artifacts and codebase map
|-- docker-compose.yml    # Local full-stack Compose topology
|-- pyproject.toml        # Workspace Python config, ruff, pyright
|-- README.md             # Development entrypoint
|-- DESIGN.md             # Current product/design planning context
|-- TODOS.md              # Current TODO context
`-- CLAUDE.md             # Repository guidance for agents
```

## Directory Purposes

**backend/:**
- Purpose: Python backend package, API, services, DB models, workers, and backend tests.
- Contains: `backend/src/ragstudio`, `backend/tests`, `backend/pyproject.toml`, `backend/Dockerfile`.
- Key files: `backend/src/ragstudio/app.py`, `backend/src/ragstudio/config.py`, `backend/src/ragstudio/db/models.py`.
- Subdirectories: `api/`, `db/`, `schemas/`, `services/`, `workers/`.

**frontend/:**
- Purpose: Studio web UI and frontend validation.
- Contains: `frontend/src`, `frontend/tests`, `frontend/package.json`, `frontend/vite.config.ts`.
- Key files: `frontend/src/App.tsx`, `frontend/src/api/client.ts`, `frontend/src/lib/routes.ts`.
- Subdirectories: `components/`, `features/`, `api/`, `lib/`.

**e2e/:**
- Purpose: Browser-level smoke and workflow tests.
- Contains: Playwright config and specs.
- Key files: `e2e/playwright.config.ts`, `e2e/studio.spec.ts`, `e2e/arabic-hanana-query.spec.ts`.

**scripts/:**
- Purpose: Developer and build automation.
- Contains: Shell scripts and Python runtime helpers.
- Key files: `scripts/setup.sh`, `scripts/dev.sh`, `scripts/test-all.sh`, `scripts/runtime_import_smoke.py`.

**docs/:**
- Purpose: User docs, workflow docs, architecture notes, reviews, and implementation plans.
- Contains: `docs/user-guide.md`, `docs/workflows.md`, `docs/architecture/`, `docs/superpowers/`.
- Key files for current launch planning: `docs/superpowers/specs/` and `docs/superpowers/plans/`.

**samples/:**
- Purpose: Sample experiment assets.
- Contains: `samples/quran_experiment/` JSON fixtures and helper scripts.

**.planning/:**
- Purpose: GSD planning state and prior debug/UI review artifacts.
- Contains: `debug/`, `ui-reviews/`, and now `codebase/`.
- Important: Core project files are expected later: `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md`.

## Key File Locations

**Entry Points:**
- `backend/src/ragstudio/app.py` - FastAPI app factory and Uvicorn entry.
- `backend/src/ragstudio/workers/index_worker.py` - Async indexing worker.
- `frontend/src/main.tsx` - React root.
- `frontend/src/App.tsx` - Manual SPA routing.

**Configuration:**
- `pyproject.toml` - Workspace dependency and Python tooling config.
- `backend/pyproject.toml` - Backend package/dependencies/script entry.
- `frontend/package.json` - Frontend dependencies and scripts.
- `frontend/vite.config.ts` - Vite dev/proxy/test config.
- `docker-compose.yml` - Local stack topology.
- `.env.example` - Example backend environment variable names.

**Core Backend Logic:**
- `backend/src/ragstudio/api/routes/` - HTTP route handlers.
- `backend/src/ragstudio/services/document_service.py` - Upload, delete, and index job orchestration.
- `backend/src/ragstudio/services/index_job_runner.py` - Worker-side job execution.
- `backend/src/ragstudio/services/retrieval_orchestrator.py` - Query evidence pipeline.
- `backend/src/ragstudio/services/domain_metadata_quality_gate.py` - Parser/domain quality policy.
- `backend/src/ragstudio/services/graph_materialization_service.py` - Neo4j graph projection.
- `backend/src/ragstudio/services/runtime_health_service.py` - Runtime readiness checks.

**Core Frontend Logic:**
- `frontend/src/api/client.ts` - API wrapper and error normalization.
- `frontend/src/features/documents/documents-page.tsx` - Upload, jobs, warnings, and warning repair UI.
- `frontend/src/features/chunks/chunk-inspector.tsx` - Chunk search/inspection.
- `frontend/src/features/query/query-page.tsx` - Query execution and trace display.
- `frontend/src/features/settings/settings-page.tsx` - Runtime/provider configuration.
- `frontend/src/features/graph/graph-page.tsx` - Graph visualization.

**Testing:**
- `backend/tests/` - Backend tests.
- `frontend/tests/` - Frontend tests.
- `e2e/` - Playwright tests.
- `scripts/test-all.sh` - Full validation script.

## Naming Conventions

**Files:**
- Python modules use snake_case: `domain_metadata_quality_gate.py`.
- Backend tests use `test_*.py`.
- Frontend feature/component files use kebab-case: `documents-page.tsx`, `chunk-inspector.tsx`.
- Frontend tests use `*.test.ts` or `*.test.tsx`.
- Major docs use uppercase or kebab-case Markdown.

**Directories:**
- Backend directories are domain/layer nouns: `api`, `db`, `schemas`, `services`, `workers`.
- Frontend feature directories are singular/plural domain names under `frontend/src/features`.
- Shared frontend primitives live under `frontend/src/components` and `frontend/src/lib`.

## Where to Add New Code

**New Backend API Surface:**
- Route: `backend/src/ragstudio/api/routes/{domain}.py`.
- Schemas: `backend/src/ragstudio/schemas/{domain}.py`.
- Service logic: `backend/src/ragstudio/services/{domain}_service.py`.
- Tests: `backend/tests/test_{domain}.py`.
- Router registration: `backend/src/ragstudio/api/routes/__init__.py`.

**New Frontend Page:**
- Page component: `frontend/src/features/{feature}/{feature}-page.tsx`.
- Route registration: `frontend/src/lib/routes.ts` and `frontend/src/App.tsx`.
- API calls/types: `frontend/src/api/client.ts` and generated `frontend/src/api/generated.ts`.
- Tests: `frontend/tests/{feature}-page.test.tsx`.

**New Proof/Benchmark Tooling:**
- CLI wrapper: `scripts/`.
- Shared backend implementation: a dedicated package under `backend/src/ragstudio/`.
- Benchmark docs/artifacts: likely under `docs/benchmarks/ragstudio-oss-proof-v1/`.
- Tests: backend tests for pure validation logic and optional script smoke tests.

**New Integration:**
- Runtime/provider client: `backend/src/ragstudio/services/`.
- Settings/schema updates: `backend/src/ragstudio/schemas/settings.py`, `db/models.py`, `db/engine.py`.
- Frontend settings UI: `frontend/src/features/settings/settings-page.tsx`.

## Special Directories

**`frontend/src/api/generated.ts`:**
- Purpose: OpenAPI-generated TypeScript types.
- Source: `scripts/generate-openapi.sh` plus frontend generate command.
- Committed: Ignored by `.gitignore`; local generation may be needed.

**`backend/src/ragstudio/static/dist/`:**
- Purpose: Built frontend static assets mounted by backend.
- Source: Frontend build output copied into backend static path.
- Committed: Ignored by `.gitignore`.

**`.ragstudio/`, `reports/`, `artifacts/`, `output/`:**
- Purpose: Runtime/local/generated artifacts.
- Committed: Ignored by `.gitignore`.

---
*Structure analysis: 2026-05-14*
*Update when directory structure changes*
