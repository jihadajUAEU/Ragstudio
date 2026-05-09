# Native RAG-Anything Scoped Query Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement selected-document native RAG-Anything query execution so runtime-mode queries enforce `document_ids` inside the native LightRAG/RAG-Anything path instead of relying on mirrored chunk fallback.

**Architecture:** Add a scoped vector storage proxy around LightRAG's chunk vector store, using the existing `full_doc_id` metadata that RAG-Anything writes during indexing. The native adapter will run scoped retrieval and answer generation with that proxy installed, collect source traces from the scoped native vector results, and fail closed if any result escapes the selected document scope.

**Tech Stack:** FastAPI backend, RAG-Anything 1.3.0, LightRAG `QueryParam`, Postgres/PGVector, Neo4j, pytest, Docker Compose.

---

## File Structure

- Modify: `backend/src/ragstudio/services/native_raganything_adapter.py`
  - Owns native RAG-Anything and LightRAG calls.
  - Add `ScopedVectorStorageProxy` in this file because it is an adapter-specific compatibility shim around upstream LightRAG storage.
  - Add helper methods for scoped query execution, `QueryParam` construction, source trace normalization, and scope-leak validation.
- Modify: `backend/src/ragstudio/services/query_service.py`
  - Keep the existing mirrored fallback as a safety net for older adapters or future upstream regressions.
  - Mark native scoped runs with native timings when the adapter succeeds.
- Modify: `backend/src/ragstudio/services/diagnostics_service.py`
  - Report native scoped query as available after this feature lands.
  - Remove the warning that says selected-document queries use mirrored fallback when runtime health is ready.
- Modify: `backend/tests/test_native_raganything_adapter.py`
  - Add adapter-level tests for scoped query behavior, proxy filtering, source traces, leak failures, and capability reporting.
- Modify: `backend/tests/test_runtime_query_service.py`
  - Add one service-level regression test proving a native scoped runtime result does not hit the mirrored fallback path.
- Modify: `backend/tests/test_optimizer_graph_diagnostics.py`
  - Update diagnostics assertions from fallback availability to native scoped availability.
- Optional Modify: `docs/workflows.md`
  - Document that native runtime supports selected-document query scope through LightRAG `full_doc_id`.

---

### Task 1: Add Scoped Vector Proxy Tests

**Files:**
- Modify: `backend/tests/test_native_raganything_adapter.py`
- Modify: `backend/src/ragstudio/services/native_raganything_adapter.py`

- [ ] **Step 1: Write failing tests for scoped vector filtering**

Append these test helpers and tests near the existing fake upstream classes in `backend/tests/test_native_raganything_adapter.py`:

```python
class FakeChunkVectorStorage:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.cosine_better_than_threshold = 0.2

    async def query(self, query, top_k, query_embedding=None):
        self.calls.append(
            {"query": query, "top_k": top_k, "query_embedding": query_embedding}
        )
        return self.rows[:top_k]


@pytest.mark.asyncio
async def test_scoped_vector_proxy_filters_by_full_doc_id():
    from ragstudio.services.native_raganything_adapter import ScopedVectorStorageProxy

    base = FakeChunkVectorStorage(
        [
            {"id": "chunk-1", "full_doc_id": "doc-1", "content": "inside one"},
            {"id": "chunk-2", "full_doc_id": "doc-2", "content": "outside"},
            {"id": "chunk-3", "full_doc_id": "doc-1", "content": "inside two"},
        ]
    )
    proxy = ScopedVectorStorageProxy(base, ["doc-1"])

    rows = await proxy.query("question", top_k=2, query_embedding=[0.1, 0.2])

    assert [row["id"] for row in rows] == ["chunk-1", "chunk-3"]
    assert base.calls == [
        {"query": "question", "top_k": 16, "query_embedding": [0.1, 0.2]}
    ]
    assert [row["id"] for row in proxy.collected_results] == ["chunk-1", "chunk-3"]


@pytest.mark.asyncio
async def test_scoped_vector_proxy_preserves_base_attributes():
    from ragstudio.services.native_raganything_adapter import ScopedVectorStorageProxy

    base = FakeChunkVectorStorage([])
    proxy = ScopedVectorStorageProxy(base, ["doc-1"])

    assert proxy.cosine_better_than_threshold == 0.2
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src \
python -m pytest \
  backend/tests/test_native_raganything_adapter.py::test_scoped_vector_proxy_filters_by_full_doc_id \
  backend/tests/test_native_raganything_adapter.py::test_scoped_vector_proxy_preserves_base_attributes \
  -q
```

