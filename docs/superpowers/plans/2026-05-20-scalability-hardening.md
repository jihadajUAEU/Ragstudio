# Ragstudio Scalability Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add the remaining worthwhile architecture-analysis improvements that protect Ragstudio from large-dataset, outbound-network, and long-running-worker scaling failures.

**Architecture:** Keep the existing FastAPI + SQLAlchemy async architecture and improve it in narrow contracts: paginated list APIs, app-lifetime HTTP clients, bounded retry policy, worker heartbeat session reuse, and defensive graph rendering caps. Do not rework completed items such as variant CRUD, experiment history existence, CPU offload, or graph fallback scoping.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async ORM, Pydantic, httpx, React/Vite, TanStack Query, Vitest, pytest.

---

## Scope Check

This plan intentionally implements only the architecture-analysis suggestions that still matter after checking current code:

- **Do:** shared HTTP clients, retry/backoff, list pagination, heartbeat session reuse, graph result caps.
- **Do not redo:** CPU offload, graph relationship metadata filtering/pagination, preset mapping, variant CRUD, experiment list endpoint.
- **Defer:** full removal of RAG-Anything/LightRAG environment variables until upstream direct storage-config support is verified. Current `scoped_native_storage_env()` is the containment boundary.

## File Structure

- Modify: `backend/src/ragstudio/schemas/common.py`
  - Add reusable pagination input/output helpers if existing schema does not already contain them.
- Modify: `backend/src/ragstudio/api/routes/documents.py`
  - Accept `offset` and `limit` query params for document listing.
- Modify: `backend/src/ragstudio/services/document_service.py`
  - Add paginated document list query and total count.
- Modify: `backend/src/ragstudio/api/routes/jobs.py`
  - Accept `offset` and `limit` query params for job listing.
- Modify: `backend/src/ragstudio/services/job_worker.py`
  - Add paginated job list query and total count.
- Modify: `backend/src/ragstudio/api/routes/runs.py`
  - Accept `offset` and `limit` query params for run listing.
- Modify: `backend/src/ragstudio/services/query_service.py`
  - Add paginated run list query and total count.
- Modify: `backend/src/ragstudio/api/routes/variants.py`
  - Accept `offset` and `limit` query params for variant listing.
- Modify: `backend/src/ragstudio/services/variant_service.py`
  - Add paginated variant list query and total count.
- Modify: `backend/src/ragstudio/api/routes/experiments.py`
  - Accept `offset` and `limit` query params for experiment listing.
- Modify: `backend/src/ragstudio/services/experiment_service.py`
  - Add paginated experiment summary list query and total count.
- Modify: `frontend/src/api/client.ts`
  - Add reusable pagination query helper for list endpoints.
- Modify: `frontend/src/api/generated.ts`
  - Add pagination fields to affected page contracts after backend schema changes.
- Modify: `frontend/src/features/documents/documents-page.tsx`
  - Keep existing first-page behavior and avoid loading unbounded lists.
- Modify: `frontend/src/features/experiments/experiments-page.tsx`
  - Keep existing first-page behavior and avoid loading unbounded lists.
- Create: `backend/src/ragstudio/services/http_client_provider.py`
  - Own app-lifetime `httpx.AsyncClient` instances.
- Modify: `backend/src/ragstudio/app.py`
  - Initialize and close HTTP client provider during lifespan.
- Create: `backend/src/ragstudio/services/http_retry.py`
  - Provide bounded retry helper for transient outbound HTTP failures.
- Modify: outbound service files that currently call `httpx.AsyncClient(...)`
  - Use injected/shared client where app context exists, with a local fallback for isolated tests.
- Modify: `backend/src/ragstudio/services/index_job_runner.py`
  - Reuse injected heartbeat session factory instead of creating a new SQLAlchemy engine per job.
- Modify: `backend/src/ragstudio/services/graph_service.py`
  - Add a defensive node/edge cap for fallback graph rendering.
- Tests:
  - `backend/tests/test_documents.py`
  - `backend/tests/test_jobs.py`
  - `backend/tests/test_query_runs.py`
  - `backend/tests/test_variants.py`
  - `backend/tests/test_experiments_scoring.py`
  - `backend/tests/test_http_client_provider.py`
  - `backend/tests/test_http_retry.py`
  - `backend/tests/test_index_job_runner.py`
  - `backend/tests/test_graph_service.py`
  - `frontend/tests/api-client.test.ts`
  - `frontend/tests/documents-page.test.tsx`
  - `frontend/tests/experiments-page.test.tsx`

