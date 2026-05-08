# RAG-Anything Production Runtime Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the production runtime foundation that lets Ragstudio move from SQLite/fallback behavior toward Postgres/PGVector, Neo4j, runtime profiles, health checks, and RAG-Anything-backed indexing/query seams.

**Architecture:** Keep the existing Studio UX and API concepts, but replace scattered fallback decisions with a runtime subsystem. Postgres becomes the default app database and PGVector host, Neo4j becomes the graph store, and `RAGAnythingAdapter` remains the only direct upstream boundary while new services handle runtime profile validation, health, lifecycle, factory construction, and trace normalization.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, Postgres with PGVector, Neo4j, RAG-Anything/LightRAG, httpx, React/Vite, Vitest, pytest.

---

## Scope And Execution Notes

The approved design is platform-sized. This plan implements the foundation in safe slices:

1. Postgres/PGVector and Neo4j local runtime setup.
2. Postgres-first app configuration without implicit SQLite runtime defaults.
3. Runtime profile schema, persistence, and Settings contracts.
4. Runtime health diagnostics.
5. Runtime factory and trace normalization seams.
6. Destructive document reindex through a lifecycle service.
7. Runtime-backed query execution with explicit fallback policy.
8. Frontend contract updates that preserve current Studio pages.

Subagents can work after Task 1 lands, but do not dispatch implementation subagents in parallel against overlapping files. Good split points:

- Backend storage/config worker: Tasks 1-2.
- Runtime profile/health worker: Tasks 3-4.
- Runtime/index/query worker: Tasks 5-7 after Tasks 2-4 land.
- Frontend/docs worker: Task 8 after backend schemas are stable.

## File Structure

Create:

- `docker-compose.yml`: local Postgres/PGVector and Neo4j services.
- `.env.example`: local runtime configuration.
- `backend/src/ragstudio/schemas/runtime.py`: typed runtime profile helpers, health checks, and runtime status contracts.
- `backend/src/ragstudio/services/runtime_profile_service.py`: converts saved settings into normalized runtime profiles.
- `backend/src/ragstudio/services/runtime_health_service.py`: probes runtime dependencies and classifies failures.
- `backend/src/ragstudio/services/runtime_factory.py`: builds fallback or RAG-Anything runtime adapters from profiles.
- `backend/src/ragstudio/services/runtime_types.py`: small dataclasses/protocols shared by runtime services.
- `backend/src/ragstudio/services/trace_normalizer.py`: normalizes runtime chunk/query outputs.
- `backend/src/ragstudio/services/index_lifecycle_service.py`: owns destructive document reindex.
- `backend/tests/test_config.py`: app settings tests.
- `backend/tests/test_runtime_profile_service.py`: runtime profile persistence/normalization tests.
- `backend/tests/test_runtime_health_service.py`: health classification tests.
- `backend/tests/test_trace_normalizer.py`: trace/chunk normalization tests.
- `backend/tests/test_index_lifecycle_service.py`: destructive reindex tests with a fake runtime.
- `backend/tests/test_runtime_query_service.py`: runtime-backed query tests with a fake runtime.

Modify:

- `pyproject.toml`
- `backend/pyproject.toml`
- `scripts/dev.sh`
- `scripts/test-all.sh`
- `backend/src/ragstudio/config.py`
- `backend/src/ragstudio/app.py`
- `backend/src/ragstudio/db/engine.py`
- `backend/src/ragstudio/db/models.py`
- `backend/src/ragstudio/schemas/settings.py`
- `backend/src/ragstudio/schemas/diagnostics.py`
- `backend/src/ragstudio/schemas/chunks.py`
- `backend/src/ragstudio/schemas/runs.py`
- `backend/src/ragstudio/services/settings_service.py`
- `backend/src/ragstudio/services/diagnostics_service.py`
- `backend/src/ragstudio/services/document_service.py`
- `backend/src/ragstudio/services/chunk_service.py`
- `backend/src/ragstudio/services/query_service.py`
- `backend/src/ragstudio/api/routes/chunks.py`
- `backend/tests/conftest.py`
- `backend/tests/test_settings.py`
- `backend/tests/test_chunks.py`
- `backend/tests/test_query_runs.py`
- `frontend/src/api/generated.ts`
- `frontend/src/features/settings/settings-page.tsx`
- `frontend/src/features/diagnostics/diagnostics-page.tsx`
- `frontend/src/features/chunks/chunk-inspector.tsx`
- `frontend/src/features/query/query-page.tsx`
- `docs/workflows.md`
- `README.md`

## Task 1: Local Runtime Stores And App Configuration

**Files:**

- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `backend/tests/test_config.py`
- Modify: `pyproject.toml`
- Modify: `backend/pyproject.toml`
- Modify: `scripts/dev.sh`
- Modify: `scripts/test-all.sh`
- Modify: `backend/src/ragstudio/config.py`
- Modify: `backend/src/ragstudio/app.py`

- [ ] **Step 1: Write config tests for Postgres defaults and explicit test database override**

Create `backend/tests/test_config.py`:

```python
from pathlib import Path

from ragstudio.config import AppSettings


def test_app_settings_default_database_is_postgres():
    settings = AppSettings(data_dir=Path("/tmp/ragstudio-test"))

    assert settings.resolved_database_url.startswith("postgresql+asyncpg://")
    assert "ragstudio" in settings.resolved_database_url
    assert settings.neo4j_uri == "bolt://127.0.0.1:7687"


def test_app_settings_accepts_explicit_database_url():
    settings = AppSettings(
        data_dir=Path("/tmp/ragstudio-test"),
        database_url="sqlite+aiosqlite:////tmp/ragstudio-test.sqlite3",
    )

    assert settings.resolved_database_url == "sqlite+aiosqlite:////tmp/ragstudio-test.sqlite3"
```

- [ ] **Step 2: Run the config tests and verify they fail**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_config.py -q
```

Expected: fail because `AppSettings` still defaults to SQLite and lacks Neo4j settings.

- [ ] **Step 3: Add runtime dependencies**

In both `pyproject.toml` and `backend/pyproject.toml`, keep the existing dependencies and add these entries inside `[project].dependencies`:

```toml
  "asyncpg>=0.31.0",
  "pydantic-settings>=2.12.0",
  "neo4j>=5.28.0",
  "pgvector>=0.4.1",
```

Do not remove `aiosqlite`; explicit SQLite URLs remain useful for fast isolated unit tests while the runtime default moves to Postgres.

- [ ] **Step 4: Add docker-compose services**

Create `docker-compose.yml`:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg17
    container_name: ragstudio-postgres
    environment:
      POSTGRES_DB: ragstudio
      POSTGRES_USER: ragstudio
      POSTGRES_PASSWORD: ragstudio
    ports:
      - "55432:5432"
    volumes:
      - ragstudio-postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ragstudio -d ragstudio"]
      interval: 5s
      timeout: 5s
      retries: 20

  neo4j:
    image: neo4j:5-community
    container_name: ragstudio-neo4j
    environment:
      NEO4J_AUTH: neo4j/ragstudio-password
      NEO4J_dbms_security_auth__enabled: "true"
    ports:
      - "57474:7474"
      - "57687:7687"
    volumes:
      - ragstudio-neo4j-data:/data
      - ragstudio-neo4j-logs:/logs
    healthcheck:
      test:
        [
          "CMD-SHELL",
          "wget --quiet --tries=1 --spider http://127.0.0.1:7474 || exit 1",
        ]
      interval: 10s
      timeout: 5s
      retries: 20

volumes:
  ragstudio-postgres-data:
  ragstudio-neo4j-data:
  ragstudio-neo4j-logs:
```

- [ ] **Step 5: Add environment example**

Create `.env.example`:

```dotenv
RAGSTUDIO_DATABASE_URL=postgresql+asyncpg://ragstudio:ragstudio@127.0.0.1:55432/ragstudio
RAGSTUDIO_DATA_DIR=.ragstudio
RAGSTUDIO_NEO4J_URI=bolt://127.0.0.1:57687
RAGSTUDIO_NEO4J_USERNAME=neo4j
RAGSTUDIO_NEO4J_PASSWORD=ragstudio-password
RAGSTUDIO_PGVECTOR_SCHEMA=public
RAGSTUDIO_PGVECTOR_TABLE_PREFIX=ragstudio
```

- [ ] **Step 6: Replace `AppSettings` with environment-aware Postgres defaults**

Replace `backend/src/ragstudio/config.py` with:

```python
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAGSTUDIO_",
        env_file=".env",
        extra="ignore",
    )

    service_name: str = "rag-anything-studio"
    data_dir: Path = Field(default_factory=lambda: Path(".ragstudio").resolve())
    database_url: str = "postgresql+asyncpg://ragstudio:ragstudio@127.0.0.1:55432/ragstudio"
    pgvector_schema: str = "public"
    pgvector_table_prefix: str = "ragstudio"
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "ragstudio-password"
    runtime_working_dir: Path | None = None

    @field_validator("data_dir", "runtime_working_dir", mode="before")
    @classmethod
    def normalize_path(cls, value: str | Path | None) -> Path | None:
        if value is None:
            return None
        return Path(value).expanduser().resolve()

    @field_validator("pgvector_schema", "pgvector_table_prefix")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Database identifier must not be empty")
        if not normalized.replace("_", "").isalnum():
            raise ValueError("Database identifier may contain only letters, numbers, and underscores")
        return normalized

    @property
    def resolved_database_url(self) -> str:
        return self.database_url

    @property
    def resolved_runtime_working_dir(self) -> Path:
        return self.runtime_working_dir or self.data_dir / "raganything"
```

- [ ] **Step 7: Allow `create_app` to receive explicit database URLs for tests**

Modify `backend/src/ragstudio/app.py` so `create_app` starts like this:

```python
def create_app(data_dir: Path | None = None, database_url: str | None = None) -> FastAPI:
    configure_logging()
    settings = AppSettings()
    if data_dir is not None or database_url is not None:
        update: dict[str, object] = {}
        if data_dir is not None:
            update["data_dir"] = data_dir
        if database_url is not None:
            update["database_url"] = database_url
        settings = settings.model_copy(update=update)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_runtime_working_dir.mkdir(parents=True, exist_ok=True)
```

