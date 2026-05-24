# Document Pipeline Stage Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a document-level stage timeline that shows the actual path each document passed through, which events happened in each stage, and where the related evidence, warnings, chunks, and graph/runtime materialization records live.

**Architecture:** Reuse the existing indexing stage contract in `Job.result["indexing_stage_events"]` as the canonical live event source, then add a document-scoped service and API endpoint that combines document upload metadata, all index jobs for that document, current stage events, job logs, chunk counts, index records, graph projection records, and parse-evidence links. The UI will mount this timeline on the Document Evidence page so operators do not need to jump between Evidence and Jobs & Warnings to reconstruct the flow.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Pydantic, pytest; React, TypeScript, TanStack Query, Testing Library, Vitest, Tailwind CSS v4, lucide-react.

---

## Current Behavior Verified

- `backend/src/ragstudio/services/index_progress.py` already defines `IndexStage`, progress percentages, labels, `stage_event_payload()`, and `update_job_stage()`.
- `update_job_stage()` already writes structured events to `job.result["indexing_stage_events"]` with `sequence`, `occurred_at`, `stage`, `label`, `detail`, `progress`, optional `chunk_count`, and optional `warning`.
- `backend/src/ragstudio/api/routes/jobs.py` already streams those events at `/api/jobs/{job_id}/events`.
- `frontend/src/features/documents/documents-page.tsx` already shows current stage, progress, latest log, and warning counts inside the Jobs & Warnings tab.
- `frontend/src/features/document-evidence/document-evidence-page.tsx` currently fetches only `/api/documents/{document_id}/parse-evidence` and renders `EvidenceInspector`.
- The missing product surface is a unified document-level timeline on the Evidence page. Today, parse evidence and job-stage flow are separated.

## File Structure

- Create `backend/src/ragstudio/schemas/document_pipeline_timeline.py`
  - Pydantic response contract for document pipeline timeline stages, events, linked records, and summary counts.
- Create `backend/src/ragstudio/services/document_pipeline_timeline_service.py`
  - Assembles the timeline from `Document`, `Job`, `Chunk`, `IndexRecord`, and `GraphProjectionRecord`.
- Modify `backend/src/ragstudio/api/routes/documents.py`
  - Adds `GET /api/documents/{document_id}/pipeline-timeline`.
- Modify `backend/src/ragstudio/services/job_queue_service.py`
  - Records a structured `queued` event when an index job is created and a `worker_claimed` event when a worker claims it.
- Modify `backend/src/ragstudio/services/index_progress.py`
  - Adds `WORKER_CLAIMED` to the stage vocabulary and exposes a helper for appending stage events without changing progress when needed.
- Create `backend/tests/test_document_pipeline_timeline.py`
  - Service and route tests for ordered stages, old-job fallback, warnings, graph/index links, and missing-document errors.
- Modify `backend/tests/test_index_progress.py`
  - Covers queue/claim events and non-progress event append behavior.
- Modify `backend/tests/test_job_queue_service.py`
  - Covers queue and worker-claim event persistence.
- Modify `frontend/src/api/generated.ts`
  - Adds frontend interfaces for `DocumentPipelineTimelineOut`, `DocumentPipelineJobOut`, and `DocumentPipelineEventOut`.
- Modify `frontend/src/api/client.ts`
  - Adds `documentPipelineTimeline(documentId)`.
- Create `frontend/src/features/document-evidence/document-pipeline-timeline.tsx`
  - Timeline component with stage list, event rows, status/progress, warning badges, and evidence links.
- Modify `frontend/src/features/document-evidence/document-evidence-page.tsx`
  - Fetches parse evidence and pipeline timeline in parallel; renders the timeline above `EvidenceInspector`.
- Create `frontend/tests/document-pipeline-timeline.test.tsx`
  - Component tests for timeline rendering, inferred events, warnings, and empty state.
- Modify `frontend/tests/document-evidence-page.test.tsx`
  - Page-level tests that both evidence and timeline requests are made and failures degrade independently.
- Modify `frontend/tests/api-client.test.ts`
  - API client test for `/api/documents/{id}/pipeline-timeline`.

## Stage Vocabulary

The first implementation should show these stages when data exists:

- `uploaded`: document row created and source artifact stored.
- `queued`: index job created.
- `worker_claimed`: worker accepted the job lease.
- `mineru_parsing`: MinerU sidecar parsing/submission activity.
- `mineru_validated`: MinerU artifacts produced validated adapter chunks.
- `chunks_persisting`: canonical chunks are being written.
- `chunks_persisted`: canonical chunks are durable in Postgres.
- `search_ready`: lexical and metadata retrieval are ready.
- `runtime_enriching`: runtime/native RAG enrichment is running or finished.
- `graph_enriching`: graph projection is queued or materialized.
- `ready`: document indexing completed without warnings.
- `ready_with_warnings`: document indexing completed with parser/runtime/graph warnings.
- `failed`: document indexing failed.

Events derived from old job logs must be marked with `source = "inferred_log"` because old logs do not have per-line timestamps. Events from `indexing_stage_events` must be marked `source = "structured_event"`.

---

### Task 1: Backend Contract For Document Timeline

**Files:**
- Create: `backend/src/ragstudio/schemas/document_pipeline_timeline.py`
- Test: `backend/tests/test_document_pipeline_timeline.py`

- [ ] **Step 1: Write the failing schema test**

Add this test to `backend/tests/test_document_pipeline_timeline.py`:

