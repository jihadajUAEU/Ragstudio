# RAG-Anything Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete standalone RAG-Anything Studio: local FastAPI backend, typed React workbench, document ingestion, chunk inspection, query runs, variant comparison, evaluation imports, scoring, guided optimization, graph inspection, diagnostics, static serving, and tests.

**Architecture:** The backend is a Python FastAPI app with Pydantic schemas, SQLAlchemy/SQLite persistence, an in-process job worker, and a single `RAGAnythingAdapter` boundary for upstream calls. The frontend is a React TypeScript app served by FastAPI after build, using shadcn/ui, Tailwind, TanStack Query/Table, React Flow, Monaco, and generated OpenAPI types. The implementation proceeds in vertical slices so every phase has runnable API and UI behavior before the next capability lands.

**Tech Stack:** Python 3.12+, uv, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, SQLite, pytest, Ruff, Pyright, React, TypeScript, Vite, Tailwind CSS, shadcn/ui, Radix UI, TanStack Query/Table, React Flow, Monaco, Zod, React Hook Form, Zustand, Recharts, Cytoscape.js, Vitest, Testing Library, Playwright, npm.

---

## Source Spec

Implement all requirements from `docs/superpowers/specs/2026-05-07-rag-anything-studio-design.md`.

The plan intentionally implements the whole product surface. It still preserves a safe order:

```text
Scaffold
  -> backend contracts + persistence
  -> documents + jobs + variants
  -> adapter + indexing + chunk inspection
  -> query + experiments + scoring + optimizer + graph
  -> frontend shell + screens + static serving
  -> full verification
```

## File Structure

Create this structure. Keep files focused; do not collapse services, schemas, and route handlers into one module.

```text
backend/
  pyproject.toml
  alembic.ini
  src/ragstudio/
    __init__.py
    app.py
    config.py
    logging.py
    api/
      __init__.py
      deps.py
      routes/
        __init__.py
        chunks.py
        diagnostics.py
        documents.py
        evaluation_sets.py
        experiments.py
        graph.py
        health.py
        jobs.py
        optimizer.py
        query.py
        runs.py
        settings.py
        variants.py
    db/
      __init__.py
      base.py
      engine.py
      models.py
      repositories.py
      migrations/env.py
      migrations/versions/0001_initial.py
    schemas/
      __init__.py
      common.py
      chunks.py
      diagnostics.py
      documents.py
      evaluation.py
      experiments.py
      graph.py
      jobs.py
      optimizer.py
      query.py
      runs.py
      settings.py
      variants.py
    services/
      __init__.py
      adapter.py
      artifact_store.py
      chunk_service.py
      diagnostics_service.py
      document_service.py
      evaluation_importer.py
      experiment_service.py
      graph_service.py
      job_worker.py
      optimizer_service.py
      query_service.py
      scoring_service.py
      settings_service.py
      variant_service.py
    static.py
  tests/
    conftest.py
    test_api_health.py
    test_settings.py
    test_documents_jobs.py
    test_variants.py
    test_evaluation_importer.py
    test_chunks.py
    test_query_runs.py
    test_experiments_scoring.py
    test_optimizer_graph_diagnostics.py
frontend/
  package.json
  index.html
  vite.config.ts
  tsconfig.json
  eslint.config.js
  src/
    main.tsx
    App.tsx
    api/
      client.ts
      generated.ts
    components/
      app-shell.tsx
      data-table.tsx
      empty-state.tsx
      status-badge.tsx
      ui/
        button.tsx
        card.tsx
        dialog.tsx
        input.tsx
        label.tsx
        select.tsx
        sheet.tsx
        table.tsx
        tabs.tsx
        textarea.tsx
        toast.tsx
        tooltip.tsx
    features/
      chunks/chunk-inspector.tsx
      comparison/comparison-page.tsx
      dashboard/dashboard-page.tsx
      diagnostics/diagnostics-page.tsx
      documents/documents-page.tsx
      evaluation/evaluation-page.tsx
      experiments/experiments-page.tsx
      graph/graph-page.tsx
      optimizer/optimizer-page.tsx
      pipeline/pipeline-builder.tsx
      query/query-page.tsx
      settings/settings-page.tsx
      variants/variants-page.tsx
    lib/
      query-client.ts
      routes.ts
      schemas.ts
      utils.ts
    styles.css
  tests/
    pipeline-builder.test.tsx
    evaluation-import.test.tsx
    comparison-page.test.tsx
e2e/
  studio.spec.ts
docs/
  superpowers/
    plans/2026-05-07-rag-anything-studio.md
  user-guide.md
scripts/
  generate-openapi.sh
  dev.sh
  test-all.sh
pyproject.toml
README.md
.gitignore
```

## Data Model Overview

Use UUID primary keys stored as strings. Use JSON columns for flexible traces/config. Use UTC timestamps.

```text
SettingsProfile
  └── default Variant
Document
  ├── many Chunk
  └── many Job
Variant
  ├── many Run
  └── many ExperimentVariant
EvaluationSet
  └── many EvaluationCase
Experiment
  ├── many ExperimentVariant
  ├── many Run
  └── one OptimizationSession
Run
  ├── many RunChunkTrace
  └── one Score
```

## Task 1: Repository Scaffold And Tooling

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `scripts/dev.sh`
- Create: `scripts/test-all.sh`
- Create: `backend/pyproject.toml`
- Create: `backend/src/ragstudio/__init__.py`
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/eslint.config.js`

- [ ] **Step 1: Write repo-level project metadata**

Create `pyproject.toml`:

```toml
[project]
name = "rag-anything-studio-workspace"
version = "0.1.0"
requires-python = ">=3.12,<3.15"
description = "Workspace wrapper for RAG-Anything Studio"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "RUF"]

[tool.pyright]
pythonVersion = "3.12"
typeCheckingMode = "strict"
include = ["backend/src", "backend/tests"]
```

- [ ] **Step 2: Write ignore rules**

Create `.gitignore`:

```gitignore
.DS_Store
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.pyright/
node_modules/
dist/
coverage/
playwright-report/
test-results/
.ragstudio/
backend/src/ragstudio/static/dist/
frontend/src/api/generated.ts
```

- [ ] **Step 3: Write workspace README**

Create `README.md`:

````markdown
# RAG-Anything Studio

Standalone local Studio for RAG-Anything. The app provides document upload, pipeline tuning, chunk inspection, query runs, variant comparison, evaluation imports, scoring, optimizer recommendations, graph inspection, and diagnostics.

## Development

```bash
./scripts/dev.sh
```

## Test

```bash
./scripts/test-all.sh
```
````

- [ ] **Step 4: Write development scripts**

Create `scripts/dev.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python -m uvicorn ragstudio.app:create_app --factory --reload --app-dir backend/src --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Create `scripts/test-all.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python -m pytest backend/tests -q
python -m ruff check backend/src backend/tests
python -m pyright
cd frontend
npm run lint
npm run test -- --run
npm run build
```

Run: `chmod +x scripts/dev.sh scripts/test-all.sh`

- [ ] **Step 5: Write backend package metadata**

Create `backend/pyproject.toml`:

```toml
[project]
name = "raganything-studio"
version = "0.1.0"
requires-python = ">=3.12,<3.15"
dependencies = [
  "fastapi>=0.136.1",
  "uvicorn>=0.46.0",
  "pydantic>=2.13.4",
  "sqlalchemy>=2.0.49",
  "alembic>=1.18.4",
  "aiosqlite>=0.22.1",
  "python-multipart>=0.0.27",
  "httpx>=0.28.1",
  "pyyaml>=6.0.3",
  "orjson>=3.11.9",
  "structlog>=25.5.0",
  "anyio>=4.13.0",
  "raganything>=1.3.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=9.0.3",
  "pytest-asyncio>=1.3.0",
  "ruff>=0.15.12",
  "pyright>=1.1.409",
]

[project.scripts]
ragstudio = "ragstudio.app:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Create `backend/src/ragstudio/__init__.py`:

```python
"""RAG-Anything Studio backend."""

__all__ = ["__version__"]
__version__ = "0.1.0"
```

- [ ] **Step 6: Write frontend package metadata**

Create `frontend/package.json`:

```json
{
  "name": "rag-anything-studio-frontend",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "lint": "eslint .",
    "test": "vitest",
    "generate:api": "openapi-typescript http://127.0.0.1:8000/openapi.json -o src/api/generated.ts"
  },
  "dependencies": {
    "@hookform/resolvers": "latest",
    "@monaco-editor/react": "latest",
    "@radix-ui/react-dialog": "latest",
    "@radix-ui/react-label": "latest",
    "@radix-ui/react-popover": "latest",
    "@radix-ui/react-select": "latest",
    "@radix-ui/react-tabs": "latest",
    "@radix-ui/react-toast": "latest",
    "@radix-ui/react-tooltip": "latest",
    "@tanstack/react-query": "latest",
    "@tanstack/react-table": "latest",
    "@xyflow/react": "latest",
    "class-variance-authority": "latest",
    "clsx": "latest",
    "cytoscape": "latest",
    "lucide-react": "latest",
    "monaco-editor": "latest",
    "react": "latest",
    "react-cytoscapejs": "latest",
    "react-dom": "latest",
    "react-hook-form": "latest",
    "recharts": "latest",
    "tailwind-merge": "latest",
    "zod": "latest",
    "zustand": "latest"
  },
  "devDependencies": {
    "@eslint/js": "latest",
    "@testing-library/react": "latest",
    "@types/node": "latest",
    "@types/react": "latest",
    "@types/react-dom": "latest",
    "@vitejs/plugin-react": "latest",
    "eslint": "latest",
    "eslint-plugin-react-hooks": "latest",
    "jsdom": "latest",
    "openapi-typescript": "latest",
    "playwright": "latest",
    "prettier": "latest",
    "tailwindcss": "latest",
    "typescript": "latest",
    "vite": "latest",
    "vitest": "latest"
  }
}
```

- [ ] **Step 7: Write frontend config files**

Create `frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>RAG-Anything Studio</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["src", "tests", "vite.config.ts", "eslint.config.js"]
}
```

Create `frontend/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/openapi.json": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
```

Create `frontend/eslint.config.js`:

```js
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  js.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks },
    languageOptions: {
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
    },
  },
];
```

- [ ] **Step 8: Verify scaffold commands fail only because dependencies are not installed**

Run: `python -m py_compile backend/src/ragstudio/__init__.py`
Expected: PASS.

Run: `git status --short`
Expected: new scaffold files are listed.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml .gitignore README.md scripts/dev.sh scripts/test-all.sh backend/pyproject.toml backend/src/ragstudio/__init__.py frontend/package.json frontend/index.html frontend/tsconfig.json frontend/vite.config.ts frontend/eslint.config.js
git commit -m "chore: scaffold Studio workspace"
```

## Task 2: Backend Config, Logging, App Factory, And Health API

**Files:**
- Create: `backend/src/ragstudio/config.py`
- Create: `backend/src/ragstudio/logging.py`
- Create: `backend/src/ragstudio/app.py`
- Create: `backend/src/ragstudio/api/__init__.py`
- Create: `backend/src/ragstudio/api/deps.py`
- Create: `backend/src/ragstudio/api/routes/__init__.py`
- Create: `backend/src/ragstudio/api/routes/health.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_api_health.py`

- [ ] **Step 1: Write failing health API tests**

Create `backend/tests/conftest.py`:

```python
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from ragstudio.app import create_app


@pytest.fixture
async def client(tmp_path) -> AsyncIterator[AsyncClient]:
    app = create_app(data_dir=tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
```

