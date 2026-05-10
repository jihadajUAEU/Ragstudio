# Runtime Fallback Consistency Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove inconsistent fallback, compatibility, and duplicate indexing paths so Ragstudio has one clear runtime policy, one parser pipeline, and one reindex API.

**Architecture:** Centralize runtime/parser policy in one backend module, extract MinerU/local parsing into one shared parser service, then make document reindex jobs the canonical indexing entrypoint. Runtime mode should fail clearly when native runtime requirements are missing instead of silently answering from fallback query or graph behavior.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async sessions, Pydantic models, pytest/pytest-asyncio, React + TypeScript + Vite, Vitest.

---

## Scope

This plan implements all audit findings:

1. Duplicate indexing/reindex APIs.
2. Duplicate MinerU parsing and fallback implementations.
3. Legacy local fallback adapter as a runtime mode.
4. Native scoped-query metadata fallback.
5. Old constructor compatibility shims.
6. Runtime/settings normalization duplicated across layers.
7. Fallback graph placeholder vs metadata graph behavior.
8. Parser defaults scattered across frontend/backend.

The cleanup is intentionally staged so each task has one testable behavior change and a commit point.

## File Structure

Create:

- `backend/src/ragstudio/services/runtime_policy.py`
  - Owns canonical constants and normalization helpers for runtime mode, storage backend, parser mode, embedding provider, and reranker fallback provider.
- `backend/src/ragstudio/services/document_parser_service.py`
  - Owns local line-split parsing, MinerU strict parsing, and MinerU-with-local-fallback parsing for both fallback and runtime indexing paths.

Modify:

- `backend/src/ragstudio/services/runtime_profile_service.py`
  - Use `runtime_policy.py` instead of local normalization helpers.
- `backend/src/ragstudio/services/settings_service.py`
  - Use `runtime_policy.py` instead of duplicate normalization helpers.
- `backend/src/ragstudio/schemas/parsing.py`
  - Import parser constants and keep schema-owned default in one place.
- `backend/src/ragstudio/schemas/settings.py`
  - Import runtime/storage/provider defaults from policy.
- `backend/src/ragstudio/services/chunk_service.py`
  - Delegate all document parsing to `DocumentParserService`.
- `backend/src/ragstudio/services/index_lifecycle_service.py`
  - Delegate all document parsing to `DocumentParserService`; remove `inspect.signature` runtime compatibility branch.
- `backend/src/ragstudio/services/adapter.py`
  - Remove fake runtime query/graph behavior; keep only local parser compatibility until `ChunkService` no longer needs it, then remove adapter dependency from services where possible.
- `backend/src/ragstudio/services/runtime_factory.py`
  - Stop returning fallback runtime adapter for runtime-mode execution.
- `backend/src/ragstudio/services/query_service.py`
  - Make runtime mode fail on scoped native limitations; remove fallback runtime query path when settings are absent or default profile is missing.
- `backend/src/ragstudio/services/retrieval_orchestrator.py`
  - Remove metadata fallback for `native_document_scope_unsupported`.
- `backend/src/ragstudio/services/native_raganything_adapter.py`
  - Report scoped query storage-filter support as required and expose failures as query failures.
- `backend/src/ragstudio/services/graph_service.py`
  - Remove placeholder adapter graph path and make relationship-metadata graph the fallback-mode behavior.
- `backend/src/ragstudio/services/diagnostics_service.py`
  - Update fallback graph wording to match relationship-metadata graph behavior.
- `backend/src/ragstudio/api/routes/chunks.py`
  - Remove duplicate indexing job route and synchronous index route; keep search route.
- `backend/src/ragstudio/api/routes/documents.py`
  - Keep document reindex as the canonical background job endpoint; use shared runtime-health helper directly.
- `frontend/src/api/client.ts`
  - Point reindex API calls to `POST /api/documents/{id}/reindex`; remove client methods for deleted chunk index endpoints.
- `frontend/src/features/documents/documents-page.tsx`
  - Use canonical parser default and canonical reindex endpoint.
- `frontend/src/features/chunks/chunk-inspector.tsx`
  - Use canonical parser default and canonical reindex endpoint.
- `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`
  - Import parser default constant from frontend API/types layer.
- `frontend/src/features/settings/settings-page.tsx`
  - Align UI defaults with backend runtime policy.
- `docs/user-guide.md`
  - Remove references to fake fallback query/placeholder graph and duplicate indexing endpoints.

Test:

- `backend/tests/test_runtime_policy.py`
- `backend/tests/test_document_parser_service.py`
- Existing tests:
  - `backend/tests/test_settings.py`
  - `backend/tests/test_config.py`
  - `backend/tests/test_documents.py`
  - `backend/tests/test_chunks.py`
  - `backend/tests/test_mineru_reindex_jobs.py`
  - `backend/tests/test_query_runs.py`
  - `backend/tests/test_retrieval_orchestrator.py`
  - `backend/tests/test_graph.py`
  - `frontend/tests/documents-page.test.tsx`
  - `frontend/tests/chunk-reindex.test.tsx`
  - `frontend/tests/settings-page.test.tsx`

---

### Task 1: Centralize Runtime And Parser Policy

**Files:**
- Create: `backend/src/ragstudio/services/runtime_policy.py`
- Modify: `backend/src/ragstudio/services/runtime_profile_service.py`
- Modify: `backend/src/ragstudio/services/settings_service.py`
- Modify: `backend/src/ragstudio/schemas/parsing.py`
- Modify: `backend/src/ragstudio/schemas/settings.py`
- Test: `backend/tests/test_runtime_policy.py`
- Test: `backend/tests/test_settings.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: Write failing runtime policy tests**

Create `backend/tests/test_runtime_policy.py`:

```python
from ragstudio.services.runtime_policy import (
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_PARSER_MODE,
    DEFAULT_RUNTIME_MODE,
    DEFAULT_STORAGE_BACKEND,
    normalize_embedding_provider,
    normalize_parser_mode,
    normalize_runtime_mode,
    normalize_storage_backend,
)


def test_runtime_policy_defaults_are_explicit():
    assert DEFAULT_RUNTIME_MODE == "runtime"
    assert DEFAULT_STORAGE_BACKEND == "postgres_pgvector_neo4j"
    assert DEFAULT_PARSER_MODE == "mineru_strict"
    assert DEFAULT_EMBEDDING_PROVIDER == "vllm_openai"


def test_fallback_storage_forces_fallback_runtime():
    assert normalize_runtime_mode("runtime", "fallback_local") == "fallback"


def test_invalid_runtime_storage_and_provider_values_use_runtime_defaults():
    assert normalize_runtime_mode("nonsense", "postgres_pgvector_neo4j") == "runtime"
    assert normalize_storage_backend("nonsense") == "postgres_pgvector_neo4j"
    assert normalize_parser_mode("nonsense") == "mineru_strict"
    assert normalize_embedding_provider("nonsense") == "vllm_openai"