Expected: FAIL with `ImportError` or `AttributeError` because `ScopedVectorStorageProxy` does not exist.

- [ ] **Step 3: Implement `ScopedVectorStorageProxy`**

Add this class near the top of `backend/src/ragstudio/services/native_raganything_adapter.py`, after imports and before `NativeRAGAnythingAdapter`:

```python
class ScopedVectorStorageProxy:
    """Filters LightRAG chunk vector results to selected RAG-Anything doc IDs."""

    def __init__(
        self,
        base: Any,
        document_ids: list[str],
        *,
        overfetch_multiplier: int = 8,
        max_fetch: int = 200,
    ) -> None:
        self.base = base
        self.document_ids = {str(document_id) for document_id in document_ids}
        self.overfetch_multiplier = max(1, overfetch_multiplier)
        self.max_fetch = max(1, max_fetch)
        self.collected_results: list[dict[str, Any]] = []

    async def query(
        self,
        query: str,
        top_k: int,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        requested_top_k = min(max(top_k * self.overfetch_multiplier, top_k), self.max_fetch)
        rows = await self.base.query(
            query,
            top_k=requested_top_k,
            query_embedding=query_embedding,
        )
        scoped_rows = [
            row
            for row in rows
            if str(row.get("full_doc_id") or "") in self.document_ids
        ][:top_k]
        self.collected_results.extend(scoped_rows)
        return scoped_rows

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src \
python -m pytest \
  backend/tests/test_native_raganything_adapter.py::test_scoped_vector_proxy_filters_by_full_doc_id \
  backend/tests/test_native_raganything_adapter.py::test_scoped_vector_proxy_preserves_base_attributes \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/native_raganything_adapter.py backend/tests/test_native_raganything_adapter.py
git commit -m "test: cover native scoped vector filtering"
```

---

### Task 2: Implement Native Scoped Query in the Adapter

**Files:**
- Modify: `backend/src/ragstudio/services/native_raganything_adapter.py`
- Modify: `backend/tests/test_native_raganything_adapter.py`

- [ ] **Step 1: Replace the refusing scoped-query test with a native success test**

In `backend/tests/test_native_raganything_adapter.py`, replace `test_native_adapter_refuses_unscoped_document_queries` with this test:

```python
@pytest.mark.asyncio
async def test_native_adapter_queries_selected_documents_with_scoped_lightrag(tmp_path):
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    result = await adapter.query(
        "how many hadith in bukhari",
        document_ids=["doc-1"],
        query_config={"mode": "hybrid", "top_k": 12, "chunk_top_k": 4},
    )

    assert result.error is None
    assert result.error_type is None
    assert result.answer == "native scoped answer: how many hadith in bukhari:hybrid:12"
    assert result.sources == [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "text": "Sahih al-Bukhari 7277 Hadith Collection",
            "source_location": {"file_path": "bukhari.pdf"},
            "metadata": {
                "full_doc_id": "doc-1",
                "score": 0.91,
                "native_scope": True,
            },
        }
    ]
    assert result.timings["native_scoped_query"] is True
    assert result.timings["runtime_query_ms"] >= 0
```

Update `FakeRAGAnything` in the same test file so it has a fake LightRAG object:

```python
class FakeLightRAG:
    def __init__(self):
        self.deleted = []
        self.chunks_vdb = FakeChunkVectorStorage(
            [
                {
                    "id": "chunk-1",
                    "full_doc_id": "doc-1",
                    "content": "Sahih al-Bukhari 7277 Hadith Collection",
                    "file_path": "bukhari.pdf",
                    "score": 0.91,
                },
                {
                    "id": "chunk-2",
                    "full_doc_id": "doc-2",
                    "content": "Outside document",
                    "file_path": "other.pdf",
                    "score": 0.88,
                },
            ]
        )

    async def adelete_by_doc_id(self, doc_id):
        self.deleted.append(doc_id)

    async def aquery_data(self, query, param):
        rows = await self.chunks_vdb.query(query, top_k=param.chunk_top_k or param.top_k)
        return {
            "status": "success",
            "data": {
                "chunks": [
                    {
                        "chunk_id": row["id"],
                        "content": row["content"],
                        "file_path": row["file_path"],
                    }
                    for row in rows
                ],
                "entities": [],
                "relationships": [],
                "references": [],
            },
        }
```