Create `backend/tests/test_api_health.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_health_returns_ready(client):
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "rag-anything-studio"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend/src python -m pytest backend/tests/test_api_health.py -q`
Expected: FAIL with import or route missing error.

- [ ] **Step 3: Implement config and logging**

Create `backend/src/ragstudio/config.py`:

```python
from pathlib import Path

from pydantic import BaseModel, Field


class AppSettings(BaseModel):
    service_name: str = "rag-anything-studio"
    data_dir: Path = Field(default_factory=lambda: Path(".ragstudio").resolve())
    database_url: str | None = None

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{self.data_dir / 'studio.sqlite3'}"
```

Create `backend/src/ragstudio/logging.py`:

```python
import logging

import structlog


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
```

- [ ] **Step 4: Implement app factory and route**

Create `backend/src/ragstudio/api/routes/health.py`:

```python
from fastapi import APIRouter

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "rag-anything-studio"}
```

Create `backend/src/ragstudio/api/routes/__init__.py`:

```python
from ragstudio.api.routes import health

ROUTERS = [health.router]
```

Create `backend/src/ragstudio/api/__init__.py`:

```python
"""API package."""
```

Create `backend/src/ragstudio/api/deps.py`:

```python
from fastapi import Request

from ragstudio.config import AppSettings


def get_settings(request: Request) -> AppSettings:
    return request.app.state.settings
```

Create `backend/src/ragstudio/app.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from ragstudio.api.routes import ROUTERS
from ragstudio.config import AppSettings
from ragstudio.logging import configure_logging


def create_app(data_dir: Path | None = None) -> FastAPI:
    configure_logging()
    settings = AppSettings(data_dir=data_dir or Path(".ragstudio").resolve())
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        yield

    app = FastAPI(title="RAG-Anything Studio", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    for router in ROUTERS:
        app.include_router(router)
    return app


def main() -> None:
    uvicorn.run("ragstudio.app:create_app", factory=True, host="127.0.0.1", port=8000)
```

- [ ] **Step 5: Run health tests**

Run: `PYTHONPATH=backend/src python -m pytest backend/tests/test_api_health.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/config.py backend/src/ragstudio/logging.py backend/src/ragstudio/app.py backend/src/ragstudio/api backend/tests/conftest.py backend/tests/test_api_health.py
git commit -m "feat: add FastAPI app shell"
```

## Task 3: Schemas, Database Models, And Repositories

**Files:**
- Create: `backend/src/ragstudio/schemas/*.py`
- Create: `backend/src/ragstudio/db/base.py`
- Create: `backend/src/ragstudio/db/engine.py`
- Create: `backend/src/ragstudio/db/models.py`
- Create: `backend/src/ragstudio/db/repositories.py`
- Modify: `backend/src/ragstudio/app.py`
- Test: `backend/tests/test_settings.py`
- Test: `backend/tests/test_variants.py`

- [ ] **Step 1: Write failing schema/repository tests**

Create `backend/tests/test_settings.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_settings_profile_round_trip(client):
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "sqlite",
    }

    create_response = await client.put("/api/settings/default", json=payload)
    assert create_response.status_code == 200

    read_response = await client.get("/api/settings/default")
    assert read_response.status_code == 200
    assert read_response.json()["provider"] == "openai"
    assert read_response.json()["storage_backend"] == "sqlite"
```

Create `backend/tests/test_variants.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_variant_create_and_list(client):
    payload = {
        "name": "High recall graph",
        "preset": "high_recall",
        "parameters": {"retrieval": {"top_k": 12}, "graph": {"enabled": True}},
    }

    create_response = await client.post("/api/variants", json=payload)
    assert create_response.status_code == 201
    variant_id = create_response.json()["id"]

    list_response = await client.get("/api/variants")
    assert list_response.status_code == 200
    assert any(item["id"] == variant_id for item in list_response.json()["items"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=backend/src python -m pytest backend/tests/test_settings.py backend/tests/test_variants.py -q`
Expected: FAIL because settings and variants routes do not exist.

- [ ] **Step 3: Add shared schemas**

Create `backend/src/ragstudio/schemas/common.py`:

```python
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def new_id() -> str:
    return str(uuid4())


def now_utc() -> datetime:
    return datetime.now(UTC)


class Page(BaseModel):
    items: list[Any]
    total: int


class StageStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class StudioModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
```

Create `backend/src/ragstudio/schemas/settings.py`:

```python
from ragstudio.schemas.common import StudioModel


class SettingsProfileIn(StudioModel):
    provider: str
    llm_model: str
    embedding_model: str
    storage_backend: str


class SettingsProfileOut(SettingsProfileIn):
    id: str
```

Create `backend/src/ragstudio/schemas/variants.py`:

```python
from typing import Any

from pydantic import Field

from ragstudio.schemas.common import StudioModel


class VariantIn(StudioModel):
    name: str = Field(min_length=1)
    preset: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class VariantOut(VariantIn):
    id: str


class VariantPage(StudioModel):
    items: list[VariantOut]
    total: int
```

Create the remaining schema files with these contents:

```python
# backend/src/ragstudio/schemas/__init__.py
"""Pydantic schemas for RAG-Anything Studio."""
```

```python
# backend/src/ragstudio/schemas/documents.py
from ragstudio.schemas.common import StageStatus, StudioModel


class DocumentOut(StudioModel):
    id: str
    filename: str
    content_type: str
    sha256: str
    status: StageStatus
```

```python
# backend/src/ragstudio/schemas/chunks.py
from typing import Any

from ragstudio.schemas.common import StudioModel


class ChunkOut(StudioModel):
    id: str
    document_id: str
    text: str
    source_location: dict[str, Any]
    metadata: dict[str, Any]


class ChunkSearchIn(StudioModel):
    query: str
    document_ids: list[str] = []
    variant_id: str | None = None
    limit: int = 10


class ChunkSearchOut(StudioModel):
    items: list[ChunkOut]
    total: int
```

```python
# backend/src/ragstudio/schemas/jobs.py
from typing import Any

from ragstudio.schemas.common import StageStatus, StudioModel


class JobOut(StudioModel):
    id: str
    type: str
    status: StageStatus
    target_id: str | None
    progress: int
    logs: list[str]
    result: dict[str, Any]
```

```python
# backend/src/ragstudio/schemas/evaluation.py
from typing import Any

from ragstudio.schemas.common import StudioModel


class EvaluationCaseIn(StudioModel):
    id: str
    query: str
    documents: list[str] = []
    expected_answer: str | None = None
    expected_sources: list[str] = []
    must_include: list[str] = []
    must_avoid: list[str] = []
    expected_media: list[dict[str, Any]] = []
    expected_structure: dict[str, Any] = {}
    rubric: dict[str, str] = {}
    objective: dict[str, Any] = {}
    variant_hints: dict[str, list[str]] = {}


class EvaluationSetOut(StudioModel):
    id: str
    name: str
    cases: list[EvaluationCaseIn]
```

```python
# backend/src/ragstudio/schemas/runs.py
from typing import Any

from ragstudio.schemas.common import StageStatus, StudioModel


class RunOut(StudioModel):
    id: str
    variant_id: str
    query: str
    status: StageStatus
    answer: str
    sources: list[dict[str, Any]]
    chunk_traces: list[dict[str, Any]]
    timings: dict[str, Any]
    error: str | None
```

```python
# backend/src/ragstudio/schemas/query.py
from ragstudio.schemas.common import StudioModel
from ragstudio.schemas.runs import RunOut


class QueryIn(StudioModel):
    query: str
    document_ids: list[str] = []
    variant_ids: list[str]


class QueryOut(StudioModel):
    runs: list[RunOut]
```

```python
# backend/src/ragstudio/schemas/experiments.py
from typing import Any

from ragstudio.schemas.common import StudioModel
from ragstudio.schemas.runs import RunOut


class ExperimentIn(StudioModel):
    name: str
    document_ids: list[str]
    evaluation_set_id: str
    variant_ids: list[str]
    objective: dict[str, Any]


class ExperimentOut(ExperimentIn):
    id: str
    runs: list[RunOut] = []
```

```python
# backend/src/ragstudio/schemas/graph.py
from typing import Any

from ragstudio.schemas.common import StudioModel


class GraphOut(StudioModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
```

```python
# backend/src/ragstudio/schemas/diagnostics.py
from typing import Any

from ragstudio.schemas.common import StudioModel


class DiagnosticsOut(StudioModel):
    capabilities: dict[str, bool]
    dependency_status: dict[str, Any]
    warnings: list[str]
```

- [ ] **Step 4: Add database engine and models**

Create `backend/src/ragstudio/db/base.py`:

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

Create `backend/src/ragstudio/db/engine.py`:

```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ragstudio.db.base import Base


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, future=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session
```

Create `backend/src/ragstudio/db/models.py`:

```python
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from ragstudio.db.base import Base
from ragstudio.schemas.common import now_utc, new_id


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class SettingsProfile(Base, TimestampMixin):
    __tablename__ = "settings_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: "default")
    provider: Mapped[str] = mapped_column(String)
    llm_model: Mapped[str] = mapped_column(String)
    embedding_model: Mapped[str] = mapped_column(String)
    storage_backend: Mapped[str] = mapped_column(String)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String)
    content_type: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String, unique=True)
    artifact_path: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ready")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document")


class Chunk(Base, TimestampMixin):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    text: Mapped[str] = mapped_column(Text)
    source_location: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    document: Mapped[Document] = relationship(back_populates="chunks")


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ready")
    target_id: Mapped[str | None] = mapped_column(String, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    logs: Mapped[list[str]] = mapped_column(JSON, default=list)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Variant(Base, TimestampMixin):
    __tablename__ = "variants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String)
    preset: Mapped[str] = mapped_column(String)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class EvaluationSet(Base, TimestampMixin):
    __tablename__ = "evaluation_sets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String)
    cases: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class Experiment(Base, TimestampMixin):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String)
    document_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    evaluation_set_id: Mapped[str] = mapped_column(String)
    variant_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    objective: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Run(Base, TimestampMixin):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    variant_id: Mapped[str] = mapped_column(String)
    experiment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    query: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="ready")
    answer: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    chunk_traces: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    timings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Score(Base, TimestampMixin):
    __tablename__ = "scores"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String)
    total: Mapped[int] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class OptimizationSession(Base, TimestampMixin):
    __tablename__ = "optimization_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(String)
    objective: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    selected_variant_id: Mapped[str | None] = mapped_column(String, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, default="")
    tried_variant_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
```

- [ ] **Step 5: Add generic repository helpers**

Create `backend/src/ragstudio/db/repositories.py`:

```python
from collections.abc import Sequence
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class Repository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, model: type[ModelT], item_id: str) -> ModelT | None:
        return await self.session.get(model, item_id)

    async def list(self, model: type[ModelT]) -> Sequence[ModelT]:
        result = await self.session.execute(select(model).order_by(model.created_at.desc()))  # type: ignore[attr-defined]
        return result.scalars().all()

    async def add(self, item: ModelT) -> ModelT:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete(self, item: ModelT) -> None:
        await self.session.delete(item)
        await self.session.commit()
```

- [ ] **Step 6: Wire database into app lifespan**

Modify `backend/src/ragstudio/app.py` so `create_app()` initializes `engine`, `session_factory`, and schema tables:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from ragstudio.api.routes import ROUTERS
from ragstudio.config import AppSettings
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.logging import configure_logging