---

### Task 1: Add Backend Pagination Contracts For List APIs

**Files:**
- Modify: `backend/src/ragstudio/schemas/common.py`
- Modify: `backend/src/ragstudio/services/document_service.py`
- Modify: `backend/src/ragstudio/api/routes/documents.py`
- Modify: `backend/src/ragstudio/services/job_worker.py`
- Modify: `backend/src/ragstudio/api/routes/jobs.py`
- Modify: `backend/src/ragstudio/services/query_service.py`
- Modify: `backend/src/ragstudio/api/routes/runs.py`
- Modify: `backend/src/ragstudio/services/variant_service.py`
- Modify: `backend/src/ragstudio/api/routes/variants.py`
- Modify: `backend/src/ragstudio/services/experiment_service.py`
- Modify: `backend/src/ragstudio/api/routes/experiments.py`
- Test: `backend/tests/test_documents.py`
- Test: `backend/tests/test_jobs.py`
- Test: `backend/tests/test_query_runs.py`
- Test: `backend/tests/test_variants.py`
- Test: `backend/tests/test_experiments_scoring.py`

- [x] **Step 1: Add a focused document pagination route test**

Append this test to `backend/tests/test_documents.py`:

```python
@pytest.mark.asyncio
async def test_list_documents_paginates_results(client):
    async with client._transport.app.state.session_factory() as session:
        for index in range(3):
            session.add(
                Document(
                    id=f"doc-page-{index}",
                    filename=f"page-{index}.pdf",
                    content_type="application/pdf",
                    sha256=f"doc-page-sha-{index}",
                    artifact_path=f"/tmp/page-{index}.pdf",
                    status="succeeded",
                )
            )
        await session.commit()

    response = await client.get("/api/documents?limit=1&offset=1")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert body["has_more"] is True
    assert len(body["items"]) == 1
```

- [x] **Step 2: Add a focused jobs pagination route test**

Append this test to `backend/tests/test_jobs.py`:

```python
@pytest.mark.asyncio
async def test_list_jobs_paginates_results(client):
    async with client._transport.app.state.session_factory() as session:
        for index in range(3):
            session.add(
                Job(
                    id=f"job-page-{index}",
                    type="index_document",
                    status=StageStatus.SUCCEEDED.value,
                    target_id=f"doc-page-{index}",
                    progress=100,
                    logs=[],
                    result={},
                )
            )
        await session.commit()

    response = await client.get("/api/jobs?limit=1&offset=1")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert body["has_more"] is True
    assert len(body["items"]) == 1
```

- [x] **Step 3: Run the new pagination tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_documents.py::test_list_documents_paginates_results backend/tests/test_jobs.py::test_list_jobs_paginates_results -q
```

Expected: FAIL because `limit`, `offset`, and `has_more` are not returned yet.

- [x] **Step 4: Add reusable pagination schema**

Modify `backend/src/ragstudio/schemas/common.py` by adding this model after `Page`:

```python
class PaginatedPage(StudioModel):
    items: list[Any]
    total: int
    limit: int
    offset: int
    has_more: bool
```

If `Any` is not already imported in `common.py`, add:

```python
from typing import Any
```

- [x] **Step 5: Implement paginated document listing**

Replace `DocumentService.list()` in `backend/src/ragstudio/services/document_service.py` with:

```python
    async def list(self, *, limit: int = 100, offset: int = 0) -> tuple[list[DocumentOut], int]:
        limit = max(1, min(limit, 500))
        offset = max(offset, 0)
        total = await self.session.scalar(select(func.count()).select_from(Document)) or 0
        result = await self.session.execute(
            select(Document)
            .order_by(Document.created_at.desc(), Document.id.desc())
            .limit(limit)
            .offset(offset)
        )
        documents = list(result.scalars().all())
        latest_options = await self._latest_index_options_by_document(
            [document.id for document in documents]
        )
        outputs = []
        for document in documents:
            output = DocumentOut.model_validate(document)
            output.latest_index_options = latest_options.get(document.id)
            outputs.append(output)
        return outputs, total
