# Ragstudio Technical Audit

> Evidence-based deep scan covering partial implementations, bugs, performance issues, and enhancement opportunities.

---

## Remediation Status

Fixed in this technical-audit remediation pass:

- §2.1: Native runtime environment overlay is guarded by a thread-visible lock.
- §1.1: Native scoped query uses LightRAG chunk `full_doc_id` filtering for selected-document vector retrieval and reports scoped query support in diagnostics.
- §3.1 and §1.2: Fallback graph scans only relationship metadata chunks, caps work, and returns user-visible detail when no graph data is available.
- §2.2 and §2.3: Empty evaluation signals no longer receive a perfect score, and unscored optimizer runs no longer outrank formally scored runs.
- §2.4: Graph visualization truncation now reports the actual displayed node and edge counts.
- §1.4 and §1.5: Variant presets now apply backend defaults, and variants can be edited or deleted.
- §1.6: Experiments now have list/get history APIs and frontend history display with on-demand detail loading.
- §5.1, §4.4, and §4.5: Active background jobs poll automatically, and duplicate frontend helpers were consolidated.

Deferred to separate plans because they span broader architecture or UX surfaces:

- §1.3 Excel regression runner product integration.
- §2.5 per-query limit controls beyond the existing query form limit.
- §2.6 and §4.1 background index handler/runtime health factory extraction.
- §3.2 shared HTTP clients and retry policies.
- §3.3 dashboard-summary endpoint or lazy dashboard graph loading.
- §3.4 API pagination across list endpoints.
- §3.5 moving CPU-bound chunk enrichment off the event loop.
- §4.2 runtime health factory extraction beyond the immediate scoped-query checks.
- §4.3 broad exception narrowing pass.
- §5.2 CSS variable theme migration.
- §5.3 and §5.4 routing and Suspense cleanup.
- §6.1 through §6.5 feature enhancements.

## 1. Partially Implemented Features

### 1.1 🔴 Native Scoped Query – Document Filtering Blocked