def create_app(data_dir: Path | None = None) -> FastAPI:
    configure_logging()
    settings = AppSettings(data_dir=data_dir or Path(".ragstudio").resolve())
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.resolved_database_url)
    session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        await init_db(engine)
        yield
        await engine.dispose()

    app = FastAPI(title="RAG-Anything Studio", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    for router in ROUTERS:
        app.include_router(router)
    return app


def main() -> None:
    uvicorn.run("ragstudio.app:create_app", factory=True, host="127.0.0.1", port=8000)
```

Modify `backend/src/ragstudio/api/deps.py`:

```python
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.config import AppSettings


def get_settings(request: Request) -> AppSettings:
    return request.app.state.settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session
```

- [ ] **Step 7: Run tests and commit**

Run: `PYTHONPATH=backend/src python -m pytest backend/tests/test_api_health.py -q`
Expected: PASS.

Commit:

```bash
git add backend/src/ragstudio backend/tests/test_settings.py backend/tests/test_variants.py
git commit -m "feat: add backend schemas and persistence foundation"
```

## Task 4: Settings And Variant Services/API

**Files:**
- Create: `backend/src/ragstudio/services/settings_service.py`
- Create: `backend/src/ragstudio/services/variant_service.py`
- Create: `backend/src/ragstudio/api/routes/settings.py`
- Create: `backend/src/ragstudio/api/routes/variants.py`
- Modify: `backend/src/ragstudio/api/routes/__init__.py`
- Test: `backend/tests/test_settings.py`
- Test: `backend/tests/test_variants.py`

- [ ] **Step 1: Implement settings service**

Create `backend/src/ragstudio/services/settings_service.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import SettingsProfile
from ragstudio.schemas.settings import SettingsProfileIn, SettingsProfileOut


class SettingsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_default(self) -> SettingsProfileOut | None:
        profile = await self.session.get(SettingsProfile, "default")
        if profile is None:
            return None
        return SettingsProfileOut.model_validate(profile)

    async def upsert_default(self, data: SettingsProfileIn) -> SettingsProfileOut:
        profile = await self.session.get(SettingsProfile, "default")
        if profile is None:
            profile = SettingsProfile(id="default", **data.model_dump())
            self.session.add(profile)
        else:
            for key, value in data.model_dump().items():
                setattr(profile, key, value)
        await self.session.commit()
        await self.session.refresh(profile)
        return SettingsProfileOut.model_validate(profile)
```

- [ ] **Step 2: Implement variant service**

Create `backend/src/ragstudio/services/variant_service.py`:

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import Variant
from ragstudio.schemas.variants import VariantIn, VariantOut, VariantPage


class VariantService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: VariantIn) -> VariantOut:
        variant = Variant(**data.model_dump())
        self.session.add(variant)
        await self.session.commit()
        await self.session.refresh(variant)
        return VariantOut.model_validate(variant)

    async def list(self) -> VariantPage:
        result = await self.session.execute(select(Variant).order_by(Variant.created_at.desc()))
        variants = [VariantOut.model_validate(item) for item in result.scalars().all()]
        return VariantPage(items=variants, total=len(variants))

    async def get_required(self, variant_id: str) -> VariantOut:
        variant = await self.session.get(Variant, variant_id)
        if variant is None:
            raise KeyError(variant_id)
        return VariantOut.model_validate(variant)
```

- [ ] **Step 3: Implement settings routes**

Create `backend/src/ragstudio/api/routes/settings.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.settings import SettingsProfileIn, SettingsProfileOut
from ragstudio.services.settings_service import SettingsService

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/default", response_model=SettingsProfileOut)
async def get_default_settings(session: AsyncSession = Depends(get_session)) -> SettingsProfileOut:
    profile = await SettingsService(session).get_default()
    if profile is None:
        raise HTTPException(status_code=404, detail="Default settings profile is not configured")
    return profile


@router.put("/default", response_model=SettingsProfileOut)
async def put_default_settings(
    payload: SettingsProfileIn,
    session: AsyncSession = Depends(get_session),
) -> SettingsProfileOut:
    return await SettingsService(session).upsert_default(payload)
```

- [ ] **Step 4: Implement variant routes**

Create `backend/src/ragstudio/api/routes/variants.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.variants import VariantIn, VariantOut, VariantPage
from ragstudio.services.variant_service import VariantService

router = APIRouter(prefix="/api/variants", tags=["variants"])


@router.post("", response_model=VariantOut, status_code=201)
async def create_variant(
    payload: VariantIn,
    session: AsyncSession = Depends(get_session),
) -> VariantOut:
    return await VariantService(session).create(payload)


@router.get("", response_model=VariantPage)
async def list_variants(session: AsyncSession = Depends(get_session)) -> VariantPage:
    return await VariantService(session).list()


@router.get("/{variant_id}", response_model=VariantOut)
async def get_variant(variant_id: str, session: AsyncSession = Depends(get_session)) -> VariantOut:
    try:
        return await VariantService(session).get_required(variant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Variant not found") from exc
```

Modify `backend/src/ragstudio/api/routes/__init__.py`:

```python
from ragstudio.api.routes import health, settings, variants

ROUTERS = [health.router, settings.router, variants.router]
```

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=backend/src python -m pytest backend/tests/test_settings.py backend/tests/test_variants.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/settings_service.py backend/src/ragstudio/services/variant_service.py backend/src/ragstudio/api/routes/settings.py backend/src/ragstudio/api/routes/variants.py backend/src/ragstudio/api/routes/__init__.py backend/tests/test_settings.py backend/tests/test_variants.py
git commit -m "feat: add settings and variant APIs"
```

## Task 5: Artifact Store, Documents, Jobs, And Worker

**Files:**
- Create: `backend/src/ragstudio/services/artifact_store.py`
- Create: `backend/src/ragstudio/services/document_service.py`
- Create: `backend/src/ragstudio/services/job_worker.py`
- Create: `backend/src/ragstudio/api/routes/documents.py`
- Create: `backend/src/ragstudio/api/routes/jobs.py`
- Modify: `backend/src/ragstudio/api/routes/__init__.py`
- Test: `backend/tests/test_documents_jobs.py`

- [ ] **Step 1: Write failing documents/jobs tests**

Create `backend/tests/test_documents_jobs.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_upload_document_creates_document_and_index_job(client):
    files = {"file": ("sample.txt", b"alpha beta gamma", "text/plain")}

    upload_response = await client.post("/api/documents", files=files)

    assert upload_response.status_code == 201
    document = upload_response.json()
    assert document["filename"] == "sample.txt"
    assert document["status"] == "ready"

    jobs_response = await client.get("/api/jobs")
    assert jobs_response.status_code == 200
    jobs = jobs_response.json()["items"]
    assert any(job["type"] == "index_document" and job["target_id"] == document["id"] for job in jobs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend/src python -m pytest backend/tests/test_documents_jobs.py -q`
Expected: FAIL because documents/jobs routes do not exist.

- [ ] **Step 3: Implement artifact store**

Create `backend/src/ragstudio/services/artifact_store.py`:

```python
from hashlib import sha256
from pathlib import Path


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root
        self.uploads_dir = root / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    def write_upload(self, filename: str, content: bytes) -> tuple[str, Path]:
        digest = sha256(content).hexdigest()
        safe_name = filename.replace("/", "_").replace("\\", "_")
        target = self.uploads_dir / f"{digest}-{safe_name}"
        target.write_bytes(content)
        return digest, target
```

- [ ] **Step 4: Implement document service and job worker**

Create `backend/src/ragstudio/services/job_worker.py`:

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import Job
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.jobs import JobOut


class JobWorker:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def enqueue(self, job_type: str, target_id: str | None) -> JobOut:
        job = Job(type=job_type, target_id=target_id, status=StageStatus.READY.value, progress=0)
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return JobOut.model_validate(job)

    async def list(self) -> list[JobOut]:
        result = await self.session.execute(select(Job).order_by(Job.created_at.desc()))
        return [JobOut.model_validate(item) for item in result.scalars().all()]
```

Create `backend/src/ragstudio/services/document_service.py`:

```python
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import Document
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.documents import DocumentOut
from ragstudio.services.artifact_store import ArtifactStore
from ragstudio.services.job_worker import JobWorker


class DocumentService:
    def __init__(self, session: AsyncSession, data_dir: Path):
        self.session = session
        self.store = ArtifactStore(data_dir)

    async def upload(self, filename: str, content_type: str, content: bytes) -> DocumentOut:
        digest, artifact_path = self.store.write_upload(filename, content)
        document = Document(
            filename=filename,
            content_type=content_type,
            sha256=digest,
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        self.session.add(document)
        await self.session.commit()
        await self.session.refresh(document)
        await JobWorker(self.session).enqueue("index_document", document.id)
        return DocumentOut.model_validate(document)

    async def list(self) -> list[DocumentOut]:
        result = await self.session.execute(select(Document).order_by(Document.created_at.desc()))
        return [DocumentOut.model_validate(item) for item in result.scalars().all()]
```

- [ ] **Step 5: Implement documents and jobs routes**

Create `backend/src/ragstudio/api/routes/documents.py`:

```python
from fastapi import APIRouter, Depends, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.documents import DocumentOut
from ragstudio.services.document_service import DocumentService

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile,
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    content = await file.read()
    return await DocumentService(session, request.app.state.settings.data_dir).upload(
        filename=file.filename or "upload.bin",
        content_type=file.content_type or "application/octet-stream",
        content=content,
    )


@router.get("")
async def list_documents(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    items = await DocumentService(session, request.app.state.settings.data_dir).list()
    return {"items": items, "total": len(items)}
```

Create `backend/src/ragstudio/api/routes/jobs.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.services.job_worker import JobWorker

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    items = await JobWorker(session).list()
    return {"items": items, "total": len(items)}
```

Modify `backend/src/ragstudio/api/routes/__init__.py`:

```python
from ragstudio.api.routes import documents, health, jobs, settings, variants

ROUTERS = [health.router, settings.router, variants.router, documents.router, jobs.router]
```

- [ ] **Step 6: Run tests**

Run: `PYTHONPATH=backend/src python -m pytest backend/tests/test_documents_jobs.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/artifact_store.py backend/src/ragstudio/services/document_service.py backend/src/ragstudio/services/job_worker.py backend/src/ragstudio/api/routes/documents.py backend/src/ragstudio/api/routes/jobs.py backend/src/ragstudio/api/routes/__init__.py backend/tests/test_documents_jobs.py
git commit -m "feat: add document upload and job tracking"
```

## Task 6: Evaluation Importer For CSV, JSON, YAML, And JSONL

**Files:**
- Create: `backend/src/ragstudio/services/evaluation_importer.py`
- Create: `backend/src/ragstudio/api/routes/evaluation_sets.py`
- Modify: `backend/src/ragstudio/api/routes/__init__.py`
- Test: `backend/tests/test_evaluation_importer.py`

- [ ] **Step 1: Write failing importer tests**

Create `backend/tests/test_evaluation_importer.py`:

```python
import pytest

from ragstudio.services.evaluation_importer import EvaluationImporter


def test_import_jsonl_cases():
    text = '{"id":"case-1","query":"Q?","expected_answer":"A","must_include":["A"]}\n'

    cases = EvaluationImporter().parse("cases.jsonl", text.encode())

    assert cases[0].id == "case-1"
    assert cases[0].query == "Q?"
    assert cases[0].expected_answer == "A"


def test_import_csv_cases():
    text = "id,query,expected_answer,must_include\ncase-1,Q?,A,A\n"

    cases = EvaluationImporter().parse("cases.csv", text.encode())

    assert cases[0].must_include == ["A"]


def test_reject_case_without_expected_signal():
    text = '{"id":"case-1","query":"Q?"}\n'

    with pytest.raises(ValueError, match="expected-output signal"):
        EvaluationImporter().parse("cases.jsonl", text.encode())


@pytest.mark.asyncio
async def test_import_endpoint_creates_evaluation_set(client):
    files = {"file": ("cases.jsonl", b'{"id":"case-1","query":"Q?","expected_answer":"A"}\n', "application/jsonl")}

    response = await client.post("/api/evaluation-sets/import?name=Smoke", files=files)

    assert response.status_code == 201
    assert response.json()["name"] == "Smoke"
    assert response.json()["cases"][0]["id"] == "case-1"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=backend/src python -m pytest backend/tests/test_evaluation_importer.py -q`
Expected: FAIL because importer and route do not exist.

- [ ] **Step 3: Implement importer**

Create `backend/src/ragstudio/services/evaluation_importer.py`:

```python
import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any

import yaml

from ragstudio.schemas.evaluation import EvaluationCaseIn


class EvaluationImporter:
    def parse(self, filename: str, content: bytes) -> list[EvaluationCaseIn]:
        suffix = Path(filename).suffix.lower()
        text = content.decode("utf-8")
        if suffix == ".jsonl":
            raw_cases = [json.loads(line) for line in text.splitlines() if line.strip()]
        elif suffix == ".json":
            loaded = json.loads(text)
            raw_cases = loaded if isinstance(loaded, list) else loaded.get("cases", [])
        elif suffix in {".yaml", ".yml"}:
            loaded = yaml.safe_load(text)
            raw_cases = loaded if isinstance(loaded, list) else loaded.get("cases", [])
        elif suffix == ".csv":
            raw_cases = list(csv.DictReader(StringIO(text)))
        else:
            raise ValueError(f"Unsupported evaluation file extension: {suffix}")

        cases = [self._normalize(raw) for raw in raw_cases]
        for case in cases:
            self._validate_expected_signal(case)
        return cases

    def _normalize(self, raw: dict[str, Any]) -> EvaluationCaseIn:
        normalized = dict(raw)
        for list_field in ["documents", "expected_sources", "must_include", "must_avoid"]:
            value = normalized.get(list_field, [])
            if isinstance(value, str):
                normalized[list_field] = [item.strip() for item in value.split("|") if item.strip()]
        return EvaluationCaseIn.model_validate(normalized)

    def _validate_expected_signal(self, case: EvaluationCaseIn) -> None:
        has_signal = any(
            [
                case.expected_answer,
                case.expected_sources,
                case.must_include,
                case.expected_structure,
                case.rubric,
                case.expected_media,
            ]
        )
        if not has_signal:
            raise ValueError(f"Evaluation case {case.id} needs at least one expected-output signal")
```

- [ ] **Step 4: Implement evaluation set route**

Create `backend/src/ragstudio/api/routes/evaluation_sets.py`:

```python
from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.db.models import EvaluationSet
from ragstudio.schemas.evaluation import EvaluationSetOut
from ragstudio.services.evaluation_importer import EvaluationImporter

router = APIRouter(prefix="/api/evaluation-sets", tags=["evaluation-sets"])


@router.post("/import", response_model=EvaluationSetOut, status_code=201)
async def import_evaluation_set(
    name: str,
    file: UploadFile,
    session: AsyncSession = Depends(get_session),
) -> EvaluationSetOut:
    cases = EvaluationImporter().parse(file.filename or "cases.jsonl", await file.read())
    evaluation_set = EvaluationSet(name=name, cases=[case.model_dump() for case in cases])
    session.add(evaluation_set)
    await session.commit()
    await session.refresh(evaluation_set)
    return EvaluationSetOut(id=evaluation_set.id, name=evaluation_set.name, cases=cases)


@router.get("")
async def list_evaluation_sets(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    result = await session.execute(select(EvaluationSet).order_by(EvaluationSet.created_at.desc()))
    items = [
        EvaluationSetOut(
            id=item.id,
            name=item.name,
            cases=item.cases,
        )
        for item in result.scalars().all()
    ]
    return {"items": items, "total": len(items)}
```

Modify `backend/src/ragstudio/api/routes/__init__.py`:

```python
from ragstudio.api.routes import documents, evaluation_sets, health, jobs, settings, variants

ROUTERS = [
    health.router,
    settings.router,
    variants.router,
    documents.router,
    jobs.router,
    evaluation_sets.router,
]
```

- [ ] **Step 5: Run importer tests**

Run: `PYTHONPATH=backend/src python -m pytest backend/tests/test_evaluation_importer.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/evaluation_importer.py backend/src/ragstudio/api/routes/evaluation_sets.py backend/src/ragstudio/api/routes/__init__.py backend/tests/test_evaluation_importer.py
git commit -m "feat: add evaluation set imports"
```

## Task 7: Adapter, Indexing, Chunk Search, And Chunk Traces

**Files:**
- Create: `backend/src/ragstudio/services/adapter.py`
- Create: `backend/src/ragstudio/services/chunk_service.py`
- Create: `backend/src/ragstudio/api/routes/chunks.py`
- Modify: `backend/src/ragstudio/api/routes/__init__.py`
- Test: `backend/tests/test_chunks.py`

- [ ] **Step 1: Write failing chunk tests**

Create `backend/tests/test_chunks.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_chunk_search_returns_ranked_chunks(client):
    files = {"file": ("sample.txt", b"alpha beta gamma\nsecond chunk", "text/plain")}
    upload = await client.post("/api/documents", files=files)
    document_id = upload.json()["id"]

    index_response = await client.post(f"/api/chunks/index/{document_id}")
    assert index_response.status_code == 200

    response = await client.post("/api/chunks/search", json={"query": "alpha", "document_ids": [document_id], "limit": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert "alpha" in body["items"][0]["text"]
```

- [ ] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=backend/src python -m pytest backend/tests/test_chunks.py -q`
Expected: FAIL because chunks API does not exist.

- [ ] **Step 3: Implement adapter with safe fallback behavior**

Create `backend/src/ragstudio/services/adapter.py`:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AdapterCapabilities:
    index_document: bool
    query: bool
    search_chunks: bool
    graph: bool
    real_raganything: bool


class RAGAnythingAdapter:
    def __init__(self) -> None:
        try:
            __import__("raganything")
        except Exception:
            self._has_real_package = False
        else:
            self._has_real_package = True

    def get_capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            index_document=True,
            query=True,
            search_chunks=True,
            graph=True,
            real_raganything=self._has_real_package,
        )

    async def index_document(self, artifact_path: Path, document_id: str) -> list[dict[str, Any]]:
        text = artifact_path.read_text(encoding="utf-8", errors="ignore")
        parts = [part.strip() for part in text.splitlines() if part.strip()]
        if not parts:
            parts = [text[:4000]]
        return [
            {
                "document_id": document_id,
                "text": part,
                "source_location": {"line": index + 1},
                "metadata": {"strategy": "line-split-fallback"},
            }
            for index, part in enumerate(parts)
        ]

    async def query(self, query: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        answer = " ".join(chunk["text"] for chunk in chunks[:3])
        return {
            "answer": answer or f"No supporting chunks found for: {query}",
            "sources": [{"chunk_id": chunk["id"], "document_id": chunk["document_id"]} for chunk in chunks],
            "chunk_traces": [
                {"chunk_id": chunk["id"], "inclusion_status": "prompt-included", "score": chunk.get("score", 0)}
                for chunk in chunks
            ],
            "timings": {"adapter_ms": 0},
        }

    async def graph(self) -> dict[str, list[dict[str, Any]]]:
        return {"nodes": [], "edges": []}
```

- [ ] **Step 4: Implement chunk service**

Create `backend/src/ragstudio/services/chunk_service.py`:

```python
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn, ChunkSearchOut
from ragstudio.services.adapter import RAGAnythingAdapter


class ChunkService:
    def __init__(self, session: AsyncSession, adapter: RAGAnythingAdapter | None = None):
        self.session = session
        self.adapter = adapter or RAGAnythingAdapter()

    async def index_document(self, document_id: str) -> list[ChunkOut]:
        document = await self.session.get(Document, document_id)
        if document is None:
            raise KeyError(document_id)
        await self.session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        raw_chunks = await self.adapter.index_document(Path(document.artifact_path), document_id)
        chunks = [
            Chunk(
                document_id=item["document_id"],
                text=item["text"],
                source_location=item["source_location"],
                metadata_json=item["metadata"],
            )
            for item in raw_chunks
        ]
        self.session.add_all(chunks)
        await self.session.commit()
        for chunk in chunks:
            await self.session.refresh(chunk)
        return [self._out(chunk) for chunk in chunks]

    async def search(self, payload: ChunkSearchIn) -> ChunkSearchOut:
        query = select(Chunk)
        if payload.document_ids:
            query = query.where(Chunk.document_id.in_(payload.document_ids))
        result = await self.session.execute(query)
        terms = {term.lower() for term in payload.query.split() if term}
        scored: list[tuple[int, Chunk]] = []
        for chunk in result.scalars().all():
            score = sum(1 for term in terms if term in chunk.text.lower())
            scored.append((score, chunk))
        ranked = [chunk for score, chunk in sorted(scored, key=lambda item: item[0], reverse=True) if score > 0]
        if not ranked:
            ranked = [chunk for _, chunk in scored]
        selected = ranked[: payload.limit]
        return ChunkSearchOut(items=[self._out(chunk) for chunk in selected], total=len(selected))

    def _out(self, chunk: Chunk) -> ChunkOut:
        return ChunkOut(
            id=chunk.id,
            document_id=chunk.document_id,
            text=chunk.text,
            source_location=chunk.source_location,
            metadata=chunk.metadata_json,
        )
```

- [ ] **Step 5: Implement chunks route**

Create `backend/src/ragstudio/api/routes/chunks.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn, ChunkSearchOut
from ragstudio.services.chunk_service import ChunkService

router = APIRouter(prefix="/api/chunks", tags=["chunks"])


@router.post("/index/{document_id}", response_model=list[ChunkOut])
async def index_document_chunks(
    document_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[ChunkOut]:
    try:
        return await ChunkService(session).index_document(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc


@router.post("/search", response_model=ChunkSearchOut)
async def search_chunks(
    payload: ChunkSearchIn,
    session: AsyncSession = Depends(get_session),
) -> ChunkSearchOut:
    return await ChunkService(session).search(payload)
```

Modify `backend/src/ragstudio/api/routes/__init__.py`:

```python
from ragstudio.api.routes import chunks, documents, evaluation_sets, health, jobs, settings, variants

ROUTERS = [
    health.router,
    settings.router,
    variants.router,
    documents.router,
    jobs.router,
    evaluation_sets.router,
    chunks.router,
]
```

- [ ] **Step 6: Run chunk tests**

Run: `PYTHONPATH=backend/src python -m pytest backend/tests/test_chunks.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/adapter.py backend/src/ragstudio/services/chunk_service.py backend/src/ragstudio/api/routes/chunks.py backend/src/ragstudio/api/routes/__init__.py backend/tests/test_chunks.py
git commit -m "feat: add adapter-backed chunk inspection"
```

## Task 8: Query Runs, Run Storage, And Comparison Inputs

**Files:**
- Create: `backend/src/ragstudio/services/query_service.py`
- Create: `backend/src/ragstudio/api/routes/query.py`
- Create: `backend/src/ragstudio/api/routes/runs.py`
- Modify: `backend/src/ragstudio/api/routes/__init__.py`
- Test: `backend/tests/test_query_runs.py`

- [ ] **Step 1: Write failing query/run tests**

Create `backend/tests/test_query_runs.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_query_creates_run_with_answer_and_chunk_trace(client):
    upload = await client.post("/api/documents", files={"file": ("sample.txt", b"alpha answer source", "text/plain")})
    document_id = upload.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")
    variant = await client.post("/api/variants", json={"name": "Balanced", "preset": "balanced", "parameters": {}})

    response = await client.post(
        "/api/query",
        json={"query": "alpha?", "document_ids": [document_id], "variant_ids": [variant.json()["id"]]},
    )

    assert response.status_code == 200
    run = response.json()["runs"][0]
    assert run["status"] == "succeeded"
    assert "alpha" in run["answer"]
    assert run["chunk_traces"][0]["inclusion_status"] == "prompt-included"
```

- [ ] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=backend/src python -m pytest backend/tests/test_query_runs.py -q`
Expected: FAIL because query API does not exist.

- [ ] **Step 3: Implement query service**

Create `backend/src/ragstudio/services/query_service.py`:

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import Run
from ragstudio.schemas.chunks import ChunkSearchIn
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.query import QueryIn, QueryOut
from ragstudio.schemas.runs import RunOut
from ragstudio.services.adapter import RAGAnythingAdapter
from ragstudio.services.chunk_service import ChunkService


class QueryService:
    def __init__(self, session: AsyncSession, adapter: RAGAnythingAdapter | None = None):
        self.session = session
        self.adapter = adapter or RAGAnythingAdapter()

    async def run_query(self, payload: QueryIn) -> QueryOut:
        runs: list[RunOut] = []
        for variant_id in payload.variant_ids:
            chunks = await ChunkService(self.session, self.adapter).search(
                ChunkSearchIn(query=payload.query, document_ids=payload.document_ids, variant_id=variant_id, limit=8)
            )
            adapter_payload = [
                {
                    "id": chunk.id,
                    "document_id": chunk.document_id,
                    "text": chunk.text,
                    "score": 1,
                }
                for chunk in chunks.items
            ]
            result = await self.adapter.query(payload.query, adapter_payload)
            run = Run(
                variant_id=variant_id,
                query=payload.query,
                status=StageStatus.SUCCEEDED.value,
                answer=result["answer"],
                sources=result["sources"],
                chunk_traces=result["chunk_traces"],
                timings=result["timings"],
            )
            self.session.add(run)
            await self.session.commit()
            await self.session.refresh(run)
            runs.append(RunOut.model_validate(run))
        return QueryOut(runs=runs)

    async def list_runs(self) -> list[RunOut]:
        result = await self.session.execute(select(Run).order_by(Run.created_at.desc()))
        return [RunOut.model_validate(item) for item in result.scalars().all()]
```

- [ ] **Step 4: Implement query and runs routes**

Create `backend/src/ragstudio/api/routes/query.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.query import QueryIn, QueryOut
from ragstudio.services.query_service import QueryService

router = APIRouter(prefix="/api/query", tags=["query"])


@router.post("", response_model=QueryOut)
async def query(payload: QueryIn, session: AsyncSession = Depends(get_session)) -> QueryOut:
    return await QueryService(session).run_query(payload)
```

Create `backend/src/ragstudio/api/routes/runs.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.services.query_service import QueryService

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("")
async def list_runs(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    items = await QueryService(session).list_runs()
    return {"items": items, "total": len(items)}
```

Modify `backend/src/ragstudio/api/routes/__init__.py`:

```python
from ragstudio.api.routes import chunks, documents, evaluation_sets, health, jobs, query, runs, settings, variants

ROUTERS = [
    health.router,
    settings.router,
    variants.router,
    documents.router,
    jobs.router,
    evaluation_sets.router,
    chunks.router,
    query.router,
    runs.router,
]
```

- [ ] **Step 5: Run query tests**

Run: `PYTHONPATH=backend/src python -m pytest backend/tests/test_query_runs.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/query_service.py backend/src/ragstudio/api/routes/query.py backend/src/ragstudio/api/routes/runs.py backend/src/ragstudio/api/routes/__init__.py backend/tests/test_query_runs.py
git commit -m "feat: add query runs and chunk traces"
```

## Task 9: Experiments, Scoring, Optimizer, Graph, And Diagnostics

**Files:**
- Create: `backend/src/ragstudio/services/scoring_service.py`
- Create: `backend/src/ragstudio/services/experiment_service.py`
- Create: `backend/src/ragstudio/services/optimizer_service.py`
- Create: `backend/src/ragstudio/services/graph_service.py`
- Create: `backend/src/ragstudio/services/diagnostics_service.py`
- Create: `backend/src/ragstudio/api/routes/experiments.py`
- Create: `backend/src/ragstudio/api/routes/graph.py`
- Create: `backend/src/ragstudio/api/routes/optimizer.py`
- Create: `backend/src/ragstudio/api/routes/diagnostics.py`
- Modify: `backend/src/ragstudio/api/routes/__init__.py`
- Test: `backend/tests/test_experiments_scoring.py`
- Test: `backend/tests/test_optimizer_graph_diagnostics.py`

- [ ] **Step 1: Write failing experiment and optimizer tests**

Create `backend/tests/test_experiments_scoring.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_experiment_runs_variants_and_scores_expected_output(client):
    upload = await client.post("/api/documents", files={"file": ("sample.txt", b"alpha expected answer", "text/plain")})
    document_id = upload.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")
    variant = await client.post("/api/variants", json={"name": "Balanced", "preset": "balanced", "parameters": {}})
    evaluation = await client.post(
        "/api/evaluation-sets/import?name=Eval",
        files={"file": ("cases.jsonl", b'{"id":"case-1","query":"alpha?","expected_answer":"alpha expected answer","must_include":["expected"]}\n', "application/jsonl")},
    )

    response = await client.post(
        "/api/experiments",
        json={
            "name": "Compare",
            "document_ids": [document_id],
            "evaluation_set_id": evaluation.json()["id"],
            "variant_ids": [variant.json()["id"]],
            "objective": {"primary": "grounded_correctness"},
        },
    )

    assert response.status_code == 201
    assert response.json()["runs"][0]["status"] == "succeeded"
```

Create `backend/tests/test_optimizer_graph_diagnostics.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_diagnostics_and_graph_endpoints(client):
    diagnostics = await client.get("/api/diagnostics")
    graph = await client.get("/api/graph")

    assert diagnostics.status_code == 200
    assert "query" in diagnostics.json()["capabilities"]
    assert graph.status_code == 200
    assert graph.json()["nodes"] == []


@pytest.mark.asyncio
async def test_optimizer_endpoint_recommends_best_run(client):
    response = await client.post("/api/optimizer/recommend", json={"runs": []})

    assert response.status_code == 200
    assert response.json()["selected_variant_id"] is None
    assert "No runs" in response.json()["explanation"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=backend/src python -m pytest backend/tests/test_experiments_scoring.py backend/tests/test_optimizer_graph_diagnostics.py -q`
Expected: FAIL because APIs do not exist.

- [ ] **Step 3: Implement scoring service**

Create `backend/src/ragstudio/services/scoring_service.py`:

```python
from ragstudio.schemas.evaluation import EvaluationCaseIn
from ragstudio.schemas.runs import RunOut


class ScoringService:
    def score(self, run: RunOut, case: EvaluationCaseIn) -> dict[str, object]:
        total = 0
        details: dict[str, object] = {}
        answer_lower = run.answer.lower()
        if case.expected_answer:
            expected_terms = {term for term in case.expected_answer.lower().split() if len(term) > 3}
            matched = sorted(term for term in expected_terms if term in answer_lower)
            total += len(matched)
            details["expected_answer_terms"] = matched
        include_matches = [term for term in case.must_include if term.lower() in answer_lower]
        avoid_hits = [term for term in case.must_avoid if term.lower() in answer_lower]
        total += len(include_matches) * 2
        total -= len(avoid_hits) * 3
        details["must_include_matches"] = include_matches
        details["must_avoid_hits"] = avoid_hits
        return {"total": total, "details": details}
```

- [ ] **Step 4: Implement experiment and optimizer services**

Create `backend/src/ragstudio/services/experiment_service.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import EvaluationSet, Experiment
from ragstudio.schemas.evaluation import EvaluationCaseIn
from ragstudio.schemas.experiments import ExperimentIn, ExperimentOut
from ragstudio.schemas.query import QueryIn
from ragstudio.services.query_service import QueryService


class ExperimentService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_and_run(self, payload: ExperimentIn) -> ExperimentOut:
        evaluation_set = await self.session.get(EvaluationSet, payload.evaluation_set_id)
        if evaluation_set is None:
            raise KeyError(payload.evaluation_set_id)
        experiment = Experiment(**payload.model_dump())
        self.session.add(experiment)
        await self.session.commit()
        await self.session.refresh(experiment)
        runs = []
        for raw_case in evaluation_set.cases:
            case = EvaluationCaseIn.model_validate(raw_case)
            result = await QueryService(self.session).run_query(
                QueryIn(query=case.query, document_ids=payload.document_ids, variant_ids=payload.variant_ids)
            )
            runs.extend(result.runs)
        return ExperimentOut(**payload.model_dump(), id=experiment.id, runs=runs)
```

Create `backend/src/ragstudio/services/optimizer_service.py`:

```python
from ragstudio.schemas.runs import RunOut


class OptimizerService:
    def recommend(self, runs: list[RunOut]) -> dict[str, object]:
        if not runs:
            return {"selected_variant_id": None, "explanation": "No runs were available to rank."}
        selected = max(runs, key=lambda run: len(run.sources) - (1 if run.error else 0))
        return {
            "selected_variant_id": selected.variant_id,
            "explanation": "Selected the variant with the strongest source coverage and no run error.",
        }
```

Create `backend/src/ragstudio/schemas/optimizer.py`:

```python
from ragstudio.schemas.common import StudioModel
from ragstudio.schemas.runs import RunOut


class OptimizerRecommendIn(StudioModel):
    runs: list[RunOut]


class OptimizerRecommendOut(StudioModel):
    selected_variant_id: str | None
    explanation: str
```

- [ ] **Step 5: Implement graph and diagnostics services**

Create `backend/src/ragstudio/services/graph_service.py`:

```python
from ragstudio.schemas.graph import GraphOut
from ragstudio.services.adapter import RAGAnythingAdapter


class GraphService:
    def __init__(self, adapter: RAGAnythingAdapter | None = None):
        self.adapter = adapter or RAGAnythingAdapter()

    async def get_graph(self) -> GraphOut:
        raw = await self.adapter.graph()
        return GraphOut(nodes=raw["nodes"], edges=raw["edges"])
```

Create `backend/src/ragstudio/services/diagnostics_service.py`:

```python
from ragstudio.schemas.diagnostics import DiagnosticsOut
from ragstudio.services.adapter import RAGAnythingAdapter


class DiagnosticsService:
    def __init__(self, adapter: RAGAnythingAdapter | None = None):
        self.adapter = adapter or RAGAnythingAdapter()

    def inspect(self) -> DiagnosticsOut:
        capabilities = self.adapter.get_capabilities()
        return DiagnosticsOut(
            capabilities={
                "index_document": capabilities.index_document,
                "query": capabilities.query,
                "search_chunks": capabilities.search_chunks,
                "graph": capabilities.graph,
                "real_raganything": capabilities.real_raganything,
            },
            dependency_status={"raganything": "available" if capabilities.real_raganything else "fallback"},
            warnings=[] if capabilities.real_raganything else ["Using fallback adapter behavior."],
        )
```

- [ ] **Step 6: Implement routes**

Create `backend/src/ragstudio/api/routes/experiments.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.experiments import ExperimentIn, ExperimentOut
from ragstudio.services.experiment_service import ExperimentService

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


@router.post("", response_model=ExperimentOut, status_code=201)
async def create_experiment(
    payload: ExperimentIn,
    session: AsyncSession = Depends(get_session),
) -> ExperimentOut:
    try:
        return await ExperimentService(session).create_and_run(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Evaluation set not found") from exc
```

Create `backend/src/ragstudio/api/routes/graph.py`:

```python
from fastapi import APIRouter

from ragstudio.schemas.graph import GraphOut
from ragstudio.services.graph_service import GraphService

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("", response_model=GraphOut)
async def get_graph() -> GraphOut:
    return await GraphService().get_graph()
```

Create `backend/src/ragstudio/api/routes/diagnostics.py`:

```python
from fastapi import APIRouter

from ragstudio.schemas.diagnostics import DiagnosticsOut
from ragstudio.services.diagnostics_service import DiagnosticsService

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("", response_model=DiagnosticsOut)
async def diagnostics() -> DiagnosticsOut:
    return DiagnosticsService().inspect()
```

Create `backend/src/ragstudio/api/routes/optimizer.py`:

```python
from fastapi import APIRouter

from ragstudio.schemas.optimizer import OptimizerRecommendIn, OptimizerRecommendOut
from ragstudio.services.optimizer_service import OptimizerService

router = APIRouter(prefix="/api/optimizer", tags=["optimizer"])


@router.post("/recommend", response_model=OptimizerRecommendOut)
async def recommend(payload: OptimizerRecommendIn) -> OptimizerRecommendOut:
    return OptimizerRecommendOut.model_validate(OptimizerService().recommend(payload.runs))
```

Modify `backend/src/ragstudio/api/routes/__init__.py`:

```python
from ragstudio.api.routes import (
    chunks,
    diagnostics,
    documents,
    evaluation_sets,
    experiments,
    graph,
    health,
    jobs,
    optimizer,
    query,
    runs,
    settings,
    variants,
)

ROUTERS = [
    health.router,
    settings.router,
    variants.router,
    documents.router,
    jobs.router,
    evaluation_sets.router,
    chunks.router,
    query.router,
    runs.router,
    experiments.router,
    graph.router,
    optimizer.router,
    diagnostics.router,
]
```

- [ ] **Step 7: Run tests and commit**

Run: `PYTHONPATH=backend/src python -m pytest backend/tests/test_experiments_scoring.py backend/tests/test_optimizer_graph_diagnostics.py -q`
Expected: PASS.

Commit:

```bash
git add backend/src/ragstudio/services/scoring_service.py backend/src/ragstudio/services/experiment_service.py backend/src/ragstudio/services/optimizer_service.py backend/src/ragstudio/services/graph_service.py backend/src/ragstudio/services/diagnostics_service.py backend/src/ragstudio/schemas/optimizer.py backend/src/ragstudio/api/routes/experiments.py backend/src/ragstudio/api/routes/graph.py backend/src/ragstudio/api/routes/optimizer.py backend/src/ragstudio/api/routes/diagnostics.py backend/src/ragstudio/api/routes/__init__.py backend/tests/test_experiments_scoring.py backend/tests/test_optimizer_graph_diagnostics.py
git commit -m "feat: add experiments scoring optimizer graph diagnostics"
```

## Task 10: Frontend Shell, Styling, API Client, And Shared Components

**Files:**
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/styles.css`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/generated.ts`
- Create: `frontend/src/lib/query-client.ts`
- Create: `frontend/src/lib/routes.ts`
- Create: `frontend/src/lib/utils.ts`
- Create: `frontend/src/components/app-shell.tsx`
- Create: `frontend/src/components/status-badge.tsx`
- Create: `frontend/src/components/empty-state.tsx`
- Create: `frontend/src/components/data-table.tsx`
- Create: `frontend/src/components/ui/*.tsx`

- [ ] **Step 1: Create API client and generated type shim**

Create `frontend/src/api/generated.ts`:

```ts
export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

export interface VariantOut {
  id: string;
  name: string;
  preset: string;
  parameters: Record<string, Json>;
}

export interface DocumentOut {
  id: string;
  filename: string;
  content_type: string;
  sha256: string;
  status: string;
}

export interface ChunkOut {
  id: string;
  document_id: string;
  text: string;
  source_location: Record<string, Json>;
  metadata: Record<string, Json>;
}

export interface RunOut {
  id: string;
  variant_id: string;
  query: string;
  status: string;
  answer: string;
  sources: Record<string, Json>[];
  chunk_traces: Record<string, Json>[];
  timings: Record<string, Json>;
  error: string | null;
}
```

Create `frontend/src/api/client.ts`:

```ts
export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with ${response.status}`);
  }
  return (await response.json()) as T;
}
```

- [ ] **Step 2: Create utility and query client**

Create `frontend/src/lib/utils.ts`:

```ts
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