```

Ensure `func` is imported from SQLAlchemy in that file:

```python
from sqlalchemy import delete, func, select, text
```

- [x] **Step 6: Wire document route pagination**

Replace `list_documents()` in `backend/src/ragstudio/api/routes/documents.py` with:

```python
@router.get("")
async def list_documents(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    items, total = await DocumentService(
        session,
        request.app.state.settings.data_dir,
        settings=request.app.state.settings,
    ).list(limit=limit, offset=offset)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }
```

Add `Query` to the FastAPI imports in `documents.py`:

```python
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, UploadFile, status
```

- [x] **Step 7: Implement paginated job listing**

Replace `JobWorker.list()` in `backend/src/ragstudio/services/job_worker.py` with:

```python
    async def list(self, *, limit: int = 100, offset: int = 0) -> tuple[list[JobOut], int]:
        limit = max(1, min(limit, 500))
        offset = max(offset, 0)
        total = await self.session.scalar(select(func.count()).select_from(Job)) or 0
        result = await self.session.execute(
            select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(limit).offset(offset)
        )
        return [JobOut.model_validate(item) for item in result.scalars().all()], total
```

Ensure `func` is imported in `job_worker.py`:

```python
from sqlalchemy import func, select
```

- [x] **Step 8: Wire job route pagination**

Replace `list_jobs()` in `backend/src/ragstudio/api/routes/jobs.py` with:

```python
@router.get("", response_model=JobPage)
async def list_jobs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> JobPage:
    items, total = await JobWorker(session).list(limit=limit, offset=offset)
    return JobPage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(items) < total,
    )
```

Update `JobPage` in `backend/src/ragstudio/schemas/jobs.py`:

```python
class JobPage(StudioModel):
    items: list[JobOut]
    total: int
    limit: int = 100
    offset: int = 0
    has_more: bool = False
```

- [x] **Step 9: Add pagination to runs**

Modify `backend/src/ragstudio/services/query_service.py`:

```python
    async def list_runs(self, *, limit: int = 100, offset: int = 0) -> tuple[list[RunOut], int]:
        limit = max(1, min(limit, 500))
        offset = max(offset, 0)
        total = await self.session.scalar(select(func.count()).select_from(Run)) or 0
        result = await self.session.execute(
            select(Run).order_by(Run.created_at.desc(), Run.id.desc()).limit(limit).offset(offset)
        )
        return [self._run_out(item) for item in result.scalars().all()], total
```

Ensure `func` is imported in `query_service.py`:

```python
from sqlalchemy import func, select
```

Modify `backend/src/ragstudio/api/routes/runs.py`:

```python
from fastapi import APIRouter, Depends, Query, Request

@router.get("", response_model=RunPage)
async def list_runs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> RunPage:
    items, total = await QueryService(
        session,
        request.app.state.settings.data_dir,
        settings=request.app.state.settings,
    ).list_runs(limit=limit, offset=offset)
    return RunPage(items=items, total=total, limit=limit, offset=offset, has_more=offset + len(items) < total)
