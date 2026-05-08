# MinerU Successful Reindex Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-index large PDFs through MinerU successfully, with visible progress and no silent fallback when the user asks for a strict MinerU parse.

**Architecture:** Move document indexing and re-indexing into explicit background jobs so the UI can monitor long MinerU parses instead of blocking an HTTP request. Keep `mineru_with_fallback` for convenience, but make `mineru_strict` visibly fail instead of indexing raw PDF fallback chunks; persist remote MinerU job IDs and poll progress in `Job.result`/`Job.logs` so users can see what is happening. Add an Arabic-friendly fallback to chunk search so exact Arabic phrases work once real text exists in chunks.

**Tech Stack:** FastAPI, SQLAlchemy async, httpx, SQLite, React, TanStack Query, Vitest, pytest, Playwright.

---

## File Structure

**Backend**
- Modify `backend/src/ragstudio/services/mineru_client.py`
  - Add progress callback support while polling MinerU.
  - Expose remote `jobId`, `status`, `progress`, `detail`, and `updatedAt` to callers.
- Modify `backend/src/ragstudio/services/chunk_service.py`
  - Accept an optional MinerU status callback.
  - Preserve strict-mode failures instead of silently writing fallback/raw PDF chunks.
  - Improve `_terms()` so Arabic tokens are searchable.
- Modify `backend/src/ragstudio/services/document_service.py`
  - Commit the document and job before long indexing starts.
  - Add a reusable `run_index_job()` method for background re-indexing.
- Modify `backend/src/ragstudio/services/job_worker.py`
  - Add helper methods for marking a job running/succeeded/failed and appending logs safely.
- Modify `backend/src/ragstudio/api/routes/documents.py`
  - Upload should create the document/job quickly and schedule background indexing.
- Modify `backend/src/ragstudio/api/routes/chunks.py`
  - Add a background re-index endpoint returning `JobOut`.
- Modify `backend/src/ragstudio/schemas/jobs.py`
  - No shape change required unless tests reveal stricter result typing is useful; `result: dict[str, Any]` already supports MinerU status.
- Test `backend/tests/test_documents.py`, `backend/tests/test_settings.py`, or create `backend/tests/test_mineru_reindex_jobs.py`
  - Cover background job creation, strict failure, metadata propagation, and Arabic phrase search.

**Frontend**
- Modify `frontend/src/api/generated.ts`
  - Add `indexDocumentJob(documentId, payload)` return type manually or regenerate OpenAPI after backend route exists.
- Modify `frontend/src/api/client.ts`
  - Add `indexDocumentJob`.
- Modify `frontend/src/features/documents/documents-page.tsx`
  - Poll jobs automatically while any job is running.
  - Show latest MinerU status/progress/detail from job result.
- Modify `frontend/src/features/chunks/chunk-inspector.tsx`
  - Change `Index` action to schedule a job and show job progress instead of waiting for all chunks inline.
- Test `frontend/tests/settings-page.test.tsx` or create `frontend/tests/chunk-reindex.test.tsx`
  - Cover strict MinerU re-index scheduling and progress display.

---

### Task 1: Add MinerU Progress Callback And Arabic Search Terms

**Files:**
- Modify: `backend/src/ragstudio/services/mineru_client.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Test: `backend/tests/test_mineru_reindex_jobs.py`

- [ ] **Step 1: Write failing tests for progress callback and Arabic token search**

Create `backend/tests/test_mineru_reindex_jobs.py` with:

```python
import pytest

from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.chunks import ChunkSearchIn
from ragstudio.services.chunk_service import ChunkService