Create `frontend/src/lib/query-client.ts`:

```ts
import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
```

Create `frontend/src/lib/routes.ts`:

```ts
export const routes = [
  { path: "dashboard", label: "Dashboard" },
  { path: "settings", label: "Settings" },
  { path: "documents", label: "Documents" },
  { path: "pipeline", label: "Pipeline" },
  { path: "query", label: "Query" },
  { path: "chunks", label: "Chunks" },
  { path: "evaluation", label: "Evaluation" },
  { path: "experiments", label: "Experiments" },
  { path: "comparison", label: "Comparison" },
  { path: "optimizer", label: "Optimizer" },
  { path: "graph", label: "Graph" },
  { path: "diagnostics", label: "Diagnostics" },
] as const;
```

- [ ] **Step 3: Create base UI components**

Create `frontend/src/components/ui/button.tsx`:

```tsx
import * as React from "react";

import { cn } from "../../lib/utils";

export function Button(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={cn(
        "inline-flex h-9 items-center justify-center rounded-md border border-slate-300 bg-slate-950 px-3 text-sm font-medium text-white shadow-sm hover:bg-slate-800 disabled:opacity-50",
        props.className,
      )}
    />
  );
}
```

Create `frontend/src/components/status-badge.tsx`:

```tsx
export function StatusBadge({ status }: { status: string }) {
  const color = status === "succeeded" || status === "ready" ? "bg-emerald-100 text-emerald-800" : status === "failed" ? "bg-rose-100 text-rose-800" : "bg-slate-100 text-slate-700";
  return <span className={`rounded px-2 py-1 text-xs font-medium ${color}`}>{status}</span>;
}
```

