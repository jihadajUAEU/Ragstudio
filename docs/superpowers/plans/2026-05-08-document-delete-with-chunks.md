# Document Delete With Chunks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe delete action for uploaded documents that removes the document, its indexed chunks, related document jobs, and the uploaded artifact file when no active indexing job is running.

**Architecture:** Implement deletion in `DocumentService` so all cleanup rules live behind one backend boundary. Expose `DELETE /api/documents/{document_id}` and call it from the Documents page through `apiClient.deleteDocument`. The UI should require explicit user confirmation, then refresh Documents, Jobs, and downstream chunk consumers after success.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, SQLite, pytest/httpx, React, TanStack Query/Table, Vitest, Testing Library, Tailwind utility classes, lucide-react icons.

---

## File Structure

- Modify `backend/src/ragstudio/services/document_service.py`
  - Add deletion orchestration: load document, block active jobs, delete related chunks/jobs/document, delete artifact file after commit.
  - Return a typed result so route can distinguish `404`, `409`, and success.
- Modify `backend/src/ragstudio/api/routes/documents.py`
  - Add `DELETE /api/documents/{document_id}` endpoint with `204 No Content`.
  - Convert missing document to `404` and active job conflict to `409`.
- Modify `backend/tests/test_documents.py`
  - Add integration tests for successful delete, missing delete, and active-job conflict.
- Modify `frontend/src/api/client.ts`
  - Add `deleteDocument(documentId)` client method.
- Modify `frontend/src/features/documents/documents-page.tsx`
  - Add delete mutation.
  - Add an Actions column with a trash button.
  - Add a confirmation prompt before destructive deletion.
  - Invalidate `documents`, `jobs`, and `chunks` query keys after success.
  - Show deletion status/error near the documents table.
- Modify `frontend/tests/documents-page.test.tsx`
  - Extend mocks.
  - Test the delete confirmation flow and refresh/invalidation-facing behavior through visible UI.

---

### Task 1: Backend Delete Service And Route

**Files:**
- Modify: `backend/src/ragstudio/services/document_service.py`
- Modify: `backend/src/ragstudio/api/routes/documents.py`
- Test: `backend/tests/test_documents.py`

- [ ] **Step 1: Write failing backend tests**

Append these tests to `backend/tests/test_documents.py`:

```python
from pathlib import Path

from ragstudio.db.models import Document, Job
from ragstudio.schemas.common import StageStatus
```

If the file already has imports at the top, merge the imports instead of duplicating them. Then append:

```python
@pytest.mark.asyncio
async def test_delete_document_removes_document_chunks_jobs_and_artifact(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("delete-me.txt", b"alpha beta\ngamma delta", "text/plain")},
    )
    assert upload_response.status_code == 201
    document_id = upload_response.json()["id"]
    artifact_path = Path(upload_response.json()["artifact_path"])

    search_before = await client.post(
        "/api/chunks/search",
        json={"query": "alpha", "document_ids": [document_id], "limit": 10},
    )
    assert search_before.status_code == 200
    assert search_before.json()["total"] == 2
    assert artifact_path.exists()

    delete_response = await client.delete(f"/api/documents/{document_id}")

    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert not artifact_path.exists()

    documents_response = await client.get("/api/documents")
    assert documents_response.status_code == 200
    assert documents_response.json()["items"] == []

    jobs_response = await client.get("/api/jobs")
    assert jobs_response.status_code == 200
    assert jobs_response.json()["items"] == []

    search_after = await client.post(
        "/api/chunks/search",
        json={"query": "alpha", "document_ids": [document_id], "limit": 10},
    )
    assert search_after.status_code == 200
    assert search_after.json()["total"] == 0


@pytest.mark.asyncio
async def test_delete_missing_document_returns_404(client):
    response = await client.delete("/api/documents/missing-document")

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


@pytest.mark.asyncio
async def test_delete_document_with_active_index_job_returns_409(client, session_factory, tmp_path):
    async with session_factory() as session:
        artifact = tmp_path / "uploads" / "active-delete-sha"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("alpha", encoding="utf-8")
        document = Document(
            filename="active.txt",
            content_type="text/plain",
            sha256="active-delete-sha",
            artifact_path=str(artifact),
            status=StageStatus.RUNNING.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Job(
                type="index_document",
                target_id=document.id,
                status=StageStatus.RUNNING.value,
                progress=10,
            )
        )
        await session.commit()
        document_id = document.id

    response = await client.delete(f"/api/documents/{document_id}")

    assert response.status_code == 409
    assert response.json()["detail"] == "Document has an active indexing job"
    assert artifact.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_documents.py -q
```