Leave the rest of `create_app` intact.

- [ ] **Step 8: Update dev/test scripts**

Modify `scripts/dev.sh` before the `uvicorn` command:

```bash
export RAGSTUDIO_DATABASE_URL="${RAGSTUDIO_DATABASE_URL:-postgresql+asyncpg://ragstudio:ragstudio@127.0.0.1:55432/ragstudio}"
export RAGSTUDIO_NEO4J_URI="${RAGSTUDIO_NEO4J_URI:-bolt://127.0.0.1:57687}"
export RAGSTUDIO_NEO4J_USERNAME="${RAGSTUDIO_NEO4J_USERNAME:-neo4j}"
export RAGSTUDIO_NEO4J_PASSWORD="${RAGSTUDIO_NEO4J_PASSWORD:-ragstudio-password}"
```

Modify `scripts/test-all.sh` before pytest:

```bash
export RAGSTUDIO_TEST_DATABASE_URL="${RAGSTUDIO_TEST_DATABASE_URL:-}"
```

- [ ] **Step 9: Run config tests**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_config.py -q
```

Expected: pass.

- [ ] **Step 10: Commit Task 1**

```bash
git add docker-compose.yml .env.example pyproject.toml backend/pyproject.toml scripts/dev.sh scripts/test-all.sh backend/src/ragstudio/config.py backend/src/ragstudio/app.py backend/tests/test_config.py
git commit -m "feat: add production runtime store configuration"
```

## Task 2: Postgres-Aware Engine And Metadata Models

**Files:**

- Create: `backend/tests/test_db_engine.py`
- Modify: `backend/src/ragstudio/db/engine.py`
- Modify: `backend/src/ragstudio/db/models.py`
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Write engine tests**

Create `backend/tests/test_db_engine.py`:

```python
from ragstudio.db.engine import is_postgres_url


def test_is_postgres_url_detects_asyncpg_url():
    assert is_postgres_url("postgresql+asyncpg://ragstudio:ragstudio@127.0.0.1/ragstudio")


def test_is_postgres_url_rejects_sqlite_url():
    assert not is_postgres_url("sqlite+aiosqlite:////tmp/ragstudio.sqlite3")
```

- [ ] **Step 2: Run engine tests and verify they fail**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_db_engine.py -q
```

Expected: fail because `is_postgres_url` does not exist.

- [ ] **Step 3: Replace engine initialization with Postgres-aware extension setup**

Replace `backend/src/ragstudio/db/engine.py` with:

```python
from collections.abc import AsyncIterator

from ragstudio.db.base import Base
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def is_postgres_url(database_url: str) -> bool:
    return make_url(database_url).get_backend_name() == "postgresql"


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, future=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    from ragstudio.db import models as _models  # noqa: F401

    async with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.create_all)


async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session
```

- [ ] **Step 4: Add Postgres-friendly JSON type and runtime metadata columns**

Modify `backend/src/ragstudio/db/models.py` imports:

```python
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
```

Add near the imports:

```python
JsonType = JSON().with_variant(JSONB, "postgresql")
```

Replace each `mapped_column(MutableDict.as_mutable(JSON), default=dict)` with:

```python
mapped_column(MutableDict.as_mutable(JsonType), default=dict)
```

Replace each `mapped_column(MutableList.as_mutable(JSON), default=list)` with:

```python
mapped_column(MutableList.as_mutable(JsonType), default=list)
```

Add these fields to `Chunk`:

```python
    runtime_profile_id: Mapped[str | None] = mapped_column(String, nullable=True)
    runtime_source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    content_type: Mapped[str] = mapped_column(String, default="text")
    preview_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Add these fields to `Run`:

```python
    runtime_profile_id: Mapped[str | None] = mapped_column(String, nullable=True)
    document_ids: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JsonType), default=list)
    query_config: Mapped[dict[str, Any]] = mapped_column(MutableDict.as_mutable(JsonType), default=dict)
    reranker_traces: Mapped[list[dict[str, Any]]] = mapped_column(
        MutableList.as_mutable(JsonType), default=list
    )
    token_metadata: Mapped[dict[str, Any]] = mapped_column(MutableDict.as_mutable(JsonType), default=dict)
    error_type: Mapped[str | None] = mapped_column(String, nullable=True)
```

Add this model after `Chunk`:

```python
class IndexRecord(Base, TimestampMixin):
    __tablename__ = "index_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    runtime_profile_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ready")
    index_shape: Mapped[dict[str, Any]] = mapped_column(MutableDict.as_mutable(JsonType), default=dict)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 5: Update test fixture to pass an explicit test database URL**

Modify `backend/tests/conftest.py`:

```python
from collections.abc import AsyncIterator
import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from ragstudio.app import create_app


@pytest_asyncio.fixture
async def client(tmp_path) -> AsyncIterator[AsyncClient]:
    database_url = os.environ.get(
        "RAGSTUDIO_TEST_DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}",
    )
    app = create_app(data_dir=tmp_path, database_url=database_url)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as test_client:
            yield test_client
```

- [ ] **Step 6: Run backend tests touched by storage**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_db_engine.py backend/tests/test_api_health.py backend/tests/test_settings.py -q
```

Expected: pass after settings tests are adjusted in Task 3. If run before Task 3, only `test_db_engine.py` and `test_api_health.py` must pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add backend/src/ragstudio/db/engine.py backend/src/ragstudio/db/models.py backend/tests/conftest.py backend/tests/test_db_engine.py
git commit -m "feat: prepare postgres metadata storage"
```

## Task 3: Runtime Profile Schema And Persistence

**Files:**

- Create: `backend/src/ragstudio/schemas/runtime.py`
- Create: `backend/src/ragstudio/services/runtime_profile_service.py`
- Create: `backend/tests/test_runtime_profile_service.py`
- Modify: `backend/src/ragstudio/db/models.py`
- Modify: `backend/src/ragstudio/schemas/settings.py`
- Modify: `backend/src/ragstudio/services/settings_service.py`
- Modify: `backend/tests/test_settings.py`

- [ ] **Step 1: Write runtime profile tests**

Create `backend/tests/test_runtime_profile_service.py`:

```python
import pytest

from ragstudio.schemas.settings import SettingsProfileIn
from ragstudio.services.runtime_profile_service import RuntimeProfileService
from ragstudio.services.settings_service import SettingsService


@pytest.mark.asyncio
async def test_runtime_profile_uses_saved_settings(client):
    payload = {
        "provider": "openai-compatible",
        "runtime_mode": "runtime",
        "llm_model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
        "llm_base_url": "http://127.0.0.1:8004/v1",
        "llm_capabilities": ["text", "vision", "reasoning"],
        "embedding_model": "Qwen/Qwen3-Embedding-8B",
        "embedding_provider": "vllm_openai",
        "embedding_base_url": "http://127.0.0.1:8001/v1",
        "embedding_dimensions": 1536,
        "storage_backend": "postgres_pgvector_neo4j",
        "reranker_provider": "cohere_compatible",
        "reranker_model": "BAAI/bge-reranker-v2-m3",
        "reranker_base_url": "http://127.0.0.1:8002/v1/rerank",
        "neo4j_uri": "bolt://127.0.0.1:57687",
        "neo4j_username": "neo4j",
        "neo4j_password": "secret",
        "query_mode": "mix",
        "top_k": 40,
        "chunk_top_k": 20,
    }

    response = await client.put("/api/settings/default", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["runtime_mode"] == "runtime"
    assert body["storage_backend"] == "postgres_pgvector_neo4j"
    assert body["has_neo4j_password"] is True
    assert body["has_reranker_api_key"] is False
    assert "neo4j_password" not in body


@pytest.mark.asyncio
async def test_runtime_profile_service_normalizes_index_shape(client):
    payload = SettingsProfileIn(
        provider="openai-compatible",
        runtime_mode="runtime",
        llm_model="gpt-4o",
        llm_base_url="http://127.0.0.1:8004/v1",
        embedding_model="text-embedding-3-large",
        embedding_dimensions=3072,
        storage_backend="postgres_pgvector_neo4j",
        parser="mineru",
        parse_method="auto",
        chunk_token_size=1200,
        chunk_overlap_token_size=100,
    )
    app = client._transport.app
    async with app.state.session_factory() as session:
        await SettingsService(session).upsert_default(payload)
        profile = await RuntimeProfileService(session, app.state.settings).get_active_profile()

    assert profile.id == "default"
    assert profile.runtime_mode == "runtime"
    assert profile.index_shape == {
        "embedding_model": "text-embedding-3-large",
        "embedding_dimensions": 3072,
        "parser": "mineru",
        "parse_method": "auto",
        "chunk_token_size": 1200,
        "chunk_overlap_token_size": 100,
        "graph_storage": "neo4j",
        "vector_storage": "pgvector",
    }
```

- [ ] **Step 2: Run runtime profile tests and verify they fail**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_runtime_profile_service.py -q
```

Expected: fail because runtime profile fields and service do not exist.

- [ ] **Step 3: Add runtime schema helpers**

Create `backend/src/ragstudio/schemas/runtime.py`:

```python
from typing import Any, Literal

from pydantic import Field

from ragstudio.schemas.common import StudioModel

RuntimeMode = Literal["runtime", "fallback", "degraded"]
RuntimeOverallStatus = Literal["ready", "degraded", "failed", "fallback"]
RuntimeCheckStatus = Literal["ok", "warning", "failed", "skipped"]
RuntimeCheckSeverity = Literal["info", "warning", "blocking"]
StorageBackend = Literal["postgres_pgvector_neo4j", "fallback_local"]
RerankerProvider = Literal["disabled", "cohere_compatible", "jina_compatible", "generic_http"]
QueryMode = Literal["mix", "hybrid", "local", "global", "naive"]


class RuntimeHealthCheck(StudioModel):
    name: str
    status: RuntimeCheckStatus
    severity: RuntimeCheckSeverity = "info"
    latency_ms: int | None = None
    detail: str
    error_type: str | None = None
    remediation: str | None = None