@pytest.mark.asyncio
async def test_arabic_phrase_search_matches_indexed_chunk(session, tmp_path):
    document = Document(
        filename="quran_arabic_english.pdf",
        content_type="application/pdf",
        sha256="arabic-search-sha",
        artifact_path=str(tmp_path / "quran.pdf"),
        status="succeeded",
    )
    session.add(document)
    await session.flush()
    session.add(
        Chunk(
            document_id=document.id,
            text="الذين يؤمنون بما أنزل إليك وما أنزل من قبلك",
            source_location={"page": 2},
            metadata_json={
                "domain_metadata": {"domain": "religious_text"},
                "parser_metadata": {"backend": "mineru", "parser_mode": "mineru_strict"},
            },
        )
    )
    await session.commit()

    result = await ChunkService(session, tmp_path).search(
        ChunkSearchIn(
            query="الذين يؤمنون بما أنزل",
            document_ids=[document.id],
            limit=5,
        )
    )

    assert result.total == 1
    assert "بما أنزل" in result.items[0].text
    assert result.items[0].metadata["parser_metadata"]["backend"] == "mineru"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_mineru_reindex_jobs.py::test_arabic_phrase_search_matches_indexed_chunk -q
```

Expected: FAIL with `assert 0 == 1`, because `_terms()` currently uses `re.findall(r"[a-z0-9]+", ...)` and ignores Arabic.

- [ ] **Step 3: Implement Arabic-friendly tokenization**

In `backend/src/ragstudio/services/chunk_service.py`, replace `_terms()` with:

```python
    def _terms(self, value: str) -> set[str]:
        return {
            match.group(0).lower()
            for match in re.finditer(r"[\w\u0600-\u06FF]+", value, flags=re.UNICODE)
        }
```

This keeps ASCII behavior while allowing Arabic script tokens.

- [ ] **Step 4: Add MinerU progress callback signature**

In `backend/src/ragstudio/services/mineru_client.py`, add imports:

```python
from collections.abc import Awaitable, Callable
```

Add this type near `MinerUJobResult`:

```python
MinerUStatusCallback = Callable[[dict[str, Any]], Awaitable[None]]
```

Update `parse_document()` signature:

```python
    async def parse_document(
        self,
        *,
        artifact_path: str | Path,
        document_id: str,
        artifact_dir: Path,
        content_type: str = "application/octet-stream",
        sha256: str | None = None,
        domain_metadata: dict[str, Any] | None = None,
        on_status: MinerUStatusCallback | None = None,
    ) -> MinerUJobResult:
```

Replace:

```python
        ready_job = await self.poll_until_ready(parse_job_id)
```

with:

```python
        if on_status is not None:
            await on_status({"jobId": parse_job_id, "status": "submitted", "progress": 0})
        ready_job = await self.poll_until_ready(parse_job_id, on_status=on_status)
```

Update `poll_until_ready()` signature:

```python
    async def poll_until_ready(
        self,
        parse_job_id: str,
        *,
        on_status: MinerUStatusCallback | None = None,
    ) -> dict[str, Any]:
```

Inside the loop, immediately after `payload = await self.poll_parse_job(parse_job_id)`, add:

```python
            if on_status is not None:
                await on_status(payload)
```

- [ ] **Step 5: Pass callback through ChunkService**

In `backend/src/ragstudio/services/chunk_service.py`, add:

```python
from collections.abc import Awaitable, Callable
```

Near imports/types:

```python
MinerUStatusCallback = Callable[[dict[str, Any]], Awaitable[None]]
```

Update `index_document()` signature:

```python
    async def index_document(
        self,
        document_id: str,
        *,
        options: IndexDocumentIn | None = None,
        commit: bool = True,
        on_mineru_status: MinerUStatusCallback | None = None,
    ) -> list[ChunkOut] | None:
```

Update:

```python
        adapter_chunks = await self._adapter_chunks(document, options)
```

to:

```python
        adapter_chunks = await self._adapter_chunks(
            document,
            options,
            on_mineru_status=on_mineru_status,
        )
```

Update `_adapter_chunks()` and `_mineru_adapter_chunks()` signatures with `on_mineru_status`, then pass it into `client.parse_document(..., on_status=on_mineru_status)`.

- [ ] **Step 6: Run test to verify it passes**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_mineru_reindex_jobs.py::test_arabic_phrase_search_matches_indexed_chunk -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/mineru_client.py backend/src/ragstudio/services/chunk_service.py backend/tests/test_mineru_reindex_jobs.py
git commit -m "feat: track mineru progress and search arabic chunks"
```

---

### Task 2: Add A Reusable Background Index Job Runner