Expected: the new tests fail because `DELETE /api/documents/{id}` is not implemented yet. The active-job test may also fail if `session_factory` is not available in the fixture signature; if so, inspect `backend/tests/conftest.py` and use the existing session fixture name exactly.

- [ ] **Step 3: Add service-level deletion**

In `backend/src/ragstudio/services/document_service.py`, update imports:

```python
from pathlib import Path
from typing import Any, Literal
```

and update the SQLAlchemy import:

```python
from sqlalchemy import delete, select
```

Add this type alias after imports:

```python
DeleteDocumentResult = Literal["deleted", "not_found", "active_job"]
```

Add this method inside `DocumentService` after `list()`:

```python
    async def delete_document(self, document_id: str) -> DeleteDocumentResult:
        document = await self.session.get(Document, document_id)
        if document is None:
            return "not_found"

        active_job_id = await self.session.scalar(
            select(Job.id)
            .where(
                Job.type == "index_document",
                Job.target_id == document.id,
                Job.status.in_([StageStatus.READY.value, StageStatus.RUNNING.value]),
            )
            .limit(1)
        )
        if active_job_id is not None:
            return "active_job"

        artifact_path = Path(document.artifact_path)
        await self.session.execute(delete(Job).where(Job.target_id == document.id))
        await self.session.delete(document)
        await self.session.commit()
        artifact_path.unlink(missing_ok=True)
        return "deleted"
```

Rationale: `Document.chunks` already has `cascade="all, delete-orphan"`, so deleting the `Document` removes its `Chunk` rows. Jobs have no foreign key, so delete them explicitly. The artifact file is deleted after the database commit to avoid losing the uploaded file if the transaction fails.

- [ ] **Step 4: Add the route**

In `backend/src/ragstudio/api/routes/documents.py`, update imports:

```python
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, UploadFile, status
```

Append this endpoint after `list_documents()`:

```python
@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    result = await DocumentService(session, request.app.state.settings.data_dir).delete_document(
        document_id
    )
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Document not found")
    if result == "active_job":
        raise HTTPException(status_code=409, detail="Document has an active indexing job")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 5: Run backend tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_documents.py backend/tests/test_documents_jobs.py backend/tests/test_chunks.py -q
```

Expected: all selected backend tests pass.

- [ ] **Step 6: Commit backend API**

Run:

```bash
git add backend/src/ragstudio/services/document_service.py backend/src/ragstudio/api/routes/documents.py backend/tests/test_documents.py
git commit -m "feat: delete documents with chunks"
```

---