**Files:** [native_raganything_adapter.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/native_raganything_adapter.py#L88-L105) · [diagnostics_service.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/diagnostics_service.py#L147-L151)

The native runtime adapter explicitly refuses to execute queries when `document_ids` are provided. This is the **single most impactful gap** in the runtime pipeline — it forces the orchestrator to fall back to metadata-only retrieval, bypassing the entire native RAG-Anything semantic engine when documents are scoped.

```python
# native_raganything_adapter.py:88-105
async def query(self, query: str, *, document_ids: list[str], ...) -> RuntimeQueryResult:
    if document_ids:
        return RuntimeQueryResult(
            answer="",
            error="Native RAG-Anything query cannot yet enforce selected document_ids; "
                  "refusing to run an unscoped runtime query.",
            error_type="native_document_scope_unsupported",
        )
```

The diagnostics page also surfaces this limitation statically:

```python
# diagnostics_service.py:147-150
"scoped_query": False,
"scoped_query_detail": "Native RAG-Anything query cannot yet enforce selected document_ids."
```

**Impact:** Every query with document selection skips the native runtime, degrading retrieval quality.

---

### 1.2 🟡 Graph – Fallback Returns Placeholder Data

**Files:** [adapter.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/adapter.py#L82-L83) · [graph_service.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/graph_service.py#L39-L53)

When the runtime is unavailable (or fallback mode), the graph endpoint returns `{"nodes": [], "edges": [], "placeholder": True}`. The `GraphService` tries `_relationship_metadata_graph()` first but falls back to this empty placeholder if no relationship metadata exists:

```python
# adapter.py:82-83
async def graph(self) -> dict[str, Any]:
    return {"nodes": [], "edges": [], "placeholder": True}
```

```python
# graph_service.py:44-53
except RuntimeProfileNotConfiguredError:
    fallback_graph = await self._relationship_metadata_graph()
    if fallback_graph["nodes"] or fallback_graph["edges"]:
        return fallback_graph
    return await self.adapter.graph()  # <-- Returns empty placeholder
```

**Impact:** Users in fallback mode always see "Graph is empty" with no actionable feedback about why.

---

### 1.3 🟡 Excel Regression Runner – Utility Without Integration

**File:** [excel_regression_runner.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/excel_regression_runner.py)

This module defines `ExcelCase` and `summarize_excel_results()` but has no API route, no CLI hook, and no frontend integration. It's a standalone utility with no entry point:

```python
@dataclass(frozen=True)
class ExcelCase:
    case_id: str
    query: str
    expected_text: str
    required_rank: int
```

**Impact:** Dead code — cannot be invoked without custom scripting.

---

### 1.4 🟡 Variant Presets – UI Labels Without Backend Semantics

**Files:** [variants-page.tsx](file:///Users/meet/Documents/Ragstudio/frontend/src/features/variants/variants-page.tsx#L144-L148) · [variant_service.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/variant_service.py)

The frontend variant form offers `Balanced`, `Precise`, `Broad`, `Fast` presets, but the backend `VariantService.create()` simply stores the `preset` string as-is without applying any default parameter overrides. The preset has no semantic effect:

```python
# variant_service.py:11-16 — just stores raw input
async def create(self, data: VariantIn) -> VariantOut:
    variant = Variant(**data.model_dump())
    self.session.add(variant)
```

**Impact:** Users expect presets to influence behavior, but they're purely cosmetic labels.

---

### 1.5 🟡 No Variant Edit or Delete

**Files:** [variant_service.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/variant_service.py) · [variants-page.tsx](file:///Users/meet/Documents/Ragstudio/frontend/src/features/variants/variants-page.tsx) · [client.ts](file:///Users/meet/Documents/Ragstudio/frontend/src/api/client.ts#L123-L129)

Variants can only be created and listed. There are no `PUT`/`PATCH`/`DELETE` API routes, no backend methods, and no frontend UI for editing or removing variants.

**Impact:** Users cannot correct mistakes or clean up experimental variants.

---

### 1.6 🟡 No Experiment List or History

**Files:** [experiments-page.tsx](file:///Users/meet/Documents/Ragstudio/frontend/src/features/experiments/experiments-page.tsx) · [client.ts](file:///Users/meet/Documents/Ragstudio/frontend/src/api/client.ts)

The experiments page only shows the *latest* experiment created via mutation. There is no `GET /api/experiments` endpoint, no experiment list in the API client, and no way to view past experiments:

```typescript
// client.ts — no listExperiments endpoint
createExperiment: (payload: ExperimentIn) =>
    request<ExperimentOut>("/api/experiments", { ... }),
```

**Impact:** Experiment history is lost when the user navigates away from the page.

---

## 2. Bugs & Correctness Issues

### 2.1 🔴 Environment Variable Concurrency Race Condition

**File:** [native_raganything_adapter.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/native_raganything_adapter.py#L258-L282)

The `_storage_env()` context manager mutates `os.environ` to inject Postgres/Neo4j credentials. While it uses `_env_lock`, this is a **class-level asyncio lock** — it serializes async coroutines, but:

1. **Thread safety:** If any synchronous code runs (e.g., `asyncio.to_thread()` in graph operations), the env mutations are visible to ALL threads.
2. **Process-wide state:** The lock doesn't protect against other services or background tasks that read `os.environ` concurrently.

```python
# native_raganything_adapter.py:258-282
@asynccontextmanager
async def _storage_env(self) -> AsyncIterator[None]:
    updates = { **self._postgres_env(), "NEO4J_URI": ..., "NEO4J_PASSWORD": ... }
    async with self._env_lock:  # asyncio.Lock — NOT thread-safe
        previous = {key: os.environ.get(key) for key in updates}
        try:
            for key, value in updates.items():
                os.environ[key] = value  # Process-wide mutation!
            yield
        finally:
            for key, value in previous.items():
                os.environ.pop(key, None) if value is None else ...
```

**Impact:** Under concurrent load, credentials from one profile may leak into another profile's operations. This is a **security risk** when running multiple profiles.

---

### 2.2 🟡 Scoring Division-by-Zero Risk

**File:** [scoring_service.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/scoring_service.py#L36-L47)

The scoring algorithm divides by `weights` which can be 0 when all three scoring categories (expected_answer, must_include, must_avoid) are empty. While `_has_expected_output_signal()` prevents truly empty cases during import, the `ScoringService.score()` method can still be called independently:

```python
# scoring_service.py:47
normalized_total = round((total / weights) * 100) if weights else 100
```

When `weights == 0`, it returns 100 (perfect score) for any answer — this is semantically wrong.

**Impact:** Edge-case scoring corruption when `expected_answer`, `must_include`, and `must_avoid` are all empty but other signals (like `rubric` or `expected_structure`) exist.

---

### 2.3 🟡 Optimizer Heuristic Score for Missing Scores

**File:** [optimizer_service.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/optimizer_service.py#L94-L99)

When a run has no score record and no error, the optimizer assigns a synthetic score based on source count:

```python
# optimizer_service.py:94-99
def _run_score(self, run: Run, score: Score | None) -> float:
    if score is not None:
        return float(score.total)
    if run.error:
        return 0.0
    return float(min(100, 50 + (10 * len(run.sources))))
```

This heuristic (`50 + 10 * sources`) can dominate real scores — a run with 5+ sources gets 100, potentially outranking a properly scored run.

**Impact:** Optimizer may recommend the wrong variant when some runs lack formal scoring.

---

### 2.4 🟡 Graph Page Truncation Without User Warning

**File:** [graph-page.tsx](file:///Users/meet/Documents/Ragstudio/frontend/src/features/graph/graph-page.tsx#L53-L55)

The graph page silently truncates to 50 nodes/edges without displaying a prominent warning:

```tsx
// graph-page.tsx:53-55
const previewNodes = nodes.slice(0, 50);
const previewEdges = edges.slice(0, 50);
const visualGraph = useMemo(() => buildVisualGraph(previewNodes, previewEdges), [...]);
```

The `GraphList` component shows "Showing X of Y" in small text, but the ReactFlow visualization just renders 50 nodes — edges referencing node IDs beyond 50 are silently filtered out at line 234:

```tsx
if (!nodeIds.has(source) || !nodeIds.has(target)) { return []; }
```

**Impact:** Graph visualization may show disconnected nodes because their edges connect to nodes beyond the first 50.

---

### 2.5 🟡 Missing `limit` Parameter in Frontend Query

**File:** [client.ts](file:///Users/meet/Documents/Ragstudio/frontend/src/api/client.ts#L201-L206) · [generated.ts](file:///Users/meet/Documents/Ragstudio/frontend/src/api/generated.ts#L301-L306)

`QueryIn` requires a `limit` field, but the frontend `query-page.tsx` always sends a fixed limit (hardcoded at the form level). There's no per-query override exposed in the API client.

---

### 2.6 🟡 `_mark_background_index_failed` Creates Redundant Engine

**Files:** [documents.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/api/routes/documents.py#L180-L198) · [chunks.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/api/routes/chunks.py#L182-L200)

Both `_mark_background_index_failed()` functions create a brand-new database engine and session factory to persist a failure status. This is identical code duplicated across two files:

```python
# documents.py:180-198 AND chunks.py:182-200 (identical)
async def _mark_background_index_failed(settings, document_id, job_id, reason):
    engine = make_engine(settings.resolved_database_url)  # New engine each time!
    factory = make_session_factory(engine)
    try:
        async with factory() as background_session:
            await DocumentService(...).mark_index_job_failed(document_id, job_id, reason)
    except Exception:
        logger.exception(...)
    finally:
        await engine.dispose()
```

**Impact:** On high-frequency failures, this creates and disposes database connections rapidly, adding latency and resource pressure.

---

## 3. Performance Improvements

### 3.1 🔴 `_relationship_metadata_graph()` Loads ALL Chunks

**File:** [graph_service.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/graph_service.py#L76-L141)

When building the fallback relationship graph, the service loads **every chunk in the database** into memory:

```python
# graph_service.py:79
result = await self.session.execute(select(Chunk))  # ALL chunks, no filter!
```

For large datasets with tens of thousands of chunks, this will cause significant memory pressure and latency.

**Fix:** Add `.limit()`, pagination, or filter by `document_id` and only load chunks that have `relationship_metadata`.

---

### 3.2 🟡 httpx Client Created Per-Request

**Files:** [runtime_answer_service.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/runtime_answer_service.py#L36-L43) · [reranker_service.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/reranker_service.py) · [mineru_client.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/mineru_client.py#L100-L106)

Multiple services create `httpx.AsyncClient(timeout=...)` inside `async with` blocks for each request. This prevents connection pooling and adds TCP/TLS handshake overhead:

```python
# runtime_answer_service.py:36-43
async with httpx.AsyncClient(timeout=timeout) as client:
    response = await client.post(self._chat_url(...), ...)
```

```python
# mineru_client.py:100-106
async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
    response = await client.post(...)
```

**Fix:** Use a shared `httpx.AsyncClient` with connection pooling (e.g., stored on the service instance or app state).

---

### 3.3 🟡 Dashboard Fires 7 Parallel API Requests

**File:** [dashboard-page.tsx](file:///Users/meet/Documents/Ragstudio/frontend/src/features/dashboard/dashboard-page.tsx#L36-L45)

The dashboard page fires 7 independent queries on mount:

```tsx
const healthQuery = useQuery({ queryKey: queryKeys.health, queryFn: apiClient.health });
const documentsQuery = useQuery({ ... });
const jobsQuery = useQuery({ ... });
const variantsQuery = useQuery({ ... });
const runsQuery = useQuery({ ... });
const diagnosticsQuery = useQuery({ ... });
const graphQuery = useQuery({ ... });
```

The graph query in particular can be expensive (Neo4j round-trip) and isn't needed for the dashboard overview.

**Fix:** Lazy-load graph data or consolidate into a single `/api/dashboard-summary` endpoint.

---

### 3.4 🟡 No API Response Pagination

**Files:** [document_service.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/document_service.py) · [variant_service.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/variant_service.py) · [evaluation_importer.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/evaluation_importer.py)

All list endpoints return the **entire dataset** without offset/limit pagination:

```python
# variant_service.py:18-21
async def list(self) -> VariantPage:
    result = await self.session.execute(select(Variant).order_by(...))
    variants = [VariantOut.model_validate(item) for item in result.scalars().all()]
    return VariantPage(items=variants, total=len(variants))
```

The `Page<T>` type has `total` but no `offset`/`limit` concept.

**Impact:** Scales poorly — with hundreds of documents or thousands of runs, responses grow unboundedly.

---

### 3.5 🟡 `ChunkSplitter` and `MinerURelationshipBuilder` Run Synchronously

**File:** [index_lifecycle_service.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/index_lifecycle_service.py#L105-L113)

After indexing, two CPU-bound processing steps run synchronously within the async request handler:

```python
adapter_chunks = ChunkSplitter().split(normalized_chunks, ...)
adapter_chunks = MinerURelationshipBuilder().annotate(adapter_chunks, ...)
```

For large documents, these can block the event loop.

**Fix:** Use `asyncio.to_thread()` for CPU-bound chunk processing.

---

## 4. Architecture & Code Quality

### 4.1 🟡 Duplicated Background Index Failure Handlers

**Files:** [documents.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/api/routes/documents.py#L149-L198) · [chunks.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/api/routes/chunks.py#L148-L200)

`_run_index_job` / `_run_index_document_job` and `_mark_background_index_failed` are **nearly identical** across both route modules. Each creates engines, handles `CancelledError`, and logs exceptions identically.

**Fix:** Extract into a shared `background_index` module.

---

### 4.2 🟡 Duplicated `_runtime_health_service()` Factory

**Files:** [documents.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/api/routes/documents.py#L230-L234) · [chunks.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/api/routes/chunks.py#L141-L145) · [index_lifecycle_service.py](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/index_lifecycle_service.py#L261-L265)

This `try: RuntimeHealthService(session, verify_storage=True) except TypeError` pattern appears 3+ times. The `TypeError` catch suggests backward compatibility with an older signature — if no longer needed, the pattern should be removed; if needed, it should be a shared factory.

---

### 4.3 🟡 Broad `except Exception` Handlers (24 instances)

Across the codebase, there are **24 bare `except Exception`** handlers. While some are appropriate (background task cleanup), many swallow potentially important errors:

| Location | Context |
|---|---|
| [document_service.py:79](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/document_service.py#L79) | Index failure categorization |
| [document_service.py:97](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/document_service.py#L97) | Silent failure |
| [retrieval_orchestrator.py:109,161,260](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/retrieval_orchestrator.py) | Retrieval degradation |
| [query_service.py:144,222](file:///Users/meet/Documents/Ragstudio/backend/src/ragstudio/services/query_service.py) | Query fallback |

**Recommendation:** Narrow exception types where possible. At minimum, add structured logging with exception class information.

---

### 4.4 🟡 `toggleId()` Function Duplicated in Frontend

**Files:** [comparison-page.tsx](file:///Users/meet/Documents/Ragstudio/frontend/src/features/comparison/comparison-page.tsx#L212-L217) · [experiments-page.tsx](file:///Users/meet/Documents/Ragstudio/frontend/src/features/experiments/experiments-page.tsx#L399-L404)

Identical `toggleId()` helper is copy-pasted:

```tsx
function toggleId(ids: string[], id: string, checked: boolean) {
  if (checked) { return ids.includes(id) ? ids : [...ids, id]; }
  return ids.filter((existingId) => existingId !== id);
}
```

**Fix:** Extract to `lib/utils.ts`.

---

### 4.5 🟡 `parseObject()` Function Duplicated

**Files:** [experiments-page.tsx](file:///Users/meet/Documents/Ragstudio/frontend/src/features/experiments/experiments-page.tsx#L406-L416) · [optimizer-page.tsx](file:///Users/meet/Documents/Ragstudio/frontend/src/features/optimizer/optimizer-page.tsx#L292-L302)

Identical JSON object parsing helper is copy-pasted across two pages.

---

## 5. Frontend Improvements

### 5.1 🟡 No Job Polling for Active Background Tasks

**Files:** [documents-page.tsx](file:///Users/meet/Documents/Ragstudio/frontend/src/features/documents/documents-page.tsx) · [dashboard-page.tsx](file:///Users/meet/Documents/Ragstudio/frontend/src/features/dashboard/dashboard-page.tsx)

When a document is uploaded or reindexed, a background job starts, but the frontend has no automatic polling mechanism. Users must manually click "Refresh" to see status updates:

```tsx
// dashboard-page.tsx:56-64 — manual refresh only
const refresh = () => {
    void healthQuery.refetch();
    void documentsQuery.refetch();
    // ... etc
};
```

**Fix:** Use `useQuery` with `refetchInterval` when there are active `RUNNING` jobs, or implement WebSocket/SSE push notifications.

---

### 5.2 🟡 Hardcoded Color Values Instead of CSS Variables

Every frontend component uses hardcoded hex colors like `#176b87`, `#62717a`, `#1f2933`, `#d6dde1` directly in JSX. While consistent, this makes theme changes require touching every file.

**Fix:** Define CSS custom properties (e.g., `--color-primary`, `--color-muted`) and reference them throughout.

---

### 5.3 🟡 `Suspense` Fallback Only for PipelineBuilder

**File:** [App.tsx](file:///Users/meet/Documents/Ragstudio/frontend/src/App.tsx#L17-L19)

Only `PipelineBuilder` is lazy-loaded. The Suspense fallback text says "Loading pipeline builder..." regardless of what's actually loading:

```tsx
<Suspense fallback={<div className="text-sm text-[#62717a]">Loading pipeline builder...</div>}>
    {page}
</Suspense>
```

Since `{page}` can be any route component, the fallback message is misleading when navigating to non-pipeline routes.

---

### 5.4 🟡 Custom Routing Instead of React Router

**File:** [App.tsx](file:///Users/meet/Documents/Ragstudio/frontend/src/App.tsx#L37-L84)

The app implements manual `window.history.pushState` routing with `popstate` listeners instead of using a router library. While functional, this:
- Doesn't support query parameters or nested routes
- Doesn't handle 404s properly (silently defaults to Dashboard)
- Makes deep linking fragile

---

## 6. Useful Feature Enhancements

### 6.1 Real-Time Indexing Progress via WebSocket/SSE

**Current state:** Background indexing runs via `asyncio.create_task()` with no progress reporting back to the frontend. The `MinerUClient` supports `on_status` callbacks but they're not surfaced.

**Enhancement:** Add an SSE endpoint (`GET /api/jobs/{job_id}/stream`) that forwards `on_mineru_status` callbacks and indexing progress to the frontend in real-time.

---

### 6.2 Retry Policies for External Service Calls

**Current state:** All HTTP calls to LLM, embedding, reranker, and MinerU endpoints have no retry logic — a single transient failure fails the entire operation.

**Enhancement:** Add configurable retry with exponential backoff for `httpx` calls in `RuntimeAnswerService`, `RerankerService`, `EmbeddingConnectionService`, and `MinerUClient`.

---

### 6.3 Query History and Saved Queries

**Current state:** The query page has no history. Once a query is run, it can only be reviewed through the runs/comparison pages.

**Enhancement:** Add a "Recent Queries" sidebar to the Query page, with ability to re-run or bookmark queries.

---

### 6.4 Bulk Document Operations

**Current state:** Documents can only be uploaded and reindexed one at a time. There's no bulk upload, bulk reindex, or bulk delete.

**Enhancement:** Add multi-file upload via the `FormData` API and batch reindex endpoint.

---

### 6.5 Settings Import/Export

**Current state:** Settings are stored in the database and can only be modified via the UI form. There's no way to export a settings profile for backup or sharing.

**Enhancement:** Add `GET /api/settings/export` and `POST /api/settings/import` endpoints for JSON-based settings portability.

---

## Summary Matrix

| Category | Critical (🔴) | Medium (🟡) | Count |
|---|---|---|---|
| Partial Implementation | 1 | 5 | 6 |
| Bugs & Correctness | 1 | 5 | 6 |
| Performance | 1 | 4 | 5 |
| Architecture/Quality | 0 | 5 | 5 |
| Frontend | 0 | 4 | 4 |
| Feature Enhancements | 0 | 5 | 5 |
| **Total** | **3** | **28** | **31** |

### Recommended Priority Order

1. **[§2.1]** Fix environment variable concurrency (security risk)
2. **[§1.1]** Implement native scoped query filtering
3. **[§3.1]** Paginate `_relationship_metadata_graph()` chunk loading
4. **[§3.2]** Add httpx connection pooling
5. **[§5.1]** Add job status polling in frontend
6. **[§4.1-4.2]** Extract duplicated background task handlers
7. **[§1.5-1.6]** Add variant CRUD and experiment listing