```python
from ragstudio.schemas.document_pipeline_timeline import (
    DocumentPipelineEventOut,
    DocumentPipelineTimelineOut,
)


def test_document_pipeline_timeline_contract_serializes_ui_safe_fields():
    event = DocumentPipelineEventOut(
        sequence=1,
        stage="chunks_persisted",
        label="Chunks persisted",
        detail="Persisted 823 canonical chunks.",
        status="succeeded",
        progress=65,
        occurred_at="2026-05-24T07:00:00+00:00",
        source="structured_event",
        job_id="job-1",
        chunk_count=823,
        warning=None,
        evidence_refs=[{"kind": "parse_evidence", "href": "/document-evidence?documentId=doc-1"}],
    )
    timeline = DocumentPipelineTimelineOut(
        document_id="doc-1",
        filename="policy.pdf",
        status="succeeded",
        latest_job_id="job-1",
        events=[event],
        totals={"jobs": 1, "chunks": 823, "warnings": 0, "graph_nodes": 3, "graph_edges": 0},
    )

    payload = timeline.model_dump(mode="json")

    assert payload["document_id"] == "doc-1"
    assert payload["events"][0]["stage"] == "chunks_persisted"
    assert payload["events"][0]["source"] == "structured_event"
    assert payload["totals"]["chunks"] == 823
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `pytest backend/tests/test_document_pipeline_timeline.py::test_document_pipeline_timeline_contract_serializes_ui_safe_fields -q`

Expected: FAIL because `ragstudio.schemas.document_pipeline_timeline` does not exist.

- [ ] **Step 3: Add the schema**

Create `backend/src/ragstudio/schemas/document_pipeline_timeline.py`:

```python
from typing import Any, Literal

from ragstudio.schemas.common import StageStatus, StudioModel


PipelineEventSource = Literal[
    "document",
    "structured_event",
    "inferred_log",
    "job",
    "chunk",
    "index_record",
    "graph_projection",
]


class DocumentPipelineJobOut(StudioModel):
    id: str
    status: StageStatus
    progress: int
    created_at: str
    updated_at: str
    attempts: int
    recovery_action: str | None = None


class DocumentPipelineEventOut(StudioModel):
    sequence: int
    stage: str
    label: str
    detail: str
    status: str
    progress: int | None = None
    occurred_at: str | None = None
    source: PipelineEventSource
    job_id: str | None = None
    chunk_count: int | None = None
    warning: str | None = None
    evidence_refs: list[dict[str, Any]] = []


class DocumentPipelineTimelineOut(StudioModel):
    document_id: str
    filename: str
    status: StageStatus
    latest_job_id: str | None = None
    jobs: list[DocumentPipelineJobOut] = []
    events: list[DocumentPipelineEventOut]
    totals: dict[str, int]
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `pytest backend/tests/test_document_pipeline_timeline.py::test_document_pipeline_timeline_contract_serializes_ui_safe_fields -q`

Expected: PASS.

### Task 2: Timeline Service From Existing Records

**Files:**
- Create: `backend/src/ragstudio/services/document_pipeline_timeline_service.py`
- Test: `backend/tests/test_document_pipeline_timeline.py`

- [ ] **Step 1: Add service tests**

Append these tests:

```python
import pytest
from ragstudio.db.models import Chunk, Document, GraphProjectionRecord, IndexRecord, Job
from ragstudio.schemas.common import StageStatus
from ragstudio.services.document_pipeline_timeline_service import (
    DocumentPipelineTimelineNotFoundError,
    DocumentPipelineTimelineService,
)
from ragstudio.services.index_progress import IndexStage, update_job_stage


@pytest.mark.asyncio
async def test_timeline_orders_document_job_chunk_and_graph_events(session):
    document = Document(
        id="doc-flow",
        filename="flow.pdf",
        content_type="application/pdf",
        sha256="sha-flow",
        artifact_path="/data/uploads/flow.pdf",
        status=StageStatus.SUCCEEDED.value,
    )
    job = Job(
        id="job-flow",
        type="index_document",
        status=StageStatus.SUCCEEDED.value,
        target_id="doc-flow",
        progress=100,
        logs=["Indexing queued.", "Worker worker-1 claimed job."],
        result={"document_id": "doc-flow"},
    )
    update_job_stage(job, IndexStage.CHUNKS_PERSISTED, detail="Persisted 2 canonical chunks.", chunk_count=2)
    update_job_stage(job, IndexStage.READY, detail="Indexed 2 chunks.", chunk_count=2)
    session.add_all(
        [
            document,
            job,
            Chunk(id="chunk-1", document_id="doc-flow", text="A", source_location={}, metadata_json={}),
            Chunk(id="chunk-2", document_id="doc-flow", text="B", source_location={}, metadata_json={}),
            IndexRecord(
                id="index-flow",
                document_id="doc-flow",
                runtime_profile_id="profile-1",
                status=StageStatus.SUCCEEDED.value,
                index_shape={},
                chunk_count=2,
            ),
            GraphProjectionRecord(
                id="graph-flow",
                document_id="doc-flow",
                runtime_profile_id="profile-1",
                status=StageStatus.SUCCEEDED.value,
                node_count=3,
                edge_count=1,
            ),
        ]
    )
    await session.commit()

    timeline = await DocumentPipelineTimelineService(session).get_timeline("doc-flow")

    assert timeline.document_id == "doc-flow"
    assert timeline.latest_job_id == "job-flow"
    assert [event.stage for event in timeline.events][:2] == ["uploaded", "queued"]
    assert "chunks_persisted" in [event.stage for event in timeline.events]
    assert "graph_enriching" in [event.stage for event in timeline.events]
    assert timeline.totals["chunks"] == 2
    assert timeline.totals["graph_nodes"] == 3
    assert timeline.totals["graph_edges"] == 1


@pytest.mark.asyncio
async def test_timeline_marks_old_log_events_as_inferred(session):
    document = Document(
        id="doc-old",
        filename="old.pdf",
        content_type="application/pdf",
        sha256="sha-old",
        artifact_path="/data/uploads/old.pdf",
        status=StageStatus.SUCCEEDED.value,
    )
    job = Job(
        id="job-old",
        type="index_document",
        status=StageStatus.SUCCEEDED.value,
        target_id="doc-old",
        progress=100,
        logs=["MinerU validated: Validated 823 chunks from MinerU."],
        result={"document_id": "doc-old", "chunk_count": 823},
    )
    session.add_all([document, job])
    await session.commit()

    timeline = await DocumentPipelineTimelineService(session).get_timeline("doc-old")

    inferred = [event for event in timeline.events if event.stage == "mineru_validated"]
    assert inferred
    assert inferred[0].source == "inferred_log"
    assert inferred[0].chunk_count == 823


@pytest.mark.asyncio
async def test_timeline_raises_for_missing_document(session):
    with pytest.raises(DocumentPipelineTimelineNotFoundError):
        await DocumentPipelineTimelineService(session).get_timeline("missing")
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `pytest backend/tests/test_document_pipeline_timeline.py -q`

Expected: FAIL because `DocumentPipelineTimelineService` does not exist.

- [ ] **Step 3: Implement the service**

Create `backend/src/ragstudio/services/document_pipeline_timeline_service.py`:

```python
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ragstudio.db.models import Chunk, Document, GraphProjectionRecord, IndexRecord, Job
from ragstudio.schemas.document_pipeline_timeline import (
    DocumentPipelineEventOut,
    DocumentPipelineJobOut,
    DocumentPipelineTimelineOut,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class DocumentPipelineTimelineNotFoundError(RuntimeError):
    pass


class DocumentPipelineTimelineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_timeline(self, document_id: str) -> DocumentPipelineTimelineOut:
        document = await self.session.get(Document, document_id)
        if document is None:
            raise DocumentPipelineTimelineNotFoundError(f"Document {document_id} not found")

        jobs = await self._jobs(document_id)
        chunk_count = await self._chunk_count(document_id)
        index_records = await self._index_records(document_id)
        graph_records = await self._graph_records(document_id)
        events = self._document_events(document, jobs)
        events.extend(self._job_events(jobs))
        events.extend(self._index_record_events(index_records))
        events.extend(self._graph_events(graph_records))
        ordered = self._renumber(events)
        latest_job = jobs[0] if jobs else None

        return DocumentPipelineTimelineOut(
            document_id=document.id,
            filename=document.filename,
            status=document.status,
            latest_job_id=latest_job.id if latest_job else None,
            jobs=[
                DocumentPipelineJobOut(
                    id=job.id,
                    status=job.status,
                    progress=job.progress,
                    created_at=job.created_at.isoformat(),
                    updated_at=job.updated_at.isoformat(),
                    attempts=job.attempts,
                    recovery_action=job.recovery_action,
                )
                for job in jobs
            ],
            events=ordered,
            totals={
                "jobs": len(jobs),
                "chunks": chunk_count,
                "warnings": self._warning_total(jobs),
                "graph_nodes": sum(record.node_count for record in graph_records),
                "graph_edges": sum(record.edge_count for record in graph_records),
            },
        )

    async def _jobs(self, document_id: str) -> list[Job]:
        result = await self.session.execute(
            select(Job)
            .where(Job.type == "index_document", Job.target_id == document_id)
            .order_by(Job.created_at.desc(), Job.id.desc())
        )
        return list(result.scalars().all())

    async def _chunk_count(self, document_id: str) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
            )
            or 0
        )

    async def _index_records(self, document_id: str) -> list[IndexRecord]:
        result = await self.session.execute(
            select(IndexRecord)
            .where(IndexRecord.document_id == document_id)
            .order_by(IndexRecord.created_at.asc(), IndexRecord.id.asc())
        )
        return list(result.scalars().all())

    async def _graph_records(self, document_id: str) -> list[GraphProjectionRecord]:
        result = await self.session.execute(
            select(GraphProjectionRecord)
            .where(GraphProjectionRecord.document_id == document_id)
            .order_by(GraphProjectionRecord.created_at.asc(), GraphProjectionRecord.id.asc())
        )
        return list(result.scalars().all())

    def _document_events(self, document: Document, jobs: list[Job]) -> list[DocumentPipelineEventOut]:
        events = [
            DocumentPipelineEventOut(
                sequence=0,
                stage="uploaded",
                label="Uploaded",
                detail=f"Stored source artifact for {document.filename}.",
                status=document.status,
                progress=0,
                occurred_at=document.created_at.isoformat(),
                source="document",
                evidence_refs=[{"kind": "artifact", "label": "Source artifact"}],
            )
        ]
        for job in reversed(jobs):
            events.append(
                DocumentPipelineEventOut(
                    sequence=0,
                    stage="queued",
                    label="Queued",
                    detail="Indexing queued.",
                    status=job.status,
                    progress=0,
                    occurred_at=job.created_at.isoformat(),
                    source="job",
                    job_id=job.id,
                )
            )
        return events

    def _job_events(self, jobs: list[Job]) -> list[DocumentPipelineEventOut]:
        events: list[DocumentPipelineEventOut] = []
        for job in reversed(jobs):
            structured = self._structured_job_events(job)
            if structured:
                events.extend(structured)
            else:
                events.extend(self._inferred_log_events(job))
        return events

    def _structured_job_events(self, job: Job) -> list[DocumentPipelineEventOut]:
        raw_events = (job.result or {}).get("indexing_stage_events")
        if not isinstance(raw_events, list):
            return []
        events: list[DocumentPipelineEventOut] = []
        for raw in raw_events:
            if not isinstance(raw, dict):
                continue
            stage = str(raw.get("stage") or "stage")
            events.append(
                DocumentPipelineEventOut(
                    sequence=0,
                    stage=stage,
                    label=str(raw.get("label") or stage.replace("_", " ").title()),
                    detail=str(raw.get("detail") or ""),
                    status=job.status,
                    progress=self._optional_int(raw.get("progress")),
                    occurred_at=str(raw.get("occurred_at")) if raw.get("occurred_at") else None,
                    source="structured_event",
                    job_id=job.id,
                    chunk_count=self._optional_int(raw.get("chunk_count")),
                    warning=str(raw.get("warning")) if raw.get("warning") else None,
                    evidence_refs=self._evidence_refs_for_stage(stage, job.target_id),
                )
            )
        return events

    def _inferred_log_events(self, job: Job) -> list[DocumentPipelineEventOut]:
        return [
            DocumentPipelineEventOut(
                sequence=0,
                stage=self._stage_from_log(log),
                label=log.split(":", 1)[0] if ":" in log else "Job log",
                detail=log.split(":", 1)[1].strip() if ":" in log else log,
                status=job.status,
                progress=job.progress,
                occurred_at=job.updated_at.isoformat(),
                source="inferred_log",
                job_id=job.id,
                chunk_count=self._optional_int((job.result or {}).get("chunk_count")),
                warning=log if "warning" in log.lower() else None,
            )
            for log in job.logs or []
            if self._stage_from_log(log) != "job_log"
        ]

    def _index_record_events(self, records: Iterable[IndexRecord]) -> list[DocumentPipelineEventOut]:
        return [
            DocumentPipelineEventOut(
                sequence=0,
                stage="runtime_enriching",
                label="Runtime enrichment",
                detail=f"Runtime index record {record.status} with {record.chunk_count} chunks.",
                status=record.status,
                progress=85 if record.status != "succeeded" else 100,
                occurred_at=record.updated_at.isoformat(),
                source="index_record",
                chunk_count=record.chunk_count,
            )
            for record in records
        ]

    def _graph_events(self, records: Iterable[GraphProjectionRecord]) -> list[DocumentPipelineEventOut]:
        return [
            DocumentPipelineEventOut(
                sequence=0,
                stage="graph_enriching",
                label="Graph enrichment",
                detail=f"Graph projection {record.status}: {record.node_count} nodes, {record.edge_count} edges.",
                status=record.status,
                progress=95 if record.status != "succeeded" else 100,
                occurred_at=record.updated_at.isoformat(),
                source="graph_projection",
                warning=record.error,
                evidence_refs=[{"kind": "graph_projection", "id": record.id}],
            )
            for record in records
        ]

    def _renumber(self, events: list[DocumentPipelineEventOut]) -> list[DocumentPipelineEventOut]:
        sorted_events = sorted(events, key=lambda event: (event.occurred_at or "", event.job_id or "", event.stage))
        return [event.model_copy(update={"sequence": index + 1}) for index, event in enumerate(sorted_events)]

    def _warning_total(self, jobs: list[Job]) -> int:
        total = 0
        for job in jobs:
            warnings = (job.result or {}).get("warnings")
            if isinstance(warnings, list):
                total += len(warnings)
        return total

    def _stage_from_log(self, log: str) -> str:
        lower = log.lower()
        if "mineru validated" in lower:
            return "mineru_validated"
        if "persisting chunks" in lower:
            return "chunks_persisting"
        if "chunks persisted" in lower:
            return "chunks_persisted"
        if "search ready" in lower:
            return "search_ready"
        if "runtime enrichment" in lower:
            return "runtime_enriching"
        if "graph" in lower:
            return "graph_enriching"
        if "ready with warnings" in lower:
            return "ready_with_warnings"
        if "indexed" in lower:
            return "ready"
        return "job_log"

    def _evidence_refs_for_stage(self, stage: str, document_id: str | None) -> list[dict[str, Any]]:
        if not document_id:
            return []
        if stage in {"mineru_validated", "chunks_persisting", "chunks_persisted", "ready", "ready_with_warnings"}:
            return [{"kind": "parse_evidence", "href": f"/document-evidence?documentId={document_id}"}]
        return []

    def _optional_int(self, value: Any) -> int | None:
        if isinstance(value, bool) or value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
