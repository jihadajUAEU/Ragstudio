# Technical Audit Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the highest-risk findings in `TECHNICAL_AUDIT.md` with tested runtime, graph, scoring, optimizer, variant, experiment, and frontend job-refresh fixes.

**Architecture:** Treat the audit as several staged remediations, not one sweeping rewrite. The first stage stabilizes native runtime isolation and scoped query behavior, the second stage fixes graph and scoring correctness, and the final stage adds missing API/UI operations that users can exercise directly.

**Tech Stack:** FastAPI, SQLAlchemy async sessions, Pydantic schemas, pytest/pytest-asyncio, React, TanStack Query, Vitest, TypeScript, lucide-react.

---

## Scope Check

`TECHNICAL_AUDIT.md` contains 31 findings across independent subsystems. This plan fixes the recommended priority order plus the adjacent product gaps that are already covered by current tests and UI patterns:

- Runtime/security: §2.1 environment mutation race, §1.1 native scoped query.
- Graph/correctness: §3.1 graph chunk loading, §1.2 fallback placeholder messaging.
- Evaluation quality: §2.2 scoring empty signal behavior, §2.3 optimizer missing-score ranking.
- Product gaps: §1.4 preset semantics, §1.5 variant edit/delete, §1.6 experiment history, §5.1 active job polling.
- Low-risk duplication: §4.4 `toggleId()`, §4.5 `parseObject()`.

The remaining performance and enhancement items, such as shared `httpx.AsyncClient`, API pagination across every list endpoint, SSE progress streams, query history, bulk operations, settings import/export, router migration, and global CSS variable replacement, should be separate plans because each can affect broad app behavior.

## File Structure

- Modify `backend/src/ragstudio/services/native_raganything_adapter.py`: make runtime env overlay thread-aware, expose native scoped query capability, and pass scoped document IDs to the native query path.
- Modify `backend/tests/test_native_raganything_adapter.py`: cover env locking and native scoped query kwargs.
- Modify `backend/src/ragstudio/services/diagnostics_service.py`: report scoped query as supported when the active runtime adapter does.
- Modify `backend/tests/test_optimizer_graph_diagnostics.py`: update diagnostics expectations and add graph limit coverage.
- Modify `backend/src/ragstudio/services/graph_service.py`: query only chunks with relationship metadata, cap fallback graph work, and return explanatory placeholder metadata instead of a silent empty graph.
- Modify `backend/src/ragstudio/schemas/graph.py`: allow an optional `detail` string for graph explanations.
- Modify `frontend/src/features/graph/graph-page.tsx`: show graph truncation and fallback detail prominently.
- Modify `frontend/tests/graph-page.test.tsx`: assert warning/detail text.
- Modify `backend/src/ragstudio/services/scoring_service.py`: return a non-perfect score when a case has no machine-scoreable signals.
- Modify `backend/tests/test_experiments_scoring.py`: add empty-signal scoring coverage.
- Modify `backend/src/ragstudio/services/optimizer_service.py`: rank unscored successful runs below formally scored runs and explain the choice.
- Modify `backend/tests/test_optimizer_graph_diagnostics.py`: add optimizer missing-score regression.
- Modify `backend/src/ragstudio/services/variant_service.py`: apply preset defaults, add update/delete methods.
- Modify `backend/src/ragstudio/schemas/variants.py`: add `VariantUpdate` and preset validation constants.
- Modify `backend/src/ragstudio/api/routes/variants.py`: add `PUT /api/variants/{variant_id}` and `DELETE /api/variants/{variant_id}`.
- Modify `backend/tests/test_variants.py`: cover preset merge, update, delete, and not-found behavior.
- Modify `frontend/src/api/client.ts`: add variant update/delete and experiment list methods.
- Modify `frontend/src/api/generated.ts`: add `VariantUpdate` and `ExperimentPage` interfaces after regenerating or manually syncing the local contract.
- Modify `frontend/src/features/variants/variants-page.tsx`: add edit/delete controls and preset-driven parameter preview.
- Modify `frontend/tests/variants-page.test.tsx`: cover update/delete flows.
- Modify `backend/src/ragstudio/services/experiment_service.py`: add list/get history methods with runs and scores.
- Modify `backend/src/ragstudio/schemas/experiments.py`: add `ExperimentPage`.
- Modify `backend/src/ragstudio/api/routes/experiments.py`: add `GET /api/experiments` and `GET /api/experiments/{experiment_id}`.
- Modify `backend/tests/test_experiments_scoring.py`: cover experiment list/history.
- Modify `frontend/src/features/experiments/experiments-page.tsx`: show experiment history from API, not only the last mutation.
- Modify `frontend/tests/evaluation-import.test.tsx`: extend or add a focused experiments page history test.
- Modify `frontend/src/lib/utils.ts`: add shared `toggleId()` and `parseJsonObject()`.
- Modify `frontend/src/features/comparison/comparison-page.tsx`, `frontend/src/features/experiments/experiments-page.tsx`, and `frontend/src/features/optimizer/optimizer-page.tsx`: use shared helpers.
- Modify `frontend/src/features/documents/documents-page.tsx` and `frontend/src/features/dashboard/dashboard-page.tsx`: refetch active jobs automatically.
- Modify `frontend/tests/documents-page.test.tsx`: cover active-job polling behavior.
- Modify `TECHNICAL_AUDIT.md`: add a short “Remediation status” section listing fixed findings and deferred follow-up plans.