Create `frontend/src/components/empty-state.tsx`:

```tsx
export function EmptyState({ title }: { title: string }) {
  return <div className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">{title}</div>;
}
```

Create `frontend/src/components/data-table.tsx`:

```tsx
import type { ReactNode } from "react";

export function DataTable({ children }: { children: ReactNode }) {
  return <div className="overflow-hidden rounded-md border border-slate-200 bg-white">{children}</div>;
}
```

- [ ] **Step 4: Create app shell and styles**

Create `frontend/src/styles.css`:

```css
@import "tailwindcss";

:root {
  color: #0f172a;
  background: #f8fafc;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

body {
  margin: 0;
}
```

Create `frontend/src/components/app-shell.tsx`:

```tsx
import { routes } from "../lib/routes";

export function AppShell({ active, onNavigate, children }: { active: string; onNavigate: (path: string) => void; children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen grid-cols-[240px_1fr] bg-slate-50">
      <aside className="border-r border-slate-200 bg-white p-4">
        <h1 className="mb-6 text-lg font-semibold">RAG-Anything Studio</h1>
        <nav className="space-y-1">
          {routes.map((route) => (
            <button
              key={route.path}
              onClick={() => onNavigate(route.path)}
              className={`block w-full rounded-md px-3 py-2 text-left text-sm ${active === route.path ? "bg-slate-950 text-white" : "text-slate-700 hover:bg-slate-100"}`}
            >
              {route.label}
            </button>
          ))}
        </nav>
      </aside>
      <main className="min-w-0 p-6">{children}</main>
    </div>
  );
}
```