```

- [ ] **Step 2: Run policy test to verify it fails**

Run:

```bash
docker compose run --rm --no-deps backend python -m pytest backend/tests/test_runtime_policy.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.runtime_policy'`.

- [ ] **Step 3: Add runtime policy module**

Create `backend/src/ragstudio/services/runtime_policy.py`:

```python
from typing import cast

from ragstudio.schemas.parsing import ParserMode
from ragstudio.schemas.runtime import RuntimeMode, StorageBackend
from ragstudio.schemas.settings import EmbeddingProvider

DEFAULT_RUNTIME_MODE: RuntimeMode = "runtime"
DEFAULT_STORAGE_BACKEND: StorageBackend = "postgres_pgvector_neo4j"
DEFAULT_PARSER_MODE: ParserMode = "mineru_strict"
DEFAULT_EMBEDDING_PROVIDER: EmbeddingProvider = "vllm_openai"

VALID_RUNTIME_MODES = {"runtime", "fallback", "degraded"}
VALID_STORAGE_BACKENDS = {"postgres_pgvector_neo4j", "fallback_local"}
VALID_PARSER_MODES = {"local_fallback", "mineru_strict", "mineru_with_fallback"}
VALID_EMBEDDING_PROVIDERS = {"fallback", "vllm_openai"}


def normalize_storage_backend(value: str | None) -> StorageBackend:
    if value in VALID_STORAGE_BACKENDS:
        return cast(StorageBackend, value)
    return DEFAULT_STORAGE_BACKEND


def normalize_runtime_mode(value: str | None, storage_backend: str | None) -> RuntimeMode:
    normalized_storage = normalize_storage_backend(storage_backend)
    if normalized_storage == "fallback_local":
        return "fallback"
    if value in VALID_RUNTIME_MODES:
        return cast(RuntimeMode, value)
    return DEFAULT_RUNTIME_MODE


def normalize_parser_mode(value: str | None) -> ParserMode:
    if value in VALID_PARSER_MODES:
        return cast(ParserMode, value)
    return DEFAULT_PARSER_MODE


def normalize_embedding_provider(value: str | None) -> EmbeddingProvider:
    if value in VALID_EMBEDDING_PROVIDERS:
        return cast(EmbeddingProvider, value)
    return DEFAULT_EMBEDDING_PROVIDER
```

- [ ] **Step 4: Break import cycle by moving parser literals out of `runtime_policy.py` if needed**

If importing `EmbeddingProvider` from `schemas.settings` creates a cycle, keep the literals in `runtime_policy.py` and use `typing.Literal` directly:

```python
from typing import Literal, cast

from ragstudio.schemas.runtime import RuntimeMode, StorageBackend

ParserModeValue = Literal["local_fallback", "mineru_strict", "mineru_with_fallback"]
EmbeddingProviderValue = Literal["fallback", "vllm_openai"]

DEFAULT_PARSER_MODE: ParserModeValue = "mineru_strict"
DEFAULT_EMBEDDING_PROVIDER: EmbeddingProviderValue = "vllm_openai"
```

Then return `ParserModeValue` and `EmbeddingProviderValue` from the helper functions.

- [ ] **Step 5: Update runtime profile service to use policy helpers**

In `backend/src/ragstudio/services/runtime_profile_service.py`, replace local `_storage_backend` and `_runtime_mode` calls with policy helpers:

```python
from ragstudio.services.runtime_policy import (
    DEFAULT_EMBEDDING_PROVIDER,
    normalize_runtime_mode,
    normalize_storage_backend,
)
```

Change:

```python
storage_backend = self._storage_backend(profile.storage_backend)
runtime_mode = self._runtime_mode(profile.runtime_mode, storage_backend)
```

to:

```python
storage_backend = normalize_storage_backend(profile.storage_backend)
runtime_mode = normalize_runtime_mode(profile.runtime_mode, storage_backend)
```

Change:

```python
embedding_provider=profile.embedding_provider or "fallback",
```

to:

```python
embedding_provider=profile.embedding_provider or DEFAULT_EMBEDDING_PROVIDER,
```

Delete `_storage_backend()` and `_runtime_mode()` from `RuntimeProfileService`.

- [ ] **Step 6: Update settings service to use policy helpers**

In `backend/src/ragstudio/services/settings_service.py`, import:

```python
from ragstudio.services.runtime_policy import (
    DEFAULT_EMBEDDING_PROVIDER,
    normalize_embedding_provider,
    normalize_runtime_mode,
    normalize_storage_backend,
)
```

Change `_to_out()` fields:

```python
storage_backend=normalize_storage_backend(profile.storage_backend),
embedding_provider=cast(
    EmbeddingProvider,
    normalize_embedding_provider(profile.embedding_provider),
),
runtime_mode=normalize_runtime_mode(profile.runtime_mode, profile.storage_backend),
```

Change the previous fallback embedding default:

```python
profile.embedding_provider if profile.embedding_provider else DEFAULT_EMBEDDING_PROVIDER
```

Delete `_storage_backend()` and `_runtime_mode()` from `SettingsService`.

Change `_normalize_runtime_values()` to:

```python
def _normalize_runtime_values(self, values: dict[str, object]) -> dict[str, object]:
    storage_backend = normalize_storage_backend(cast(str | None, values.get("storage_backend")))
    values["storage_backend"] = storage_backend
    values["runtime_mode"] = normalize_runtime_mode(
        cast(str | None, values.get("runtime_mode")),
        storage_backend,
    )
    values["embedding_provider"] = normalize_embedding_provider(
        cast(str | None, values.get("embedding_provider"))
    )
    timeout = values.get("mineru_timeout_ms")
    if isinstance(timeout, int):
        values["mineru_timeout_ms"] = max(timeout, MINERU_DEFAULT_TIMEOUT_MS)
    return values
```

- [ ] **Step 7: Keep schema defaults aligned**

In `backend/src/ragstudio/schemas/parsing.py`, import the default without creating a cycle. If `runtime_policy.py` cannot import `ParserMode`, define constants here and import them in policy:

```python
ParserMode = Literal["local_fallback", "mineru_strict", "mineru_with_fallback"]
DEFAULT_PARSER_MODE: ParserMode = "mineru_strict"
```

Change:

```python
parser_mode: ParserMode = "local_fallback"
```

to:

```python
parser_mode: ParserMode = DEFAULT_PARSER_MODE
```

In `backend/src/ragstudio/schemas/settings.py`, align defaults:

```python
embedding_provider: EmbeddingProvider = "vllm_openai"
runtime_mode: RuntimeMode = "runtime"
storage_backend: StorageBackend = "postgres_pgvector_neo4j"
```

- [ ] **Step 8: Run policy and settings tests**

Run:

```bash
docker compose run --rm --no-deps backend python -m pytest \
  backend/tests/test_runtime_policy.py \
  backend/tests/test_settings.py \
  backend/tests/test_config.py \
  -q
```