---

### Task 1: Runtime Environment Isolation

**Files:**
- Modify: `backend/src/ragstudio/services/native_raganything_adapter.py`
- Test: `backend/tests/test_native_raganything_adapter.py`

- [ ] **Step 1: Write the failing env isolation test**

Append this test to `backend/tests/test_native_raganything_adapter.py`:

```python
@pytest.mark.asyncio
async def test_storage_env_uses_thread_visible_lock(tmp_path):
    profile = _runtime_profile(tmp_path)
    adapter = NativeRAGAnythingAdapter(profile)

    async with adapter._storage_env():
        assert NativeRAGAnythingAdapter._env_lock.locked()
        assert os.environ["POSTGRES_WORKSPACE"] == f"ragstudio_{profile.id}"
        assert await asyncio.to_thread(lambda: os.environ["NEO4J_WORKSPACE"]) == f"ragstudio_{profile.id}"

    assert "POSTGRES_WORKSPACE" not in os.environ
    assert "NEO4J_WORKSPACE" not in os.environ
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/pytest backend/tests/test_native_raganything_adapter.py::test_storage_env_uses_thread_visible_lock -v
```

Expected: FAIL because `_env_lock` is an `asyncio.Lock` and has no thread-visible `locked()` behavior suitable for cross-thread protection.

- [ ] **Step 3: Replace the async-only lock with a thread-visible async wrapper**

In `backend/src/ragstudio/services/native_raganything_adapter.py`, replace the `_env_lock` declaration and `_storage_env()` body:

```python
import threading


class AsyncThreadLock:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._locked = False

    async def __aenter__(self) -> "AsyncThreadLock":
        await asyncio.to_thread(self._lock.acquire)
        self._locked = True
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self._locked = False
        self._lock.release()

    def locked(self) -> bool:
        return self._locked


class NativeRAGAnythingAdapter:
    """Runtime adapter for the real RAG-Anything and LightRAG stack."""

    _env_lock = AsyncThreadLock()
```

Keep `_storage_env()` using `async with self._env_lock:` exactly as today. This preserves the existing critical section while making lock acquisition safe when native code uses `asyncio.to_thread()`.

- [ ] **Step 4: Run runtime adapter tests**

Run:

```bash
.venv/bin/pytest backend/tests/test_native_raganything_adapter.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/native_raganything_adapter.py backend/tests/test_native_raganything_adapter.py
git commit -m "fix: protect native runtime env overlay across threads"
```

---

### Task 2: Native Scoped Query Support

**Files:**
- Modify: `backend/src/ragstudio/services/native_raganything_adapter.py`
- Modify: `backend/src/ragstudio/services/diagnostics_service.py`
- Test: `backend/tests/test_native_raganything_adapter.py`
- Test: `backend/tests/test_optimizer_graph_diagnostics.py`

- [ ] **Step 1: Write the failing scoped query test**

Replace the existing test that expects `native_document_scope_unsupported` in `backend/tests/test_native_raganything_adapter.py` with:

```python
@pytest.mark.asyncio
async def test_native_adapter_passes_document_ids_to_query(tmp_path):
    profile = _runtime_profile(tmp_path)
    fake = FakeRAGAnything()
    adapter = NativeRAGAnythingAdapter(profile)
    adapter._rag = fake

    result = await adapter.query(
        "What is in doc one?",
        document_ids=["doc-1"],
        query_config={"top_k": 7, "mode": "mix"},
    )

    assert result.error is None
    assert result.answer == "native answer"
    assert fake.queries == [
        {
            "query": "What is in doc one?",
            "mode": "mix",
            "kwargs": {"top_k": 7, "ids": ["doc-1"]},
        }
    ]
    assert result.sources == [{"document_id": "doc-1"}]
    assert result.timings["native_scoped_query"] is True
```

Ensure `FakeRAGAnything.aquery()` stores kwargs:

```python
async def aquery(self, query, mode="mix", **kwargs):
    self.queries.append({"query": query, "mode": mode, "kwargs": kwargs})
    return "native answer"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/pytest backend/tests/test_native_raganything_adapter.py::test_native_adapter_passes_document_ids_to_query -v
```

Expected: FAIL because the adapter currently refuses scoped native queries.

- [ ] **Step 3: Implement scoped query kwargs and capability reporting**

In `backend/src/ragstudio/services/native_raganything_adapter.py`, update `capability_report()`:

```python
"scoped_query": True,
"scoped_query_detail": "Native RAG-Anything query receives selected document_ids via LightRAG ids filtering.",
```

Replace the early `if document_ids:` refusal in `query()` with:

```python
rag = self._raganything()
mode = str(query_config.get("mode") or self.profile.query_mode)
kwargs = self._query_kwargs(query_config)
if document_ids:
    kwargs["ids"] = list(dict.fromkeys(document_ids))
started = asyncio.get_running_loop().time()
async with self._storage_env():
    await self._ensure_lightrag(rag)
    answer = await rag.aquery(query, mode=mode, **kwargs)
return RuntimeQueryResult(
    answer=str(answer or ""),
    sources=[{"document_id": document_id} for document_id in document_ids],
    timings={
        "runtime_query_ms": round(
            (asyncio.get_running_loop().time() - started) * 1000,
            3,
        ),
        "native_scoped_query": bool(document_ids),
    },
)
```