### Task 2: Frontend API Client And Documents UI

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/features/documents/documents-page.tsx`
- Test: `frontend/tests/documents-page.test.tsx`

- [ ] **Step 1: Write failing frontend test**

In `frontend/tests/documents-page.test.tsx`, update imports:

```typescript
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
```

Update the API mock to include `deleteDocument`:

```typescript
vi.mock("../src/api/client", () => ({
  apiClient: {
    documents: vi.fn(),
    jobs: vi.fn(),
    domainProfiles: vi.fn(),
    uploadDocument: vi.fn(),
    deleteDocument: vi.fn(),
  },
}));
```

Append this test:

```typescript
it("confirms and deletes an uploaded document", async () => {
  vi.mocked(apiClient.documents).mockResolvedValue({
    items: [
      {
        id: "doc-1",
        filename: "delete-me.pdf",
        content_type: "application/pdf",
        status: "succeeded",
        sha256: "sha-1",
      },
    ],
    total: 1,
  });
  vi.mocked(apiClient.deleteDocument).mockResolvedValue(undefined);
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

  renderDocumentsPage();

  fireEvent.click(await screen.findByRole("button", { name: /delete delete-me\.pdf/i }));

  await waitFor(() => {
    expect(apiClient.deleteDocument).toHaveBeenCalledWith("doc-1");
  });
  expect(confirmSpy).toHaveBeenCalledWith(
    "Delete delete-me.pdf and all indexed chunks? This cannot be undone.",
  );
  expect(await screen.findByText("Deleted delete-me.pdf")).toBeVisible();

  confirmSpy.mockRestore();
});
```

Append the cancellation test too:

```typescript
it("does not delete when confirmation is cancelled", async () => {
  vi.mocked(apiClient.documents).mockResolvedValue({
    items: [
      {
        id: "doc-1",
        filename: "keep-me.pdf",
        content_type: "application/pdf",
        status: "succeeded",
        sha256: "sha-1",
      },
    ],
    total: 1,
  });
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

  renderDocumentsPage();

  fireEvent.click(await screen.findByRole("button", { name: /delete keep-me\.pdf/i }));

  expect(apiClient.deleteDocument).not.toHaveBeenCalled();
  confirmSpy.mockRestore();
});
```

- [ ] **Step 2: Run frontend test to verify it fails**

Run:

```bash
cd frontend && npm test -- --run tests/documents-page.test.tsx
```

Expected: fail because `apiClient.deleteDocument` and the delete action button do not exist.

- [ ] **Step 3: Add the API client method**

In `frontend/src/api/client.ts`, add this method immediately after `uploadDocument`:

```typescript
  deleteDocument: (documentId: string) =>
    request<void>(`/api/documents/${encodeURIComponent(documentId)}`, {
      method: "DELETE",
    }),
```

- [ ] **Step 4: Add delete UI state and mutation**

In `frontend/src/features/documents/documents-page.tsx`, update the lucide import:

```typescript
import { AlertCircle, FileUp, Loader2, RefreshCcw, Trash2, Upload } from "lucide-react";
```

Add state near the existing `file` state:

```typescript
  const [deletedFilename, setDeletedFilename] = useState("");
```

Add this mutation after `uploadDocument`:

```typescript
  const deleteDocument = useMutation({
    mutationFn: apiClient.deleteDocument,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.documents }),
        queryClient.invalidateQueries({ queryKey: queryKeys.jobs }),
        queryClient.invalidateQueries({ queryKey: ["chunks"] }),
      ]);
    },
  });
```

Add this helper before `documentColumns`:

```typescript
  const confirmAndDeleteDocument = (document: DocumentOut) => {
    const confirmed = window.confirm(
      `Delete ${document.filename} and all indexed chunks? This cannot be undone.`,
    );
    if (!confirmed) {
      return;
    }
    setDeletedFilename(document.filename);
    deleteDocument.mutate(document.id);
  };
```

- [ ] **Step 5: Add the Actions column**

In `documentColumns`, add this column after the SHA-256 column:

```typescript
      {
        id: "actions",
        header: "Actions",
        cell: ({ row }) => {
          const document = row.original;
          const isDeleting = deleteDocument.isPending && deleteDocument.variables === document.id;

          return (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => confirmAndDeleteDocument(document)}
              disabled={isDeleting}
              aria-label={`Delete ${document.filename}`}
            >
              {isDeleting ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              )}
              Delete
            </Button>
          );
        },
      },
```

Update the `useMemo` dependency array from `[]` to:

```typescript
    [deleteDocument.isPending, deleteDocument.variables],
```

If ESLint reports `confirmAndDeleteDocument` is missing from dependencies, wrap it in `useCallback`:

```typescript
  const confirmAndDeleteDocument = useCallback(
    (document: DocumentOut) => {
      const confirmed = window.confirm(
        `Delete ${document.filename} and all indexed chunks? This cannot be undone.`,
      );
      if (!confirmed) {
        return;
      }
      setDeletedFilename(document.filename);
      deleteDocument.mutate(document.id);
    },
    [deleteDocument],
  );
```

and update the React import:

```typescript
import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";
```

Then use this dependency array:

```typescript
    [confirmAndDeleteDocument, deleteDocument.isPending, deleteDocument.variables],