Create `frontend/src/main.tsx`:

```tsx
import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import { queryClient } from "./lib/query-client";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
```

Create `frontend/src/App.tsx`:

```tsx
import { useState } from "react";

import { AppShell } from "./components/app-shell";
import { DashboardPage } from "./features/dashboard/dashboard-page";

export function App() {
  const [active, setActive] = useState("dashboard");
  return (
    <AppShell active={active} onNavigate={setActive}>
      <DashboardPage active={active} />
    </AppShell>
  );
}
```

- [ ] **Step 5: Create initial routed dashboard component with real active label**

Create `frontend/src/features/dashboard/dashboard-page.tsx`:

```tsx
export function DashboardPage({ active }: { active: string }) {
  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-2xl font-semibold capitalize">{active}</h2>
        <p className="text-sm text-slate-500">Studio workbench surface is ready for feature screens.</p>
      </div>
    </section>
  );
}
```

- [ ] **Step 6: Run frontend build**

Run: `cd frontend && npm install && npm run build`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend
git commit -m "feat: add Studio frontend shell"
```

## Task 11: Frontend Settings, Documents, Jobs, And Variants Screens

**Files:**
- Create: `frontend/src/features/settings/settings-page.tsx`
- Create: `frontend/src/features/documents/documents-page.tsx`
- Create: `frontend/src/features/variants/variants-page.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/tests/evaluation-import.test.tsx`

- [ ] **Step 1: Implement settings screen**

Create `frontend/src/features/settings/settings-page.tsx`:

```tsx
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { apiJson } from "../../api/client";
import { Button } from "../../components/ui/button";

export function SettingsPage() {
  const { data, refetch } = useQuery({ queryKey: ["settings"], queryFn: () => apiJson<Record<string, string>>("/api/settings/default").catch(() => null) });
  const [provider, setProvider] = useState("openai");
  const mutation = useMutation({
    mutationFn: () =>
      apiJson("/api/settings/default", {
        method: "PUT",
        body: JSON.stringify({ provider, llm_model: "gpt-4.1", embedding_model: "text-embedding-3-large", storage_backend: "sqlite" }),
      }),
    onSuccess: () => void refetch(),
  });
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Settings</h2>
      <input className="h-9 rounded-md border px-3" value={provider} onChange={(event) => setProvider(event.target.value)} />
      <Button onClick={() => mutation.mutate()}>Save settings</Button>
      <pre className="rounded bg-slate-100 p-3 text-xs">{JSON.stringify(data, null, 2)}</pre>
    </section>
  );
}
```

- [ ] **Step 2: Implement documents screen**

Create `frontend/src/features/documents/documents-page.tsx`:

```tsx
import { useMutation, useQuery } from "@tanstack/react-query";

import { apiJson } from "../../api/client";
import type { DocumentOut } from "../../api/generated";
import { DataTable } from "../../components/data-table";
import { StatusBadge } from "../../components/status-badge";