class RuntimeProfile(StudioModel):
    id: str
    runtime_mode: RuntimeMode
    provider: str
    llm_model: str
    llm_base_url: str | None = None
    llm_timeout_ms: int
    llm_capabilities: list[str] = Field(default_factory=list)
    vision_model: str | None = None
    vision_base_url: str | None = None
    vision_timeout_ms: int
    embedding_provider: str
    embedding_model: str
    embedding_base_url: str | None = None
    embedding_dimensions: int
    embedding_batch_size: int
    embedding_timeout_ms: int
    reranker_provider: RerankerProvider
    reranker_model: str | None = None
    reranker_base_url: str | None = None
    reranker_timeout_ms: int
    storage_backend: StorageBackend
    pgvector_schema: str
    pgvector_table_prefix: str
    neo4j_uri: str | None = None
    neo4j_username: str | None = None
    parser: str
    parse_method: str
    chunk_token_size: int
    chunk_overlap_token_size: int
    enable_image_processing: bool
    enable_table_processing: bool
    enable_equation_processing: bool
    context_window: int
    context_mode: str
    max_context_tokens: int
    include_headers: bool
    include_captions: bool
    query_mode: QueryMode
    top_k: int
    chunk_top_k: int
    enable_rerank: bool
    cosine_better_than_threshold: float
    max_total_tokens: int
    max_entity_tokens: int
    max_relation_tokens: int
    enable_llm_cache: bool
    enable_llm_cache_for_entity_extract: bool
    llm_model_max_async: int
    embedding_func_max_async: int
    max_parallel_insert: int
    runtime_working_dir: str
    index_shape: dict[str, Any]
```

- [ ] **Step 4: Extend `SettingsProfile` model with runtime fields**

Add these fields to `SettingsProfile` in `backend/src/ragstudio/db/models.py`:

```python
    runtime_mode: Mapped[str] = mapped_column(String, default="runtime")
    vision_model: Mapped[str | None] = mapped_column(String, nullable=True)
    vision_base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    vision_api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    vision_timeout_ms: Mapped[int] = mapped_column(Integer, default=10000)
    reranker_provider: Mapped[str] = mapped_column(String, default="disabled")
    reranker_model: Mapped[str | None] = mapped_column(String, nullable=True)
    reranker_base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    reranker_api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    reranker_timeout_ms: Mapped[int] = mapped_column(Integer, default=10000)
    pgvector_schema: Mapped[str] = mapped_column(String, default="public")
    pgvector_table_prefix: Mapped[str] = mapped_column(String, default="ragstudio")
    neo4j_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    neo4j_username: Mapped[str | None] = mapped_column(String, nullable=True)
    neo4j_password: Mapped[str | None] = mapped_column(String, nullable=True)
    parser: Mapped[str] = mapped_column(String, default="mineru")
    parse_method: Mapped[str] = mapped_column(String, default="auto")
    chunk_token_size: Mapped[int] = mapped_column(Integer, default=1200)
    chunk_overlap_token_size: Mapped[int] = mapped_column(Integer, default=100)
    enable_image_processing: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_table_processing: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_equation_processing: Mapped[bool] = mapped_column(Boolean, default=True)
    context_window: Mapped[int] = mapped_column(Integer, default=1)
    context_mode: Mapped[str] = mapped_column(String, default="page")
    max_context_tokens: Mapped[int] = mapped_column(Integer, default=2000)
    include_headers: Mapped[bool] = mapped_column(Boolean, default=True)
    include_captions: Mapped[bool] = mapped_column(Boolean, default=True)
    query_mode: Mapped[str] = mapped_column(String, default="mix")
    top_k: Mapped[int] = mapped_column(Integer, default=40)
    chunk_top_k: Mapped[int] = mapped_column(Integer, default=20)
    enable_rerank: Mapped[bool] = mapped_column(Boolean, default=True)
    cosine_better_than_threshold: Mapped[float] = mapped_column(default=0.2)
    max_total_tokens: Mapped[int] = mapped_column(Integer, default=30000)
    max_entity_tokens: Mapped[int] = mapped_column(Integer, default=6000)
    max_relation_tokens: Mapped[int] = mapped_column(Integer, default=8000)
    enable_llm_cache: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_llm_cache_for_entity_extract: Mapped[bool] = mapped_column(Boolean, default=True)
    llm_model_max_async: Mapped[int] = mapped_column(Integer, default=4)
    embedding_func_max_async: Mapped[int] = mapped_column(Integer, default=8)
    max_parallel_insert: Mapped[int] = mapped_column(Integer, default=2)
```

Also import `Float` from SQLAlchemy and change `cosine_better_than_threshold` to:

```python
    cosine_better_than_threshold: Mapped[float] = mapped_column(Float, default=0.2)
```

- [ ] **Step 5: Extend settings schemas**

Add imports in `backend/src/ragstudio/schemas/settings.py`:

```python
from ragstudio.schemas.runtime import (
    QueryMode,
    RerankerProvider,
    RuntimeMode,
    StorageBackend,
)
```

Add fields to `SettingsProfileIn`:

```python
    runtime_mode: RuntimeMode = "runtime"
    vision_model: str | None = None
    vision_base_url: str | None = None
    vision_api_key: str | None = None
    vision_timeout_ms: int = Field(default=10000, ge=100, le=1_800_000)
    reranker_provider: RerankerProvider = "disabled"
    reranker_model: str | None = None
    reranker_base_url: str | None = None
    reranker_api_key: str | None = None
    reranker_timeout_ms: int = Field(default=10000, ge=100, le=1_800_000)
    pgvector_schema: str = "public"
    pgvector_table_prefix: str = "ragstudio"
    neo4j_uri: str | None = None
    neo4j_username: str | None = None
    neo4j_password: str | None = None
    parser: str = "mineru"
    parse_method: str = "auto"
    chunk_token_size: int = Field(default=1200, ge=100, le=8192)
    chunk_overlap_token_size: int = Field(default=100, ge=0, le=2048)
    enable_image_processing: bool = True
    enable_table_processing: bool = True
    enable_equation_processing: bool = True
    context_window: int = Field(default=1, ge=0, le=10)
    context_mode: str = "page"
    max_context_tokens: int = Field(default=2000, ge=100, le=100000)
    include_headers: bool = True
    include_captions: bool = True
    query_mode: QueryMode = "mix"
    top_k: int = Field(default=40, ge=1, le=200)
    chunk_top_k: int = Field(default=20, ge=1, le=200)
    enable_rerank: bool = True
    cosine_better_than_threshold: float = Field(default=0.2, ge=0, le=1)
    max_total_tokens: int = Field(default=30000, ge=1000, le=1000000)
    max_entity_tokens: int = Field(default=6000, ge=0, le=1000000)
    max_relation_tokens: int = Field(default=8000, ge=0, le=1000000)
    enable_llm_cache: bool = True
    enable_llm_cache_for_entity_extract: bool = True
    llm_model_max_async: int = Field(default=4, ge=1, le=128)
    embedding_func_max_async: int = Field(default=8, ge=1, le=128)
    max_parallel_insert: int = Field(default=2, ge=1, le=64)