**Files:**
- Modify: `backend/src/ragstudio/services/job_worker.py`
- Modify: `backend/src/ragstudio/services/document_service.py`
- Test: `backend/tests/test_mineru_reindex_jobs.py`

- [ ] **Step 1: Write failing test for strict failure preserving job state**

Append to `backend/tests/test_mineru_reindex_jobs.py`:

```python
import pytest

from ragstudio.db.models import Document, Job
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.document_service import DocumentService


class FailingIndexService(DocumentService):
    async def _index_document_for_job(self, document, job, options=None):
        job.status = "running"
        job.progress = 25
        job.logs = [*job.logs, "MinerU parsing on HPC."]
        raise RuntimeError("MinerU parse timed out for job remote-123.")


@pytest.mark.asyncio
async def test_run_index_job_marks_strict_mineru_failure(session, tmp_path):
    artifact = tmp_path / "quran.pdf"
    artifact.write_bytes(b"%PDF-1.4")
    document = Document(
        filename="quran_arabic_english.pdf",
        content_type="application/pdf",
        sha256="strict-failure-sha",
        artifact_path=str(artifact),
        status="ready",
    )
    job = Job(type="index_document", target_id=document.id, status="ready", progress=0)
    session.add(document)
    await session.flush()
    job.target_id = document.id
    session.add(job)
    await session.commit()

    service = FailingIndexService(session, tmp_path)
    await service.run_index_job(
        document.id,
        job.id,
        IndexDocumentIn(parser_mode="mineru_strict"),
    )

    refreshed_doc = await session.get(Document, document.id)
    refreshed_job = await session.get(Job, job.id)
    assert refreshed_doc is not None
    assert refreshed_job is not None
    assert refreshed_doc.status == "failed"
    assert refreshed_job.status == "failed"
    assert refreshed_job.progress == 100
    assert "MinerU parse timed out" in refreshed_job.logs[-1]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_mineru_reindex_jobs.py::test_run_index_job_marks_strict_mineru_failure -q
```

Expected: FAIL because `DocumentService.run_index_job()` does not exist.

- [ ] **Step 3: Add job helper methods**

In `backend/src/ragstudio/services/job_worker.py`, add methods inside `JobWorker`:

```python
    async def mark_running(self, job: Job, log: str | None = None) -> None:
        job.status = StageStatus.RUNNING.value
        job.progress = max(job.progress, 1)
        if log:
            job.logs = [*job.logs, log]
        await self.session.commit()

    async def update_progress(
        self,
        job: Job,
        *,
        progress: int | None = None,
        log: str | None = None,
        result_patch: dict[str, object] | None = None,
    ) -> None:
        if progress is not None:
            job.progress = max(0, min(progress, 99))
        if log:
            job.logs = [*job.logs, log]
        if result_patch:
            job.result = {**job.result, **result_patch}
        await self.session.commit()

    async def mark_succeeded(
        self,
        job: Job,
        *,
        progress: int = 100,
        log: str | None = None,
        result_patch: dict[str, object] | None = None,
    ) -> None:
        job.status = StageStatus.SUCCEEDED.value
        job.progress = progress
        if log:
            job.logs = [*job.logs, log]
        if result_patch:
            job.result = {**job.result, **result_patch}
        await self.session.commit()

    async def mark_failed(self, job: Job, exc: Exception) -> None:
        job.status = StageStatus.FAILED.value
        job.progress = 100
        job.logs = [*job.logs, str(exc)]
        job.result = {**job.result, "error": str(exc)}
        await self.session.commit()
```

- [ ] **Step 4: Add `DocumentService.run_index_job()`**

In `backend/src/ragstudio/services/document_service.py`, add imports:

```python
from typing import Any
```

Add this method inside `DocumentService`:

```python
    async def run_index_job(
        self,
        document_id: str,
        job_id: str,
        options: IndexDocumentIn,
    ) -> None:
        document = await self.session.get(Document, document_id)
        job = await self.session.get(Job, job_id)
        if document is None or job is None:
            return

        async def on_mineru_status(payload: dict[str, Any]) -> None:
            status = str(payload.get("status") or "unknown")
            progress_value = payload.get("progress")
            progress = progress_value if isinstance(progress_value, int) else None
            remote_job_id = payload.get("jobId")
            detail = str(payload.get("detail") or status)
            job.result = {
                **job.result,
                "mineru": {
                    "job_id": str(remote_job_id) if remote_job_id else None,
                    "status": status,
                    "progress": progress,
                    "detail": detail,
                    "updated_at": payload.get("updatedAt"),
                },
            }
            if progress is not None:
                job.progress = max(1, min(progress, 99))
            job.logs = [*job.logs, f"MinerU {status}: {detail}"][-20:]
            await self.session.commit()

        try:
            job.status = StageStatus.RUNNING.value
            job.progress = 1
            job.logs = [*job.logs, "Indexing document chunks."]
            document.status = StageStatus.RUNNING.value
            await self.session.commit()
            chunks = await ChunkService(self.session, self.store.root).index_document(
                document.id,
                options=options,
                commit=False,
                on_mineru_status=on_mineru_status,
            )
            chunk_count = len(chunks or [])
            document.status = StageStatus.SUCCEEDED.value
            job.status = StageStatus.SUCCEEDED.value
            job.progress = 100
            job.result = {**job.result, "document_id": document.id, "chunk_count": chunk_count}
            job.logs = [*job.logs, f"Indexed {chunk_count} chunks."]
            await self.session.commit()
        except Exception as exc:
            document.status = StageStatus.FAILED.value
            job.status = StageStatus.FAILED.value
            job.progress = 100
            job.logs = [*job.logs, str(exc)]
            job.result = {**job.result, "document_id": document.id, "error": str(exc)}
            await self.session.commit()
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_mineru_reindex_jobs.py::test_run_index_job_marks_strict_mineru_failure -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/job_worker.py backend/src/ragstudio/services/document_service.py backend/tests/test_mineru_reindex_jobs.py
git commit -m "feat: run document indexing as resumable jobs"
```

---

### Task 3: Add Background Upload And Strict Reindex API

**Files:**
- Modify: `backend/src/ragstudio/api/routes/documents.py`
- Modify: `backend/src/ragstudio/api/routes/chunks.py`
- Modify: `backend/src/ragstudio/services/document_service.py`
- Test: `backend/tests/test_mineru_reindex_jobs.py`

- [ ] **Step 1: Write failing API test for strict reindex job creation**

Append to `backend/tests/test_mineru_reindex_jobs.py`:

```python
import pytest

from ragstudio.db.models import Document


@pytest.mark.asyncio
async def test_create_strict_reindex_job_returns_immediately(client, session, tmp_path, monkeypatch):
    artifact = tmp_path / "quran.pdf"
    artifact.write_bytes(b"%PDF-1.4")
    document = Document(
        filename="quran_arabic_english.pdf",
        content_type="application/pdf",
        sha256="strict-reindex-api-sha",
        artifact_path=str(artifact),
        status="succeeded",
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)

    scheduled = {}

    def fake_add_task(fn, *args, **kwargs):
        scheduled["fn"] = fn
        scheduled["args"] = args
        scheduled["kwargs"] = kwargs

    monkeypatch.setattr(
        "fastapi.BackgroundTasks.add_task",
        lambda self, fn, *args, **kwargs: fake_add_task(fn, *args, **kwargs),
    )

    response = await client.post(
        f"/api/chunks/index/{document.id}/jobs",
        json={
            "parser_mode": "mineru_strict",
            "domain_metadata": {
                "domain": "religious_text",
                "document_type": "scripture_translation",
                "language": "arabic_english",
                "tags": ["quran", "arabic", "english", "translation"],
                "collection": "quran_arabic_english",
            },
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["type"] == "index_document"
    assert body["target_id"] == document.id
    assert body["status"] == "ready"
    assert scheduled["args"][0] == document.id
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_mineru_reindex_jobs.py::test_create_strict_reindex_job_returns_immediately -q
```

Expected: FAIL with `404 Not Found`, because `/api/chunks/index/{document_id}/jobs` does not exist.

- [ ] **Step 3: Add job creation helper to DocumentService**

In `backend/src/ragstudio/services/document_service.py`, add:

```python
    async def create_index_job(self, document_id: str) -> Job | None:
        document = await self.session.get(Document, document_id)
        if document is None:
            return None
        job = JobWorker.build("index_document", document.id)
        self.session.add(job)
        document.status = StageStatus.RUNNING.value
        await self.session.commit()
        await self.session.refresh(job)
        return job
```

- [ ] **Step 4: Add strict reindex endpoint**

In `backend/src/ragstudio/api/routes/chunks.py`, update imports:

```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from ragstudio.schemas.jobs import JobOut
from ragstudio.services.document_service import DocumentService
```

Add route above `@router.post("/index/{document_id}", ...)`:

```python
@router.post(
    "/index/{document_id}/jobs",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_index_document_job(
    document_id: str,
    options: IndexDocumentIn,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JobOut:
    service = DocumentService(session, request.app.state.settings.data_dir)
    job = await service.create_index_job(document_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Document not found")
    background_tasks.add_task(
        _run_index_document_job,
        request.app.state.settings.data_dir,
        document_id,
        job.id,
        options,
    )
    return JobOut.model_validate(job)
```

At module bottom, add:

```python
async def _run_index_document_job(
    data_dir,
    document_id: str,
    job_id: str,
    options: IndexDocumentIn,
) -> None:
    from ragstudio.db.engine import make_engine, make_session_factory
    from ragstudio.config import AppSettings

    settings = AppSettings(data_dir=data_dir)
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    async with factory() as background_session:
        await DocumentService(background_session, data_dir).run_index_job(
            document_id,
            job_id,
            options,
        )
    await engine.dispose()
```

- [ ] **Step 5: Make upload return after scheduling job**

In `backend/src/ragstudio/api/routes/documents.py`, update imports:

```python
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, UploadFile
```

Update `upload_document()` signature:

```python
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile,
    parser_mode: str | None = Form(default=None),
    domain_metadata: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
```

After `content = await read_upload_file(file)`, replace the existing return with:

```python
    document = await DocumentService(session, request.app.state.settings.data_dir).upload_without_index(
        filename=file.filename or "upload.bin",
        content_type=file.content_type or "application/octet-stream",
        content=content,
    )
    job = await DocumentService(session, request.app.state.settings.data_dir).create_index_job(document.id)
    if job is not None:
        background_tasks.add_task(
            _run_upload_index_job,
            request.app.state.settings.data_dir,
            document.id,
            job.id,
            options or IndexDocumentIn(),
        )
    return document
```

Add `DocumentService.upload_without_index()` by extracting the existing upload persistence path without calling `_index_document_for_job()`. Keep duplicate SHA behavior: if the document already exists, return it and schedule reindex only if options were supplied.

Add `_run_upload_index_job()` in `documents.py` with the same body as `_run_index_document_job()` from `chunks.py`.

- [ ] **Step 6: Run backend tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_mineru_reindex_jobs.py backend/tests/test_settings.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/api/routes/documents.py backend/src/ragstudio/api/routes/chunks.py backend/src/ragstudio/services/document_service.py backend/tests/test_mineru_reindex_jobs.py
git commit -m "feat: schedule mineru indexing jobs"
```

---

### Task 4: Show Reindex Jobs And MinerU Progress In The UI

**Files:**
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/features/chunks/chunk-inspector.tsx`
- Modify: `frontend/src/features/documents/documents-page.tsx`
- Test: `frontend/tests/chunk-reindex.test.tsx`

- [ ] **Step 1: Add frontend API client method**

In `frontend/src/api/client.ts`, add after `indexDocumentChunks`:

```ts
  createIndexDocumentJob: (documentId: string, payload: IndexDocumentIn = {}) =>
    request<JobOut>(`/api/chunks/index/${encodeURIComponent(documentId)}/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
```

Ensure `JobOut` is already imported at the top; it is.

- [ ] **Step 2: Write failing UI test**

Create `frontend/tests/chunk-reindex.test.tsx`:

```tsx
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../src/api/client";
import { ChunkInspector } from "../src/features/chunks/chunk-inspector";