```

- [ ] **Step 4: Run backend timeline tests**

Run: `pytest backend/tests/test_document_pipeline_timeline.py -q`

Expected: PASS.

### Task 3: Document Timeline API Endpoint

**Files:**
- Modify: `backend/src/ragstudio/api/routes/documents.py`
- Test: `backend/tests/test_document_pipeline_timeline.py`

- [ ] **Step 1: Add route tests**

Append:

```python
@pytest.mark.asyncio
async def test_document_pipeline_timeline_route_returns_timeline(client):
    async with client._transport.app.state.session_factory() as session:
        session.add(
            Document(
                id="doc-route-flow",
                filename="route.pdf",
                content_type="application/pdf",
                sha256="sha-route-flow",
                artifact_path="/data/uploads/route.pdf",
                status=StageStatus.SUCCEEDED.value,
            )
        )
        await session.commit()

    response = await client.get("/api/documents/doc-route-flow/pipeline-timeline")

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == "doc-route-flow"
    assert body["events"][0]["stage"] == "uploaded"


@pytest.mark.asyncio
async def test_document_pipeline_timeline_route_returns_404(client):
    response = await client.get("/api/documents/missing/pipeline-timeline")

    assert response.status_code == 404
```

- [ ] **Step 2: Run route tests and confirm failure**

Run: `pytest backend/tests/test_document_pipeline_timeline.py::test_document_pipeline_timeline_route_returns_timeline backend/tests/test_document_pipeline_timeline.py::test_document_pipeline_timeline_route_returns_404 -q`

Expected: FAIL with 404 for the missing endpoint.

- [ ] **Step 3: Add endpoint**

In `backend/src/ragstudio/api/routes/documents.py`, add imports:

```python
from ragstudio.schemas.document_pipeline_timeline import DocumentPipelineTimelineOut
from ragstudio.services.document_pipeline_timeline_service import (
    DocumentPipelineTimelineNotFoundError,
    DocumentPipelineTimelineService,
)
```

Add this route above `get_document_parse_evidence()`:

```python
@router.get("/{document_id}/pipeline-timeline", response_model=DocumentPipelineTimelineOut)
async def get_document_pipeline_timeline(
    document_id: str,
    session: AsyncSession = Depends(get_session),
) -> DocumentPipelineTimelineOut:
    try:
        return await DocumentPipelineTimelineService(session).get_timeline(document_id)
    except DocumentPipelineTimelineNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