```

Add URL validators for `vision_base_url`, `reranker_base_url`, and `neo4j_uri`. Use `_validate_http_base_url` for HTTP fields. For Neo4j:

```python
    @field_validator("neo4j_uri")
    @classmethod
    def validate_neo4j_uri(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        parsed = urlparse(normalized)
        if parsed.scheme not in {"bolt", "neo4j", "neo4j+s", "bolt+s"} or not parsed.netloc:
            raise ValueError("Neo4j URI must use bolt, neo4j, neo4j+s, or bolt+s")
        return normalized
```

Add these fields to `SettingsProfileOut`:

```python
    runtime_mode: RuntimeMode
    vision_model: str | None
    vision_base_url: str | None
    has_vision_api_key: bool
    vision_timeout_ms: int
    reranker_provider: RerankerProvider
    reranker_model: str | None
    reranker_base_url: str | None
    has_reranker_api_key: bool
    reranker_timeout_ms: int
    pgvector_schema: str
    pgvector_table_prefix: str
    neo4j_uri: str | None
    neo4j_username: str | None
    has_neo4j_password: bool
    parser: str
    parse_method: str
    chunk_token_size: int
    chunk_overlap_token_size: int
    enable_image_processing: bool
    enable_table_processing: bool
    enable_equation_processing: bool
    context_window: int
    context_mode: str
    max_context_tokens: int
    include_headers: bool
    include_captions: bool
    query_mode: QueryMode
    top_k: int
    chunk_top_k: int
    enable_rerank: bool
    cosine_better_than_threshold: float
    max_total_tokens: int
    max_entity_tokens: int
    max_relation_tokens: int
    enable_llm_cache: bool
    enable_llm_cache_for_entity_extract: bool
    llm_model_max_async: int
    embedding_func_max_async: int
    max_parallel_insert: int
```

- [ ] **Step 6: Update `SettingsService` secret handling and output mapping**

In `backend/src/ragstudio/services/settings_service.py`, change `values` creation:

```python
        values = data.model_dump(
            exclude={
                "embedding_api_key",
                "llm_api_key",
                "vision_api_key",
                "reranker_api_key",
                "neo4j_password",
            }
        )
```

After LLM/embedding secret updates, add:

```python
        if data.vision_api_key is not None:
            profile.vision_api_key = data.vision_api_key or None
        if data.reranker_api_key is not None:
            profile.reranker_api_key = data.reranker_api_key or None
        if data.neo4j_password is not None:
            profile.neo4j_password = data.neo4j_password or None
```

Extend `_to_out` by mapping each new field from `profile`, casting literal fields where needed and using the same defaults defined in `SettingsProfileIn`.

- [ ] **Step 7: Add `RuntimeProfileService`**

Create `backend/src/ragstudio/services/runtime_profile_service.py`:

```python
from pathlib import Path
from typing import cast

from ragstudio.config import AppSettings
from ragstudio.db.models import SettingsProfile
from ragstudio.schemas.runtime import RuntimeMode, RuntimeProfile
from sqlalchemy.ext.asyncio import AsyncSession


class RuntimeProfileNotConfiguredError(RuntimeError):
    pass


class RuntimeProfileService:
    def __init__(self, session: AsyncSession, settings: AppSettings):
        self.session = session
        self.settings = settings

    async def get_active_profile(self) -> RuntimeProfile:
        profile = await self.session.get(SettingsProfile, "default")
        if profile is None:
            raise RuntimeProfileNotConfiguredError("Default runtime profile is not configured.")

        runtime_working_dir = Path(self.settings.resolved_runtime_working_dir)
        runtime_working_dir.mkdir(parents=True, exist_ok=True)
        index_shape = {
            "embedding_model": profile.embedding_model,
            "embedding_dimensions": profile.embedding_dimensions or 1536,
            "parser": profile.parser or "mineru",
            "parse_method": profile.parse_method or "auto",
            "chunk_token_size": profile.chunk_token_size or 1200,
            "chunk_overlap_token_size": profile.chunk_overlap_token_size or 100,
            "graph_storage": "neo4j",
            "vector_storage": "pgvector",
        }

        return RuntimeProfile(
            id=profile.id,
            runtime_mode=cast(RuntimeMode, profile.runtime_mode or "runtime"),
            provider=profile.provider,
            llm_model=profile.llm_model,
            llm_base_url=profile.llm_base_url,
            llm_timeout_ms=profile.llm_timeout_ms or 10000,
            llm_capabilities=profile.llm_capabilities or [],
            vision_model=profile.vision_model,
            vision_base_url=profile.vision_base_url,
            vision_timeout_ms=profile.vision_timeout_ms or 10000,
            embedding_provider=profile.embedding_provider or "fallback",
            embedding_model=profile.embedding_model,
            embedding_base_url=profile.embedding_base_url,
            embedding_dimensions=profile.embedding_dimensions or 1536,
            embedding_batch_size=profile.embedding_batch_size or 16,
            embedding_timeout_ms=profile.embedding_timeout_ms or 10000,
            reranker_provider=profile.reranker_provider or "disabled",
            reranker_model=profile.reranker_model,
            reranker_base_url=profile.reranker_base_url,
            reranker_timeout_ms=profile.reranker_timeout_ms or 10000,
            storage_backend=profile.storage_backend or "postgres_pgvector_neo4j",
            pgvector_schema=profile.pgvector_schema or self.settings.pgvector_schema,
            pgvector_table_prefix=profile.pgvector_table_prefix or self.settings.pgvector_table_prefix,
            neo4j_uri=profile.neo4j_uri or self.settings.neo4j_uri,
            neo4j_username=profile.neo4j_username or self.settings.neo4j_username,
            parser=profile.parser or "mineru",
            parse_method=profile.parse_method or "auto",
            chunk_token_size=profile.chunk_token_size or 1200,
            chunk_overlap_token_size=profile.chunk_overlap_token_size or 100,
            enable_image_processing=bool(profile.enable_image_processing),
            enable_table_processing=bool(profile.enable_table_processing),
            enable_equation_processing=bool(profile.enable_equation_processing),
            context_window=profile.context_window or 1,
            context_mode=profile.context_mode or "page",
            max_context_tokens=profile.max_context_tokens or 2000,
            include_headers=bool(profile.include_headers),
            include_captions=bool(profile.include_captions),
            query_mode=profile.query_mode or "mix",
            top_k=profile.top_k or 40,
            chunk_top_k=profile.chunk_top_k or 20,
            enable_rerank=bool(profile.enable_rerank),
            cosine_better_than_threshold=profile.cosine_better_than_threshold or 0.2,
            max_total_tokens=profile.max_total_tokens or 30000,
            max_entity_tokens=profile.max_entity_tokens or 6000,
            max_relation_tokens=profile.max_relation_tokens or 8000,
            enable_llm_cache=bool(profile.enable_llm_cache),
            enable_llm_cache_for_entity_extract=bool(profile.enable_llm_cache_for_entity_extract),
            llm_model_max_async=profile.llm_model_max_async or 4,
            embedding_func_max_async=profile.embedding_func_max_async or 8,
            max_parallel_insert=profile.max_parallel_insert or 2,
            runtime_working_dir=str(runtime_working_dir),
            index_shape=index_shape,
        )
```

Add `RuntimeMode` to the imports from `ragstudio.schemas.runtime` so the cast above is typed consistently.

- [ ] **Step 8: Update existing settings tests**

In `backend/tests/test_settings.py`, change payloads that use:

```python
"storage_backend": "sqlite"
```

to:

```python
"storage_backend": "postgres_pgvector_neo4j"
```

Add assertions for defaults in `test_settings_profile_round_trip`:

```python
    assert read_response.json()["runtime_mode"] == "runtime"
    assert read_response.json()["query_mode"] == "mix"
    assert read_response.json()["top_k"] == 40
```

- [ ] **Step 9: Run settings/profile tests**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_settings.py backend/tests/test_runtime_profile_service.py -q
```

Expected: pass.

- [ ] **Step 10: Commit Task 3**

```bash
git add backend/src/ragstudio/schemas/runtime.py backend/src/ragstudio/services/runtime_profile_service.py backend/src/ragstudio/db/models.py backend/src/ragstudio/schemas/settings.py backend/src/ragstudio/services/settings_service.py backend/tests/test_settings.py backend/tests/test_runtime_profile_service.py
git commit -m "feat: add runtime profile settings"
```

## Task 4: Runtime Health Diagnostics

**Files:**

- Create: `backend/src/ragstudio/services/runtime_health_service.py`
- Create: `backend/tests/test_runtime_health_service.py`
- Modify: `backend/src/ragstudio/schemas/diagnostics.py`
- Modify: `backend/src/ragstudio/services/diagnostics_service.py`
- Modify: `backend/src/ragstudio/api/routes/diagnostics.py`

- [ ] **Step 1: Write health service tests**

Create `backend/tests/test_runtime_health_service.py`:

```python
import pytest

from ragstudio.schemas.runtime import RuntimeHealthCheck, RuntimeProfile
from ragstudio.services.runtime_health_service import RuntimeHealthService


def profile(**overrides):
    data = {
        "id": "default",
        "runtime_mode": "runtime",
        "provider": "openai-compatible",
        "llm_model": "gpt-4o",
        "llm_base_url": "http://127.0.0.1:8004/v1",
        "llm_timeout_ms": 10000,
        "llm_capabilities": ["text", "vision"],
        "vision_model": None,
        "vision_base_url": None,
        "vision_timeout_ms": 10000,
        "embedding_provider": "vllm_openai",
        "embedding_model": "text-embedding-3-large",
        "embedding_base_url": "http://127.0.0.1:8001/v1",
        "embedding_dimensions": 3072,
        "embedding_batch_size": 32,
        "embedding_timeout_ms": 10000,
        "reranker_provider": "disabled",
        "reranker_model": None,
        "reranker_base_url": None,
        "reranker_timeout_ms": 10000,
        "storage_backend": "postgres_pgvector_neo4j",
        "pgvector_schema": "public",
        "pgvector_table_prefix": "ragstudio",
        "neo4j_uri": "bolt://127.0.0.1:57687",
        "neo4j_username": "neo4j",
        "parser": "mineru",
        "parse_method": "auto",
        "enable_image_processing": True,
        "enable_table_processing": True,
        "enable_equation_processing": True,
        "context_window": 1,
        "context_mode": "page",
        "max_context_tokens": 2000,
        "include_headers": True,
        "include_captions": True,
        "query_mode": "mix",
        "top_k": 40,
        "chunk_top_k": 20,
        "enable_rerank": True,
        "cosine_better_than_threshold": 0.2,
        "max_total_tokens": 30000,
        "max_entity_tokens": 6000,
        "max_relation_tokens": 8000,
        "enable_llm_cache": True,
        "enable_llm_cache_for_entity_extract": True,
        "llm_model_max_async": 4,
        "embedding_func_max_async": 8,
        "max_parallel_insert": 2,
        "runtime_working_dir": "/tmp/ragstudio-runtime",
        "index_shape": {},
    }
    data.update(overrides)
    return RuntimeProfile(**data)


@pytest.mark.asyncio
async def test_runtime_health_marks_missing_required_urls_as_blocking():
    checks = await RuntimeHealthService().check(profile(llm_base_url=None))

    llm = next(item for item in checks if item.name == "llm")
    assert llm.status == "failed"
    assert llm.severity == "blocking"
    assert llm.error_type == "configuration"


@pytest.mark.asyncio
async def test_runtime_health_skips_disabled_reranker():
    checks = await RuntimeHealthService().check(profile(reranker_provider="disabled"))

    reranker = next(item for item in checks if item.name == "reranker")
    assert reranker.status == "skipped"
    assert reranker.severity == "info"
```

- [ ] **Step 2: Run health tests and verify they fail**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_runtime_health_service.py -q
```

Expected: fail because `RuntimeHealthService` does not exist.

- [ ] **Step 3: Implement health service**

Create `backend/src/ragstudio/services/runtime_health_service.py`:

```python
from importlib.util import find_spec
from typing import Iterable

from ragstudio.schemas.runtime import RuntimeHealthCheck, RuntimeProfile


class RuntimeHealthService:
    async def check(self, profile: RuntimeProfile | None) -> list[RuntimeHealthCheck]:
        if profile is None:
            return [
                RuntimeHealthCheck(
                    name="runtime_profile",
                    status="failed",
                    severity="blocking",
                    detail="Default runtime profile is not configured.",
                    error_type="configuration",
                    remediation="Save Settings before indexing or querying.",
                )
            ]

        checks = [
            self._package_check("raganything", "RAG-Anything package"),
            self._package_check("lightrag", "LightRAG package"),
            self._required_url_check("llm", profile.llm_base_url, "LLM base URL"),
            self._vision_check(profile),
            self._required_url_check("embedding", profile.embedding_base_url, "Embedding base URL"),
            self._reranker_check(profile),
            self._required_text_check("pgvector", profile.pgvector_schema, "PGVector schema"),
            self._required_url_check("neo4j", profile.neo4j_uri, "Neo4j URI"),
            self._required_text_check("parser", profile.parser, "Parser"),
        ]
        return checks

    def blocking_failures(self, checks: Iterable[RuntimeHealthCheck]) -> list[RuntimeHealthCheck]:
        return [item for item in checks if item.status == "failed" and item.severity == "blocking"]

    def _package_check(self, module: str, label: str) -> RuntimeHealthCheck:
        if find_spec(module) is None:
            return RuntimeHealthCheck(
                name=module,
                status="failed",
                severity="blocking",
                detail=f"{label} is not installed in this Python environment.",
                error_type="dependency_import",
                remediation="Run ./scripts/setup.sh.",
            )
        return RuntimeHealthCheck(name=module, status="ok", detail=f"{label} is importable.")

    def _required_url_check(self, name: str, value: str | None, label: str) -> RuntimeHealthCheck:
        if not value:
            return RuntimeHealthCheck(
                name=name,
                status="failed",
                severity="blocking",
                detail=f"{label} is not configured.",
                error_type="configuration",
            )
        return RuntimeHealthCheck(name=name, status="ok", detail=f"{label} is configured.")

    def _required_text_check(self, name: str, value: str | None, label: str) -> RuntimeHealthCheck:
        if not value:
            return RuntimeHealthCheck(
                name=name,
                status="failed",
                severity="blocking",
                detail=f"{label} is not configured.",
                error_type="configuration",
            )
        return RuntimeHealthCheck(name=name, status="ok", detail=f"{label} is configured.")

    def _vision_check(self, profile: RuntimeProfile) -> RuntimeHealthCheck:
        if "vision" in profile.llm_capabilities:
            return RuntimeHealthCheck(
                name="vision",
                status="ok",
                detail="Vision is available through the configured LLM endpoint.",
            )
        if profile.vision_base_url:
            return RuntimeHealthCheck(name="vision", status="ok", detail="Vision endpoint is configured.")
        return RuntimeHealthCheck(
            name="vision",
            status="warning",
            severity="warning",
            detail="No vision-capable endpoint is configured.",
            error_type="capability_mismatch",
        )

    def _reranker_check(self, profile: RuntimeProfile) -> RuntimeHealthCheck:
        if profile.reranker_provider == "disabled":
            return RuntimeHealthCheck(
                name="reranker",
                status="skipped",
                detail="Reranker is disabled for this profile.",
            )
        if not profile.reranker_base_url:
            return RuntimeHealthCheck(
                name="reranker",
                status="failed",
                severity="blocking",
                detail="Reranker is enabled but no base URL is configured.",
                error_type="configuration",
            )
        return RuntimeHealthCheck(name="reranker", status="ok", detail="Reranker endpoint is configured.")
```

- [ ] **Step 4: Extend diagnostics schema**

Replace `backend/src/ragstudio/schemas/diagnostics.py` with:

```python
from typing import Any

from ragstudio.schemas.common import StudioModel
from ragstudio.schemas.runtime import RuntimeHealthCheck, RuntimeOverallStatus


class DiagnosticsOut(StudioModel):
    capabilities: dict[str, bool]
    dependency_status: dict[str, Any]
    warnings: list[str]
    runtime_mode: str = "fallback"
    overall_status: RuntimeOverallStatus = "fallback"
    checks: list[RuntimeHealthCheck] = []
```

- [ ] **Step 5: Use runtime health in diagnostics service**

Modify `DiagnosticsService` so `__init__` accepts `session` and `settings`, then `get_diagnostics` becomes async:

```python
class DiagnosticsService:
    def __init__(
        self,
        session,
        settings,
        adapter: RAGAnythingAdapter | None = None,
        health_service: RuntimeHealthService | None = None,
    ):
        self.session = session
        self.settings = settings
        self.adapter = adapter or RAGAnythingAdapter()
        self.health_service = health_service or RuntimeHealthService()

    async def get_diagnostics(self) -> DiagnosticsOut:
        report = self.adapter.capability_report()
        profile = None
        warnings = []
        try:
            profile = await RuntimeProfileService(self.session, self.settings).get_active_profile()
        except RuntimeProfileNotConfiguredError as exc:
            warnings.append(str(exc))
        checks = await self.health_service.check(profile)
        blocking = self.health_service.blocking_failures(checks)
        runtime_mode = profile.runtime_mode if profile else "fallback"
        overall_status = "ready"
        if runtime_mode == "fallback":
            overall_status = "fallback"
        elif blocking:
            overall_status = "failed"
        elif any(item.status == "warning" for item in checks):
            overall_status = "degraded"

        if not bool(report.get("raganything_available")):
            warnings.append(
                "raganything dependency is not installed in this Python environment; runtime mode cannot execute."
            )

        return DiagnosticsOut(
            capabilities={
                "raganything_available": bool(report.get("raganything_available")),
                "fallback_active": runtime_mode == "fallback",
                "indexing": not blocking,
                "query": not blocking,
                "graph": any(item.name == "neo4j" and item.status == "ok" for item in checks),
            },
            dependency_status=self._dependency_status(report),
            warnings=warnings,
            runtime_mode=runtime_mode,
            overall_status=overall_status,
            checks=checks,
        )
```

Add imports:

```python
from ragstudio.schemas.diagnostics import DiagnosticsOut
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_profile_service import (
    RuntimeProfileNotConfiguredError,
    RuntimeProfileService,
)
```

- [ ] **Step 6: Update diagnostics route**

Modify `backend/src/ragstudio/api/routes/diagnostics.py`:

```python
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.diagnostics import DiagnosticsOut
from ragstudio.services.diagnostics_service import DiagnosticsService

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("", response_model=DiagnosticsOut)
async def get_diagnostics(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> DiagnosticsOut:
    return await DiagnosticsService(session, request.app.state.settings).get_diagnostics()
```

- [ ] **Step 7: Run diagnostics tests**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_runtime_health_service.py backend/tests/test_api_health.py -q
```

Expected: pass.

- [ ] **Step 8: Commit Task 4**

```bash
git add backend/src/ragstudio/services/runtime_health_service.py backend/src/ragstudio/schemas/diagnostics.py backend/src/ragstudio/services/diagnostics_service.py backend/src/ragstudio/api/routes/diagnostics.py backend/tests/test_runtime_health_service.py
git commit -m "feat: add runtime health diagnostics"
```

## Task 5: Runtime Factory And Trace Normalization

**Files:**

- Create: `backend/src/ragstudio/services/runtime_types.py`
- Create: `backend/src/ragstudio/services/runtime_factory.py`
- Create: `backend/src/ragstudio/services/trace_normalizer.py`
- Create: `backend/tests/test_trace_normalizer.py`
- Modify: `backend/src/ragstudio/services/adapter.py`

- [ ] **Step 1: Write trace normalizer tests**

Create `backend/tests/test_trace_normalizer.py`:

```python
from ragstudio.services.runtime_types import RuntimeChunk, RuntimeQueryResult
from ragstudio.services.trace_normalizer import TraceNormalizer


def test_normalize_chunk_adds_runtime_metadata():
    chunk = RuntimeChunk(
        text="Evidence text",
        source_location={"page": 2},
        metadata={"score": 0.93},
        runtime_source_id="runtime-chunk-1",
        content_type="text",
        preview_ref=None,
    )

    normalized = TraceNormalizer().chunk_to_adapter_chunk(
        chunk,
        document_id="doc-1",
        runtime_profile_id="default",
        index_shape={"embedding_model": "text-embedding-3-large"},
    )

    assert normalized.text == "Evidence text"
    assert normalized.metadata["runtime_profile_id"] == "default"
    assert normalized.metadata["runtime_source_id"] == "runtime-chunk-1"
    assert normalized.metadata["index_shape"]["embedding_model"] == "text-embedding-3-large"


def test_normalize_query_result_keeps_reranker_and_token_metadata():
    result = RuntimeQueryResult(
        answer="Grounded answer",
        sources=[{"chunk_id": "chunk-1"}],
        chunk_traces=[{"rank": 1}],
        reranker_traces=[{"rank": 1, "score": 0.99}],
        timings={"query_ms": 12},
        token_metadata={"prompt_tokens": 10},
        error=None,
        error_type=None,
    )

    normalized = TraceNormalizer().query_result(result)

    assert normalized["answer"] == "Grounded answer"
    assert normalized["reranker_traces"][0]["score"] == 0.99
    assert normalized["token_metadata"]["prompt_tokens"] == 10
```

- [ ] **Step 2: Run normalizer tests and verify they fail**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_trace_normalizer.py -q
```

Expected: fail because runtime types and normalizer do not exist.

- [ ] **Step 3: Add runtime dataclasses and protocol**

Create `backend/src/ragstudio/services/runtime_types.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class RuntimeChunk:
    text: str
    source_location: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    runtime_source_id: str | None = None
    content_type: str = "text"
    preview_ref: str | None = None


@dataclass(frozen=True)
class RuntimeQueryResult:
    answer: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    chunk_traces: list[dict[str, Any]] = field(default_factory=list)
    reranker_traces: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, Any] = field(default_factory=dict)
    token_metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_type: str | None = None


class RuntimeAdapter(Protocol):
    def capability_report(self) -> dict[str, Any]:
        raise NotImplementedError

    async def index_document(self, artifact_path: str | Path) -> list[RuntimeChunk]:
        raise NotImplementedError

    async def query(
        self,
        query: str,
        *,
        document_ids: list[str],
        query_config: dict[str, Any],
    ) -> RuntimeQueryResult:
        raise NotImplementedError

    async def delete_document_index(self, document_id: str) -> None:
        raise NotImplementedError
```

- [ ] **Step 4: Implement trace normalizer**

Create `backend/src/ragstudio/services/trace_normalizer.py`:

```python
from typing import Any

from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.runtime_types import RuntimeChunk, RuntimeQueryResult


class TraceNormalizer:
    def chunk_to_adapter_chunk(
        self,
        chunk: RuntimeChunk,
        *,
        document_id: str,
        runtime_profile_id: str,
        index_shape: dict[str, Any],
    ) -> AdapterChunk:
        metadata = {
            **chunk.metadata,
            "runtime_profile_id": runtime_profile_id,
            "runtime_source_id": chunk.runtime_source_id,
            "document_id": document_id,
            "content_type": chunk.content_type,
            "preview_ref": chunk.preview_ref,
            "index_shape": index_shape,
            "mirrored_snapshot": True,
        }
        return AdapterChunk(
            text=chunk.text,
            source_location=chunk.source_location,
            metadata=metadata,
        )

    def query_result(self, result: RuntimeQueryResult) -> dict[str, Any]:
        return {
            "answer": result.answer,
            "sources": result.sources,
            "chunk_traces": result.chunk_traces,
            "reranker_traces": result.reranker_traces,
            "timings": result.timings,
            "token_metadata": result.token_metadata,
            "error": result.error,
            "error_type": result.error_type,
        }
```

- [ ] **Step 5: Update fallback adapter to satisfy runtime protocol**

Modify `backend/src/ragstudio/services/adapter.py`:

```python
from ragstudio.services.runtime_types import RuntimeChunk, RuntimeQueryResult
```

Add method:

```python
    async def delete_document_index(self, document_id: str) -> None:
        return None
```

Change `index_document` return type to `list[RuntimeChunk]`, and construct `RuntimeChunk` instead of `AdapterChunk`. Keep `AdapterChunk` defined for existing chunk persistence.

Change `query` signature to:

```python
    async def query(
        self,
        query: str,
        chunks: list[AdapterChunk] | None = None,
        limit: int = 10,
        *,
        document_ids: list[str] | None = None,
        query_config: dict[str, Any] | None = None,
    ) -> dict[str, Any] | RuntimeQueryResult:
```

Keep old chunk-based behavior when `chunks` is provided. When `chunks` is `None`, return:

```python
        return RuntimeQueryResult(
            answer="",
            timings={},
            error="Fallback runtime query requires mirrored chunks.",
            error_type="fallback_runtime_without_chunks",
        )
```

- [ ] **Step 6: Add runtime factory**

Create `backend/src/ragstudio/services/runtime_factory.py`:

```python
from importlib.util import find_spec

from ragstudio.schemas.runtime import RuntimeProfile
from ragstudio.services.adapter import RAGAnythingAdapter
from ragstudio.services.runtime_types import RuntimeAdapter


class RuntimeUnavailableError(RuntimeError):
    pass


class RAGAnythingRuntimeFactory:
    def build(self, profile: RuntimeProfile) -> RuntimeAdapter:
        if profile.runtime_mode == "fallback":
            return RAGAnythingAdapter()
        if find_spec("raganything") is None:
            raise RuntimeUnavailableError("raganything package is not installed.")
        return RAGAnythingAdapter()
```

This returns the fallback adapter for the first seam. Later tasks replace the runtime branch with a real RAG-Anything wrapper while tests use a fake factory.

- [ ] **Step 7: Run normalizer tests**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_trace_normalizer.py -q
```

Expected: pass.

- [ ] **Step 8: Commit Task 5**

```bash
git add backend/src/ragstudio/services/runtime_types.py backend/src/ragstudio/services/runtime_factory.py backend/src/ragstudio/services/trace_normalizer.py backend/src/ragstudio/services/adapter.py backend/tests/test_trace_normalizer.py
git commit -m "feat: add runtime factory seams"
```

## Task 6: Destructive Document Reindex Lifecycle

**Files:**

- Create: `backend/src/ragstudio/services/index_lifecycle_service.py`
- Create: `backend/tests/test_index_lifecycle_service.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Modify: `backend/src/ragstudio/services/document_service.py`
- Modify: `backend/src/ragstudio/api/routes/chunks.py`
- Modify: `backend/src/ragstudio/schemas/chunks.py`
- Modify: `backend/tests/test_chunks.py`

- [ ] **Step 1: Write lifecycle tests with a fake runtime**

Create `backend/tests/test_index_lifecycle_service.py`:

```python
import pytest

from ragstudio.db.models import Chunk, Document, SettingsProfile
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.index_lifecycle_service import IndexLifecycleService
from ragstudio.services.runtime_types import RuntimeChunk
from sqlalchemy import select


class FakeRuntime:
    def __init__(self):
        self.deleted = []

    def capability_report(self):
        return {"active_backend": "runtime", "raganything_available": True}

    async def delete_document_index(self, document_id):
        self.deleted.append(document_id)

    async def index_document(self, artifact_path):
        return [
            RuntimeChunk(
                text="Runtime chunk",
                source_location={"page": 1},
                metadata={"score": 1.0},
                runtime_source_id="runtime-1",
            )
        ]


class FakeFactory:
    def __init__(self, runtime):
        self.runtime = runtime

    def build(self, profile):
        return self.runtime


@pytest.mark.asyncio
async def test_lifecycle_deletes_existing_chunks_and_mirrors_runtime_chunks(client):
    app = client._transport.app
    runtime = FakeRuntime()
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
            )
        )
        document = Document(
            filename="doc.txt",
            content_type="text/plain",
            sha256="abc",
            artifact_path=str(app.state.settings.data_dir / "doc.txt"),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.flush()
        session.add(Chunk(document_id=document.id, text="old", source_location={}, metadata_json={}))
        await session.commit()

        chunks = await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(runtime),
        ).reindex_document(document.id, options=IndexDocumentIn())

        remaining = await session.execute(select(Chunk).where(Chunk.document_id == document.id))
        stored = remaining.scalars().all()

    assert runtime.deleted == [document.id]
    assert [chunk.text for chunk in chunks] == ["Runtime chunk"]
    assert len(stored) == 1
    assert stored[0].metadata_json["mirrored_snapshot"] is True
    assert stored[0].runtime_profile_id == "default"