```

- [x] **Step 10: Add pagination to variants**

Modify `backend/src/ragstudio/services/variant_service.py`:

```python
    async def list(self, *, limit: int = 100, offset: int = 0) -> tuple[list[VariantOut], int]:
        limit = max(1, min(limit, 500))
        offset = max(offset, 0)
        total = await self.session.scalar(select(func.count()).select_from(Variant)) or 0
        result = await self.session.execute(
            select(Variant)
            .order_by(Variant.created_at.desc(), Variant.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [VariantOut.model_validate(item) for item in result.scalars().all()], total
```

Ensure `func` is imported in `variant_service.py`:

```python
from sqlalchemy import func, select
```

Modify `backend/src/ragstudio/api/routes/variants.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

@router.get("", response_model=VariantPage)
async def list_variants(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> VariantPage:
    items, total = await VariantService(session).list(limit=limit, offset=offset)
    return VariantPage(items=items, total=total, limit=limit, offset=offset, has_more=offset + len(items) < total)
```

- [x] **Step 11: Add pagination to experiments**

Modify `backend/src/ragstudio/services/experiment_service.py`:

```python
    async def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ExperimentSummaryOut], int]:
        limit = max(1, min(limit, 500))
        offset = max(offset, 0)
        total = await self.session.scalar(select(func.count()).select_from(Experiment)) or 0
        run_counts = (
            select(
                Run.experiment_id.label("experiment_id"),
                func.count(Run.id).label("run_count"),
            )
            .where(Run.experiment_id.is_not(None))
            .group_by(Run.experiment_id)
            .subquery()
        )
        score_counts = (
            select(
                Run.experiment_id.label("experiment_id"),
                func.count(Score.id).label("score_count"),
            )
            .join(Score, Score.run_id == Run.id)
            .where(Run.experiment_id.is_not(None))
            .group_by(Run.experiment_id)
            .subquery()
        )
        result = await self.session.execute(
            select(
                Experiment,
                func.coalesce(run_counts.c.run_count, 0),
                func.coalesce(score_counts.c.score_count, 0),
            )
            .outerjoin(run_counts, run_counts.c.experiment_id == Experiment.id)
            .outerjoin(score_counts, score_counts.c.experiment_id == Experiment.id)
            .order_by(Experiment.created_at.desc(), Experiment.id.desc())
            .limit(limit)
            .offset(offset)
        )
        items = [
            ExperimentSummaryOut(
                id=experiment.id,
                name=experiment.name,
                document_ids=experiment.document_ids,
                evaluation_set_id=experiment.evaluation_set_id,
                variant_ids=experiment.variant_ids,
                objective=experiment.objective,
                run_count=run_count,
                score_count=score_count,
            )
            for experiment, run_count, score_count in result.all()
        ]
        return items, total
```

Modify `backend/src/ragstudio/api/routes/experiments.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, Request

@router.get("", response_model=ExperimentPage)
async def list_experiments(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> ExperimentPage:
    items, total = await ExperimentService(
        session,
        request.app.state.settings.data_dir,
        settings=request.app.state.settings,
    ).list(limit=limit, offset=offset)
    return ExperimentPage(items=items, total=total, limit=limit, offset=offset, has_more=offset + len(items) < total)
```

- [x] **Step 12: Update page schemas**

Add these fields to `RunPage`, `VariantPage`, and `ExperimentPage`:

```python
limit: int = 100
offset: int = 0
has_more: bool = False
```

- [x] **Step 13: Run focused backend pagination tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_documents.py::test_list_documents_paginates_results backend/tests/test_jobs.py::test_list_jobs_paginates_results backend/tests/test_query_runs.py backend/tests/test_variants.py backend/tests/test_experiments_scoring.py -q
```

Expected: PASS.

- [x] **Step 14: Commit backend pagination**

Run:

```powershell
git add backend/src/ragstudio/schemas backend/src/ragstudio/api/routes backend/src/ragstudio/services backend/tests
git commit -m "feat: paginate list APIs"
```

---

### Task 2: Update Frontend List Clients For Pagination

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/features/documents/documents-page.tsx`
- Modify: `frontend/src/features/experiments/experiments-page.tsx`
- Test: `frontend/tests/api-client.test.ts`
- Test: `frontend/tests/documents-page.test.tsx`
- Test: `frontend/tests/experiments-page.test.tsx`

- [x] **Step 1: Add API client pagination tests**

Append this test to `frontend/tests/api-client.test.ts`:

```ts
it("passes pagination query params for list endpoints", async () => {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url) => {
      urls.push(String(url));
      return new Response(JSON.stringify({ items: [], total: 0, limit: 25, offset: 50, has_more: false }), {
        headers: { "Content-Type": "application/json" },
      });
    }),
  );

  await apiClient.documents({ limit: 25, offset: 50 });
  await apiClient.jobs({ limit: 25, offset: 50 });
  await apiClient.runs({ limit: 25, offset: 50 });
  await apiClient.variants({ limit: 25, offset: 50 });
  await apiClient.experiments({ limit: 25, offset: 50 });

  expect(urls).toEqual([
    "/api/documents?limit=25&offset=50",
    "/api/jobs?limit=25&offset=50",
    "/api/runs?limit=25&offset=50",
    "/api/variants?limit=25&offset=50",
    "/api/experiments?limit=25&offset=50",
  ]);
});
```

- [x] **Step 2: Run the API client test and verify it fails**

Run from `frontend/`:

```powershell
cmd /c npm test -- --run tests/api-client.test.ts
```

Expected: FAIL because list helpers do not accept pagination options yet.

- [x] **Step 3: Add pagination options to the API client**

Modify `frontend/src/api/client.ts`:

```ts
export type ApiQueryOptions = Record<string, string | number | boolean | null | undefined>;
export type PageQueryOptions = Pick<ApiQueryOptions, "limit" | "offset">;
```

Replace list helpers with:

```ts
documents: (options?: PageQueryOptions) => request<Page<DocumentOut>>(withQuery("/api/documents", options)),
jobs: (options?: PageQueryOptions) => request<Page<JobOut>>(withQuery("/api/jobs", options)),
variants: (options?: PageQueryOptions) => request<Page<VariantOut>>(withQuery("/api/variants", options)),
experiments: (options?: PageQueryOptions) => request<ExperimentPage>(withQuery("/api/experiments", options)),
runs: (options?: PageQueryOptions) => request<Page<RunOut>>(withQuery("/api/runs", options)),
```

- [x] **Step 4: Update generated frontend types**

Modify each affected page interface in `frontend/src/api/generated.ts`:

```ts
export interface Page<T> {
  items: T[];
  total: number;
  limit?: number;
  offset?: number;
  has_more?: boolean;
}
```

Update `ExperimentPage` and any non-generic page interfaces in the same style:

```ts
export interface ExperimentPage {
  items: ExperimentSummaryOut[];
  total: number;
  limit?: number;
  offset?: number;
  has_more?: boolean;
}
```

- [x] **Step 5: Keep UI first-page behavior explicit**

In `frontend/src/features/documents/documents-page.tsx`, update query functions:

```ts
const FIRST_PAGE = { limit: 100, offset: 0 };