```

- [ ] **Step 4: Run route tests**

Run: `pytest backend/tests/test_document_pipeline_timeline.py -q`

Expected: PASS.

### Task 4: Queue And Worker Claim Structured Events

**Files:**
- Modify: `backend/src/ragstudio/services/index_progress.py`
- Modify: `backend/src/ragstudio/services/job_queue_service.py`
- Modify: `backend/tests/test_index_progress.py`
- Modify: `backend/tests/test_job_queue_service.py`

- [ ] **Step 1: Add tests for queue and claim events**

Append to `backend/tests/test_index_progress.py`:

```python
from ragstudio.services.index_progress import append_job_stage_event


def test_append_job_stage_event_can_record_worker_claim_without_progress_override():
    job = FakeJob()
    job.progress = 0

    append_job_stage_event(
        job,
        IndexStage.WORKER_CLAIMED,
        detail="Worker worker-1 claimed job.",
    )

    assert job.progress == 0
    assert job.result["indexing_stage_events"][-1]["stage"] == "worker_claimed"
    assert job.logs[-1] == "Worker claimed: Worker worker-1 claimed job."
```

Add to `backend/tests/test_job_queue_service.py`:

```python
@pytest.mark.asyncio
async def test_enqueue_and_claim_record_structured_stage_events(session):
    service = JobQueueService(session)
    job = await service.enqueue_index_document("doc-stage-events", {})
    await session.commit()

    queued_events = job.result["indexing_stage_events"]
    assert queued_events[-1]["stage"] == "queued"

    claimed = await service.claim_next("worker-1", ["index_document"])
    await session.commit()

    assert claimed is not None
    events = claimed.result["indexing_stage_events"]
    assert [event["stage"] for event in events][-2:] == ["queued", "worker_claimed"]
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `pytest backend/tests/test_index_progress.py backend/tests/test_job_queue_service.py -q`

Expected: FAIL because `WORKER_CLAIMED` and `append_job_stage_event` do not exist.

- [ ] **Step 3: Extend stage helper**

In `backend/src/ragstudio/services/index_progress.py`, add enum member and label/progress entries:

```python
class IndexStage(StrEnum):
    QUEUED = "queued"
    WORKER_CLAIMED = "worker_claimed"
    MINERU_PARSING = "mineru_parsing"
```

Add:

```python
_STAGE_PROGRESS = {
    IndexStage.QUEUED: 1,
    IndexStage.WORKER_CLAIMED: 2,
```

Add:

```python
_STAGE_LABELS = {
    IndexStage.QUEUED: "Queued",
    IndexStage.WORKER_CLAIMED: "Worker claimed",
```

Add helper:

```python
def append_job_stage_event(
    job: Any,
    stage: IndexStage,
    *,
    detail: str,
    chunk_count: int | None = None,
    warning: str | None = None,
    progress: int | None = None,
    update_progress: bool = False,
) -> None:
    result = dict(job.result or {})
    previous_events = [
        event for event in result.get("indexing_stage_events", []) if isinstance(event, dict)
    ]
    last_sequence = max(
        (
            event.get("sequence", 0)
            for event in previous_events
            if isinstance(event.get("sequence"), int)
        ),
        default=0,
    )
    event = stage_event_payload(
        stage,
        detail=detail,
        chunk_count=chunk_count,
        warning=warning,
        sequence=last_sequence + 1,
        progress=progress,
    )
    result["indexing_stage_events"] = [*previous_events, event][-_MAX_STAGE_EVENTS:]
    result["indexing_stage"] = stage_payload(
        stage,
        detail=detail,
        chunk_count=chunk_count,
        warning=warning,
        progress=progress,
    )
    if update_progress:
        job.progress = result["indexing_stage"]["progress"]
    job.result = result
    job.logs = [*(job.logs or []), f"{event['label']}: {detail}"][-20:]
```

- [ ] **Step 4: Use helper in job queue**

In `backend/src/ragstudio/services/job_queue_service.py`, import:

```python
from ragstudio.services.index_progress import IndexStage, append_job_stage_event
```

In `enqueue_index_document()`, after creating `job`, call:

```python
append_job_stage_event(
    job,
    IndexStage.QUEUED,
    detail="Indexing queued.",
    progress=0,
    update_progress=False,
)
```

In `claim_next()`, replace the manual claim log append with:

```python
append_job_stage_event(
    job,
    IndexStage.WORKER_CLAIMED,
    detail=f"Worker {worker_id} claimed job.",
    progress=job.progress,
    update_progress=False,
)
```

- [ ] **Step 5: Run backend tests**

Run: `pytest backend/tests/test_index_progress.py backend/tests/test_job_queue_service.py backend/tests/test_jobs.py backend/tests/test_document_pipeline_timeline.py -q`

Expected: PASS.

### Task 5: Frontend Types And API Client