Expected: PASS after updating tests that asserted fallback defaults to assert runtime defaults.

- [ ] **Step 9: Commit**

```bash
git add backend/src/ragstudio/services/runtime_policy.py \
  backend/src/ragstudio/services/runtime_profile_service.py \
  backend/src/ragstudio/services/settings_service.py \
  backend/src/ragstudio/schemas/parsing.py \
  backend/src/ragstudio/schemas/settings.py \
  backend/tests/test_runtime_policy.py \
  backend/tests/test_settings.py \
  backend/tests/test_config.py
git commit -m "refactor: centralize runtime fallback policy"
```

---

### Task 2: Extract A Shared Document Parser Service

**Files:**
- Create: `backend/src/ragstudio/services/document_parser_service.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
- Test: `backend/tests/test_document_parser_service.py`
- Test: `backend/tests/test_documents.py`
- Test: `backend/tests/test_mineru_reindex_jobs.py`

- [ ] **Step 1: Write failing shared parser service tests**

Create `backend/tests/test_document_parser_service.py`:

```python
from pathlib import Path

import pytest

from ragstudio.db.models import Document, SettingsProfile
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn
from ragstudio.services.document_parser_service import DocumentParserService
from ragstudio.services.runtime_types import RuntimeChunk


class FakeLocalParser:
    async def index_document(self, artifact_path):
        return [
            RuntimeChunk(
                text=Path(artifact_path).read_text(),
                source_location={"line": 1},
                metadata={"backend": "fallback", "artifact_ref": Path(artifact_path).name},
            )
        ]


class ExplodingMinerUClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def health(self):
        class Health:
            ready = True
            is_hpc_coordinator = True
            detail = "ready"
            hpc_enabled = True
            hpc_mode = "coordinator"

        return Health()

    async def parse_document(self, **kwargs):
        raise RuntimeError("mineru exploded")


@pytest.mark.asyncio
async def test_mineru_with_fallback_uses_local_chunks_with_failure_metadata(db_session, tmp_path):
    artifact = tmp_path / "doc.txt"
    artifact.write_text("alpha")
    document = Document(
        id="doc-1",
        filename="doc.txt",
        content_type="text/plain",
        sha256="abc",
        size_bytes=5,
        artifact_path=str(artifact),
    )
    db_session.add(document)
    db_session.add(
        SettingsProfile(
            id="default",
            mineru_enabled=True,
            mineru_base_url="http://mineru.test",
            mineru_require_hpc=True,
        )
    )
    await db_session.commit()

    service = DocumentParserService(
        db_session,
        tmp_path,
        local_parser=FakeLocalParser(),
        mineru_client_factory=ExplodingMinerUClient,
    )

    chunks = await service.parse(
        document,
        IndexDocumentIn(
            parser_mode="mineru_with_fallback",
            domain_metadata=DomainMetadata(domain="test"),
        ),
    )

    assert [chunk.text for chunk in chunks] == ["alpha"]
    assert chunks[0].metadata["parser_metadata"]["backend"] == "fallback"
    assert chunks[0].metadata["parser_metadata"]["fallback_used"] is True
    assert "mineru exploded" in chunks[0].metadata["parser_metadata"]["mineru_error"]
```

- [ ] **Step 2: Run parser service test to verify it fails**

Run:

```bash
docker compose run --rm --no-deps backend python -m pytest backend/tests/test_document_parser_service.py -q
```

Expected: FAIL with missing `DocumentParserService`.

- [ ] **Step 3: Implement shared parser service**

Create `backend/src/ragstudio/services/document_parser_service.py`:

```python
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
from ragstudio.db.models import Document, SettingsProfile
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.adapter import AdapterChunk, RAGAnythingAdapter
from ragstudio.services.mineru_client import MinerUClient
from sqlalchemy.ext.asyncio import AsyncSession

MinerUStatusCallback = Callable[[dict[str, Any]], Awaitable[None]]


class DocumentParserService:
    def __init__(
        self,
        session: AsyncSession,
        data_dir: Path,
        *,
        local_parser: RAGAnythingAdapter | None = None,
        mineru_client_factory: type[MinerUClient] | None = None,
    ) -> None:
        self.session = session
        self.data_dir = data_dir
        self.local_parser = local_parser or RAGAnythingAdapter()
        self.mineru_client_factory = mineru_client_factory or MinerUClient

    async def parse(
        self,
        document: Document,
        options: IndexDocumentIn,
        *,
        on_mineru_status: MinerUStatusCallback | None = None,
    ) -> list[AdapterChunk]:
        if options.parser_mode == "local_fallback":
            return await self.local_parse(document)
        try:
            return await self.mineru_parse(
                document,
                options,
                on_mineru_status=on_mineru_status,
            )
        except Exception as exc:
            if options.parser_mode == "mineru_strict":
                raise
            return await self.local_parse_with_mineru_failure(document, options, exc)

    async def local_parse(self, document: Document) -> list[AdapterChunk]:
        return await self.local_parser.index_document(document.artifact_path)

    async def local_parse_with_mineru_failure(
        self,
        document: Document,
        options: IndexDocumentIn,
        exc: Exception,
    ) -> list[AdapterChunk]:
        chunks = await self.local_parse(document)
        return [
            AdapterChunk(
                text=chunk.text,
                source_location=chunk.source_location,
                metadata={
                    **chunk.metadata,
                    "parser_metadata": {
                        "backend": "fallback",
                        "parser_mode": options.parser_mode,
                        "mineru_error": str(exc),
                        "fallback_used": True,
                    },
                },
                runtime_source_id=chunk.runtime_source_id,
                content_type=chunk.content_type,
                preview_ref=chunk.preview_ref,
            )
            for chunk in chunks
        ]

    async def validate_strict_mineru_sidecar(self, options: IndexDocumentIn) -> None:
        if options.parser_mode != "mineru_strict":
            return
        await self.validated_mineru_client()

    async def mineru_parse(
        self,
        document: Document,
        options: IndexDocumentIn,
        *,
        on_mineru_status: MinerUStatusCallback | None = None,
    ) -> list[AdapterChunk]:
        _, client = await self.validated_mineru_client()
        artifact_dir = self.data_dir / "mineru-artifacts" / document.id
        job_result = await client.parse_document(
            artifact_path=document.artifact_path,
            document_id=document.id,
            artifact_dir=artifact_dir,
            content_type=document.content_type,
            sha256=document.sha256,
            domain_metadata=options.domain_metadata.model_dump(exclude_none=True),
            on_status=on_mineru_status,
        )
        return client.normalize_artifact_zip(
            artifact_zip=job_result.artifact_zip,
            extract_dir=artifact_dir / "extracted",
            document_id=document.id,
            parser_mode=options.parser_mode,
            parse_job_id=job_result.parse_job_id,
        )

    async def validated_mineru_client(self) -> tuple[SettingsProfile, MinerUClient]:
        settings = await self.session.get(SettingsProfile, "default")
        if settings is None or not settings.mineru_base_url:
            raise RuntimeError("MinerU base URL is not configured.")
        if not settings.mineru_enabled:
            raise RuntimeError("MinerU is disabled in settings.")
        client = self.mineru_client_factory(
            base_url=settings.mineru_base_url,
            timeout_ms=settings.mineru_timeout_ms or 14_400_000,
            poll_interval_ms=settings.mineru_poll_interval_ms or 1_000,
        )
        try:
            health = await client.health()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"MinerU health check failed: {exc}") from exc
        if not health.ready:
            raise RuntimeError(health.detail or "MinerU sidecar is not ready.")
        if settings.mineru_require_hpc and not health.is_hpc_coordinator:
            mode = health.hpc_mode or "unknown"
            raise RuntimeError(
                "MinerU sidecar is not in HPC coordinator mode. "
                f"Health detail: {health.detail or 'no detail'}; "
                f"hpcMineru.enabled={health.hpc_enabled}; mode={mode}. "
                "Start the HPC MinerU sidecar/coordinator or disable "
                "'Require HPC MinerU coordinator' in Settings."
            )
        return settings, client
