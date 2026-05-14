# Technology Stack

**Analysis Date:** 2026-05-14

## Languages

**Primary:**
- Python 3.12 - Backend API, ingestion, RAG runtime, workers, and tests in `backend/src/ragstudio` and `backend/tests`.
- TypeScript - Frontend app, generated API bindings, Vitest tests, and Playwright E2E tests in `frontend/src`, `frontend/tests`, and `e2e`.

**Secondary:**
- Bash - Developer scripts in `scripts/`.
- JSON/YAML/TOML - Project configuration in `frontend/package.json`, `docker-compose.yml`, `pyproject.toml`, and `backend/pyproject.toml`.

## Runtime

**Environment:**
- Backend runs on Python `>=3.12,<3.15` using FastAPI and Uvicorn.
- Frontend Docker image uses Node 24 via `frontend/Dockerfile`.
- Local development runs through Docker Compose in `docker-compose.yml`.

**Package Managers:**
- Python packages install from `backend/pyproject.toml` and root `pyproject.toml`.
- Frontend packages install with npm from `frontend/package-lock.json`.
- Runtime Python dependency versions are constrained through `constraints/runtime-latest.txt`.

## Frameworks

**Backend:**
- FastAPI - HTTP API in `backend/src/ragstudio/app.py` and `backend/src/ragstudio/api/routes/`.
- SQLAlchemy async ORM - PostgreSQL metadata models and sessions in `backend/src/ragstudio/db/`.
- Pydantic and pydantic-settings - API schemas and environment-backed settings in `backend/src/ragstudio/schemas/` and `backend/src/ragstudio/config.py`.

**Frontend:**
- React - UI screens in `frontend/src/features/`.
- Vite - Dev server, proxying, and build in `frontend/vite.config.ts`.
- TanStack Query - API fetching/caching through feature pages and `frontend/src/lib/query-client.ts`.
- TanStack Table - Data tables, notably `frontend/src/components/data-table.tsx`.
- Tailwind CSS v4 - Utility styling via `frontend/src/styles.css` and `@tailwindcss/vite`.
- React Flow - Pipeline and graph visualization via `@xyflow/react`.

**Testing:**
- pytest and pytest-asyncio - Backend tests under `backend/tests`.
- Ruff and Pyright - Backend lint/type checks configured in root `pyproject.toml`.
- Vitest, Testing Library, and jsdom - Frontend unit/component tests under `frontend/tests`.
- Playwright - E2E tests under `e2e`.

## Key Dependencies

**Critical Backend:**
- `raganything[all]` - Native RAG-Anything integration and runtime dependency.
- `lightrag` - Imported by runtime smoke checks and native runtime setup.
- `torch`, `mineru`, `paddleocr`, `paddlex`, `PyMuPDF` - Heavy document parsing/OCR/runtime stack validated by `scripts/runtime_import_smoke.py`.
- `asyncpg`, `pgvector`, `neo4j` - Storage and graph dependencies.
- `httpx` - Outbound calls to MinerU, provider manifests, embedding/LLM/reranker endpoints.

**Critical Frontend:**
- `@tanstack/react-query` - Main async state pattern.
- `@tanstack/react-table` - Reusable table behavior.
- `@xyflow/react` - Visual graph/pipeline surfaces.
- `lucide-react` - Shared icon set.
- `class-variance-authority`, `clsx`, `tailwind-merge` - Component class composition.

## Configuration

**Environment:**
- Backend settings use `RAGSTUDIO_` environment variables via `AppSettings` in `backend/src/ragstudio/config.py`.
- Important settings include database URL, Neo4j URI, data directory, runtime working directory, pgvector schema/table prefix, and allowed reranker hosts.
- Frontend API base is controlled by `VITE_API_BASE_URL`; dev proxy target uses `VITE_API_PROXY_TARGET`.

**Build:**
- `backend/Dockerfile` installs native dependencies, patches the PaddleX wheel, installs backend dev dependencies, and runs `scripts/runtime_import_smoke.py`.
- `frontend/Dockerfile` runs `npm ci` and starts the Vite dev server.
- `scripts/generate-openapi.sh` emits an OpenAPI schema from `create_app()`.

## Platform Requirements

**Development:**
- Docker Desktop or Docker Engine is required for `./scripts/setup.sh`, `./scripts/dev.sh`, and `./scripts/test-all.sh`.
- Backend tests require PostgreSQL; `backend/tests/conftest.py` creates per-test databases from `RAGSTUDIO_TEST_DATABASE_URL` or default settings.
- Frontend commands must be run from `frontend/`, not the repo root.

**Production/Deploy Shape:**
- Current deployable unit is Docker Compose with `backend`, `worker`, `frontend`, `postgres`, and `neo4j`.
- Local exposed dev ports are frontend `127.0.0.1:5173`, backend `127.0.0.1:8000`, Postgres `55432`, and Neo4j HTTP/Bolt `57474`/`57687`.

---
*Stack analysis: 2026-05-14*
*Update after major dependency or runtime changes*