**Files:**
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/tests/api-client.test.ts`

- [ ] **Step 1: Add API client test**

Append to `frontend/tests/api-client.test.ts`:

```ts
it("requests document pipeline timeline", async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({ document_id: "doc-1", events: [], totals: {} }));

  await apiClient.documentPipelineTimeline("doc/1");

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/documents/doc%2F1/pipeline-timeline",
    expect.objectContaining({
      headers: expect.any(Headers),
    }),
  );
});
```

- [ ] **Step 2: Run test and confirm failure**

Run: `cd frontend; npx.cmd vitest run tests/api-client.test.ts`

Expected: FAIL because `documentPipelineTimeline` does not exist.

- [ ] **Step 3: Add frontend interfaces**

Add to `frontend/src/api/generated.ts` after `JobOut`:

```ts
export interface DocumentPipelineJobOut {
  id: string;
  status: StageStatus;
  progress: number;
  created_at: string;
  updated_at: string;
  attempts: number;
  recovery_action: string | null;
}

export interface DocumentPipelineEventOut {
  sequence: number;
  stage: string;
  label: string;
  detail: string;
  status: string;
  progress: number | null;
  occurred_at: string | null;
  source:
    | "document"
    | "structured_event"
    | "inferred_log"
    | "job"
    | "chunk"
    | "index_record"
    | "graph_projection";
  job_id: string | null;
  chunk_count: number | null;
  warning: string | null;
  evidence_refs: Array<Record<string, unknown>>;
}

export interface DocumentPipelineTimelineOut {
  document_id: string;
  filename: string;
  status: StageStatus;
  latest_job_id: string | null;
  jobs: DocumentPipelineJobOut[];
  events: DocumentPipelineEventOut[];
  totals: Record<string, number>;
}
```

- [ ] **Step 4: Add client method**

In `frontend/src/api/client.ts`, import `DocumentPipelineTimelineOut` from `./generated`, then add:

```ts
documentPipelineTimeline: (documentId: string) =>
  request<DocumentPipelineTimelineOut>(
    `/api/documents/${encodeURIComponent(documentId)}/pipeline-timeline`,
  ),
```

- [ ] **Step 5: Run API client test**

Run: `cd frontend; npx.cmd vitest run tests/api-client.test.ts`

Expected: PASS.

### Task 6: Timeline Component

**Files:**
- Create: `frontend/src/features/document-evidence/document-pipeline-timeline.tsx`
- Create: `frontend/tests/document-pipeline-timeline.test.tsx`

- [ ] **Step 1: Add component tests**

Create `frontend/tests/document-pipeline-timeline.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";

import { DocumentPipelineTimeline } from "../src/features/document-evidence/document-pipeline-timeline";
import type { DocumentPipelineTimelineOut } from "../src/api/generated";

const timeline: DocumentPipelineTimelineOut = {
  document_id: "doc-1",
  filename: "policy.pdf",
  status: "succeeded",
  latest_job_id: "job-1",
  jobs: [],
  totals: { jobs: 1, chunks: 823, warnings: 1, graph_nodes: 3, graph_edges: 0 },
  events: [
    {
      sequence: 1,
      stage: "uploaded",
      label: "Uploaded",
      detail: "Stored source artifact for policy.pdf.",
      status: "succeeded",
      progress: 0,
      occurred_at: "2026-05-24T07:00:00+00:00",
      source: "document",
      job_id: null,
      chunk_count: null,
      warning: null,
      evidence_refs: [],
    },
    {
      sequence: 2,
      stage: "chunks_persisted",
      label: "Chunks persisted",
      detail: "Persisted 823 canonical chunks.",
      status: "succeeded",
      progress: 65,
      occurred_at: "2026-05-24T07:01:00+00:00",
      source: "structured_event",
      job_id: "job-1",
      chunk_count: 823,
      warning: null,
      evidence_refs: [{ kind: "parse_evidence", href: "/document-evidence?documentId=doc-1" }],
    },
    {
      sequence: 3,
      stage: "ready_with_warnings",
      label: "Ready with warnings",
      detail: "Indexed 823 chunks with warnings.",
      status: "succeeded",
      progress: 100,
      occurred_at: "2026-05-24T07:02:00+00:00",
      source: "structured_event",
      job_id: "job-1",
      chunk_count: 823,
      warning: "reference_unit_unresolved=820",
      evidence_refs: [],
    },
  ],
};

describe("DocumentPipelineTimeline", () => {
  it("renders document stage flow and totals", () => {
    render(<DocumentPipelineTimeline timeline={timeline} />);

    expect(screen.getByRole("region", { name: "Document pipeline timeline" })).toBeVisible();
    expect(screen.getByText("policy.pdf")).toBeVisible();
    expect(screen.getByText("823 chunks")).toBeVisible();
    expect(screen.getByText("3 graph nodes")).toBeVisible();
    expect(screen.getByText("Chunks persisted")).toBeVisible();
    expect(screen.getByText("Ready with warnings")).toBeVisible();
    expect(screen.getByText("reference_unit_unresolved=820")).toBeVisible();
  });

  it("marks inferred events explicitly", () => {
    render(
      <DocumentPipelineTimeline
        timeline={{
          ...timeline,
          events: [{ ...timeline.events[1], source: "inferred_log" }],
        }}
      />,
    );

    const row = screen.getByRole("listitem", { name: /chunks persisted/i });
    expect(within(row).getByText("inferred from log")).toBeVisible();
  });
});
```

- [ ] **Step 2: Run component test and confirm failure**

Run: `cd frontend; npx.cmd vitest run tests/document-pipeline-timeline.test.tsx`

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement component**

Create `frontend/src/features/document-evidence/document-pipeline-timeline.tsx`:

```tsx
import { AlertTriangle, CheckCircle2, Circle, Clock, Database, GitBranch } from "lucide-react";