vi.mock("../src/api/client", () => ({
  apiClient: {
    documents: vi.fn(),
    domainProfiles: vi.fn(),
    createIndexDocumentJob: vi.fn(),
    indexDocumentChunks: vi.fn(),
    searchChunks: vi.fn(),
  },
}));

function renderChunks() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ChunkInspector />
    </QueryClientProvider>,
  );
}

describe("ChunkInspector MinerU reindex jobs", () => {
  beforeEach(() => {
    vi.mocked(apiClient.documents).mockResolvedValue({
      total: 1,
      items: [
        {
          id: "quran-doc",
          filename: "quran_arabic_english.pdf",
          content_type: "application/pdf",
          sha256: "sha",
          status: "succeeded",
        },
      ],
    });
    vi.mocked(apiClient.domainProfiles).mockResolvedValue({ total: 0, items: [] });
    vi.mocked(apiClient.createIndexDocumentJob).mockResolvedValue({
      id: "job-1",
      type: "index_document",
      target_id: "quran-doc",
      status: "ready",
      progress: 0,
      logs: [],
      result: {},
    });
  });

  it("schedules strict MinerU reindex instead of blocking for chunks", async () => {
    renderChunks();

    await screen.findByText("quran_arabic_english.pdf");
    fireEvent.click(screen.getByLabelText("Parser"));
    fireEvent.change(screen.getByLabelText("Parser"), { target: { value: "mineru_strict" } });
    fireEvent.click(screen.getByRole("button", { name: /Index/i }));

    await waitFor(() => expect(apiClient.createIndexDocumentJob).toHaveBeenCalled());
    expect(vi.mocked(apiClient.createIndexDocumentJob).mock.calls[0][0]).toBe("quran-doc");
    expect(vi.mocked(apiClient.createIndexDocumentJob).mock.calls[0][1]).toEqual(
      expect.objectContaining({ parser_mode: "mineru_strict" }),
    );
    expect(await screen.findByText(/Index job queued/i)).toBeVisible();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run:

```bash
cd frontend && npm test -- --run tests/chunk-reindex.test.tsx
```

Expected: FAIL because `ChunkInspector` still calls `apiClient.indexDocumentChunks`.

- [ ] **Step 4: Update `ChunkInspector` to use job endpoint**

In `frontend/src/features/chunks/chunk-inspector.tsx`, replace mutation:

```ts
  const indexDocument = useMutation({
    mutationFn: (documentId: string) => apiClient.indexDocumentChunks(documentId, indexOptions),
    onSuccess: () => {
      setIndexVersion((version) => version + 1);
      setSearchResult(null);
    },
  });
```

with:

```ts
  const indexDocument = useMutation({
    mutationFn: (documentId: string) => apiClient.createIndexDocumentJob(documentId, indexOptions),
    onSuccess: () => {
      setSearchResult(null);
    },
  });
```

Replace status message:

```tsx
            (indexDocument.isSuccess ? `Indexed ${indexDocument.data.length} chunks` : "")}
```

with:

```tsx
            (indexDocument.isSuccess ? `Index job queued: ${indexDocument.data.id}` : "")}
```

- [ ] **Step 5: Add automatic polling on Documents page**

In `frontend/src/features/documents/documents-page.tsx`, change jobs query:

```ts
  const jobsQuery = useQuery({ queryKey: queryKeys.jobs, queryFn: apiClient.jobs });
```

to:

```ts
  const jobsQuery = useQuery({
    queryKey: queryKeys.jobs,
    queryFn: apiClient.jobs,
    refetchInterval: (query) => {
      const jobs = query.state.data?.items ?? [];
      return jobs.some((job) => job.status === "running" || job.status === "ready") ? 2000 : false;
    },
  });
```

In `jobColumns`, replace Latest log cell with:

```tsx
        cell: ({ row }) => {
          const mineru = row.original.result.mineru as
            | { status?: string; progress?: number; detail?: string; job_id?: string }
            | undefined;
          const latestLog = row.original.logs.at(-1) ?? "No logs";
          return (
            <span className="line-clamp-3 text-xs text-[#62717a]">
              {mineru?.status
                ? `MinerU ${mineru.status}${mineru.progress ?? row.original.progress}%: ${mineru.detail ?? latestLog}`
                : latestLog}
            </span>
          );
        },
```

- [ ] **Step 6: Run frontend tests**

Run:

```bash
cd frontend && npm test -- --run tests/chunk-reindex.test.tsx frontend/tests/settings-page.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/features/chunks/chunk-inspector.tsx frontend/src/features/documents/documents-page.tsx frontend/tests/chunk-reindex.test.tsx
git commit -m "feat: monitor mineru reindex jobs in ui"
```

---

### Task 5: End-To-End Verification With Quran PDF

**Files:**
- No production file changes required.
- Optional docs update: `docs/workflows.md`

- [ ] **Step 1: Run full automated tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH ./scripts/test-all.sh
```

Expected:
- Backend tests pass.
- Ruff passes.
- Pyright has only the known pre-existing warning in `backend/src/ragstudio/db/repositories.py`.
- Frontend lint/test/build pass.

- [ ] **Step 2: Restart local app**

Run:

```bash
(lsof -ti tcp:5173; lsof -ti tcp:8000) | sort -u | xargs -r kill
PATH=$PWD/.venv/bin:$PATH ./scripts/dev.sh
```

Expected:
- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173`

- [ ] **Step 3: Increase MinerU timeout for large PDF**

In the Settings UI:
- Go to `http://127.0.0.1:5173/settings`.
- Confirm `MinerU parser` is enabled.
- Set `MinerU timeout (ms)` to `3600000`.
- Save.
- Click `Test MinerU`.

Expected:
- `Connected: ...`

- [ ] **Step 4: Reindex Quran PDF in strict mode**

In the Chunks UI:
- Go to `http://127.0.0.1:5173/chunks`.
- Select `quran_arabic_english.pdf`.
- Set Parser to `MinerU strict`.
- Set metadata:
  - Domain: `religious_text`
  - Document type: `scripture_translation`
  - Language: `arabic_english`
  - Collection: `quran_arabic_english`
  - Tags: `quran, arabic, english, translation`
- Click `Index`.

Expected:
- UI shows `Index job queued: <job-id>`.
- Documents page shows running job with MinerU status updates.
- Job must finish `succeeded`.
- Latest log must say `Indexed <N> chunks.`
- The chunk metadata must show `parser_metadata.backend == "mineru"`, not `fallback`.

- [ ] **Step 5: Verify phrase search**

Run direct API search:

```bash
curl -sS -H 'Content-Type: application/json' \
  -d '{"query":"الذين يؤمنون بما أنزل","document_ids":["6c712d77-a914-4fb9-bee7-22709a4206ff"],"limit":10}' \
  http://127.0.0.1:8000/api/chunks/search \
  | python -c 'import json,sys; p=json.load(sys.stdin); print(json.dumps({"total":p["total"],"first":p["items"][0]["text"][:500] if p["items"] else ""}, ensure_ascii=False, indent=2))'
```

Expected:

```json
{
  "total": 1,
  "first": "..."
}
```

The returned text should contain `بما أنزل` or the surrounding verse text.

- [ ] **Step 6: Verify UI search**

In the Chunks UI:
- Select `quran_arabic_english.pdf`.
- Search:

```text
الذين يؤمنون بما أنزل
```

Expected:
- Results appear.
- At least one result includes the Arabic phrase or nearby verse.
- Metadata badge/domain shows `religious_text`.

- [ ] **Step 7: Commit docs if updated**

If `docs/workflows.md` was updated:

```bash
git add docs/workflows.md
git commit -m "docs: explain strict mineru reindex workflow"
```

---

## Self-Review

**Spec coverage:** The plan addresses the observed failure: `mineru_with_fallback` timed out and indexed raw PDF internals, making Arabic phrase search impossible. Tasks add strict re-indexing, background progress monitoring, Arabic search, and an E2E Quran PDF verification.

**Placeholder scan:** No TBD/TODO placeholders remain. Each task includes concrete file paths, commands, expected outcomes, and code snippets.

**Type consistency:** The plan consistently uses `IndexDocumentIn`, `JobOut`, `parser_mode`, `domain_metadata`, `mineru_strict`, `mineru_with_fallback`, and existing `Job.result` for MinerU status.