```

- [ ] **Step 2: Run lifecycle tests and verify they fail**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_index_lifecycle_service.py -q
```

Expected: fail because `IndexLifecycleService` does not exist.

- [ ] **Step 3: Extend chunk schema with mirrored fields**

Modify `backend/src/ragstudio/schemas/chunks.py`:

```python
class ChunkOut(StudioModel):
    id: str
    document_id: str
    text: str
    source_location: dict[str, Any]
    metadata: dict[str, Any] = Field(
        validation_alias=AliasChoices("metadata_json", "metadata"),
        serialization_alias="metadata",
    )
    runtime_profile_id: str | None = None
    runtime_source_id: str | None = None
    content_type: str = "text"
    preview_ref: str | None = None
    indexed_at: str | None = None
```

If Pydantic rejects datetime-to-string conversion, type `indexed_at` as `datetime | None` and import `datetime`.

- [ ] **Step 4: Implement index lifecycle service**

Create `backend/src/ragstudio/services/index_lifecycle_service.py`:

```python
from datetime import UTC, datetime

from ragstudio.config import AppSettings
from ragstudio.db.models import Chunk, Document, IndexRecord
from ragstudio.schemas.chunks import ChunkOut
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.runtime_factory import RAGAnythingRuntimeFactory
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_profile_service import RuntimeProfileService
from ragstudio.services.trace_normalizer import TraceNormalizer
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession


class RuntimeHealthBlockedError(RuntimeError):
    pass


class IndexLifecycleService:
    def __init__(
        self,
        session: AsyncSession,
        settings: AppSettings,
        *,
        runtime_factory=None,
        health_service: RuntimeHealthService | None = None,
        normalizer: TraceNormalizer | None = None,
    ):
        self.session = session
        self.settings = settings
        self.runtime_factory = runtime_factory or RAGAnythingRuntimeFactory()
        self.health_service = health_service or RuntimeHealthService()
        self.normalizer = normalizer or TraceNormalizer()

    async def reindex_document(
        self,
        document_id: str,
        *,
        options: IndexDocumentIn | None = None,
    ) -> list[ChunkOut] | None:
        document = await self.session.get(Document, document_id)
        if document is None:
            return None
        profile = await RuntimeProfileService(self.session, self.settings).get_active_profile()
        if profile.runtime_mode != "fallback":
            checks = await self.health_service.check(profile)
            blocking = self.health_service.blocking_failures(checks)
            if blocking:
                details = "; ".join(f"{item.name}: {item.detail}" for item in blocking)
                raise RuntimeHealthBlockedError(details)

        runtime = self.runtime_factory.build(profile)
        document.status = StageStatus.RUNNING.value
        await runtime.delete_document_index(document.id)
        await self.session.execute(delete(Chunk).where(Chunk.document_id == document.id))
        await self.session.execute(delete(IndexRecord).where(IndexRecord.document_id == document.id))

        runtime_chunks = await runtime.index_document(document.artifact_path)
        indexed_at = datetime.now(UTC)
        chunks = []
        for runtime_chunk in runtime_chunks:
            adapter_chunk = self.normalizer.chunk_to_adapter_chunk(
                runtime_chunk,
                document_id=document.id,
                runtime_profile_id=profile.id,
                index_shape=profile.index_shape,
            )
            chunks.append(
                Chunk(
                    document_id=document.id,
                    text=adapter_chunk.text,
                    source_location=adapter_chunk.source_location,
                    metadata_json=adapter_chunk.metadata,
                    runtime_profile_id=profile.id,
                    runtime_source_id=adapter_chunk.metadata.get("runtime_source_id"),
                    content_type=str(adapter_chunk.metadata.get("content_type") or "text"),
                    preview_ref=adapter_chunk.metadata.get("preview_ref"),
                    indexed_at=indexed_at,
                )
            )
        self.session.add_all(chunks)
        self.session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id=profile.id,
                status=StageStatus.SUCCEEDED.value,
                index_shape=profile.index_shape,
                chunk_count=len(chunks),
            )
        )
        document.status = StageStatus.SUCCEEDED.value
        await self.session.flush()
        for chunk in chunks:
            await self.session.refresh(chunk)
        return [ChunkOut.model_validate(chunk) for chunk in chunks]
```