import type { DocumentPipelineEventOut, DocumentPipelineTimelineOut } from "../../api/generated";

export function DocumentPipelineTimeline({ timeline }: { timeline: DocumentPipelineTimelineOut }) {
  return (
    <section
      className="rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] p-4"
      aria-label="Document pipeline timeline"
    >
      <div className="flex flex-col gap-3 border-b border-[var(--rs-line)] pb-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h2 className="truncate text-base font-semibold text-[var(--rs-ink)]">
            Pipeline path
          </h2>
          <p className="mt-1 truncate text-sm text-[var(--rs-text)]">{timeline.filename}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs font-medium text-[var(--rs-text)]">
          <Metric value={`${timeline.totals.jobs ?? 0} jobs`} />
          <Metric value={`${timeline.totals.chunks ?? 0} chunks`} />
          <Metric value={`${timeline.totals.warnings ?? 0} warnings`} tone="warning" />
          <Metric value={`${timeline.totals.graph_nodes ?? 0} graph nodes`} />
        </div>
      </div>

      {timeline.events.length ? (
        <ol className="mt-4 grid gap-3">
          {timeline.events.map((event) => (
            <PipelineEventRow key={`${event.sequence}-${event.stage}-${event.job_id ?? "document"}`} event={event} />
          ))}
        </ol>
      ) : (
        <p className="mt-4 text-sm text-[var(--rs-muted)]">No pipeline events are recorded for this document.</p>
      )}
    </section>
  );
}

function PipelineEventRow({ event }: { event: DocumentPipelineEventOut }) {
  const Icon = iconForEvent(event);
  return (
    <li
      className="grid gap-3 rounded-md border border-[var(--rs-line)] bg-[var(--rs-field)] p-3 sm:grid-cols-[auto_minmax(0,1fr)_auto]"
      aria-label={`${event.label} pipeline event`}
    >
      <span className="flex h-8 w-8 items-center justify-center rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)]">
        <Icon className="h-4 w-4 text-[var(--rs-accent)]" aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-semibold text-[var(--rs-ink)]">{event.label}</p>
          <span className="rounded-md border border-[var(--rs-line)] px-2 py-0.5 text-xs text-[var(--rs-muted)]">
            {sourceLabel(event.source)}
          </span>
          {event.chunk_count !== null ? (
            <span className="rounded-md border border-[var(--rs-line)] px-2 py-0.5 text-xs text-[var(--rs-text)]">
              {event.chunk_count} chunks
            </span>
          ) : null}
        </div>
        <p className="mt-1 break-words text-sm text-[var(--rs-text)]">{event.detail}</p>
        {event.warning ? (
          <p className="mt-2 inline-flex max-w-full rounded-md border border-[#e2c46b] bg-[#fff8df] px-2 py-1 text-xs font-medium text-[#705000]">
            {event.warning}
          </p>
        ) : null}
      </div>
      <div className="text-xs text-[var(--rs-muted)]">
        <p>{event.progress !== null ? `${event.progress}%` : "no progress"}</p>
        <p>{event.occurred_at ? formatDateTime(event.occurred_at) : "time unavailable"}</p>
      </div>
    </li>
  );
}

function Metric({ value, tone = "neutral" }: { value: string; tone?: "neutral" | "warning" }) {
  return (
    <span
      className={
        tone === "warning"
          ? "rounded-md border border-[#e2c46b] bg-[#fff8df] px-2 py-1 text-[#705000]"
          : "rounded-md border border-[var(--rs-line)] bg-[var(--rs-field)] px-2 py-1"
      }
    >
      {value}
    </span>
  );
}

function iconForEvent(event: DocumentPipelineEventOut) {
  if (event.warning || event.stage === "ready_with_warnings") {
    return AlertTriangle;
  }
  if (event.stage.includes("graph")) {
    return GitBranch;
  }
  if (event.stage.includes("chunk") || event.stage.includes("runtime")) {
    return Database;
  }
  if (event.stage === "ready") {
    return CheckCircle2;
  }
  if (event.status === "running" || event.progress !== null && event.progress < 100) {
    return Clock;
  }
  return Circle;
}

function sourceLabel(source: DocumentPipelineEventOut["source"]) {
  if (source === "structured_event") {
    return "structured";
  }
  if (source === "inferred_log") {
    return "inferred from log";
  }
  return source.replaceAll("_", " ");
}

function formatDateTime(value: string) {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(timestamp);
}
```

- [ ] **Step 4: Run component tests**

Run: `cd frontend; npx.cmd vitest run tests/document-pipeline-timeline.test.tsx`

Expected: PASS.

### Task 7: Evidence Page Integration

**Files:**
- Modify: `frontend/src/features/document-evidence/document-evidence-page.tsx`
- Modify: `frontend/tests/document-evidence-page.test.tsx`

- [ ] **Step 1: Add page tests**

Add or update `frontend/tests/document-evidence-page.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { apiClient } from "../src/api/client";
import { DocumentEvidencePage } from "../src/features/document-evidence/document-evidence-page";

vi.mock("../src/api/client", () => ({
  apiClient: {
    documentParseEvidence: vi.fn(),
    documentPipelineTimeline: vi.fn(),
  },
}));

vi.mock("../src/features/document-evidence/evidence-inspector", () => ({
  EvidenceInspector: () => <section aria-label="Parse evidence">Parse evidence loaded</section>,
}));

function renderPage(url = "http://localhost/document-evidence?documentId=doc-1") {
  window.history.pushState(null, "", url);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DocumentEvidencePage />
    </QueryClientProvider>,
  );
}