```

- [ ] **Step 6: Add visible delete status**

Inside the `Panel title="Documents"` block, wrap the existing table state in a container so status can render below it:

```tsx
        <Panel title="Documents" icon={FileUp}>
          <div className="space-y-3">
            {documentsQuery.isLoading ? (
              <EmptyState
                icon={Loader2}
                title="Loading documents"
                description="Fetching uploaded files."
              />
            ) : documentsQuery.isError ? (
              <EmptyState
                icon={AlertCircle}
                title="Documents unavailable"
                description={documentsQuery.error.message}
                action={
                  <Button variant="secondary" onClick={() => void documentsQuery.refetch()}>
                    <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                    Retry
                  </Button>
                }
              />
            ) : (
              <DataTable
                columns={documentColumns}
                data={documentsQuery.data?.items ?? []}
                emptyTitle="No documents"
                emptyDescription="Uploaded files will appear here."
              />
            )}
            <p className="min-h-5 text-sm text-[#62717a]" role="status">
              {deleteDocument.isSuccess
                ? `Deleted ${deletedFilename}`
                : deleteDocument.error?.message}
            </p>
          </div>
        </Panel>
```

- [ ] **Step 7: Run frontend tests**

Run:

```bash
cd frontend && npm test -- --run tests/documents-page.test.tsx
```

Expected: all Documents page tests pass.

- [ ] **Step 8: Commit frontend UI**

Run:

```bash
git add frontend/src/api/client.ts frontend/src/features/documents/documents-page.tsx frontend/tests/documents-page.test.tsx
git commit -m "feat: delete documents from documents page"
```

---

### Task 3: Integration Verification And UI QA

**Files:**
- No new production files.
- Use existing app and tests.

- [ ] **Step 1: Run backend focused tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_documents.py backend/tests/test_documents_jobs.py backend/tests/test_chunks.py backend/tests/test_query_runs.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend focused tests**

Run:

```bash
cd frontend && npm test -- --run tests/documents-page.test.tsx tests/chunk-inspector.test.tsx tests/pipeline-builder.test.tsx
```

Expected: all tests pass.

- [ ] **Step 3: Run full project verification**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH ./scripts/test-all.sh
```

Expected:

```text
backend tests pass
ruff passes
pyright has no new errors
frontend lint passes
frontend tests pass
frontend build passes
```

The existing pyright warning in `backend/src/ragstudio/db/repositories.py` may still appear; do not fix it in this feature unless the warning changes into an error.

- [ ] **Step 4: Manual browser QA**

Start or reuse the dev server:

```bash
./scripts/dev.sh
```

Open:

```text
http://127.0.0.1:5173/documents
```

Perform this manual flow:

1. Upload `sample-delete.txt` containing `delete flow alpha`.
2. Confirm the document appears in the Documents table.
3. Confirm the table row has a **Delete** button.
4. Click **Delete** and cancel the confirmation.
5. Confirm the document remains visible.
6. Click **Delete** again and accept the confirmation.
7. Confirm the row disappears.
8. Go to `http://127.0.0.1:5173/chunks`.
9. Confirm the deleted document no longer appears in the document selector.
10. Search for `delete flow alpha` with no deleted document selected and confirm no chunks from the deleted document appear.

- [ ] **Step 5: Commit verification notes only if needed**

If manual QA reveals a small UI copy issue, fix it and commit:

```bash
git add frontend/src/features/documents/documents-page.tsx frontend/tests/documents-page.test.tsx
git commit -m "fix: clarify document delete feedback"
```

If no code changes are needed, do not create a verification-only commit.

---

## Self-Review

**Spec coverage:** The plan adds a CRUD-style delete operation for uploaded documents from the Documents page and guarantees indexed chunks are removed via the existing ORM cascade. It also removes related indexing jobs and uploaded artifact files, and blocks deletion while indexing is active.

**Placeholder scan:** No placeholders remain. Every code step includes concrete snippets, exact paths, exact commands, and expected outcomes.

**Type consistency:** Backend uses `DocumentService.delete_document(document_id: str) -> DeleteDocumentResult`; the route calls that exact method. Frontend uses `apiClient.deleteDocument(documentId: string)` and `DocumentsPage` calls the same method. Test names and API paths match the planned implementation.