Change `FakeRAGAnything.__init__` to use the fake LightRAG:

```python
self.lightrag = FakeLightRAG()
self.deleted = self.lightrag.deleted
```

Change `FakeRAGAnything.aquery` to prove the scoped proxy is installed:

```python
async def aquery(self, query, mode="mix", **kwargs):
    if not self.initialized:
        raise AssertionError("aquery called before LightRAG initialization")
    rows = await self.lightrag.chunks_vdb.query(
        query,
        top_k=kwargs.get("chunk_top_k") or kwargs["top_k"],
    )
    if [row["full_doc_id"] for row in rows] != ["doc-1"]:
        raise AssertionError(f"unscoped rows reached native query: {rows}")
    return f"native scoped answer: {query}:{mode}:{kwargs['top_k']}"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src \
python -m pytest \
  backend/tests/test_native_raganything_adapter.py::test_native_adapter_queries_selected_documents_with_scoped_lightrag \
  -q
```

Expected: FAIL because `NativeRAGAnythingAdapter.query()` still returns `native_document_scope_unsupported`.

- [ ] **Step 3: Add scoped query helpers**

In `backend/src/ragstudio/services/native_raganything_adapter.py`, add these methods inside `NativeRAGAnythingAdapter`:

```python
    @asynccontextmanager
    async def _scoped_chunks_vdb(
        self,
        rag: Any,
        document_ids: list[str],
    ) -> AsyncIterator[ScopedVectorStorageProxy]:
        await self._ensure_lightrag(rag)
        lightrag = getattr(rag, "lightrag", None)
        if lightrag is None or not hasattr(lightrag, "chunks_vdb"):
            raise RuntimeError("LightRAG chunks vector storage is not initialized.")

        original_chunks_vdb = lightrag.chunks_vdb
        proxy = ScopedVectorStorageProxy(original_chunks_vdb, document_ids)
        lightrag.chunks_vdb = proxy
        try:
            yield proxy
        finally:
            lightrag.chunks_vdb = original_chunks_vdb

    def _query_param(self, mode: str, query_config: dict[str, Any]) -> Any:
        query_param_cls = import_module("lightrag.base").QueryParam
        return query_param_cls(mode=mode, **self._query_kwargs(query_config))

    def _native_sources_from_proxy(
        self,
        proxy: ScopedVectorStorageProxy,
        document_ids: list[str],
    ) -> list[dict[str, Any]]:
        allowed = set(document_ids)
        deduped: dict[str, dict[str, Any]] = {}
        for row in proxy.collected_results:
            document_id = str(row.get("full_doc_id") or "")
            if document_id not in allowed:
                continue
            chunk_id = str(row.get("id") or "")
            if not chunk_id or chunk_id in deduped:
                continue
            deduped[chunk_id] = {
                "chunk_id": chunk_id,
                "document_id": document_id,
                "text": str(row.get("content") or ""),
                "source_location": {"file_path": row.get("file_path")},
                "metadata": {
                    "full_doc_id": document_id,
                    "score": row.get("score"),
                    "native_scope": True,
                },
            }
        return list(deduped.values())

    def _scope_leak_error(
        self,
        proxy: ScopedVectorStorageProxy,
        document_ids: list[str],
    ) -> RuntimeQueryResult | None:
        allowed = set(document_ids)
        leaked_ids = sorted(
            {
                str(row.get("full_doc_id") or "")
                for row in proxy.collected_results
                if str(row.get("full_doc_id") or "") not in allowed
            }
        )
        if not leaked_ids:
            return None
        return RuntimeQueryResult(
            answer="",
            sources=[],
            timings={},
            error=(
                "Native RAG-Anything scoped query returned chunks outside selected "
                f"document_ids: {', '.join(leaked_ids)}"
            ),
            error_type="native_document_scope_leak",
        )
```

- [ ] **Step 4: Replace scoped refusal with native scoped execution**

In `NativeRAGAnythingAdapter.query()`, replace the current `if document_ids:` failure block and following unscoped logic with:

```python
        rag = self._raganything()
        mode = str(query_config.get("mode") or self.profile.query_mode)
        kwargs = self._query_kwargs(query_config)
        started = asyncio.get_running_loop().time()
        async with self._storage_env():
            if document_ids:
                async with self._scoped_chunks_vdb(rag, document_ids) as scoped_proxy:
                    query_param = self._query_param(mode, query_config)
                    lightrag = getattr(rag, "lightrag")
                    if hasattr(lightrag, "aquery_data"):
                        await lightrag.aquery_data(query, query_param)
                    answer = await rag.aquery(query, mode=mode, **kwargs)
                    leak = self._scope_leak_error(scoped_proxy, document_ids)
                    if leak is not None:
                        return leak
                    return RuntimeQueryResult(
                        answer=str(answer or ""),
                        sources=self._native_sources_from_proxy(scoped_proxy, document_ids),
                        timings={
                            "runtime_query_ms": round(
                                (asyncio.get_running_loop().time() - started) * 1000,
                                3,
                            ),
                            "native_scoped_query": True,
                        },
                    )

            await self._ensure_lightrag(rag)
            answer = await rag.aquery(query, mode=mode, **kwargs)
        return RuntimeQueryResult(
            answer=str(answer or ""),
            sources=[],
            timings={
                "runtime_query_ms": round(
                    (asyncio.get_running_loop().time() - started) * 1000,
                    3,
                ),
                "native_scoped_query": False,
            },
        )
```

- [ ] **Step 5: Update capability report**

In `NativeRAGAnythingAdapter.capability_report()`, change the scoped query keys to:

```python
            "native_scoped_query": True,
            "scoped_query": "raganything_full_doc_id",
            "scoped_query_detail": (
                "Native RAG-Anything query scopes selected documents through "
                "LightRAG chunk full_doc_id filtering."
            ),
```

- [ ] **Step 6: Run adapter tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src \
python -m pytest backend/tests/test_native_raganything_adapter.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/native_raganything_adapter.py backend/tests/test_native_raganything_adapter.py
git commit -m "feat: enforce native raganything document scope"
```

---

### Task 3: Fail Closed on Scope Leaks

**Files:**
- Modify: `backend/tests/test_native_raganything_adapter.py`
- Modify: `backend/src/ragstudio/services/native_raganything_adapter.py`

- [ ] **Step 1: Add a leak regression test**

Append this test to `backend/tests/test_native_raganything_adapter.py`:

```python
@pytest.mark.asyncio
async def test_native_adapter_fails_if_scoped_proxy_records_outside_doc(tmp_path):
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    rag = adapter._raganything()
    rag.lightrag.chunks_vdb = FakeChunkVectorStorage(
        [
            {
                "id": "chunk-9",
                "full_doc_id": "doc-2",
                "content": "outside",
                "file_path": "outside.pdf",
            }
        ]
    )

    result = adapter._scope_leak_error(
        ScopedVectorStorageProxy(rag.lightrag.chunks_vdb, ["doc-1"]),
        ["doc-1"],
    )

    assert result is None

    proxy = ScopedVectorStorageProxy(rag.lightrag.chunks_vdb, ["doc-1"])
    proxy.collected_results.append(
        {
            "id": "chunk-9",
            "full_doc_id": "doc-2",
            "content": "outside",
            "file_path": "outside.pdf",
        }
    )
    result = adapter._scope_leak_error(proxy, ["doc-1"])

    assert result is not None
    assert result.error_type == "native_document_scope_leak"
    assert "doc-2" in (result.error or "")
```

- [ ] **Step 2: Run test to verify it passes**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src \
python -m pytest \
  backend/tests/test_native_raganything_adapter.py::test_native_adapter_fails_if_scoped_proxy_records_outside_doc \
  -q
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/src/ragstudio/services/native_raganything_adapter.py backend/tests/test_native_raganything_adapter.py
git commit -m "test: fail closed on native scope leaks"
```

---

### Task 4: Update Query Service Regression Coverage

**Files:**
- Modify: `backend/tests/test_runtime_query_service.py`
- Modify: `backend/src/ragstudio/services/query_service.py`

- [ ] **Step 1: Add a native scoped success test**

In `backend/tests/test_runtime_query_service.py`, append this test after `test_query_service_uses_runtime_without_chunk_search`:

```python
@pytest.mark.asyncio
async def test_query_service_records_native_scoped_runtime_success(client):
    app = client._transport.app
    runtime = FakeRuntime(
        RuntimeQueryResult(
            answer="native scoped answer",
            sources=[
                {
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "text": "Sahih al-Bukhari 7277 Hadith Collection",
                    "metadata": {"native_scope": True},
                }
            ],
            chunk_traces=[{"rank": 1, "inclusion_status": "native-scoped"}],
            timings={"runtime_query_ms": 7, "native_scoped_query": True},
        )
    )
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(session, app)

        result = await QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
        ).run_query(
            QueryIn(
                query="how many hadith in bukhari",
                document_ids=[document.id],
                variant_ids=[variant.id],
            )
        )

    run = result.runs[0]
    assert run.status == StageStatus.SUCCEEDED
    assert run.answer == "native scoped answer"
    assert run.sources[0]["metadata"]["native_scope"] is True
    assert run.timings["native_scoped_query"] is True
    assert "scoped_runtime_fallback" not in run.timings
```

- [ ] **Step 2: Run test**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src \
python -m pytest \
  backend/tests/test_runtime_query_service.py::test_query_service_records_native_scoped_runtime_success \
  -q
```

Expected: PASS. `QueryService` already persists successful runtime results without fallback when the adapter does not return `native_document_scope_unsupported`.

- [ ] **Step 3: Keep mirrored fallback as compatibility behavior**

Do not remove `_run_scoped_mirrored_runtime_query()` from `backend/src/ragstudio/services/query_service.py`. It remains useful if an older adapter or upstream package version returns `native_document_scope_unsupported`.

- [ ] **Step 4: Run query service tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src \
python -m pytest backend/tests/test_runtime_query_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_runtime_query_service.py backend/src/ragstudio/services/query_service.py
git commit -m "test: record native scoped query success"
```

---

### Task 5: Update Diagnostics to Report Native Scoped Query

**Files:**
- Modify: `backend/src/ragstudio/services/diagnostics_service.py`
- Modify: `backend/tests/test_optimizer_graph_diagnostics.py`

- [ ] **Step 1: Update diagnostics test expectations**

In `backend/tests/test_optimizer_graph_diagnostics.py`, update `test_diagnostics_reports_native_dependency_status_for_runtime_mode` assertions to:

```python
    assert payload.capabilities["fallback_active"] is False
    assert payload.capabilities["graph"] is True
    assert payload.capabilities["native_scoped_query"] is True
    assert payload.capabilities["scoped_query_fallback"] is False
    assert payload.dependency_status["active_backend"] == "runtime"
    assert payload.dependency_status["indexing"] == "raganything"
    assert payload.dependency_status["query"] == "raganything"
    assert payload.dependency_status["graph"] == "neo4j"
    assert payload.dependency_status["native_scoped_query"] is True
    assert payload.dependency_status["scoped_query"] == "raganything_full_doc_id"
    assert (
        payload.dependency_status["scoped_query_detail"]
        == "Native RAG-Anything query scopes selected documents through "
        "LightRAG chunk full_doc_id filtering."
    )
    assert not any(
        "mirrored chunk fallback" in warning
        for warning in payload.warnings
    )
```

- [ ] **Step 2: Run diagnostics test to verify it fails**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src \
python -m pytest \
  backend/tests/test_optimizer_graph_diagnostics.py::test_diagnostics_reports_native_dependency_status_for_runtime_mode \
  -q
```

Expected: FAIL because diagnostics still reports fallback scoped behavior.

- [ ] **Step 3: Update runtime dependency report**

In `backend/src/ragstudio/services/diagnostics_service.py`, update `_runtime_dependency_report()` scoped query fields to:

```python
            "native_scoped_query": runtime_available,
            "scoped_query": (
                "raganything_full_doc_id" if runtime_available else "unavailable"
            ),
            "scoped_query_detail": (
                "Native RAG-Anything query scopes selected documents through "
                "LightRAG chunk full_doc_id filtering."
                if runtime_available
                else "Native RAG-Anything query is unavailable because runtime health is blocked."
            ),
```

In `_get_diagnostics_async()`, set capabilities to:

```python
                "native_scoped_query": dependency_report.get("native_scoped_query") is True,
                "scoped_query_fallback": False,
```

Remove the runtime-mode warning that says:

```python
"Native RAG-Anything scoped query is unavailable; selected-document queries use Ragstudio's mirrored chunk fallback."
```

- [ ] **Step 4: Run diagnostics test**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src \
python -m pytest \
  backend/tests/test_optimizer_graph_diagnostics.py::test_diagnostics_reports_native_dependency_status_for_runtime_mode \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/diagnostics_service.py backend/tests/test_optimizer_graph_diagnostics.py
git commit -m "feat: report native scoped query diagnostics"
```

---

### Task 6: Live Runtime Verification