it("loads pipeline timeline with parse evidence", async () => {
  vi.mocked(apiClient.documentParseEvidence).mockResolvedValue({
    document: { id: "doc-1", filename: "policy.pdf", status: "succeeded" },
    totals: { chunks: 0, parser_blocks: 0, warnings: 0 },
    parser_blocks: [],
    chunks: [],
    warnings: [],
    normalization_decisions: [],
    source_artifacts: [],
    proof: { redaction_summary: [] },
  } as never);
  vi.mocked(apiClient.documentPipelineTimeline).mockResolvedValue({
    document_id: "doc-1",
    filename: "policy.pdf",
    status: "succeeded",
    latest_job_id: "job-1",
    jobs: [],
    totals: { jobs: 1, chunks: 823, warnings: 0, graph_nodes: 3, graph_edges: 0 },
    events: [
      {
        sequence: 1,
        stage: "uploaded",
        label: "Uploaded",
        detail: "Stored source artifact for policy.pdf.",
        status: "succeeded",
        progress: 0,
        occurred_at: "2026-05-24T07:00:00+00:00",
        source: "document",
        job_id: null,
        chunk_count: null,
        warning: null,
        evidence_refs: [],
      },
    ],
  });

  renderPage();

  expect(await screen.findByRole("region", { name: "Document pipeline timeline" })).toBeVisible();
  expect(apiClient.documentPipelineTimeline).toHaveBeenCalledWith("doc-1");
  expect(apiClient.documentParseEvidence).toHaveBeenCalledWith("doc-1");
});
```

- [ ] **Step 2: Run page test and confirm failure**

Run: `cd frontend; npx.cmd vitest run tests/document-evidence-page.test.tsx`

Expected: FAIL because the page does not request `documentPipelineTimeline`.

- [ ] **Step 3: Integrate query and component**

In `frontend/src/features/document-evidence/document-evidence-page.tsx`, import:

```tsx
import { DocumentPipelineTimeline } from "./document-pipeline-timeline";
```

Add query:

```tsx
const timelineQuery = useQuery({
  queryKey: ["document-pipeline-timeline", documentId],
  queryFn: () => apiClient.documentPipelineTimeline(documentId),
  enabled: documentId.length > 0,
});
```

Render above `EvidenceInspector`:

```tsx
{timelineQuery.data ? (
  <DocumentPipelineTimeline timeline={timelineQuery.data} />
) : timelineQuery.isError ? (
  <section className="rounded-md border border-[#e5c36b] bg-[#fff8e6] p-4" role="alert">
    <p className="text-sm font-semibold text-[#5f4600]">Pipeline timeline unavailable</p>
    <p className="mt-1 text-sm text-[#705300]">
      {timelineQuery.error instanceof Error ? timelineQuery.error.message : "Timeline could not be loaded."}
    </p>
  </section>
) : null}
```

- [ ] **Step 4: Run frontend tests**

Run: `cd frontend; npx.cmd vitest run tests/document-pipeline-timeline.test.tsx tests/document-evidence-page.test.tsx tests/api-client.test.ts`

Expected: PASS.

### Task 8: Verification And Documentation

**Files:**
- Modify: `docs/superpowers/plans/2026-05-24-document-pipeline-stage-timeline.md`

- [ ] **Step 1: Backend verification**

Run: `pytest backend/tests/test_document_pipeline_timeline.py backend/tests/test_index_progress.py backend/tests/test_job_queue_service.py backend/tests/test_jobs.py -q`

Expected: PASS.

- [ ] **Step 2: Frontend verification**

Run: `cd frontend; npx.cmd vitest run tests/document-pipeline-timeline.test.tsx tests/document-evidence-page.test.tsx tests/documents-page.test.tsx tests/api-client.test.ts`

Expected: PASS.

- [ ] **Step 3: Generate OpenAPI and check generated client alignment**

Run: `bash scripts/generate-openapi.sh`

Expected: OpenAPI generation succeeds and includes `/api/documents/{document_id}/pipeline-timeline`.

- [ ] **Step 4: Manual runtime check**

With the development stack running, open:

`http://127.0.0.1:5173/document-evidence?documentId=b84e2c0b-5f2b-474e-a1cf-43e1dd58392a`

Expected visible facts:

- Pipeline path panel appears above parse evidence.
- It shows upload, queue, MinerU validation, chunk persistence, search readiness, runtime enrichment, graph enrichment, and ready-with-warnings events when the latest job has those records.
- The ready-with-warnings stage shows parser quality warning context instead of hiding it in the Jobs tab only.
- Existing Evidence Inspector still renders parser blocks, warnings, chunks, source artifacts, and proof metadata.

---

## Self-Review

Spec coverage:

- The plan answers whether this already exists: yes, structured job stages exist, but only under jobs/SSE and not as a unified document Evidence-page timeline.
- It adds a document-level timeline API rather than duplicating the Jobs table.
- It preserves existing `indexing_stage_events` as the primary source and marks old log-derived rows as inferred.
- It adds queue and worker-claim structured events so the beginning of the path is no longer only a log string.
- It connects stages to evidence refs so the UI can explain where events happened and where to inspect supporting data.

Design limitations made explicit:

- Historical logs without structured `occurred_at` cannot be reconstructed exactly. They are displayed as inferred with job `updated_at`.
- `indexing_stage_events` are capped at 100 by current policy. This is acceptable for the current timeline because batch chunk persistence events are bounded, but future very chatty stages should summarize progress instead of emitting one event per chunk.
- This plan does not add a new `job_stage_events` table because the current architecture already committed to `Job.result` JSON for first-pass durable ingestion stages. A table can be justified later only if retention, querying, or analytics exceed the JSON event contract.

Placeholder scan:

- No placeholder tasks are included.
- Every new file has an explicit contract or component snippet.
- Every verification step includes an exact command and expected result.