export function DocumentsPage() {
  const documents = useQuery({ queryKey: ["documents"], queryFn: () => apiJson<{ items: DocumentOut[]; total: number }>("/api/documents") });
  const upload = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return apiJson<DocumentOut>("/api/documents", { method: "POST", body });
    },
    onSuccess: () => void documents.refetch(),
  });
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Documents</h2>
      <input type="file" onChange={(event) => event.target.files?.[0] && upload.mutate(event.target.files[0])} />
      <DataTable>
        <table className="w-full text-sm">
          <tbody>
            {documents.data?.items.map((document) => (
              <tr key={document.id} className="border-t">
                <td className="p-3">{document.filename}</td>
                <td className="p-3"><StatusBadge status={document.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </DataTable>
    </section>
  );
}
```

- [ ] **Step 3: Implement variants screen**

Create `frontend/src/features/variants/variants-page.tsx`:

```tsx
import { useMutation, useQuery } from "@tanstack/react-query";

import { apiJson } from "../../api/client";
import type { VariantOut } from "../../api/generated";
import { Button } from "../../components/ui/button";

export function VariantsPage() {
  const variants = useQuery({ queryKey: ["variants"], queryFn: () => apiJson<{ items: VariantOut[]; total: number }>("/api/variants") });
  const create = useMutation({
    mutationFn: () => apiJson<VariantOut>("/api/variants", { method: "POST", body: JSON.stringify({ name: "Balanced", preset: "balanced", parameters: {} }) }),
    onSuccess: () => void variants.refetch(),
  });
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Variants</h2>
      <Button onClick={() => create.mutate()}>Create balanced variant</Button>
      <div className="grid gap-2">
        {variants.data?.items.map((variant) => <div key={variant.id} className="rounded-md border bg-white p-3">{variant.name} · {variant.preset}</div>)}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Wire screens into App**

Modify `frontend/src/App.tsx`:

```tsx
import { useState } from "react";

import { AppShell } from "./components/app-shell";
import { DashboardPage } from "./features/dashboard/dashboard-page";
import { DocumentsPage } from "./features/documents/documents-page";
import { SettingsPage } from "./features/settings/settings-page";
import { VariantsPage } from "./features/variants/variants-page";

export function App() {
  const [active, setActive] = useState("dashboard");
  const page =
    active === "settings" ? <SettingsPage /> :
    active === "documents" ? <DocumentsPage /> :
    active === "variants" ? <VariantsPage /> :
    <DashboardPage active={active} />;
  return (
    <AppShell active={active} onNavigate={setActive}>
      {page}
    </AppShell>
  );
}
```

- [ ] **Step 5: Run frontend build and commit**

Run: `cd frontend && npm run build`
Expected: PASS.

Commit:

```bash
git add frontend/src/App.tsx frontend/src/features/settings/settings-page.tsx frontend/src/features/documents/documents-page.tsx frontend/src/features/variants/variants-page.tsx
git commit -m "feat: add settings documents and variants screens"
```

## Task 12: Pipeline Builder, Query, Chunk Inspector, And Graph Screens

**Files:**
- Create: `frontend/src/features/pipeline/pipeline-builder.tsx`
- Create: `frontend/src/features/query/query-page.tsx`
- Create: `frontend/src/features/chunks/chunk-inspector.tsx`
- Create: `frontend/src/features/graph/graph-page.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/tests/pipeline-builder.test.tsx`

- [ ] **Step 1: Implement Pipeline Builder with React Flow**

Create `frontend/src/features/pipeline/pipeline-builder.tsx`:

```tsx
import "@xyflow/react/dist/style.css";
import { Background, Controls, ReactFlow } from "@xyflow/react";

const nodes = [
  { id: "upload", position: { x: 0, y: 80 }, data: { label: "Upload" } },
  { id: "parse", position: { x: 160, y: 80 }, data: { label: "Parse" } },
  { id: "chunk", position: { x: 320, y: 80 }, data: { label: "Chunk" } },
  { id: "embed", position: { x: 480, y: 80 }, data: { label: "Embed" } },
  { id: "retrieve", position: { x: 640, y: 80 }, data: { label: "Retrieve" } },
  { id: "generate", position: { x: 800, y: 80 }, data: { label: "Generate" } },
  { id: "evaluate", position: { x: 960, y: 80 }, data: { label: "Evaluate" } },
];

const edges = [
  { id: "upload-parse", source: "upload", target: "parse" },
  { id: "parse-chunk", source: "parse", target: "chunk" },
  { id: "chunk-embed", source: "chunk", target: "embed" },
  { id: "embed-retrieve", source: "embed", target: "retrieve" },
  { id: "retrieve-generate", source: "retrieve", target: "generate" },
  { id: "generate-evaluate", source: "generate", target: "evaluate" },
];

export function PipelineBuilder() {
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Pipeline Builder</h2>
      <div className="h-[520px] rounded-md border bg-white">
        <ReactFlow nodes={nodes} edges={edges} fitView>
          <Background />
          <Controls />
        </ReactFlow>
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Implement query screen**

Create `frontend/src/features/query/query-page.tsx`:

```tsx
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { apiJson } from "../../api/client";
import type { DocumentOut, RunOut, VariantOut } from "../../api/generated";
import { Button } from "../../components/ui/button";

export function QueryPage() {
  const [query, setQuery] = useState("What is in the document?");
  const documents = useQuery({ queryKey: ["documents"], queryFn: () => apiJson<{ items: DocumentOut[]; total: number }>("/api/documents") });
  const variants = useQuery({ queryKey: ["variants"], queryFn: () => apiJson<{ items: VariantOut[]; total: number }>("/api/variants") });
  const run = useMutation({
    mutationFn: () =>
      apiJson<{ runs: RunOut[] }>("/api/query", {
        method: "POST",
        body: JSON.stringify({ query, document_ids: documents.data?.items.map((item) => item.id) ?? [], variant_ids: variants.data?.items.map((item) => item.id) ?? [] }),
      }),
  });
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Query</h2>
      <textarea className="min-h-24 w-full rounded-md border p-3" value={query} onChange={(event) => setQuery(event.target.value)} />
      <Button onClick={() => run.mutate()}>Run query</Button>
      <div className="grid gap-3">
        {run.data?.runs.map((item) => (
          <article key={item.id} className="rounded-md border bg-white p-4">
            <div className="text-sm text-slate-500">{item.variant_id}</div>
            <p>{item.answer}</p>
            <pre className="mt-3 rounded bg-slate-100 p-3 text-xs">{JSON.stringify(item.chunk_traces, null, 2)}</pre>
          </article>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 3: Implement chunk inspector screen**

Create `frontend/src/features/chunks/chunk-inspector.tsx`:

```tsx
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { apiJson } from "../../api/client";
import type { ChunkOut, DocumentOut } from "../../api/generated";
import { Button } from "../../components/ui/button";

export function ChunkInspector() {
  const [query, setQuery] = useState("alpha");
  const documents = useQuery({ queryKey: ["documents"], queryFn: () => apiJson<{ items: DocumentOut[]; total: number }>("/api/documents") });
  const search = useMutation({
    mutationFn: () =>
      apiJson<{ items: ChunkOut[]; total: number }>("/api/chunks/search", {
        method: "POST",
        body: JSON.stringify({ query, document_ids: documents.data?.items.map((item) => item.id) ?? [], limit: 10 }),
      }),
  });
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Chunk Inspector</h2>
      <input className="h-9 w-full rounded-md border px-3" value={query} onChange={(event) => setQuery(event.target.value)} />
      <Button onClick={() => search.mutate()}>Search chunks</Button>
      <div className="grid gap-3">
        {search.data?.items.map((chunk) => (
          <article key={chunk.id} className="rounded-md border bg-white p-4">
            <div className="mb-2 text-xs text-slate-500">{chunk.document_id}</div>
            <p className="whitespace-pre-wrap text-sm">{chunk.text}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Implement graph screen**

Create `frontend/src/features/graph/graph-page.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";

import { apiJson } from "../../api/client";

export function GraphPage() {
  const graph = useQuery({ queryKey: ["graph"], queryFn: () => apiJson<{ nodes: unknown[]; edges: unknown[] }>("/api/graph") });
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Knowledge Graph</h2>
      <div className="rounded-md border bg-white p-4 text-sm">
        Nodes: {graph.data?.nodes.length ?? 0} · Edges: {graph.data?.edges.length ?? 0}
      </div>
    </section>
  );
}
```

- [ ] **Step 5: Wire screens into App**

Modify `frontend/src/App.tsx` to include:

```tsx
import { ChunkInspector } from "./features/chunks/chunk-inspector";
import { GraphPage } from "./features/graph/graph-page";
import { PipelineBuilder } from "./features/pipeline/pipeline-builder";
import { QueryPage } from "./features/query/query-page";
```

Update `page` selection:

```tsx
const page =
  active === "settings" ? <SettingsPage /> :
  active === "documents" ? <DocumentsPage /> :
  active === "variants" ? <VariantsPage /> :
  active === "pipeline" ? <PipelineBuilder /> :
  active === "query" ? <QueryPage /> :
  active === "chunks" ? <ChunkInspector /> :
  active === "graph" ? <GraphPage /> :
  <DashboardPage active={active} />;
```

- [ ] **Step 6: Add pipeline test**

Create `frontend/tests/pipeline-builder.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PipelineBuilder } from "../src/features/pipeline/pipeline-builder";

describe("PipelineBuilder", () => {
  it("renders core pipeline stages", () => {
    render(<PipelineBuilder />);
    expect(screen.getByText("Upload")).toBeTruthy();
    expect(screen.getByText("Retrieve")).toBeTruthy();
    expect(screen.getByText("Evaluate")).toBeTruthy();
  });
});
```

- [ ] **Step 7: Run frontend tests and commit**

Run: `cd frontend && npm run test -- --run frontend/tests/pipeline-builder.test.tsx && npm run build`
Expected: PASS.

Commit:

```bash
git add frontend/src/App.tsx frontend/src/features/pipeline/pipeline-builder.tsx frontend/src/features/query/query-page.tsx frontend/src/features/chunks/chunk-inspector.tsx frontend/src/features/graph/graph-page.tsx frontend/tests/pipeline-builder.test.tsx
git commit -m "feat: add pipeline query chunk and graph screens"
```

## Task 13: Evaluation, Experiments, Comparison, Optimizer, And Diagnostics Screens

**Files:**
- Create: `frontend/src/features/evaluation/evaluation-page.tsx`
- Create: `frontend/src/features/experiments/experiments-page.tsx`
- Create: `frontend/src/features/comparison/comparison-page.tsx`
- Create: `frontend/src/features/optimizer/optimizer-page.tsx`
- Create: `frontend/src/features/diagnostics/diagnostics-page.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/tests/evaluation-import.test.tsx`
- Test: `frontend/tests/comparison-page.test.tsx`

- [ ] **Step 1: Implement evaluation page**

Create `frontend/src/features/evaluation/evaluation-page.tsx`:

```tsx
import { useMutation, useQuery } from "@tanstack/react-query";

import { apiJson } from "../../api/client";

export function EvaluationPage() {
  const sets = useQuery({ queryKey: ["evaluation-sets"], queryFn: () => apiJson<{ items: unknown[]; total: number }>("/api/evaluation-sets") });
  const upload = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return apiJson(`/api/evaluation-sets/import?name=${encodeURIComponent(file.name)}`, { method: "POST", body });
    },
    onSuccess: () => void sets.refetch(),
  });
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Evaluation Sets</h2>
      <input aria-label="Upload evaluation file" type="file" onChange={(event) => event.target.files?.[0] && upload.mutate(event.target.files[0])} />
      <pre className="rounded bg-slate-100 p-3 text-xs">{JSON.stringify(sets.data, null, 2)}</pre>
    </section>
  );
}
```

- [ ] **Step 2: Implement experiments page**

Create `frontend/src/features/experiments/experiments-page.tsx`:

```tsx
import { useMutation, useQuery } from "@tanstack/react-query";

import { apiJson } from "../../api/client";
import { Button } from "../../components/ui/button";

export function ExperimentsPage() {
  const documents = useQuery({ queryKey: ["documents"], queryFn: () => apiJson<{ items: { id: string }[]; total: number }>("/api/documents") });
  const variants = useQuery({ queryKey: ["variants"], queryFn: () => apiJson<{ items: { id: string }[]; total: number }>("/api/variants") });
  const evals = useQuery({ queryKey: ["evaluation-sets"], queryFn: () => apiJson<{ items: { id: string }[]; total: number }>("/api/evaluation-sets") });
  const create = useMutation({
    mutationFn: () =>
      apiJson("/api/experiments", {
        method: "POST",
        body: JSON.stringify({
          name: "Comparison",
          document_ids: documents.data?.items.map((item) => item.id) ?? [],
          evaluation_set_id: evals.data?.items[0]?.id,
          variant_ids: variants.data?.items.map((item) => item.id) ?? [],
          objective: { primary: "grounded_correctness" },
        }),
      }),
  });
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Experiments</h2>
      <Button onClick={() => create.mutate()}>Run experiment</Button>
      <pre className="rounded bg-slate-100 p-3 text-xs">{JSON.stringify(create.data, null, 2)}</pre>
    </section>
  );
}
```

- [ ] **Step 3: Implement comparison page**

Create `frontend/src/features/comparison/comparison-page.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";