- [ ] **Step 5: Route direct chunk indexing through lifecycle service**

Modify `backend/src/ragstudio/api/routes/chunks.py` direct indexing endpoint:

```python
from ragstudio.services.index_lifecycle_service import IndexLifecycleService
```

Replace the body of `index_document_chunks` with:

```python
    chunks = await IndexLifecycleService(session, request.app.state.settings).reindex_document(
        document_id,
        options=options or IndexDocumentIn(),
    )
```

Keep the 404 behavior.

- [ ] **Step 6: Fix background job database URL propagation**

In `create_index_document_job`, pass `request.app.state.settings` to the background task:

```python
        request.app.state.settings,
```

Change `_run_index_document_job` signature:

```python
async def _run_index_document_job(
    settings: AppSettings,
    document_id: str,
    job_id: str,
    options: IndexDocumentIn,
) -> None:
    engine = make_engine(settings.resolved_database_url)
    factory = make_session_factory(engine)
    try:
        async with factory() as background_session:
            await DocumentService(background_session, settings.data_dir, settings=settings).run_index_job(
                document_id,
                job_id,
                options,
            )
    finally:
        await engine.dispose()
```

- [ ] **Step 7: Let `DocumentService` use lifecycle service**

Change `DocumentService.__init__` signature:

```python
    def __init__(self, session: AsyncSession, data_dir: Path, settings=None):
        self.session = session
        self.store = ArtifactStore(data_dir)
        self.settings = settings
```