**Files:**
- No source file edits.

- [ ] **Step 1: Restart backend and frontend**

Run:

```bash
docker compose restart backend frontend
```

Expected: both containers restart successfully.

- [ ] **Step 2: Confirm runtime diagnostics**

Run:

```bash
curl -sS http://localhost:5173/api/diagnostics | python -m json.tool | sed -n '1,120p'
```

Expected output includes:

```json
"runtime_mode": "runtime",
"overall_status": "ready",
"dependency_status": {
  "active_backend": "runtime",
  "query": "raganything",
  "native_scoped_query": true,
  "scoped_query": "raganything_full_doc_id"
}
```

- [ ] **Step 3: Confirm selected-document query succeeds natively**

Run:

```bash
DOC_ID=$(curl -sS http://localhost:5173/api/documents | python - <<'PY'
import json, sys
payload = json.load(sys.stdin)
print(payload["items"][0]["id"])
PY
)
VARIANT_ID=$(curl -sS http://localhost:5173/api/variants | python - <<'PY'
import json, sys
payload = json.load(sys.stdin)
print(payload["items"][0]["id"])
PY
)
curl -sS -X POST http://localhost:5173/api/query \
  -H 'content-type: application/json' \
  -d "{\"query\":\"how many hadith in bukhari\",\"document_ids\":[\"$DOC_ID\"],\"variant_ids\":[\"$VARIANT_ID\"],\"limit\":8}" \
  | python -m json.tool | sed -n '1,180p'
```

Expected output includes:

```json
"status": "succeeded",
"error": null,
"error_type": null,
"timings": {
  "native_scoped_query": true
}
```

Expected output does not include:

```text
native_document_scope_unsupported
scoped_runtime_fallback
```

- [ ] **Step 4: Verify sources are scoped to the selected document**

Run:

```bash
curl -sS -X POST http://localhost:5173/api/query \
  -H 'content-type: application/json' \
  -d "{\"query\":\"how many hadith in bukhari\",\"document_ids\":[\"$DOC_ID\"],\"variant_ids\":[\"$VARIANT_ID\"],\"limit\":8}" \
  | python - <<'PY'
import json, sys
payload = json.load(sys.stdin)
for run in payload["runs"]:
    bad = [
        source
        for source in run["sources"]
        if source.get("document_id") != run["document_ids"][0]
    ]
    assert run["status"] == "succeeded", run
    assert not bad, bad
print("all sources scoped")
PY
```

Expected:

```text
all sources scoped
```

- [ ] **Step 5: Commit verification notes if docs changed**

If `docs/workflows.md` was updated, commit it:

```bash
git add docs/workflows.md
git commit -m "docs: describe native scoped query"
```

If no docs changed, skip this commit.

---

### Task 7: Full Focused Validation

**Files:**
- No source file edits.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src \
python -m pytest \
  backend/tests/test_native_raganything_adapter.py \
  backend/tests/test_runtime_query_service.py \
  backend/tests/test_optimizer_graph_diagnostics.py::test_diagnostics_reports_native_dependency_status_for_runtime_mode \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run focused lint on touched files**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH python -m ruff check \
  backend/src/ragstudio/services/native_raganything_adapter.py \
  backend/src/ragstudio/services/query_service.py \
  backend/src/ragstudio/services/diagnostics_service.py \
  backend/tests/test_native_raganything_adapter.py \
  backend/tests/test_runtime_query_service.py
```

Expected: PASS.

Do not include `backend/tests/test_optimizer_graph_diagnostics.py` in this focused Ruff command until the unrelated existing long-line edits in that file are cleaned up. The focused diagnostics pytest above still validates the changed behavior.

- [ ] **Step 3: Check worktree**

Run:

```bash
git status --short
```

Expected: only files intentionally touched by this plan are modified, plus any unrelated user work that existed before implementation.

---

## Self-Review

**Spec coverage:** This plan implements native selected-document query scope in the RAG-Anything adapter, preserves the mirrored fallback as compatibility behavior, updates diagnostics so the UI stops reporting scoped native query as missing, and includes live verification against the Bukhari query path.

**Placeholder scan:** The plan contains exact file paths, commands, expected outputs, and code blocks for every code-changing step.

**Type consistency:** The plan consistently uses `document_ids`, LightRAG `full_doc_id`, `ScopedVectorStorageProxy`, `RuntimeQueryResult`, and diagnostics keys `native_scoped_query` plus `scoped_query`.