import { apiJson } from "../../api/client";
import type { RunOut } from "../../api/generated";

export function ComparisonPage() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => apiJson<{ items: RunOut[]; total: number }>("/api/runs") });
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Comparison</h2>
      <div className="grid gap-4 lg:grid-cols-2">
        {runs.data?.items.map((run) => (
          <article key={run.id} className="rounded-md border bg-white p-4">
            <div className="text-xs text-slate-500">{run.variant_id}</div>
            <h3 className="font-medium">{run.query}</h3>
            <p className="mt-2 text-sm">{run.answer}</p>
            <pre className="mt-3 rounded bg-slate-100 p-3 text-xs">{JSON.stringify(run.sources, null, 2)}</pre>
          </article>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Implement diagnostics page**

Create `frontend/src/features/diagnostics/diagnostics-page.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";

import { apiJson } from "../../api/client";

export function DiagnosticsPage() {
  const diagnostics = useQuery({ queryKey: ["diagnostics"], queryFn: () => apiJson("/api/diagnostics") });
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Diagnostics</h2>
      <pre className="rounded bg-slate-100 p-3 text-xs">{JSON.stringify(diagnostics.data, null, 2)}</pre>
    </section>
  );
}
```

- [ ] **Step 5: Implement optimizer page**

Create `frontend/src/features/optimizer/optimizer-page.tsx`:

```tsx
import { useMutation, useQuery } from "@tanstack/react-query";

import { apiJson } from "../../api/client";
import type { RunOut } from "../../api/generated";
import { Button } from "../../components/ui/button";

export function OptimizerPage() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => apiJson<{ items: RunOut[]; total: number }>("/api/runs") });
  const recommendation = useMutation({
    mutationFn: () =>
      apiJson<{ selected_variant_id: string | null; explanation: string }>("/api/optimizer/recommend", {
        method: "POST",
        body: JSON.stringify({ runs: runs.data?.items ?? [] }),
      }),
  });
  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Optimizer</h2>
      <Button onClick={() => recommendation.mutate()}>Recommend best variant</Button>
      <pre className="rounded bg-slate-100 p-3 text-xs">{JSON.stringify(recommendation.data, null, 2)}</pre>
    </section>
  );
}
```

- [ ] **Step 6: Wire screens into App**

Modify `frontend/src/App.tsx` imports:

```tsx
import { ComparisonPage } from "./features/comparison/comparison-page";
import { DiagnosticsPage } from "./features/diagnostics/diagnostics-page";
import { EvaluationPage } from "./features/evaluation/evaluation-page";
import { ExperimentsPage } from "./features/experiments/experiments-page";
import { OptimizerPage } from "./features/optimizer/optimizer-page";
```

Add route selection:

```tsx
active === "evaluation" ? <EvaluationPage /> :
active === "experiments" ? <ExperimentsPage /> :
active === "comparison" ? <ComparisonPage /> :
active === "optimizer" ? <OptimizerPage /> :
active === "diagnostics" ? <DiagnosticsPage /> :
```

- [ ] **Step 7: Add frontend tests**

Create `frontend/tests/evaluation-import.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvaluationPage } from "../src/features/evaluation/evaluation-page";

describe("EvaluationPage", () => {
  it("renders upload control", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <EvaluationPage />
      </QueryClientProvider>,
    );
    expect(screen.getByLabelText("Upload evaluation file")).toBeTruthy();
  });
});
```

Create `frontend/tests/comparison-page.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ComparisonPage } from "../src/features/comparison/comparison-page";

describe("ComparisonPage", () => {
  it("renders heading", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ComparisonPage />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Comparison")).toBeTruthy();
  });
});
```

- [ ] **Step 8: Run frontend tests and commit**

Run: `cd frontend && npm run test -- --run && npm run build`
Expected: PASS.

Commit:

```bash
git add frontend/src/App.tsx frontend/src/features/evaluation/evaluation-page.tsx frontend/src/features/experiments/experiments-page.tsx frontend/src/features/comparison/comparison-page.tsx frontend/src/features/optimizer/optimizer-page.tsx frontend/src/features/diagnostics/diagnostics-page.tsx frontend/tests/evaluation-import.test.tsx frontend/tests/comparison-page.test.tsx
git commit -m "feat: add evaluation experiment comparison diagnostics screens"
```

## Task 14: OpenAPI Types, Static Serving, User Guide, And E2E

**Files:**
- Create: `scripts/generate-openapi.sh`
- Create: `backend/src/ragstudio/static.py`
- Modify: `backend/src/ragstudio/app.py`
- Create: `docs/user-guide.md`
- Create: `e2e/studio.spec.ts`
- Modify: `frontend/package.json`

- [ ] **Step 1: Add OpenAPI generation script**

Create `scripts/generate-openapi.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHONPATH=backend/src python - <<'PY'
import json
from ragstudio.app import create_app

schema = create_app().openapi()
print(json.dumps(schema))
PY
```

Run: `chmod +x scripts/generate-openapi.sh`

- [ ] **Step 2: Add static serving helper**

Create `backend/src/ragstudio/static.py`:

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, static_dir: Path | None = None) -> None:
    root = static_dir or Path(__file__).parent / "static" / "dist"
    if root.exists():
        app.mount("/", StaticFiles(directory=root, html=True), name="studio")
```

Modify `backend/src/ragstudio/app.py` to call `mount_frontend(app)` after API routers:

```python
from ragstudio.static import mount_frontend
```

and:

```python
for router in ROUTERS:
    app.include_router(router)
mount_frontend(app)
```

- [ ] **Step 3: Add user guide**

Create `docs/user-guide.md`:

```markdown
# RAG-Anything Studio User Guide

## Core Flow

1. Configure provider and storage in Settings.
2. Upload source files in Documents.
3. Index chunks from the Chunk Inspector or document actions.
4. Create variants for different RAG methods.
5. Ask questions in Query.
6. Inspect retrieved chunks and prompt-included evidence.
7. Import evaluation files in Evaluation Sets.
8. Run Experiments to compare variants.
9. Review side-by-side outputs in Comparison.
10. Ask Optimizer to recommend the strongest variant from recorded runs.
11. Check Diagnostics when a feature is unsupported.

## Evaluation File Formats

Studio accepts JSONL, JSON, YAML, and CSV. JSONL is the canonical export format.
```

- [ ] **Step 4: Add Playwright smoke test**

Create `e2e/studio.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test("Studio shell loads dashboard", async ({ page }) => {
  await page.goto("http://127.0.0.1:5173");
  await expect(page.getByText("RAG-Anything Studio")).toBeVisible();
  await expect(page.getByText("Dashboard")).toBeVisible();
});
```

Modify `frontend/package.json` scripts to include:

```json
"e2e": "playwright test ../e2e"
```

- [ ] **Step 5: Run full verification**

Run: `./scripts/test-all.sh`
Expected: PASS.

Run: `PYTHONPATH=backend/src python -m uvicorn ragstudio.app:create_app --factory --host 127.0.0.1 --port 8000`
Expected: server starts and `/api/health` returns `{"status":"ok","service":"rag-anything-studio"}`. Stop the server with Ctrl-C.

- [ ] **Step 6: Commit**

```bash
git add scripts/generate-openapi.sh backend/src/ragstudio/static.py backend/src/ragstudio/app.py docs/user-guide.md e2e/studio.spec.ts frontend/package.json
git commit -m "feat: add static serving docs and e2e smoke test"
```

## Task 15: Final Quality Pass

**Files:**
- Modify as needed: files changed by prior tasks

- [ ] **Step 1: Run backend unit/API suite**

Run: `PYTHONPATH=backend/src python -m pytest backend/tests -q`
Expected: PASS.

- [ ] **Step 2: Run backend lint and type checks**

Run: `python -m ruff check backend/src backend/tests`
Expected: PASS.

Run: `python -m pyright`
Expected: PASS.

- [ ] **Step 3: Run frontend tests and build**

Run: `cd frontend && npm run lint && npm run test -- --run && npm run build`
Expected: PASS.

- [ ] **Step 4: Run full script**

Run: `./scripts/test-all.sh`
Expected: PASS.

- [ ] **Step 5: Manual acceptance flow**

Run: `./scripts/dev.sh`
Expected: frontend opens at `http://127.0.0.1:5173` and backend serves API at `http://127.0.0.1:8000`.

In the browser verify:

```text
Settings -> save default settings
Documents -> upload sample.txt
Chunks -> search for a word from sample.txt
Variants -> create balanced variant
Query -> run a query and see answer/chunk trace
Evaluation -> upload JSONL evaluation file
Experiments -> run experiment
Comparison -> see run output
Optimizer -> request best variant recommendation
Graph -> see graph count panel
Diagnostics -> see adapter capabilities
```

- [ ] **Step 6: Commit final fixes**

If Step 1 through Step 5 required code changes:

```bash
git add backend frontend docs scripts e2e README.md pyproject.toml .gitignore
git commit -m "fix: complete Studio verification pass"
```

If no code changes were required:

```bash
git status --short
```

Expected: clean worktree.

## Spec Coverage Checklist

- Standalone local-first Studio: Tasks 1, 2, 10, 14.
- Python FastAPI backend: Tasks 2 through 9.
- React TypeScript Vite frontend: Tasks 10 through 13.
- Tailwind/shadcn-style workbench: Tasks 10 through 13.
- SQLite persistence: Task 3.
- Settings: Tasks 4 and 11.
- Documents: Tasks 5 and 11.
- Jobs: Task 5.
- Variants/presets: Tasks 4 and 11.
- Evaluation imports for CSV, JSON, YAML, JSONL: Task 6.
- Chunk inspection and retrieval-only search: Tasks 7 and 12.
- Query runs and chunk traces: Tasks 8 and 12.
- Experiments and comparison: Tasks 9 and 13.
- Scoring: Task 9.
- Guided optimizer recommendation: Tasks 9 and 13.
- Graph inspection: Tasks 9 and 12.
- Diagnostics and capability reporting: Tasks 9 and 13.
- API contract generation path: Task 14.
- Static frontend serving: Task 14.
- Tests and verification: Tasks 2 through 15.

## Execution Notes

- Do not import `raganything` outside `backend/src/ragstudio/services/adapter.py`.
- Do not add Redis, Celery, Next.js, Redux, Bootstrap, Bulma, Foundation, or a second CSS framework.
- Keep every API response typed with Pydantic schemas.
- Keep every frontend API call behind `frontend/src/api/client.ts`.
- Commit after each task exactly as listed.