- [ ] **Step 4: Update diagnostics expectations**

In `backend/tests/test_optimizer_graph_diagnostics.py`, update the diagnostics assertion:

```python
assert payload.dependency_status["scoped_query"] is True
assert (
    payload.dependency_status["scoped_query_detail"]
    == "Native RAG-Anything query receives selected document_ids via LightRAG ids filtering."
)
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
.venv/bin/pytest backend/tests/test_native_raganything_adapter.py backend/tests/test_optimizer_graph_diagnostics.py::test_diagnostics_reports_runtime_dependency_status -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/native_raganything_adapter.py backend/src/ragstudio/services/diagnostics_service.py backend/tests/test_native_raganything_adapter.py backend/tests/test_optimizer_graph_diagnostics.py
git commit -m "feat: enable scoped native runtime queries"
```

---

### Task 3: Fallback Graph Scalability and Feedback

**Files:**
- Modify: `backend/src/ragstudio/services/graph_service.py`
- Modify: `backend/src/ragstudio/schemas/graph.py`
- Modify: `frontend/src/features/graph/graph-page.tsx`
- Test: `backend/tests/test_optimizer_graph_diagnostics.py`
- Test: `frontend/tests/graph-page.test.tsx`

- [ ] **Step 1: Write backend graph tests**

Append these tests to `backend/tests/test_optimizer_graph_diagnostics.py`:

```python
@pytest.mark.asyncio
async def test_graph_fallback_scans_only_relationship_metadata_chunks(client):
    from ragstudio.db.models import Chunk, Document
    from ragstudio.schemas.common import StageStatus
    from ragstudio.services.graph_service import GraphService

    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="graph.txt",
            content_type="text/plain",
            sha256="graph-filtered",
            artifact_path=str(app.state.settings.data_dir / "graph.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add_all(
            [
                Chunk(document_id=document.id, text="plain", metadata_json={}),
                Chunk(
                    document_id=document.id,
                    text="relationship",
                    metadata_json={
                        "relationship_metadata": {
                            "graph_relationships": [
                                {"source": "a", "target": "b", "type": "related"}
                            ]
                        }
                    },
                ),
            ]
        )
        await session.commit()

        graph = await GraphService(session, app.state.settings).get_graph()

    assert {node["id"] for node in graph.nodes} == {"a", "b"}
    assert graph.edges[0]["id"] == "a-b-related"


@pytest.mark.asyncio
async def test_empty_fallback_graph_returns_detail(client):
    response = await client.get("/api/graph")

    assert response.status_code == 200
    assert response.json()["nodes"] == []
    assert response.json()["edges"] == []
    assert response.json()["detail"] == "No runtime graph or relationship metadata is available."
```

- [ ] **Step 2: Run backend tests to verify they fail**

Run:

```bash
.venv/bin/pytest backend/tests/test_optimizer_graph_diagnostics.py::test_graph_fallback_scans_only_relationship_metadata_chunks backend/tests/test_optimizer_graph_diagnostics.py::test_empty_fallback_graph_returns_detail -v
```

Expected: FAIL because `GraphOut` has no `detail`, and `_relationship_metadata_graph()` selects all chunks.

- [ ] **Step 3: Add graph detail schema**

In `backend/src/ragstudio/schemas/graph.py`, define:

```python
from typing import Any

from ragstudio.schemas.common import StudioModel


class GraphOut(StudioModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    detail: str | None = None
```

- [ ] **Step 4: Cap fallback relationship graph loading**

In `backend/src/ragstudio/services/graph_service.py`, change `get_graph()` and `_relationship_metadata_graph()`:

```python
async def get_graph(self) -> GraphOut:
    graph = await self._graph()
    return GraphOut(
        nodes=list(graph.get("nodes") or []),
        edges=list(graph.get("edges") or []),
        detail=graph.get("detail"),
    )

async def _relationship_metadata_graph(self, *, limit: int = 2_000) -> dict[str, list[dict[str, Any]] | str]:
    if self.session is None:
        return {"nodes": [], "edges": [], "detail": "No database session is available for fallback graph metadata."}
    statement = (
        select(Chunk)
        .where(Chunk.metadata_json["relationship_metadata"].is_not(None))
        .order_by(Chunk.created_at.desc())
        .limit(limit)
    )
    result = await self.session.execute(statement)
    chunks = result.scalars().all()
```

Keep the existing node/edge build loop, then return:

```python
detail = None
if not nodes and not edges:
    detail = "No runtime graph or relationship metadata is available."
return {"nodes": list(nodes.values()), "edges": list(edges.values()), "detail": detail}
```

Where `_graph()` previously returned `await self.adapter.graph()` after an empty fallback graph, return the fallback graph directly in fallback/no-profile mode.

- [ ] **Step 5: Add frontend graph detail warning**

In `frontend/src/features/graph/graph-page.tsx`, render this near the graph summary:

```tsx
{graphQuery.data?.detail ? (
  <div className="rounded-md border border-[#f4c95d] bg-[#fff8e1] px-3 py-2 text-sm text-[#6d5700]">
    {graphQuery.data.detail}
  </div>
) : null}
```

Also make the existing 50-node truncation notice prominent:

```tsx
{nodes.length > previewNodes.length || edges.length > previewEdges.length ? (
  <div className="rounded-md border border-[#d6dde1] bg-[#f7fafb] px-3 py-2 text-sm text-[#3a4a53]">
    Showing {previewNodes.length} of {nodes.length} nodes and {previewEdges.length} of {edges.length} edges in the visual preview.
  </div>
) : null}
```

- [ ] **Step 6: Run backend and frontend tests**

Run:

```bash
.venv/bin/pytest backend/tests/test_optimizer_graph_diagnostics.py -v
cd frontend && npm test -- graph-page.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/graph_service.py backend/src/ragstudio/schemas/graph.py backend/tests/test_optimizer_graph_diagnostics.py frontend/src/features/graph/graph-page.tsx frontend/tests/graph-page.test.tsx
git commit -m "fix: bound fallback graph loading and surface graph state"
```

---

### Task 4: Evaluation Scoring and Optimizer Ranking Correctness

**Files:**
- Modify: `backend/src/ragstudio/services/scoring_service.py`
- Modify: `backend/src/ragstudio/services/optimizer_service.py`
- Test: `backend/tests/test_experiments_scoring.py`
- Test: `backend/tests/test_optimizer_graph_diagnostics.py`

- [ ] **Step 1: Write scoring regression test**

Append to `backend/tests/test_experiments_scoring.py`:

```python
def test_score_without_machine_scoreable_signals_is_zero():
    case = EvaluationCaseIn(
        id="empty",
        query="q",
        expected_answer="",
        must_include=[],
        must_avoid=[],
        rubric="Judge manually",
        expected_structure="bullet list",
    )
    run = Run(variant_id="variant", query="q", answer="anything")

    score = ScoringService().score(run, case)

    assert score.total == 0
    assert score.details["scoreable"] is False
    assert score.details["reason"] == "No expected_answer, must_include, or must_avoid signals were provided."
```

- [ ] **Step 2: Write optimizer missing-score regression test**

Append to `backend/tests/test_optimizer_graph_diagnostics.py`:

```python
@pytest.mark.asyncio
async def test_optimizer_does_not_prefer_unscored_success_over_scored_run(client):
    transport = client._transport
    async with transport.app.state.session_factory() as session:
        experiment = Experiment(
            name="Missing score optimizer experiment",
            document_ids=[],
            evaluation_set_id="eval",
            variant_ids=["scored", "unscored"],
            objective={"metric": "total"},
        )
        session.add(experiment)
        await session.flush()
        scored = Run(
            variant_id="scored",
            experiment_id=experiment.id,
            query="q",
            status="succeeded",
            answer="ok",
            sources=[],
        )
        unscored = Run(
            variant_id="unscored",
            experiment_id=experiment.id,
            query="q",
            status="succeeded",
            answer="ok",
            sources=[{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}, {"id": "e"}],
        )
        session.add_all([scored, unscored])
        await session.flush()
        session.add(Score(run_id=scored.id, total=40, details={"total": 40}))
        await session.commit()
        experiment_id = experiment.id

    response = await client.post("/api/optimizer", json={"experiment_id": experiment_id, "objective": {}})

    assert response.status_code == 200
    assert response.json()["selected_variant_id"] == "scored"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest backend/tests/test_experiments_scoring.py::test_score_without_machine_scoreable_signals_is_zero backend/tests/test_optimizer_graph_diagnostics.py::test_optimizer_does_not_prefer_unscored_success_over_scored_run -v
```

Expected: FAIL because empty scoring returns 100 and optimizer gives unscored runs a source-count heuristic.

- [ ] **Step 4: Fix scoring empty-signal behavior**

In `backend/src/ragstudio/services/scoring_service.py`, replace the `weights else 100` branch:

```python
if not weights:
    return {
        "total": 0,
        "scoreable": False,
        "reason": "No expected_answer, must_include, or must_avoid signals were provided.",
        "expected_terms": [],
        "expected_hits": [],
        "must_include_hits": [],
        "must_include_missing": [],
        "must_avoid_hits": [],
    }

normalized_total = round((total / weights) * 100)
```

Then keep the existing return block and add `"scoreable": True`.

- [ ] **Step 5: Fix optimizer missing-score ranking**

In `backend/src/ragstudio/services/optimizer_service.py`, replace `_run_score()`:

```python
def _run_score(self, run: Run, score: Score | None) -> float:
    if score is not None:
        return float(score.total)
    if run.error or run.status == "failed":
        return 0.0
    return -1.0
```

In `_summarize_candidates()`, keep totals as-is so unscored candidates remain visible but sort below scored candidates.

- [ ] **Step 6: Run focused tests**

Run:

```bash
.venv/bin/pytest backend/tests/test_experiments_scoring.py backend/tests/test_optimizer_graph_diagnostics.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/scoring_service.py backend/src/ragstudio/services/optimizer_service.py backend/tests/test_experiments_scoring.py backend/tests/test_optimizer_graph_diagnostics.py
git commit -m "fix: avoid inflated scores without evaluation signals"
```

---

### Task 5: Variant Presets, Edit, and Delete

**Files:**
- Modify: `backend/src/ragstudio/schemas/variants.py`
- Modify: `backend/src/ragstudio/services/variant_service.py`
- Modify: `backend/src/ragstudio/api/routes/variants.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/features/variants/variants-page.tsx`
- Test: `backend/tests/test_variants.py`
- Test: `frontend/tests/variants-page.test.tsx`

- [ ] **Step 1: Write backend variant tests**

Append to `backend/tests/test_variants.py`:

```python
@pytest.mark.asyncio
async def test_variant_presets_apply_default_parameters(client):
    response = await client.post(
        "/api/variants",
        json={"name": "Precise", "preset": "precise", "parameters": {"temperature": 0.3}},
    )

    assert response.status_code == 201
    parameters = response.json()["parameters"]
    assert parameters["top_k"] == 3
    assert parameters["enable_rerank"] is True
    assert parameters["temperature"] == 0.3


@pytest.mark.asyncio
async def test_variant_update_and_delete(client):
    created = await client.post(
        "/api/variants",
        json={"name": "Draft", "preset": "balanced", "parameters": {}},
    )
    variant_id = created.json()["id"]

    updated = await client.put(
        f"/api/variants/{variant_id}",
        json={"name": "Fast draft", "preset": "fast", "parameters": {"top_k": 2}},
    )

    assert updated.status_code == 200
    assert updated.json()["name"] == "Fast draft"
    assert updated.json()["parameters"]["top_k"] == 2
    assert updated.json()["parameters"]["enable_rerank"] is False

    deleted = await client.delete(f"/api/variants/{variant_id}")
    assert deleted.status_code == 204
    missing = await client.get(f"/api/variants/{variant_id}")
    assert missing.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest backend/tests/test_variants.py -v
```

Expected: FAIL because presets are raw labels and update/delete routes do not exist.

- [ ] **Step 3: Add variant schema and preset defaults**

In `backend/src/ragstudio/schemas/variants.py`, add:

```python
VARIANT_PRESET_DEFAULTS: dict[str, dict[str, Any]] = {
    "balanced": {"top_k": 5, "temperature": 0.2, "enable_rerank": True},
    "precise": {"top_k": 3, "temperature": 0.1, "enable_rerank": True},
    "broad": {"top_k": 12, "temperature": 0.3, "enable_rerank": True},
    "fast": {"top_k": 4, "temperature": 0.0, "enable_rerank": False},
}


class VariantUpdate(StudioModel):
    name: str = Field(min_length=1)
    preset: str
    parameters: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Apply presets in the service**

In `backend/src/ragstudio/services/variant_service.py`, import `VariantUpdate` and `VARIANT_PRESET_DEFAULTS`, then add:

```python
def _parameters_for(data: VariantIn | VariantUpdate) -> dict:
    defaults = VARIANT_PRESET_DEFAULTS.get(data.preset, VARIANT_PRESET_DEFAULTS["balanced"])
    return {**defaults, **data.parameters}
```

Update `create()`:

```python
variant = Variant(
    name=data.name,
    preset=data.preset,
    parameters=_parameters_for(data),
)
```

Add:

```python
async def update(self, variant_id: str, data: VariantUpdate) -> VariantOut:
    variant = await self.session.get(Variant, variant_id)
    if variant is None:
        raise KeyError(variant_id)
    variant.name = data.name
    variant.preset = data.preset
    variant.parameters = _parameters_for(data)
    await self.session.commit()
    await self.session.refresh(variant)
    return VariantOut.model_validate(variant)

async def delete(self, variant_id: str) -> None:
    variant = await self.session.get(Variant, variant_id)
    if variant is None:
        raise KeyError(variant_id)
    await self.session.delete(variant)
    await self.session.commit()