const documentsQuery = useQuery({
  queryKey: queryKeys.documents,
  queryFn: () => apiClient.documents(FIRST_PAGE),
});

const jobsQuery = useQuery({
  queryKey: queryKeys.jobs,
  queryFn: () => apiClient.jobs(FIRST_PAGE),
  refetchInterval: activeJobs ? 1500 : false,
});
```

In `frontend/src/features/experiments/experiments-page.tsx`, update:

```ts
const FIRST_PAGE = { limit: 100, offset: 0 };

const experimentsQuery = useQuery({
  queryKey: queryKeys.experiments,
  queryFn: () => apiClient.experiments(FIRST_PAGE),
});
```

- [x] **Step 6: Update frontend tests**

In `frontend/tests/documents-page.test.tsx`, assert first-page query params:

```ts
await waitFor(() => {
  expect(apiClient.documents).toHaveBeenCalledWith({ limit: 100, offset: 0 });
  expect(apiClient.jobs).toHaveBeenCalledWith({ limit: 100, offset: 0 });
});
```

In `frontend/tests/experiments-page.test.tsx`, assert:

```ts
await waitFor(() => {
  expect(apiClient.experiments).toHaveBeenCalledWith({ limit: 100, offset: 0 });
});
```

- [x] **Step 7: Run focused frontend tests**

Run from `frontend/`:

```powershell
cmd /c npm test -- --run tests/api-client.test.ts tests/documents-page.test.tsx tests/experiments-page.test.tsx
```

Expected: PASS.

- [x] **Step 8: Commit frontend pagination**

Run:

```powershell
git add frontend/src/api/client.ts frontend/src/api/generated.ts frontend/src/features/documents/documents-page.tsx frontend/src/features/experiments/experiments-page.tsx frontend/tests/api-client.test.ts frontend/tests/documents-page.test.tsx frontend/tests/experiments-page.test.tsx
git commit -m "feat: request paginated list pages from frontend"
```

---

### Task 3: Add App-Lifetime HTTP Client Provider

**Files:**
- Create: `backend/src/ragstudio/services/http_client_provider.py`
- Modify: `backend/src/ragstudio/app.py`
- Test: `backend/tests/test_http_client_provider.py`

- [x] **Step 1: Write the provider tests**

Create `backend/tests/test_http_client_provider.py`:

```python
import pytest

from ragstudio.services.http_client_provider import HttpClientProvider


@pytest.mark.asyncio
async def test_http_client_provider_reuses_named_clients():
    provider = HttpClientProvider()
    client_a = provider.client("mineru", timeout=5.0)
    client_b = provider.client("mineru", timeout=5.0)

    assert client_a is client_b

    await provider.aclose()
    assert client_a.is_closed


@pytest.mark.asyncio
async def test_http_client_provider_rejects_use_after_close():
    provider = HttpClientProvider()
    await provider.aclose()

    with pytest.raises(RuntimeError, match="closed"):
        provider.client("mineru")
```

- [x] **Step 2: Run the provider tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_http_client_provider.py -q
```

Expected: FAIL because `http_client_provider.py` does not exist.

- [x] **Step 3: Implement the provider**

Create `backend/src/ragstudio/services/http_client_provider.py`:

```python
from __future__ import annotations

import httpx


class HttpClientProvider:
    def __init__(self) -> None:
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._closed = False

    def client(self, name: str, *, timeout: float | httpx.Timeout = 30.0) -> httpx.AsyncClient:
        if self._closed:
            raise RuntimeError("HTTP client provider is closed.")
        if name not in self._clients:
            self._clients[name] = httpx.AsyncClient(timeout=timeout)
        return self._clients[name]

    async def aclose(self) -> None:
        self._closed = True
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
```

- [x] **Step 4: Register provider in app lifespan**

Modify `backend/src/ragstudio/app.py`:

```python
from ragstudio.services.http_client_provider import HttpClientProvider
```

Inside `create_app()`, after app creation:

```python
app.state.http_clients = HttpClientProvider()
```

Inside lifespan shutdown, before engine disposal:

```python
await app.state.http_clients.aclose()
```

- [x] **Step 5: Run provider and app smoke tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_http_client_provider.py backend/tests/test_static.py -q
```

Expected: PASS.

- [x] **Step 6: Commit HTTP client provider**

Run:

```powershell
git add backend/src/ragstudio/services/http_client_provider.py backend/src/ragstudio/app.py backend/tests/test_http_client_provider.py
git commit -m "feat: add shared http client provider"
```

---

### Task 4: Add Bounded Retry Policy For Outbound HTTP Calls

**Files:**
- Create: `backend/src/ragstudio/services/http_retry.py`
- Modify: `backend/src/ragstudio/services/mineru_client.py`
- Modify: `backend/src/ragstudio/services/reranker_service.py`
- Modify: `backend/src/ragstudio/services/llm_connection_service.py`
- Modify: `backend/src/ragstudio/services/embedding_connection_service.py`
- Test: `backend/tests/test_http_retry.py`
- Test: `backend/tests/test_mineru_client.py`

- [x] **Step 1: Write retry helper tests**

Create `backend/tests/test_http_retry.py`:

```python
import httpx
import pytest

from ragstudio.services.http_retry import retry_async_http


@pytest.mark.asyncio
async def test_retry_async_http_retries_transient_status():
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            response = httpx.Response(503, request=httpx.Request("GET", "http://test"))
            raise httpx.HTTPStatusError("unavailable", request=response.request, response=response)
        return "ok"

    result = await retry_async_http(operation, attempts=2, base_delay_seconds=0)

    assert result == "ok"
    assert calls == 2


@pytest.mark.asyncio
async def test_retry_async_http_does_not_retry_client_error():
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        response = httpx.Response(400, request=httpx.Request("GET", "http://test"))
        raise httpx.HTTPStatusError("bad request", request=response.request, response=response)

    with pytest.raises(httpx.HTTPStatusError):
        await retry_async_http(operation, attempts=3, base_delay_seconds=0)

    assert calls == 1
```

- [x] **Step 2: Run retry tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_http_retry.py -q
```

Expected: FAIL because `http_retry.py` does not exist.

- [x] **Step 3: Implement retry helper**

Create `backend/src/ragstudio/services/http_retry.py`:

```python
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

T = TypeVar("T")

TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}


async def retry_async_http(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay_seconds: float = 0.25,
) -> T:
    attempts = max(attempts, 1)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return await operation()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in TRANSIENT_STATUS_CODES:
                raise
            last_error = exc
        except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException) as exc:
            last_error = exc
        if attempt < attempts - 1 and base_delay_seconds > 0:
            await asyncio.sleep(base_delay_seconds * (2**attempt))
    if last_error is not None:
        raise last_error
    raise RuntimeError("retry_async_http exhausted without result or error.")
```

- [x] **Step 4: Wrap MinerU idempotent calls**

In `backend/src/ragstudio/services/mineru_client.py`, import:

```python
from ragstudio.services.http_retry import retry_async_http
```

For GET-style status/artifact calls, wrap the client call:

```python
response = await retry_async_http(
    lambda: client.get(url, headers=headers),
    attempts=3,
)
response.raise_for_status()
```

For `POST /parse-async`, retry only when the call includes an idempotency key. If no idempotency key exists in the request metadata, leave the existing single-attempt behavior.

- [x] **Step 5: Wrap connection-test calls**

In `embedding_connection_service.py`, `llm_connection_service.py`, and `reranker_service.py`, wrap the single outbound request:

```python
response = await retry_async_http(lambda: client.post(url, json=payload, headers=headers), attempts=2)
response.raise_for_status()
```

Do not retry provider calls after a successful response with invalid JSON; invalid response shape is not transient.

- [x] **Step 6: Run retry and outbound service tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_http_retry.py backend/tests/test_mineru_client.py backend/tests/test_settings.py backend/tests/test_reranker_service.py -q
```

Expected: PASS.

- [x] **Step 7: Commit retry policy**

Run:

```powershell
git add backend/src/ragstudio/services/http_retry.py backend/src/ragstudio/services/mineru_client.py backend/src/ragstudio/services/embedding_connection_service.py backend/src/ragstudio/services/llm_connection_service.py backend/src/ragstudio/services/reranker_service.py backend/tests/test_http_retry.py backend/tests/test_mineru_client.py
git commit -m "feat: retry transient outbound http failures"
```

---

### Task 5: Reuse Worker Session Factory For Heartbeats

**Files:**
- Modify: `backend/src/ragstudio/services/index_job_runner.py`
- Modify: `backend/src/ragstudio/workers/index_worker.py`
- Test: `backend/tests/test_index_job_runner.py`

- [x] **Step 1: Add heartbeat session-factory regression test**

Create or append to `backend/tests/test_index_job_runner.py`:

```python
import pytest

from ragstudio.services.index_job_runner import IndexJobRunner


@pytest.mark.asyncio
async def test_index_job_runner_uses_injected_session_factory_for_heartbeat(monkeypatch, client):
    async with client._transport.app.state.session_factory() as session:
        runner = IndexJobRunner(
            session,
            client._transport.app.state.settings,
            worker_id="worker-test",
            session_factory=client._transport.app.state.session_factory,
        )

        def fail_make_engine(_database_url):
            raise AssertionError("heartbeat should not create a new engine")

        monkeypatch.setattr("ragstudio.services.index_job_runner.make_engine", fail_make_engine)
        assert runner._external_session_factory is client._transport.app.state.session_factory
```

- [x] **Step 2: Run the test and verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_index_job_runner.py::test_index_job_runner_uses_injected_session_factory_for_heartbeat -q
```

Expected: FAIL because `IndexJobRunner` does not accept `session_factory`.

- [x] **Step 3: Add optional session factory to runner**

Modify `IndexJobRunner.__init__()` in `backend/src/ragstudio/services/index_job_runner.py`:

```python
from collections.abc import Callable
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
```

Add parameter:

```python
        session_factory: async_sessionmaker[AsyncSession] | None = None,
```

Store it:

```python
        self._external_session_factory = session_factory
```

- [x] **Step 4: Use injected session factory in heartbeat loop**

Replace `_heartbeat_until_stopped()` with:

```python
    async def _heartbeat_until_stopped(self, job_id: str, stop_heartbeat: asyncio.Event) -> None:
        engine = None
        session_factory = self._external_session_factory
        if session_factory is None:
            engine = make_engine(self.settings.resolved_database_url)
            session_factory = make_session_factory(engine)
        try:
            while not stop_heartbeat.is_set():
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        stop_heartbeat.wait(),
                        timeout=self.heartbeat_interval_seconds,
                    )
                    return
                async with session_factory() as heartbeat_session:
                    should_continue = await self._heartbeat_external(heartbeat_session, job_id)
                    await heartbeat_session.commit()
                if not should_continue:
                    return
        finally:
            if engine is not None:
                await engine.dispose()
```

- [x] **Step 5: Pass app session factory from worker**

Modify `backend/src/ragstudio/workers/index_worker.py` so `run_once()` accepts:

```python
    session_factory=None,
```

Pass it to the runner:

```python
        await IndexJobRunner(
            session,
            settings,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            session_factory=session_factory,
        ).run(job)
```

In `run_forever()`, pass the created factory:

```python
processed = await run_once(
    session,
    settings,
    worker_id=resolved_worker_id,
    lease_seconds=lease_seconds,
    session_factory=session_factory,
)
```