```

- [ ] **Step 4: Run parser service test**

Run:

```bash
docker compose run --rm --no-deps backend python -m pytest backend/tests/test_document_parser_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Update `ChunkService` to delegate parsing**

In `backend/src/ragstudio/services/chunk_service.py`, import:

```python
from ragstudio.services.document_parser_service import DocumentParserService
```

In `__init__`, add:

```python
document_parser: DocumentParserService | None = None,
```

Set:

```python
self.document_parser = document_parser or DocumentParserService(
    session,
    data_dir,
    local_parser=self.adapter,
    mineru_client_factory=self.mineru_client_factory,
)
```

Replace `_adapter_chunks()` body with:

```python
return await self.document_parser.parse(
    document,
    options,
    on_mineru_status=on_mineru_status,
)
```

Replace `validate_strict_mineru_sidecar()` body with:

```python
await self.document_parser.validate_strict_mineru_sidecar(options)
```

Delete `_mineru_adapter_chunks()` and `_validated_mineru_client()` from `ChunkService`.

- [ ] **Step 6: Update `IndexLifecycleService` to delegate preparse**

In `backend/src/ragstudio/services/index_lifecycle_service.py`, import:

```python
from ragstudio.services.document_parser_service import DocumentParserService
```

Add constructor dependency:

```python
document_parser: DocumentParserService | None = None,
```

Set:

```python
self.document_parser = document_parser or DocumentParserService(session, settings.data_dir)
```

Replace `_preparse_runtime_document()` with:

```python
async def _preparse_runtime_document(
    self,
    runtime: Any,
    document: Document,
    options: IndexDocumentIn,
    *,
    on_mineru_status: MinerUStatusCallback | None = None,
) -> list[AdapterChunk] | None:
    if options.parser_mode == "local_fallback":
        return None
    if not hasattr(runtime, "index_preparsed_chunks"):
        raise RuntimeError("Runtime adapter does not support preparsed chunks.")
    return await self.document_parser.parse(
        document,
        options,
        on_mineru_status=on_mineru_status,
    )
```

Delete `_mineru_adapter_chunks()` from `IndexLifecycleService`.

- [ ] **Step 7: Remove now-unused imports**

From `chunk_service.py`, remove `httpx`, `SettingsProfile`, and `MinerUClient` imports if no longer referenced.

From `index_lifecycle_service.py`, remove `httpx`, `SettingsProfile`, `MinerUClient`, and `signature` imports if no longer referenced after Task 5.

- [ ] **Step 8: Run parsing and indexing tests**

Run:

```bash
docker compose run --rm --no-deps backend python -m pytest \
  backend/tests/test_document_parser_service.py \
  backend/tests/test_documents.py \
  backend/tests/test_chunks.py \
  backend/tests/test_mineru_reindex_jobs.py \
  -q
```

Expected: PASS after updating tests to inject `DocumentParserService` fakes instead of separate ChunkService/IndexLifecycleService MinerU fakes.

- [ ] **Step 9: Commit**

```bash
git add backend/src/ragstudio/services/document_parser_service.py \
  backend/src/ragstudio/services/chunk_service.py \
  backend/src/ragstudio/services/index_lifecycle_service.py \
  backend/tests/test_document_parser_service.py \
  backend/tests/test_documents.py \
  backend/tests/test_chunks.py \
  backend/tests/test_mineru_reindex_jobs.py
git commit -m "refactor: share document parser pipeline"
```

---

### Task 3: Remove Constructor Compatibility Shims

**Files:**
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
- Modify: `backend/src/ragstudio/services/query_service.py`
- Modify: `backend/src/ragstudio/api/routes/documents.py`
- Modify: `backend/src/ragstudio/api/routes/chunks.py`
- Test: `backend/tests/test_documents.py`
- Test: `backend/tests/test_chunks.py`
- Test: `backend/tests/test_query_runs.py`

- [ ] **Step 1: Search for constructor shim patterns**

Run:

```bash
rg -n "except TypeError|RAGAnythingRuntimeFactory\\(\\)|RuntimeHealthService\\(\\)" backend/src/ragstudio backend/tests
```

Expected before implementation: matches in `index_lifecycle_service.py`, `query_service.py`, `documents.py`, and `chunks.py`.

- [ ] **Step 2: Remove shim from `IndexLifecycleService`**

In `backend/src/ragstudio/services/index_lifecycle_service.py`, replace:

```python
self.runtime_factory = runtime_factory or self._runtime_factory(settings)
self.health_service = health_service or self._health_service(session)
```

with:

```python
self.runtime_factory = runtime_factory or RAGAnythingRuntimeFactory(settings)
self.health_service = health_service or RuntimeHealthService(session, verify_storage=True)
```

Delete `_runtime_factory()` and `_health_service()`.

- [ ] **Step 3: Remove shim from `QueryService`**

In `backend/src/ragstudio/services/query_service.py`, replace:

```python
self.runtime_factory = runtime_factory or self._runtime_factory(settings)
self.health_service = health_service or self._health_service(session)
```

with:

```python
self.runtime_factory = runtime_factory or RAGAnythingRuntimeFactory(settings)
self.health_service = health_service or RuntimeHealthService(session, verify_storage=True)
```

Delete `_runtime_factory()` and `_health_service()` methods.

- [ ] **Step 4: Remove route health-service shim**

In `backend/src/ragstudio/api/routes/documents.py`, replace `_runtime_health_service(session)` calls with:

```python
RuntimeHealthService(session, verify_storage=True)
```

Delete `_runtime_health_service()`.

In `backend/src/ragstudio/api/routes/chunks.py`, do the same and delete `_runtime_health_service()`.

- [ ] **Step 5: Verify no shim remains**

Run:

```bash
rg -n "except TypeError|_runtime_factory|_health_service|_runtime_health_service" backend/src/ragstudio
```

Expected: no matches for constructor fallback helpers.

- [ ] **Step 6: Run affected tests**

Run:

```bash
docker compose run --rm --no-deps backend python -m pytest \
  backend/tests/test_documents.py \
  backend/tests/test_chunks.py \
  backend/tests/test_query_runs.py \
  -q
```

Expected: PASS after tests are updated to use current constructor signatures.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/index_lifecycle_service.py \
  backend/src/ragstudio/services/query_service.py \
  backend/src/ragstudio/api/routes/documents.py \
  backend/src/ragstudio/api/routes/chunks.py \
  backend/tests/test_documents.py \
  backend/tests/test_chunks.py \
  backend/tests/test_query_runs.py
git commit -m "refactor: remove runtime constructor shims"
```

---

### Task 4: Make Document Reindex The Only Indexing API

**Files:**
- Modify: `backend/src/ragstudio/api/routes/chunks.py`
- Modify: `backend/src/ragstudio/api/routes/documents.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/features/documents/documents-page.tsx`
- Modify: `frontend/src/features/chunks/chunk-inspector.tsx`
- Test: `backend/tests/test_documents.py`
- Test: `backend/tests/test_chunks.py`
- Test: `backend/tests/test_mineru_reindex_jobs.py`
- Test: `frontend/tests/documents-page.test.tsx`
- Test: `frontend/tests/chunk-reindex.test.tsx`

- [ ] **Step 1: Write failing API removal tests**

In `backend/tests/test_chunks.py`, add:

```python
async def test_removed_chunk_index_job_endpoint_returns_not_found(client, document):
    response = await client.post(
        f"/api/chunks/index/{document.id}/jobs",
        json={"parser_mode": "mineru_strict", "domain_metadata": {}},
    )
    assert response.status_code == 404


async def test_removed_sync_chunk_index_endpoint_returns_not_found(client, document):
    response = await client.post(
        f"/api/chunks/index/{document.id}",
        json={"parser_mode": "mineru_strict", "domain_metadata": {}},
    )
    assert response.status_code == 404
```

If the test fixture is named differently, use the existing document fixture from the file and keep the assertion unchanged.

- [ ] **Step 2: Run removal tests to verify they fail**

Run:

```bash
docker compose run --rm --no-deps backend python -m pytest \
  backend/tests/test_chunks.py::test_removed_chunk_index_job_endpoint_returns_not_found \
  backend/tests/test_chunks.py::test_removed_sync_chunk_index_endpoint_returns_not_found \
  -q
```

Expected: FAIL because endpoints still exist and return 202/200 or validation conflicts.

- [ ] **Step 3: Remove duplicate chunk indexing routes**

In `backend/src/ragstudio/api/routes/chunks.py`, delete:

```python
@router.post("/index/{document_id}/jobs", ...)
async def create_index_document_job(...):
    ...

@router.post("/index/{document_id}", response_model=list[ChunkOut])
async def index_document_chunks(...):
    ...
```

Also delete route-only helpers no longer used by `search_chunks()`:

```python
_validate_index_options
_run_index_document_job
_mark_background_index_failed
```

Remove imports no longer used:

```python
asyncio
logging
HTTPException
status
create_background_task
AppSettings
make_engine
make_session_factory
Document
ChunkOut
JobOut
IndexDocumentIn
DocumentService
ActiveIndexJobError
IndexLifecycleService
RuntimeHealthBlockedError
validate_custom_json
RuntimeUnavailableError
RuntimeHealthService
RuntimeProfileNotConfiguredError
RuntimeProfileService
```

The resulting `chunks.py` should keep only:

```python
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.chunks import ChunkSearchIn, ChunkSearchOut
from ragstudio.services.chunk_service import ChunkService

router = APIRouter(prefix="/api/chunks", tags=["chunks"])