In `_index_document_for_job`, replace the existing `ChunkService(self.session, self.store.root).index_document` call with:

```python
        if self.settings is not None:
            chunks = await IndexLifecycleService(self.session, self.settings).reindex_document(
                document.id,
                options=options,
            )
        else:
            chunks = await ChunkService(self.session, self.store.root).index_document(
                document.id,
                options=options,
                commit=False,
                on_mineru_status=on_mineru_status,
            )
```

Add import:

```python
from ragstudio.services.index_lifecycle_service import IndexLifecycleService
```

- [ ] **Step 8: Run lifecycle and chunk tests**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_index_lifecycle_service.py backend/tests/test_chunks.py -q
```

Expected: lifecycle test passes. Existing chunk tests may need metadata expectation updates because default indexing now uses runtime mode when settings exist. Preserve fallback tests by creating a default settings profile with `runtime_mode="fallback"` in those tests or by using `ChunkService` unit tests directly.

- [ ] **Step 9: Commit Task 6**

```bash
git add backend/src/ragstudio/services/index_lifecycle_service.py backend/src/ragstudio/services/chunk_service.py backend/src/ragstudio/services/document_service.py backend/src/ragstudio/api/routes/chunks.py backend/src/ragstudio/schemas/chunks.py backend/tests/test_index_lifecycle_service.py backend/tests/test_chunks.py
git commit -m "feat: add runtime index lifecycle"
```

## Task 7: Runtime-Backed Query Execution

**Files:**

- Create: `backend/tests/test_runtime_query_service.py`
- Modify: `backend/src/ragstudio/services/query_service.py`
- Modify: `backend/src/ragstudio/schemas/runs.py`
- Modify: `backend/src/ragstudio/db/models.py`
- Modify: `backend/tests/test_query_runs.py`

- [ ] **Step 1: Write runtime query tests with fake runtime**

Create `backend/tests/test_runtime_query_service.py`:

```python
import pytest

from ragstudio.db.models import Document, IndexRecord, SettingsProfile, Variant
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.query import QueryIn
from ragstudio.services.query_service import QueryService
from ragstudio.services.runtime_types import RuntimeQueryResult


class FakeRuntime:
    def capability_report(self):
        return {"active_backend": "runtime", "raganything_available": True}

    async def delete_document_index(self, document_id):
        return None

    async def index_document(self, artifact_path):
        return []

    async def query(self, query, *, document_ids, query_config):
        return RuntimeQueryResult(
            answer=f"runtime answer: {query}",
            sources=[{"document_id": document_ids[0], "text": "source"}],
            chunk_traces=[{"rank": 1, "inclusion_status": "prompt-included"}],
            reranker_traces=[{"rank": 1, "score": 0.9}],
            timings={"runtime_query_ms": 5},
            token_metadata={"prompt_tokens": 11},
        )


class FakeFactory:
    def build(self, profile):
        return FakeRuntime()


@pytest.mark.asyncio
async def test_query_service_uses_runtime_without_chunk_search(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        settings = SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="gpt-4o",
            llm_base_url="http://127.0.0.1:8004/v1",
            embedding_model="text-embedding-3-large",
            embedding_base_url="http://127.0.0.1:8001/v1",
            storage_backend="postgres_pgvector_neo4j",
            runtime_mode="runtime",
        )
        document = Document(
            filename="doc.txt",
            content_type="text/plain",
            sha256="runtime-query",
            artifact_path=str(app.state.settings.data_dir / "doc.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        variant = Variant(name="Runtime", preset="balanced", parameters={"top_k": 12})
        session.add_all([settings, document, variant])
        await session.flush()
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status=StageStatus.SUCCEEDED.value,
                index_shape={"embedding_model": "text-embedding-3-large"},
                chunk_count=1,
            )
        )
        await session.commit()

        result = await QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(),
        ).run_query(
            QueryIn(query="What happened?", document_ids=[document.id], variant_ids=[variant.id])
        )

    run = result.runs[0]
    assert run.status == StageStatus.SUCCEEDED
    assert run.answer == "runtime answer: What happened?"
    assert run.runtime_profile_id == "default"
    assert run.document_ids == [document.id]
    assert run.query_config["top_k"] == 12
    assert run.reranker_traces[0]["score"] == 0.9
    assert run.token_metadata["prompt_tokens"] == 11
```

- [ ] **Step 2: Run runtime query tests and verify they fail**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_runtime_query_service.py -q
```

Expected: fail because `QueryService` does not accept runtime settings/factory and `RunOut` lacks fields.

- [ ] **Step 3: Extend run schema**

Modify `backend/src/ragstudio/schemas/runs.py`:

```python
class RunOut(StudioModel):
    id: str
    variant_id: str
    experiment_id: str | None
    query: str
    status: StageStatus
    answer: str
    sources: list[dict[str, Any]]
    chunk_traces: list[dict[str, Any]]
    timings: dict[str, Any]
    error: str | None
    runtime_profile_id: str | None = None
    document_ids: list[str] = []
    query_config: dict[str, Any] = {}
    reranker_traces: list[dict[str, Any]] = []
    token_metadata: dict[str, Any] = {}
    error_type: str | None = None
```

- [ ] **Step 4: Compile variant parameters into query config**

In `backend/src/ragstudio/services/query_service.py`, add:

```python
    def _query_config(self, profile, variant: Variant, limit: int) -> dict[str, Any]:
        parameters = variant.parameters or {}
        return {
            "mode": parameters.get("mode", profile.query_mode),
            "top_k": int(parameters.get("top_k", profile.top_k)),
            "chunk_top_k": int(parameters.get("chunk_top_k", profile.chunk_top_k)),
            "enable_rerank": bool(parameters.get("enable_rerank", profile.enable_rerank)),
            "max_total_tokens": int(parameters.get("max_total_tokens", profile.max_total_tokens)),
            "max_context_tokens": int(parameters.get("max_context_tokens", profile.max_context_tokens)),
            "cosine_better_than_threshold": float(
                parameters.get(
                    "cosine_better_than_threshold",
                    profile.cosine_better_than_threshold,
                )
            ),
            "limit": limit,
        }
```

- [ ] **Step 5: Add runtime factory dependencies to `QueryService`**

Change `QueryService.__init__`:

```python
    def __init__(
        self,
        session: AsyncSession,
        data_dir: Path,
        adapter: RAGAnythingAdapter | None = None,
        *,
        settings=None,
        runtime_factory=None,
        health_service=None,
        normalizer=None,
    ):
        self.session = session
        self.data_dir = data_dir
        self.adapter = adapter or RAGAnythingAdapter()
        self.settings = settings
        self.runtime_factory = runtime_factory or RAGAnythingRuntimeFactory()
        self.health_service = health_service or RuntimeHealthService()
        self.normalizer = normalizer or TraceNormalizer()
```

Add imports:

```python
from ragstudio.db.models import Document, IndexRecord, Run, Variant
from ragstudio.services.runtime_factory import RAGAnythingRuntimeFactory
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_profile_service import RuntimeProfileService
from ragstudio.services.trace_normalizer import TraceNormalizer
```

- [ ] **Step 6: Add indexed document readiness check**

Add method:

```python
    async def _validate_index_readiness(self, document_ids: list[str], runtime_profile_id: str) -> None:
        if not document_ids:
            return
        result = await self.session.execute(
            select(IndexRecord.document_id).where(
                IndexRecord.document_id.in_(document_ids),
                IndexRecord.runtime_profile_id == runtime_profile_id,
                IndexRecord.status == StageStatus.SUCCEEDED.value,
            )
        )
        ready = set(result.scalars().all())
        missing = [document_id for document_id in document_ids if document_id not in ready]
        if missing:
            raise QueryResourceNotFoundError("Runtime index", missing)
```

- [ ] **Step 7: Use runtime path when settings are available**

At the start of `run_query`, after `_validate_query_inputs`, add:

```python
        if self.settings is not None:
            return await self._run_runtime_query(payload)
```

Add `_run_runtime_query`:

```python
    async def _run_runtime_query(self, payload: QueryIn) -> QueryOut:
        profile = await RuntimeProfileService(self.session, self.settings).get_active_profile()
        checks = await self.health_service.check(profile)
        blocking = self.health_service.blocking_failures(checks)
        if profile.runtime_mode != "fallback" and blocking:
            return await self._failed_runtime_runs(payload, profile.id, blocking)
        if profile.runtime_mode != "fallback":
            await self._validate_index_readiness(payload.document_ids, profile.id)
        runtime = self.runtime_factory.build(profile)
        variants = await self._variants_by_id(payload.variant_ids)
        runs: list[Run] = []
        for variant_id in payload.variant_ids:
            variant = variants[variant_id]
            started_at = perf_counter()
            query_config = self._query_config(profile, variant, payload.limit)
            run = Run(
                variant_id=variant_id,
                query=payload.query,
                status=StageStatus.RUNNING.value,
                runtime_profile_id=profile.id,
                document_ids=payload.document_ids,
                query_config=query_config,
            )
            self.session.add(run)
            try:
                runtime_result = await runtime.query(
                    payload.query,
                    document_ids=payload.document_ids,
                    query_config=query_config,
                )
                normalized = self.normalizer.query_result(runtime_result)
                run.status = StageStatus.SUCCEEDED.value if not normalized.get("error") else StageStatus.FAILED.value
                run.answer = str(normalized.get("answer") or "")
                run.sources = self._result_list(normalized.get("sources"))
                run.chunk_traces = self._result_list(normalized.get("chunk_traces"))
                run.reranker_traces = self._result_list(normalized.get("reranker_traces"))
                run.token_metadata = normalized.get("token_metadata") or {}
                run.error = normalized.get("error")
                run.error_type = normalized.get("error_type")
                timings = normalized.get("timings") or {}
                run.timings = {**timings, "total_ms": self._elapsed_ms(started_at)}
            except Exception as exc:
                run.status = StageStatus.FAILED.value
                run.error = str(exc)
                run.error_type = exc.__class__.__name__
                run.timings = {"total_ms": self._elapsed_ms(started_at)}
            runs.append(run)
        await self.session.commit()
        for run in runs:
            await self.session.refresh(run)
        return QueryOut(runs=[RunOut.model_validate(run) for run in runs])
```