- [x] **Step 6: Run worker tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_index_job_runner.py backend/tests/test_index_worker_recovery.py -q
```

Expected: PASS.

- [x] **Step 7: Commit worker heartbeat reuse**

Run:

```powershell
git add backend/src/ragstudio/services/index_job_runner.py backend/src/ragstudio/workers/index_worker.py backend/tests/test_index_job_runner.py
git commit -m "fix: reuse worker session factory for heartbeats"
```

---

### Task 6: Add Defensive Graph Result Caps

**Files:**
- Modify: `backend/src/ragstudio/services/graph_service.py`
- Test: `backend/tests/test_graph_service.py`

- [x] **Step 1: Add graph cap test**

Append to `backend/tests/test_graph_service.py`:

```python
@pytest.mark.asyncio
async def test_relationship_metadata_graph_caps_rendered_nodes(database_url):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        document = Document(
            id="doc-graph-cap",
            filename="graph-cap.pdf",
            content_type="application/pdf",
            sha256="graph-cap-sha",
            artifact_path="/tmp/graph-cap.pdf",
            status="succeeded",
        )
        session.add(document)
        await session.flush()
        session.add_all(
            [
                Chunk(
                    id=f"chunk-graph-cap-{index}",
                    document_id=document.id,
                    text=f"chunk {index}",
                    metadata_json={
                        "relationship_metadata": {
                            "graph_relationships": [
                                {"source": f"s{index}", "target": f"t{index}", "type": "NEXT"}
                            ]
                        }
                    },
                    source_location={},
                )
                for index in range(150)
            ]
        )
        await session.commit()

        graph = await GraphService(session).get_graph(limit=150)

    await engine.dispose()

    assert len(graph.nodes) <= 100
    assert len(graph.edges) <= 100
    assert graph.has_more is True
```

- [x] **Step 2: Run the graph cap test and verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_graph_service.py::test_relationship_metadata_graph_caps_rendered_nodes -q
```

Expected: FAIL because rendered nodes/edges can exceed 100.

- [x] **Step 3: Implement graph render cap**

In `backend/src/ragstudio/services/graph_service.py`, add constants near the top:

```python
DEFAULT_GRAPH_FALLBACK_LIMIT = 2_000
MAX_RENDERED_GRAPH_NODES = 100
MAX_RENDERED_GRAPH_EDGES = 100
```

Before returning from `_relationship_metadata_graph()`, cap values:

```python
        node_values = list(nodes.values())
        edge_values = list(edges.values())
        rendered_nodes = node_values[:MAX_RENDERED_GRAPH_NODES]
        rendered_node_ids = {node["id"] for node in rendered_nodes}
        rendered_edges = [
            edge
            for edge in edge_values
            if edge["source"] in rendered_node_ids and edge["target"] in rendered_node_ids
        ][:MAX_RENDERED_GRAPH_EDGES]
        render_truncated = len(node_values) > len(rendered_nodes) or len(edge_values) > len(rendered_edges)
```

Return:

```python
        return {
            "nodes": rendered_nodes,
            "edges": rendered_edges,
            "detail": detail,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total or render_truncated,
        }
```

- [x] **Step 4: Run graph tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_graph_service.py -q
```

Expected: PASS.

- [x] **Step 5: Commit graph caps**

Run:

```powershell
git add backend/src/ragstudio/services/graph_service.py backend/tests/test_graph_service.py
git commit -m "fix: cap fallback graph rendering"
```

---

## Validation

Run these after all tasks:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_documents.py::test_list_documents_paginates_results backend/tests/test_jobs.py backend/tests/test_query_runs.py backend/tests/test_variants.py backend/tests/test_experiments_scoring.py backend/tests/test_http_client_provider.py backend/tests/test_http_retry.py backend/tests/test_index_job_runner.py backend/tests/test_graph_service.py -q
```

Run frontend checks:

```powershell
cd frontend
cmd /c npm test -- --run tests/api-client.test.ts tests/documents-page.test.tsx tests/experiments-page.test.tsx
```

Run lint on changed backend files:

```powershell
D:\python312\Scripts\ruff.exe check backend/src/ragstudio backend/tests
```

## Self-Review

- Spec coverage:
  - Shared HTTP clients: Task 3.
  - Retry/backoff: Task 4.
  - List pagination: Tasks 1 and 2.
  - Heartbeat engine reuse: Task 5.
  - Graph cap: Task 6.
  - CPU offload, graph scoping, variant CRUD, and experiment list existence are intentionally excluded because current code already covers them.
- Placeholder scan:
  - This plan intentionally contains no `TBD`, no unspecified tests, and no open-ended implementation steps.
- Type consistency:
  - Pagination fields use `limit`, `offset`, `total`, and `has_more` across backend schemas, API client, generated types, and tests.