```

- [ ] **Step 5: Add routes**

In `backend/src/ragstudio/api/routes/variants.py`, import `Response` and `VariantUpdate`, then add:

```python
@router.put("/{variant_id}", response_model=VariantOut)
async def update_variant(
    variant_id: str,
    payload: VariantUpdate,
    session: AsyncSession = Depends(get_session),
) -> VariantOut:
    try:
        return await VariantService(session).update(variant_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Variant not found") from exc


@router.delete("/{variant_id}", status_code=204)
async def delete_variant(
    variant_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await VariantService(session).delete(variant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Variant not found") from exc
    return Response(status_code=204)
```

- [ ] **Step 6: Add frontend client methods**

In `frontend/src/api/generated.ts`, add:

```typescript
export interface VariantUpdate {
  name: string;
  preset: string;
  parameters?: Record<string, unknown>;
}
```

In `frontend/src/api/client.ts`, import `VariantUpdate` and add:

```typescript
updateVariant: (variantId: string, payload: VariantUpdate) =>
  request<VariantOut>(`/api/variants/${encodeURIComponent(variantId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }),
deleteVariant: (variantId: string) =>
  request<void>(`/api/variants/${encodeURIComponent(variantId)}`, {
    method: "DELETE",
  }),
```

- [ ] **Step 7: Add edit/delete UI**

In `frontend/src/features/variants/variants-page.tsx`, add `Pencil` and `Trash2` imports, `editingId` state, update/delete mutations, and an actions column:

```tsx
const [editingId, setEditingId] = useState<string | null>(null);

const updateVariant = useMutation({
  mutationFn: ({ variantId, payload }: { variantId: string; payload: VariantIn }) =>
    apiClient.updateVariant(variantId, payload),
  onSuccess: () => {
    setEditingId(null);
    setName("");
    setPreset("balanced");
    setParametersText(defaultParameters);
    void queryClient.invalidateQueries({ queryKey: queryKeys.variants });
  },
});

const deleteVariant = useMutation({
  mutationFn: apiClient.deleteVariant,
  onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.variants }),
});
```

In submit:

```tsx
if (editingId) {
  updateVariant.mutate({ variantId: editingId, payload: { name, preset, parameters } });
} else {
  createVariant.mutate({ name, preset, parameters });
}
```

Add actions column:

```tsx
{
  id: "actions",
  header: "",
  cell: ({ row }) => (
    <div className="flex justify-end gap-2">
      <Button
        type="button"
        variant="secondary"
        aria-label={`Edit ${row.original.name}`}
        onClick={() => {
          setEditingId(row.original.id);
          setName(row.original.name);
          setPreset(row.original.preset);
          setParametersText(JSON.stringify(row.original.parameters, null, 2));
        }}
      >
        <Pencil className="h-4 w-4" aria-hidden="true" />
      </Button>
      <Button
        type="button"
        variant="secondary"
        aria-label={`Delete ${row.original.name}`}
        onClick={() => deleteVariant.mutate(row.original.id)}
      >
        <Trash2 className="h-4 w-4" aria-hidden="true" />
      </Button>
    </div>
  ),
}
```

- [ ] **Step 8: Run tests**

Run:

```bash
.venv/bin/pytest backend/tests/test_variants.py -v
cd frontend && npm test -- variants-page.test.tsx
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/src/ragstudio/schemas/variants.py backend/src/ragstudio/services/variant_service.py backend/src/ragstudio/api/routes/variants.py backend/tests/test_variants.py frontend/src/api/client.ts frontend/src/api/generated.ts frontend/src/features/variants/variants-page.tsx frontend/tests/variants-page.test.tsx
git commit -m "feat: add semantic variant presets and CRUD"
```

---

### Task 6: Experiment History API and UI

**Files:**
- Modify: `backend/src/ragstudio/schemas/experiments.py`
- Modify: `backend/src/ragstudio/services/experiment_service.py`
- Modify: `backend/src/ragstudio/api/routes/experiments.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/features/experiments/experiments-page.tsx`
- Test: `backend/tests/test_experiments_scoring.py`
- Test: `frontend/tests/evaluation-import.test.tsx`

- [ ] **Step 1: Write backend history test**

Append to `backend/tests/test_experiments_scoring.py`:

```python
@pytest.mark.asyncio
async def test_experiment_list_returns_history(client):
    upload = await client.post(
        "/api/documents",
        files={"file": ("history.txt", b"alpha answer", "text/plain")},
    )
    document_id = upload.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")
    variant = await client.post(
        "/api/variants", json={"name": "History", "preset": "balanced", "parameters": {}}
    )
    evaluation = await client.post(
        "/api/evaluation-sets/import?name=History",
        files={"file": ("cases.csv", b"id,query,expected_answer\none,alpha,alpha\n", "text/csv")},
    )
    created = await client.post(
        "/api/experiments",
        json={
            "name": "History experiment",
            "document_ids": [document_id],
            "evaluation_set_id": evaluation.json()["id"],
            "variant_ids": [variant.json()["id"]],
            "objective": {"metric": "total"},
        },
    )

    response = await client.get("/api/experiments")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["id"] == created.json()["id"]
    assert payload["items"][0]["runs"]
    assert payload["items"][0]["scores"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/pytest backend/tests/test_experiments_scoring.py::test_experiment_list_returns_history -v
```

Expected: FAIL because `GET /api/experiments` does not exist.

- [ ] **Step 3: Add schema page**

In `backend/src/ragstudio/schemas/experiments.py`, add:

```python
class ExperimentPage(StudioModel):
    items: list[ExperimentOut]
    total: int
```

- [ ] **Step 4: Add service list/get methods**

In `backend/src/ragstudio/services/experiment_service.py`, import `Score` and `ExperimentPage`, then add:

```python
async def list(self) -> ExperimentPage:
    result = await self.session.execute(select(Experiment).order_by(Experiment.created_at.desc()))
    experiments = list(result.scalars().all())
    items = [await self._out_with_history(experiment) for experiment in experiments]
    return ExperimentPage(items=items, total=len(items))

async def get_required(self, experiment_id: str) -> ExperimentOut:
    experiment = await self.session.get(Experiment, experiment_id)
    if experiment is None:
        raise KeyError(experiment_id)
    return await self._out_with_history(experiment)

async def _out_with_history(self, experiment: Experiment) -> ExperimentOut:
    runs_result = await self.session.execute(
        select(Run).where(Run.experiment_id == experiment.id).order_by(Run.created_at.asc())
    )
    runs = list(runs_result.scalars().all())
    scores: list[Score] = []
    if runs:
        scores_result = await self.session.execute(
            select(Score).where(Score.run_id.in_([run.id for run in runs]))
        )
        scores = list(scores_result.scalars().all())
    return ExperimentOut(
        id=experiment.id,
        name=experiment.name,
        document_ids=experiment.document_ids,
        evaluation_set_id=experiment.evaluation_set_id,
        variant_ids=experiment.variant_ids,
        objective=experiment.objective,
        runs=[RunOut.model_validate(run) for run in runs],
        scores=[ExperimentScoreOut.model_validate(score) for score in scores],
    )
```

- [ ] **Step 5: Add routes**

In `backend/src/ragstudio/api/routes/experiments.py`, import `ExperimentPage`, then add before `@router.post`:

```python
@router.get("", response_model=ExperimentPage)
async def list_experiments(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ExperimentPage:
    return await ExperimentService(
        session,
        request.app.state.settings.data_dir,
        settings=request.app.state.settings,
    ).list()


@router.get("/{experiment_id}", response_model=ExperimentOut)
async def get_experiment(
    experiment_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ExperimentOut:
    try:
        return await ExperimentService(
            session,
            request.app.state.settings.data_dir,
            settings=request.app.state.settings,
        ).get_required(experiment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Experiment not found") from exc
```

- [ ] **Step 6: Add frontend experiment history**

In `frontend/src/api/generated.ts`, add:

```typescript
export interface ExperimentPage {
  items: ExperimentOut[];
  total: number;
}
```

In `frontend/src/api/client.ts`, import `ExperimentPage` and add:

```typescript
experiments: () => request<ExperimentPage>("/api/experiments"),
getExperiment: (experimentId: string) =>
  request<ExperimentOut>(`/api/experiments/${encodeURIComponent(experimentId)}`),
```

In `frontend/src/features/experiments/experiments-page.tsx`, add:

```tsx
experiments: ["experiments"],
```

Then query and invalidate:

```tsx
const experimentsQuery = useQuery({ queryKey: queryKeys.experiments, queryFn: apiClient.experiments });

onSuccess: () => {
  setFormError("");
  void queryClient.invalidateQueries({ queryKey: queryKeys.runs });
  void queryClient.invalidateQueries({ queryKey: queryKeys.experiments });
},
```

Render history above the current run tables:

```tsx
<DataTable
  columns={experimentColumns}
  data={experimentsQuery.data?.items ?? []}
  emptyTitle="No experiment history"
  emptyDescription="Completed experiments will appear here."
/>
```

Define `experimentColumns` with name, run count, score count, and objective keys.

- [ ] **Step 7: Run tests**

Run:

```bash
.venv/bin/pytest backend/tests/test_experiments_scoring.py -v
cd frontend && npm test -- evaluation-import.test.tsx
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/src/ragstudio/schemas/experiments.py backend/src/ragstudio/services/experiment_service.py backend/src/ragstudio/api/routes/experiments.py backend/tests/test_experiments_scoring.py frontend/src/api/client.ts frontend/src/api/generated.ts frontend/src/features/experiments/experiments-page.tsx frontend/tests/evaluation-import.test.tsx
git commit -m "feat: add experiment history"
```

---

### Task 7: Shared Frontend Helpers and Active Job Polling

**Files:**
- Modify: `frontend/src/lib/utils.ts`
- Modify: `frontend/src/features/comparison/comparison-page.tsx`
- Modify: `frontend/src/features/experiments/experiments-page.tsx`
- Modify: `frontend/src/features/optimizer/optimizer-page.tsx`
- Modify: `frontend/src/features/documents/documents-page.tsx`
- Modify: `frontend/src/features/dashboard/dashboard-page.tsx`
- Test: `frontend/tests/documents-page.test.tsx`
- Test: `frontend/tests/comparison-page.test.tsx`
- Test: `frontend/tests/optimizer-page.test.tsx`

- [ ] **Step 1: Write active job polling test**

In `frontend/tests/documents-page.test.tsx`, add a test using fake timers:

```tsx
it("polls jobs while indexing is active", async () => {
  vi.useFakeTimers();
  const jobs = vi.fn()
    .mockResolvedValueOnce({ items: [{ id: "job-1", status: "running", type: "index_document" }], total: 1 })
    .mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(apiClient, "jobs").mockImplementation(jobs);

  renderDocumentsPage();
  await screen.findByText(/running/i);

  await act(async () => {
    vi.advanceTimersByTime(2000);
  });

  expect(jobs).toHaveBeenCalledTimes(2);
  vi.useRealTimers();
});
```

- [ ] **Step 2: Run frontend tests to verify failure**

Run:

```bash
cd frontend && npm test -- documents-page.test.tsx
```

Expected: FAIL because jobs currently refresh only on manual action.

- [ ] **Step 3: Add shared helpers**

In `frontend/src/lib/utils.ts`, add:

```typescript
export function toggleId(ids: string[], id: string, checked: boolean) {
  if (checked) {
    return ids.includes(id) ? ids : [...ids, id];
  }
  return ids.filter((existingId) => existingId !== id);
}

export function parseJsonObject(value: string): { ok: true; value: Record<string, unknown> } | { ok: false; message: string } {
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, message: "Value must be a JSON object" };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch {
    return { ok: false, message: "Value must be valid JSON" };
  }
}
```

Delete local `toggleId()` from comparison and experiments pages. Delete local `parseObject()` from experiments and optimizer pages. Import the shared helpers.

- [ ] **Step 4: Add active job polling**

In `frontend/src/features/documents/documents-page.tsx` and `frontend/src/features/dashboard/dashboard-page.tsx`, compute:

```tsx
const hasActiveJobs = (jobsQuery.data?.items ?? []).some((job) =>
  ["ready", "running"].includes(job.status),
);
```

Configure jobs query:

```tsx
const jobsQuery = useQuery({
  queryKey: queryKeys.jobs,
  queryFn: apiClient.jobs,
  refetchInterval: (query) => {
    const jobs = query.state.data?.items ?? [];
    return jobs.some((job) => ["ready", "running"].includes(job.status)) ? 2000 : false;
  },
});
```

When `hasActiveJobs` is true, also set document query refetch interval to `2000`.

- [ ] **Step 5: Run frontend tests**

Run:

```bash
cd frontend && npm test -- documents-page.test.tsx comparison-page.test.tsx optimizer-page.test.tsx evaluation-import.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/utils.ts frontend/src/features/comparison/comparison-page.tsx frontend/src/features/experiments/experiments-page.tsx frontend/src/features/optimizer/optimizer-page.tsx frontend/src/features/documents/documents-page.tsx frontend/src/features/dashboard/dashboard-page.tsx frontend/tests/documents-page.test.tsx
git commit -m "fix: poll active jobs and share frontend helpers"
```

---

### Task 8: Audit Document Closure and Full Verification

**Files:**
- Modify: `TECHNICAL_AUDIT.md`

- [x] **Step 1: Add remediation status to the audit**

Insert this section after the opening horizontal rule in `TECHNICAL_AUDIT.md`:

```markdown
## Remediation Status

Fixed in the technical-audit remediation branch:

- §2.1: Native runtime environment overlay is guarded by a thread-visible lock.
- §1.1: Native scoped query passes selected document IDs to the LightRAG query path and reports scoped query support in diagnostics.
- §3.1 and §1.2: Fallback graph scans only relationship metadata chunks, caps work, and returns user-visible detail when no graph data is available.
- §2.2 and §2.3: Empty evaluation signals no longer receive a perfect score, and unscored optimizer runs no longer outrank formally scored runs.
- §1.4 and §1.5: Variant presets now apply backend defaults, and variants can be edited or deleted.
- §1.6: Experiments now have list/get history APIs and frontend history display.
- §5.1, §4.4, and §4.5: Active background jobs poll automatically, and duplicate frontend helpers were consolidated.

Deferred to separate plans because they span broader architecture or UX surfaces:

- §3.2 shared HTTP clients and retry policies.
- §3.3 dashboard-summary endpoint or lazy dashboard graph loading.
- §3.4 API pagination across list endpoints.
- §3.5 moving CPU-bound chunk enrichment off the event loop.
- §4.1 and §4.2 background index handler/runtime health factory extraction.
- §4.3 broad exception narrowing pass.
- §5.2 CSS variable theme migration.
- §5.3 and §5.4 routing and Suspense cleanup.
- §6.1 through §6.5 feature enhancements.
```

- [x] **Step 2: Run full backend verification**

Run:

```bash
.venv/bin/pytest backend/tests -v
```

Expected: PASS.

Actual: PASS with `.venv/bin/pytest backend/tests -q` after installing the declared `pymupdf==1.26.6` dependency into the active repo venv. Result: 312 passed, 5 PyMuPDF/SWIG deprecation warnings.

- [x] **Step 3: Run full frontend verification**

Run:

```bash
cd frontend && npm test -- --run && npm run build
```

Expected: PASS for Vitest and successful TypeScript/Vite build.

Actual: PASS. `npm test -- --run` completed 13 files / 51 tests. `npm run build` completed successfully with the existing Vite chunk-size warning.

- [x] **Step 4: Run lint if available**

Run:

```bash
cd frontend && npm run lint
```

Expected: PASS.

Actual: PASS with `npm run lint`.

- [ ] **Step 5: Commit**

Not run: no commit was requested during this execution pass.

```bash
git add TECHNICAL_AUDIT.md
git commit -m "docs: record technical audit remediation status"
```

---

## Self-Review

**Spec coverage:** The plan maps directly to the audit’s recommended priority order and closes the most user-visible partial implementation gaps: runtime scoped query, graph feedback, scoring/optimizer correctness, variant CRUD, experiment history, active job polling, and duplicated frontend helpers.

**Placeholder scan:** The plan contains no placeholder tasks. Every code change step includes concrete target files, snippets, commands, and expected outcomes.

**Type consistency:** Backend page schemas follow the existing `items` and `total` pattern. Variant update payloads match the existing `VariantIn` shape. Frontend client methods use the same `request<T>()` helper and `encodeURIComponent()` pattern already present in `client.ts`.