Add helper:

```python
    async def _variants_by_id(self, variant_ids: list[str]) -> dict[str, Variant]:
        result = await self.session.execute(select(Variant).where(Variant.id.in_(variant_ids)))
        return {variant.id: variant for variant in result.scalars().all()}
```

Add failed runtime helper:

```python
    async def _failed_runtime_runs(self, payload, runtime_profile_id, checks) -> QueryOut:
        detail = "; ".join(f"{item.name}: {item.detail}" for item in checks)
        runs = [
            Run(
                variant_id=variant_id,
                query=payload.query,
                status=StageStatus.FAILED.value,
                runtime_profile_id=runtime_profile_id,
                document_ids=payload.document_ids,
                error=detail,
                error_type="runtime_health_blocked",
            )
            for variant_id in payload.variant_ids
        ]
        self.session.add_all(runs)
        await self.session.commit()
        for run in runs:
            await self.session.refresh(run)
        return QueryOut(runs=[RunOut.model_validate(run) for run in runs])
```

- [ ] **Step 8: Run runtime query tests**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_runtime_query_service.py backend/tests/test_query_runs.py -q
```

Expected: pass after existing query tests are adjusted to use explicit fallback settings or accept new runtime fields.

- [ ] **Step 9: Commit Task 7**

```bash
git add backend/src/ragstudio/services/query_service.py backend/src/ragstudio/schemas/runs.py backend/src/ragstudio/db/models.py backend/tests/test_runtime_query_service.py backend/tests/test_query_runs.py
git commit -m "feat: route queries through runtime profiles"
```

## Task 8: Frontend Contracts, Copy, And Documentation

**Files:**

- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/features/settings/settings-page.tsx`
- Modify: `frontend/src/features/diagnostics/diagnostics-page.tsx`
- Modify: `frontend/src/features/chunks/chunk-inspector.tsx`
- Modify: `frontend/src/features/query/query-page.tsx`
- Modify: `docs/workflows.md`
- Modify: `README.md`
- Modify: `backend/tests/test_settings.py`
- Modify: `frontend/tests/settings-page.test.tsx`
- Modify: `frontend/tests/pipeline-builder.test.tsx`
- Modify: `frontend/tests/chunk-inspector.test.tsx`
- Modify: `frontend/tests/chunk-reindex.test.tsx`
- Modify: `frontend/tests/comparison-page.test.tsx`
- Modify: `frontend/tests/optimizer-page.test.tsx`

- [ ] **Step 1: Update generated API types**

In `frontend/src/api/generated.ts`, add:

```ts
export type RuntimeMode = "runtime" | "fallback" | "degraded";
export type RuntimeOverallStatus = "ready" | "degraded" | "failed" | "fallback";
export type RuntimeCheckStatus = "ok" | "warning" | "failed" | "skipped";
export type RuntimeCheckSeverity = "info" | "warning" | "blocking";
export type StorageBackend = "postgres_pgvector_neo4j" | "fallback_local";
export type RerankerProvider = "disabled" | "cohere_compatible" | "jina_compatible" | "generic_http";
export type QueryMode = "mix" | "hybrid" | "local" | "global" | "naive";

export interface RuntimeHealthCheck {
  name: string;
  status: RuntimeCheckStatus;
  severity: RuntimeCheckSeverity;
  latency_ms?: number | null;
  detail: string;
  error_type?: string | null;
  remediation?: string | null;
}
```

Extend `SettingsProfileIn`, `SettingsProfileOut`, `DiagnosticsOut`, `ChunkOut`, and `RunOut` to match backend schema fields from Tasks 3, 4, 6, and 7.

- [ ] **Step 2: Update Settings page sections**

In `frontend/src/features/settings/settings-page.tsx`, keep the existing form but add inputs for:

- `runtime_mode`
- `storage_backend`
- `pgvector_schema`
- `pgvector_table_prefix`
- `neo4j_uri`
- `neo4j_username`
- `neo4j_password`
- `vision_model`
- `vision_base_url`
- `reranker_provider`
- `reranker_model`
- `reranker_base_url`
- `query_mode`
- `top_k`
- `chunk_top_k`
- `enable_rerank`
- `max_total_tokens`
- `parser`
- `parse_method`
- `include_headers`
- `include_captions`

Use existing input/select/toggle components. Do not add explanatory marketing copy. Labels should be operational, such as `Runtime mode`, `Storage backend`, `Neo4j URI`, and `Reranker provider`.

- [ ] **Step 3: Update Diagnostics page**

In `frontend/src/features/diagnostics/diagnostics-page.tsx`, render:

```tsx
<StatusBadge status={diagnosticsQuery.data.overall_status} />
```

Render `diagnosticsQuery.data.checks` as rows with `name`, `status`, `severity`, and `detail`. Keep raw diagnostics JSON visible.

- [ ] **Step 4: Update Chunks page copy**

In `frontend/src/features/chunks/chunk-inspector.tsx`, change the main empty/result copy from generic chunks to mirrored snapshots:

```tsx
<EmptyState icon={Search} title="No mirrored chunks matched" description="Index selected documents through the active runtime profile." />
```

In `ChunkCard`, show badges for `runtime_profile_id`, `content_type`, and `metadata.mirrored_snapshot`.

- [ ] **Step 5: Update Query page run details**

In `frontend/src/features/query/query-page.tsx`, show for each run:

- runtime profile id
- query config JSON
- reranker traces JSON when present
- token metadata JSON when present
- error type when failed

Keep the current question/documents/variants flow intact.

- [ ] **Step 6: Update docs**

In `README.md`, change the development section:

```markdown
Start local runtime stores first:

```bash
docker compose up -d postgres neo4j
./scripts/setup.sh
./scripts/dev.sh
```
```

In `docs/workflows.md`, replace the SQLite storage sentence with:

```markdown
The target runtime stores Studio metadata in Postgres, vector retrieval data through PGVector, and graph retrieval state in Neo4j. Local development uses the repository docker-compose services. Uploaded artifacts and parser outputs still live under `.ragstudio/`.
```

- [ ] **Step 7: Run frontend tests**

Run:

```bash
npm --prefix frontend run test -- --run
npm --prefix frontend run lint
```

Expected: pass.

- [ ] **Step 8: Run backend focused tests**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_settings.py backend/tests/test_runtime_health_service.py backend/tests/test_index_lifecycle_service.py backend/tests/test_runtime_query_service.py -q
```

Expected: pass.

- [ ] **Step 9: Commit Task 8**

```bash
git add frontend/src/api/generated.ts frontend/src/features/settings/settings-page.tsx frontend/src/features/diagnostics/diagnostics-page.tsx frontend/src/features/chunks/chunk-inspector.tsx frontend/src/features/query/query-page.tsx README.md docs/workflows.md frontend/tests backend/tests
git commit -m "feat: expose runtime profile state in studio"
```

## Task 9: Full Verification And Release Notes

**Files:**

- Modify: `CHANGELOG.md`
- Modify: `docs/workflows.md`

- [ ] **Step 1: Update changelog**

Add under `## Unreleased` in `CHANGELOG.md`:

```markdown
- Added the production runtime foundation for RAG-Anything: Postgres/PGVector defaults, Neo4j local runtime service, runtime profile fields, health diagnostics, mirrored chunk metadata, destructive runtime reindex seams, and runtime-backed query traces.
```

- [ ] **Step 2: Run full backend quality checks**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests -q
python -m ruff check backend/src backend/tests
python -m pyright
```

Expected: pass.

- [ ] **Step 3: Run full frontend checks**

Run:

```bash
npm --prefix frontend run lint
npm --prefix frontend run test -- --run
npm --prefix frontend run build
```

Expected: pass.

- [ ] **Step 4: Run optional runtime store smoke check when Docker is available**

Run:

```bash
docker compose up -d postgres neo4j
PYTHONPATH=backend/src RAGSTUDIO_DATABASE_URL=postgresql+asyncpg://ragstudio:ragstudio@127.0.0.1:55432/ragstudio python -m pytest backend/tests/test_db_engine.py -q
docker compose ps
```

Expected: tests pass and both services report healthy or running.

- [ ] **Step 5: Commit verification docs**

```bash
git add CHANGELOG.md docs/workflows.md
git commit -m "docs: document production runtime foundation"
```

## Self-Review Checklist

- Spec coverage: Tasks cover Postgres default, PGVector extension setup, Neo4j configuration, runtime profiles, health checks, factory seams, destructive reindex, mirrored chunks, runtime-backed query traces, frontend visibility, docs, and tests.
- Fallback policy: Production runtime paths fail explicitly on blocking health checks. Fallback remains explicit through `runtime_mode="fallback"` and test-only explicit database URLs.
- Type consistency: Runtime fields use the same names across models, schemas, generated TypeScript, services, and tests.
- Execution risk: The actual live RAG-Anything wrapper is deliberately isolated behind `RAGAnythingRuntimeFactory`; this plan first lands the seams and fake-runtime tests, then future tasks can deepen upstream method mapping without breaking Studio pages.