@router.post("/search", response_model=ChunkSearchOut)
async def search_chunks(
    search_in: ChunkSearchIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ChunkSearchOut:
    return await ChunkService(session, request.app.state.settings.data_dir).search(search_in)
```

- [ ] **Step 4: Ensure document reindex route is complete**

In `backend/src/ragstudio/api/routes/documents.py`, keep:

```python
@router.post("/{document_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
async def reindex_document(...)
```

Confirm it:

- validates document exists,
- validates index options,
- checks runtime health when runtime mode is active,
- validates strict MinerU sidecar,
- creates a background job,
- returns `{"document_id": document_id, "job_id": job.id, "status": job.status}`.

- [ ] **Step 5: Update frontend API client**

In `frontend/src/api/client.ts`, remove client methods that call:

```ts
"/api/chunks/index/"
```

Keep or add one canonical method:

```ts
createDocumentReindexJob: (documentId: string, payload: IndexDocumentIn) =>
  request<JobOut>(`/api/documents/${documentId}/reindex`, {
    method: "POST",
    body: JSON.stringify(payload),
  }),
```

Use the existing `JobOut` and `IndexDocumentIn` types if they already exist in the file.

- [ ] **Step 6: Update Documents page reindex calls**

In `frontend/src/features/documents/documents-page.tsx`, replace chunk-index job API calls with:

```ts
apiClient.createDocumentReindexJob(document.id, parserOptions)
```

Keep the existing job polling behavior if it polls `/api/jobs`.

- [ ] **Step 7: Update Chunk Inspector reindex calls**

In `frontend/src/features/chunks/chunk-inspector.tsx`, replace chunk-index job API calls with:

```ts
apiClient.createDocumentReindexJob(selectedDocumentId, parserOptions)
```

If the component expects `JobOut`, keep the response handling unchanged because the canonical route returns `job_id` and `status`.

- [ ] **Step 8: Run backend API tests**

Run:

```bash
docker compose run --rm --no-deps backend python -m pytest \
  backend/tests/test_documents.py \
  backend/tests/test_chunks.py \
  backend/tests/test_mineru_reindex_jobs.py \
  -q
```

Expected: PASS after moving tests for job creation to `/api/documents/{id}/reindex`.

- [ ] **Step 9: Run frontend reindex tests**

Run:

```bash
docker compose run --rm --no-deps frontend npm run test -- --run \
  tests/documents-page.test.tsx \
  tests/chunk-reindex.test.tsx
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add backend/src/ragstudio/api/routes/chunks.py \
  backend/src/ragstudio/api/routes/documents.py \
  backend/tests/test_documents.py \
  backend/tests/test_chunks.py \
  backend/tests/test_mineru_reindex_jobs.py \
  frontend/src/api/client.ts \
  frontend/src/features/documents/documents-page.tsx \
  frontend/src/features/chunks/chunk-inspector.tsx \
  frontend/tests/documents-page.test.tsx \
  frontend/tests/chunk-reindex.test.tsx
git commit -m "refactor: use document reindex as canonical indexing api"
```

---

### Task 5: Remove Fallback Runtime Query And Graph Behavior

**Files:**
- Modify: `backend/src/ragstudio/services/adapter.py`
- Modify: `backend/src/ragstudio/services/runtime_factory.py`
- Modify: `backend/src/ragstudio/services/query_service.py`
- Modify: `backend/src/ragstudio/services/graph_service.py`
- Modify: `backend/src/ragstudio/services/diagnostics_service.py`
- Test: `backend/tests/test_query_runs.py`
- Test: `backend/tests/test_graph.py`
- Test: `backend/tests/test_diagnostics.py`

- [ ] **Step 1: Write failing query test for missing runtime profile**

In `backend/tests/test_query_runs.py`, add:

```python
async def test_query_fails_when_runtime_profile_missing(client, variant, document):
    response = await client.post(
        "/api/query",
        json={
            "query": "alpha",
            "variant_ids": [variant.id],
            "document_ids": [document.id],
            "limit": 3,
        },
    )

    assert response.status_code == 409
    assert "Default runtime profile is not configured" in response.json()["detail"]
```

If the query route currently returns `200` with failed runs instead of raising HTTP errors, keep the HTTP shape used by the existing query route and assert:

```python
body = response.json()
assert body["runs"][0]["status"] == "failed"
assert body["runs"][0]["error_type"] == "runtime_profile_missing"
```

Use the route's existing error style consistently across the file.

- [ ] **Step 2: Run query test to verify it fails**

Run:

```bash
docker compose run --rm --no-deps backend python -m pytest \
  backend/tests/test_query_runs.py::test_query_fails_when_runtime_profile_missing \
  -q
```

Expected: FAIL because `QueryService` currently calls `_run_legacy_query()`.

- [ ] **Step 3: Remove fake runtime query from adapter**

In `backend/src/ragstudio/services/adapter.py`, remove:

```python
async def query(...)
async def graph(...)
def _simple_answer(...)
```

Keep:

```python
class RAGAnythingAdapter:
    """Local line-split parser used only by local_fallback parser mode."""

    def __init__(self) -> None:
        self._package_available = self._can_import("raganything")

    def capability_report(self) -> dict[str, Any]:
        return {
            "raganything_available": self._package_available,
            "active_backend": "local_parser",
            "indexing": "line_split_parser",
        }

    async def index_document(self, artifact_path: str | Path) -> list[RuntimeChunk]:
        return self._line_split_index(Path(artifact_path))
```

- [ ] **Step 4: Remove fallback runtime construction**

In `backend/src/ragstudio/services/runtime_factory.py`, replace:

```python
if profile.runtime_mode == "fallback":
    return RAGAnythingAdapter()
```

with:

```python
if profile.runtime_mode != "runtime":
    raise RuntimeUnavailableError(
        f"Runtime mode '{profile.runtime_mode}' does not provide native RAG-Anything execution."
    )
```

Remove `RAGAnythingAdapter` import from `runtime_factory.py`.

- [ ] **Step 5: Make query service fail without runtime profile**

In `backend/src/ragstudio/services/query_service.py`, replace:

```python
except RuntimeProfileNotConfiguredError:
    return await self._run_legacy_query(payload)
```

with:

```python
except RuntimeProfileNotConfiguredError as exc:
    return await self._failed_runtime_runs(
        payload,
        runtime_profile_id="missing",
        checks=[
            RuntimeHealthCheck(
                name="runtime_profile",
                status="failed",
                severity="blocking",
                detail=str(exc),
                error_type="runtime_profile_missing",
            )
        ],
    )
```

Replace:

```python
if profile.runtime_mode != "fallback":
    return await self._run_runtime_query(payload, profile)
return await self._run_legacy_query(payload, profile)
```

with:

```python
if profile.runtime_mode != "runtime":
    return await self._failed_runtime_runs(
        payload,
        profile.id,
        [
            RuntimeHealthCheck(
                name="runtime_mode",
                status="failed",
                severity="blocking",
                detail=f"Runtime mode '{profile.runtime_mode}' cannot execute queries.",
                error_type="runtime_mode_inactive",
            )
        ],
    )
return await self._run_runtime_query(payload, profile)
```

Keep `_run_legacy_query()` only if tests still exercise it directly. If no production code calls it after this task, delete `_run_legacy_query()`, `_adapter_chunk()`, and `_source()` in the same commit.

- [ ] **Step 6: Make graph service use relationship metadata instead of adapter placeholder**

In `backend/src/ragstudio/services/graph_service.py`, replace:

```python
if self.session is None or self.settings is None:
    return await self.adapter.graph()
```

with:

```python
if self.session is None:
    return {
        "nodes": [],
        "edges": [],
        "detail": "No database session is available for relationship metadata graph.",
    }
if self.settings is None:
    return await self._relationship_metadata_graph()
```

Remove `adapter` from `GraphService.__init__()` if no tests require injecting it. Remove the `RAGAnythingAdapter` import from `graph_service.py`.

- [ ] **Step 7: Update diagnostics wording**

In `backend/src/ragstudio/services/diagnostics_service.py`, replace fallback graph wording:

```python
"Graph is unavailable because fallback mode uses the local placeholder graph."
```

with:

```python
"Runtime graph is inactive; Graph uses relationship metadata derived during parsing when available."
```

Update capability key if present:

```python
"graph": "relationship_metadata"
```

- [ ] **Step 8: Run query, graph, diagnostics tests**

Run:

```bash
docker compose run --rm --no-deps backend python -m pytest \
  backend/tests/test_query_runs.py \
  backend/tests/test_graph.py \
  backend/tests/test_diagnostics.py \
  -q
```

Expected: PASS after updating tests that expected fake query answers or placeholder graph output.

- [ ] **Step 9: Commit**

```bash
git add backend/src/ragstudio/services/adapter.py \
  backend/src/ragstudio/services/runtime_factory.py \
  backend/src/ragstudio/services/query_service.py \
  backend/src/ragstudio/services/graph_service.py \
  backend/src/ragstudio/services/diagnostics_service.py \
  backend/tests/test_query_runs.py \
  backend/tests/test_graph.py \
  backend/tests/test_diagnostics.py
git commit -m "refactor: remove fallback runtime execution"
```

---

### Task 6: Make Scoped Native Query Fail Instead Of Metadata Fallback

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/src/ragstudio/services/native_raganything_adapter.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`
- Test: `backend/tests/test_query_runs.py`

- [ ] **Step 1: Update failing-orchestrator expectation**

In `backend/tests/test_retrieval_orchestrator.py`, replace the test that asserts metadata fallback for scoped native limitation:

```python
async def test_orchestrator_uses_metadata_fallback_for_scoped_native_limitation():
```

with:

```python
async def test_orchestrator_fails_when_native_scoped_query_is_unsupported():
    chunk_service = FakeChunkService([])
    result = await RetrievalOrchestrator(chunk_service=chunk_service).query(
        "alpha",
        runtime=FakeRuntimeTool(
            answer="",
            sources=[],
            error="LightRAG vector storage does not support storage-level full_doc_id filtering.",
            error_type="native_document_scope_unsupported",
            timings={"runtime_query_ms": 7, "native_scoped_query": True},
        ),
        profile=object(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 3},
    )

    assert result.error_type == "native_document_scope_unsupported"
    assert "full_doc_id filtering" in (result.error or "")
    assert result.sources == []
    assert result.timings["runtime_query_ms"] == 7
```

Use the existing fake helper constructors in the file. The important assertion is that metadata candidates are not returned when native scoped filtering is unsupported.

- [ ] **Step 2: Run updated orchestrator test to verify it fails**

Run:

```bash
docker compose run --rm --no-deps backend python -m pytest \
  backend/tests/test_retrieval_orchestrator.py::test_orchestrator_fails_when_native_scoped_query_is_unsupported \
  -q
```

Expected: FAIL because orchestrator currently marks `scoped_runtime_fallback`.

- [ ] **Step 3: Remove scoped fallback branch**

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, change:

```python
if isinstance(native_result, NativeScopedQueryUnsupported):
    timings.update(native_result.timings)
    timings["scoped_runtime_fallback"] = True
    native_status = "scoped_unsupported"
else:
    raise native_result
```

to:

```python
if isinstance(native_result, NativeScopedQueryUnsupported):
    raise NativeRuntimeQueryFailed(
        native_result.error,
        "native_document_scope_unsupported",
        {**timings, **native_result.timings},
    ) from native_result
raise native_result
```

Remove `native_status = "scoped_unsupported"` behavior and remove tests that assert `scoped_runtime_fallback`.

- [ ] **Step 4: Make native adapter require storage filter**

In `backend/src/ragstudio/services/native_raganything_adapter.py`, confirm `_scoped_chunks_vdb()` constructs `ScopedVectorStorageProxy` with:

```python
require_storage_filter=True
```

If it currently passes a profile-controlled value, replace it with the hard requirement:

```python
ScopedVectorStorageProxy(
    base=chunks_vdb,
    document_ids=document_ids,
    require_storage_filter=True,
)
```

Keep the existing `NativeScopedStorageUnsupported` exception and the `RuntimeQueryResult(error_type="native_document_scope_unsupported")` return from `query()`.

- [ ] **Step 5: Run retrieval and query tests**

Run:

```bash
docker compose run --rm --no-deps backend python -m pytest \
  backend/tests/test_retrieval_orchestrator.py \
  backend/tests/test_query_runs.py \
  -q
```

Expected: PASS after updating expected error type for unsupported scoped native query.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/retrieval_orchestrator.py \
  backend/src/ragstudio/services/native_raganything_adapter.py \
  backend/tests/test_retrieval_orchestrator.py \
  backend/tests/test_query_runs.py
git commit -m "refactor: fail unsupported scoped runtime queries"
```

---

### Task 7: Centralize Parser Defaults In Frontend And Backend

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/features/documents/documents-page.tsx`
- Modify: `frontend/src/features/chunks/chunk-inspector.tsx`
- Modify: `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`
- Modify: `backend/src/ragstudio/api/routes/documents.py`
- Test: `frontend/tests/documents-page.test.tsx`
- Test: `frontend/tests/chunk-reindex.test.tsx`
- Test: `backend/tests/test_documents.py`

- [ ] **Step 1: Add frontend parser default constant**

In `frontend/src/api/client.ts`, add near parser type definitions:

```ts
export const DEFAULT_PARSER_MODE: ParserMode = "mineru_strict";
```

Change upload form creation:

```ts
formData.set("parser_mode", options.parser_mode ?? "local_fallback");
```

to:

```ts
formData.set("parser_mode", options.parser_mode ?? DEFAULT_PARSER_MODE);
```

- [ ] **Step 2: Update Documents page default**

In `frontend/src/features/documents/documents-page.tsx`, import:

```ts
import { DEFAULT_PARSER_MODE } from "../../api/client";
```

Change:

```ts
parser_mode: "local_fallback",
```

to:

```ts
parser_mode: DEFAULT_PARSER_MODE,
```

- [ ] **Step 3: Update Chunk Inspector default**

In `frontend/src/features/chunks/chunk-inspector.tsx`, import:

```ts
import { DEFAULT_PARSER_MODE } from "../../api/client";
```

Change:

```ts
parser_mode: "local_fallback",
```

to:

```ts
parser_mode: DEFAULT_PARSER_MODE,
```

- [ ] **Step 4: Update domain metadata panel default**

In `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`, import:

```ts
import { DEFAULT_PARSER_MODE } from "../../api/client";
```

Change:

```tsx
value={value.parser_mode ?? "local_fallback"}
```

to:

```tsx
value={value.parser_mode ?? DEFAULT_PARSER_MODE}
```

- [ ] **Step 5: Update backend upload parser default**

In `backend/src/ragstudio/api/routes/documents.py`, import:

```python
from ragstudio.services.runtime_policy import DEFAULT_PARSER_MODE
```

Change:

```python
"parser_mode": parser_mode or "local_fallback",
```

to:

```python
"parser_mode": parser_mode or DEFAULT_PARSER_MODE,
```

- [ ] **Step 6: Run frontend and backend parser-default tests**

Run:

```bash
docker compose run --rm --no-deps frontend npm run test -- --run \
  tests/documents-page.test.tsx \
  tests/chunk-reindex.test.tsx
docker compose run --rm --no-deps backend python -m pytest backend/tests/test_documents.py -q
```

Expected: PASS after updating assertions that expect `local_fallback` as the default to expect `mineru_strict`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/client.ts \
  frontend/src/features/documents/documents-page.tsx \
  frontend/src/features/chunks/chunk-inspector.tsx \
  frontend/src/features/domain-metadata/domain-metadata-panel.tsx \
  frontend/tests/documents-page.test.tsx \
  frontend/tests/chunk-reindex.test.tsx \
  backend/src/ragstudio/api/routes/documents.py \
  backend/tests/test_documents.py
git commit -m "refactor: centralize parser defaults"
```

---

### Task 8: Update Docs To Match Runtime-First Behavior

**Files:**
- Modify: `docs/user-guide.md`
- Modify: `docs/superpowers/specs/2026-05-08-rag-anything-production-runtime-design.md`
- Test: documentation grep checks

- [ ] **Step 1: Replace fallback-runtime wording in user guide**

In `docs/user-guide.md`, replace sections that say fallback mode generates answers from excerpts or graph placeholders with:

```markdown
Local fallback parsing remains available as an explicit parser mode for small text-oriented documents. It creates local chunks for inspection and metadata search, but query execution in runtime profiles requires a configured native RAG-Anything runtime.
```

Replace graph wording with:

```markdown
When runtime graph storage is inactive, the Graph page shows relationship metadata derived during parsing when those relationships exist. If no relationship metadata exists, the page reports that no runtime graph or relationship metadata is available.
```

- [ ] **Step 2: Document canonical reindex endpoint**

In `docs/user-guide.md`, ensure reindex instructions mention only:

```markdown
POST /api/documents/{document_id}/reindex
```

Remove references to:

```markdown
POST /api/chunks/index/{document_id}
POST /api/chunks/index/{document_id}/jobs
```

- [ ] **Step 3: Update production runtime design note**

In `docs/superpowers/specs/2026-05-08-rag-anything-production-runtime-design.md`, append:

```markdown
Runtime-first cleanup: production runtime profiles no longer use local fallback query or placeholder graph behavior. Unsupported scoped native query filtering is a runtime error, not a metadata fallback. Local fallback remains only as a parser mode for explicit local chunk creation.
```

- [ ] **Step 4: Run docs grep checks**

Run:

```bash
rg -n "simple_fallback|placeholder graph|/api/chunks/index|fallback adapter behavior|generated answer is the question" docs/user-guide.md docs/superpowers/specs/2026-05-08-rag-anything-production-runtime-design.md
```

Expected: no matches.

- [ ] **Step 5: Commit**

```bash
git add docs/user-guide.md docs/superpowers/specs/2026-05-08-rag-anything-production-runtime-design.md
git commit -m "docs: describe runtime-first fallback cleanup"
```

---

### Task 9: Full Verification And Baseline Repair

**Files:**
- Modify only files required by failures discovered in this task.
- Test: backend and frontend full suites.

- [ ] **Step 1: Run backend ruff**

Run:

```bash
docker compose run --rm --no-deps backend python -m ruff check backend/src backend/tests
```

Expected: PASS.

If the existing unrelated ruff failures still exist, fix them in this task:

```python
# backend/src/ragstudio/services/optimizer_service.py
grouped.setdefault(run.variant_id, []).append(
    self._run_score(run, scores_by_run_id.get(run.id))
)

scoreable_scores = [
    item.score
    for item in run_scores
    if item.scoreable and item.score is not None
]
```

For `backend/tests/test_page_sampler.py`, run:

```bash
docker compose run --rm --no-deps backend python -m ruff check backend/tests/test_page_sampler.py --fix
```

- [ ] **Step 2: Run backend pyright**

Run:

```bash
docker compose run --rm --no-deps backend python -m pyright
```

Expected: PASS.

If pyright reports existing unrelated errors, fix them in the same files pyright names. Keep fixes mechanical and covered by tests.

- [ ] **Step 3: Run backend pytest**

Run:

```bash
docker compose run --rm --no-deps backend python -m pytest backend/tests -q
```

Expected: PASS.

If tests need Postgres/Neo4j but active fixed-name containers conflict, use the isolated-network method from the worktree setup:

```bash
docker run -d --rm --name codex-cleanup-postgres \
  --network codex-isolated-workspace_default \
  --network-alias postgres \
  -e POSTGRES_DB=ragstudio \
  -e POSTGRES_USER=ragstudio \
  -e POSTGRES_PASSWORD=ragstudio \
  -v codex-isolated-workspace_ragstudio-postgres-data:/var/lib/postgresql/data \
  pgvector/pgvector:pg17

docker run -d --rm --name codex-cleanup-neo4j \
  --network codex-isolated-workspace_default \
  --network-alias neo4j \
  -e NEO4J_AUTH=neo4j/ragstudio-password \
  -e NEO4J_dbms_security_auth__enabled=true \
  -v codex-isolated-workspace_ragstudio-neo4j-data:/data \
  -v codex-isolated-workspace_ragstudio-neo4j-logs:/logs \
  neo4j:5-community
```

Wait:

```bash
for i in $(seq 1 60); do
  pg=0
  neo=0
  docker exec codex-cleanup-postgres pg_isready -U ragstudio -d ragstudio >/dev/null 2>&1 && pg=1
  docker exec codex-cleanup-neo4j wget --quiet --tries=1 --spider http://127.0.0.1:7474 >/dev/null 2>&1 && neo=1
  [ "$pg" = 1 ] && [ "$neo" = 1 ] && exit 0
  sleep 5
done
exit 1
```

Then run pytest with the in-network environment:

```bash
docker compose run --rm --no-deps \
  -e RAGSTUDIO_DATABASE_URL=postgresql+asyncpg://ragstudio:ragstudio@postgres:5432/ragstudio \
  -e RAGSTUDIO_TEST_DATABASE_URL=postgresql+asyncpg://ragstudio:ragstudio@postgres:5432/ragstudio \
  -e RAGSTUDIO_NEO4J_URI=bolt://neo4j:7687 \
  backend python -m pytest backend/tests -q
```

Clean up:

```bash
docker rm -f codex-cleanup-postgres codex-cleanup-neo4j
```

- [ ] **Step 4: Run frontend lint, test, and build**

Run:

```bash
docker compose run --rm --no-deps frontend npm run lint
docker compose run --rm --no-deps frontend npm run test -- --run
docker compose run --rm --no-deps frontend npm run build
```

Expected: all PASS. The build may warn about chunk size; that warning is acceptable if the command exits 0.

- [ ] **Step 5: Run removal grep checks**

Run:

```bash
rg -n "simple_fallback|fallback_runtime_without_chunks|scoped_runtime_fallback|/api/chunks/index|except TypeError|placeholder graph" backend/src backend/tests frontend/src frontend/tests docs
```

Expected: no matches except historical docs under `docs/superpowers/plans/` if they are intentionally preserving old implementation plans.

- [ ] **Step 6: Commit verification fixes**

If Task 9 changed files:

```bash
git add backend/src backend/tests frontend/src frontend/tests docs
git commit -m "test: restore runtime cleanup baseline"
```

If Task 9 changed no files:

```bash
git status --short
```

Expected: clean working tree.

---

## Self-Review

**Spec coverage:** All eight audit findings are covered:

- Duplicate indexing APIs: Task 4.
- Duplicate MinerU parsing/fallback: Task 2.
- Legacy fallback runtime adapter: Task 5.
- Native scoped-query metadata fallback: Task 6.
- Constructor compatibility shims: Task 3.
- Runtime/settings normalization duplication: Task 1.
- Fallback graph messaging and behavior mismatch: Task 5.
- Parser defaults scattered across frontend/backend: Task 7.

**Placeholder scan:** This plan contains no unresolved markers, no unassigned edge handling, and no step that asks an engineer to write unspecified tests. Each code-changing task includes exact files, code shape, commands, and expected outcomes.

**Type consistency:** Parser mode uses `local_fallback | mineru_strict | mineru_with_fallback`. Runtime mode uses `runtime | fallback | degraded`. Storage backend uses `postgres_pgvector_neo4j | fallback_local`. The canonical reindex client method is `createDocumentReindexJob(documentId, payload)` and maps to `POST /api/documents/{documentId}/reindex`.
