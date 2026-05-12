# Durable RAG Indexing Worker Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Ragstudio document indexing, runtime enrichment, and graph projection out of the FastAPI request process into a durable worker that can recover after backend reloads or restarts without leaving jobs stuck at `running` or graph projections stuck at `pending`.

**Architecture:** The web backend becomes an API and health surface only: it persists job options, returns job ids, and never owns long-running RAG work. A separate worker process claims jobs from Postgres with leases, heartbeats while MinerU, LightRAG, pgvector, and Neo4j work runs, and resumes graph projection from persisted chunks when a restart happens after search readiness. Retrieval quality remains tied to the current Ragstudio architecture: Postgres plus pgvector remains source of truth for chunks and vector metadata, Neo4j remains a rebuildable graph projection, and every indexing path records enough metadata for hybrid retrieval and evaluation.

**Tech Stack:** FastAPI, SQLAlchemy async, PostgreSQL with pgvector and `FOR UPDATE SKIP LOCKED`, Neo4j, Docker Compose, pytest, RAG-Anything, MinerU, Ragstudio `DocumentService`, `GraphProjectionRunner`, `IndexLifecycleService`.

---

## RAG Architecture Context

The `rag-architect` constraints apply to this change:

- **Vector store design:** keep Postgres/pgvector as the transactional source for documents, chunks, index records, and job leases. Keep Neo4j as a derived projection that can be deleted and rebuilt.
- **Chunking strategy:** preserve MinerU strict parsing, `ChunkSplitter`, `MinerURelationshipBuilder`, `source_location`, `metadata_json`, `text_search_ar`, and `tokens_ar`. Do not add a new chunker in this plan.
- **Retrieval pipeline:** preserve hybrid retrieval: metadata filters for document scope, lexical/token search, pgvector runtime search, graph expansion only when projection is succeeded, and reranker settings from `SettingsProfile`.
- **Evaluation:** add durable run metadata that lets retrieval evaluation compare chunk count, parser quality, runtime profile, embedding dimensions, graph readiness, and latency across indexing attempts.

```mermaid
flowchart LR
  UI["Frontend"] --> API["FastAPI backend"]
  API --> Queue["Postgres jobs table"]
  Worker["ragstudio-worker"] --> Queue
  Worker --> MinerU["MinerU parser"]
  Worker --> Canonical["Postgres chunks and index_records"]
  Worker --> Runtime["RAG-Anything pgvector runtime"]
  Worker --> Graph["Neo4j graph projection"]
  Query["Query API"] --> Canonical
  Query --> Runtime
  Query --> Graph
  Diagnostics["Diagnostics API"] --> Queue
  Diagnostics --> Graph
```

## File Structure

- Modify `backend/src/ragstudio/db/models.py`
  - Add durable job lease fields and indexing metadata fields to `Job`.
- Modify `backend/src/ragstudio/db/engine.py`
  - Backfill new job columns on existing databases.
- Create `backend/src/ragstudio/services/job_queue_service.py`
  - Own enqueue, claim, heartbeat, completion, failure, stale recovery, and graph-resume markers.
- Create `backend/src/ragstudio/services/index_job_runner.py`
  - Own one claimed `index_document` job execution. Use `DocumentService.run_index_job()` for full indexing and `GraphProjectionRunner.materialize_pending()` for graph-only resume.
- Create `backend/src/ragstudio/workers/__init__.py`
  - Package marker for worker modules.
- Create `backend/src/ragstudio/workers/index_worker.py`
  - Long-running worker loop for Docker Compose and local CLI.
- Modify `backend/src/ragstudio/services/document_service.py`
  - Persist index options when creating jobs and stop assuming the caller holds options in memory.
- Modify `backend/src/ragstudio/api/routes/documents.py`
  - Enqueue only. Remove `create_background_task()` usage from upload/reindex routes.
- Modify `backend/src/ragstudio/services/diagnostics_service.py`
  - Report stale job count, pending graph projection count, and worker lease health.
- Modify `docker-compose.yml`
  - Add a `worker` service using the backend image.
- Create `backend/tests/test_job_queue_service.py`
  - Unit/integration tests for enqueue, claim, heartbeat, stale recovery, and option persistence.
- Create `backend/tests/test_index_worker_recovery.py`
  - Tests for graph-only resume and interrupted job recovery.
- Modify `backend/tests/test_documents.py`
  - Update upload/reindex tests to assert durable enqueue behavior instead of in-process background tasks.
- Modify `backend/tests/test_mineru_reindex_jobs.py`
  - Add job metadata assertions and runner-level tests for final job state.
- Modify `backend/tests/test_db_engine.py`
  - Verify new columns are added to existing `jobs` tables.
- Create `docs/architecture/durable-rag-indexing.md`
  - User-facing architecture note with ingestion/retrieval diagram, vector-store tradeoffs, chunking strategy, retrieval flow, and evaluation thresholds.

---

### Task 1: Persist Durable Job Metadata

**Files:**
- Modify: `backend/src/ragstudio/db/models.py`
- Modify: `backend/src/ragstudio/db/engine.py`
- Test: `backend/tests/test_db_engine.py`

- [ ] **Step 1: Write failing migration test**

Add this test to `backend/tests/test_db_engine.py`:

```python
async def test_init_db_adds_durable_job_worker_columns(database_url):
    engine = make_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                CREATE TABLE jobs (
                    id VARCHAR PRIMARY KEY,
                    type VARCHAR NOT NULL,
                    status VARCHAR NOT NULL,
                    target_id VARCHAR,
                    progress INTEGER NOT NULL,
                    logs JSONB NOT NULL,
                    result JSONB NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO jobs (
                    id, type, status, target_id, progress, logs, result, created_at, updated_at
                )
                VALUES (
                    'job-1',
                    'index_document',
                    'running',
                    'doc-1',
                    75,
                    '["Search ready"]',
                    '{"indexing_stage":{"stage":"search_ready"}}',
                    now(),
                    now()
                )
                """
            )
        )

    await init_db(engine)

    async with engine.begin() as connection:
        columns = {
            column["name"]
            for column in inspect(connection.sync_connection).get_columns("jobs")
        }
        row = (
            await connection.execute(
                text(
                    """
                    SELECT worker_id,
                           lease_expires_at,
                           heartbeat_at,
                           attempts,
                           max_attempts,
                           available_at,
                           job_options,
                           recovery_action
                    FROM jobs
                    WHERE id = 'job-1'
                    """
                )
            )
        ).mappings().one()

    await engine.dispose()

    assert {
        "worker_id",
        "lease_expires_at",
        "heartbeat_at",
        "attempts",
        "max_attempts",
        "available_at",
        "job_options",
        "recovery_action",
    }.issubset(columns)
    assert row["worker_id"] is None
    assert row["lease_expires_at"] is None
    assert row["heartbeat_at"] is None
    assert row["attempts"] == 0
    assert row["max_attempts"] == 3
    assert row["available_at"] is not None
    assert row["job_options"] == {}
    assert row["recovery_action"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./.venv/bin/pytest backend/tests/test_db_engine.py::test_init_db_adds_durable_job_worker_columns -q
```

Expected: FAIL because the `jobs` table does not have the durable worker columns.

- [ ] **Step 3: Add model columns**

In `backend/src/ragstudio/db/models.py`, extend `Job`:

```python
class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "uq_active_index_document_job",
            "target_id",
            unique=True,
            sqlite_where=text(
                "type = 'index_document' AND status IN ('ready', 'running') "
                "AND target_id IS NOT NULL"
            ),
            postgresql_where=text(
                "type = 'index_document' AND status IN ('ready', 'running') "
                "AND target_id IS NOT NULL"
            ),
        ),
        Index("ix_jobs_claimable", "type", "status", "available_at"),
        Index("ix_jobs_lease_expires_at", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ready")
    target_id: Mapped[str | None] = mapped_column(String, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    logs: Mapped[list[str]] = mapped_column(JsonListType, default=list)
    result: Mapped[dict[str, Any]] = mapped_column(JsonDictType, default=dict)
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    job_options: Mapped[dict[str, Any]] = mapped_column(JsonDictType, default=dict)
    recovery_action: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4: Add init-time migration**

In `backend/src/ragstudio/db/engine.py`, inside `_ensure_runtime_columns()`, add:

```python
    if "jobs" in table_names:
        _ensure_columns(
            connection,
            inspector,
            "jobs",
            {
                "worker_id": "VARCHAR",
                "lease_expires_at": _datetime_column(connection),
                "heartbeat_at": _datetime_column(connection),
                "attempts": "INTEGER DEFAULT 0 NOT NULL",
                "max_attempts": "INTEGER DEFAULT 3 NOT NULL",
                "available_at": _datetime_column(connection),
                "job_options": _json_object_column(connection),
                "recovery_action": "VARCHAR",
            },
        )
        connection.execute(
            text(
                """
                UPDATE jobs
                SET attempts = COALESCE(attempts, 0),
                    max_attempts = COALESCE(max_attempts, 3),
                    available_at = COALESCE(available_at, updated_at, created_at, now()),
                    job_options = COALESCE(job_options, CAST('{}' AS JSONB))
                WHERE attempts IS NULL
                   OR max_attempts IS NULL
                   OR available_at IS NULL
                   OR job_options IS NULL
                """
            )
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
./.venv/bin/pytest backend/tests/test_db_engine.py::test_init_db_adds_durable_job_worker_columns -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/db/models.py backend/src/ragstudio/db/engine.py backend/tests/test_db_engine.py
git commit -m "feat: add durable job lease metadata"
```

---

### Task 2: Add Durable Job Queue Service

**Files:**
- Create: `backend/src/ragstudio/services/job_queue_service.py`
- Test: `backend/tests/test_job_queue_service.py`

- [ ] **Step 1: Write failing queue tests**

Create `backend/tests/test_job_queue_service.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from ragstudio.db.models import Job
from ragstudio.schemas.common import StageStatus
from ragstudio.services.job_queue_service import JobQueueService
from sqlalchemy import select


@pytest.mark.asyncio
async def test_enqueue_persists_index_options(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        queue = JobQueueService(session)
        job = await queue.enqueue_index_document(
            document_id="doc-1",
            options={
                "parser_mode": "mineru_strict",
                "domain_metadata": {"domain": "quran", "tags": ["arabic"]},
            },
        )
        await session.commit()

        refreshed = await session.get(Job, job.id)

    assert refreshed is not None
    assert refreshed.type == "index_document"
    assert refreshed.target_id == "doc-1"
    assert refreshed.status == StageStatus.READY.value
    assert refreshed.job_options == {
        "parser_mode": "mineru_strict",
        "domain_metadata": {"domain": "quran", "tags": ["arabic"]},
    }
    assert refreshed.result["index_options"] == refreshed.job_options


@pytest.mark.asyncio
async def test_claim_next_sets_lease_and_worker_id(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        queue = JobQueueService(session)
        await queue.enqueue_index_document(
            document_id="doc-1",
            options={"parser_mode": "mineru_strict", "domain_metadata": {}},
        )
        await session.commit()

    async with app.state.session_factory() as session:
        claimed = await JobQueueService(session).claim_next(
            worker_id="worker-a",
            job_types=["index_document"],
            lease_seconds=120,
        )
        await session.commit()

    assert claimed is not None
    assert claimed.status == StageStatus.RUNNING.value
    assert claimed.worker_id == "worker-a"
    assert claimed.lease_expires_at is not None
    assert claimed.heartbeat_at is not None
    assert claimed.attempts == 1
    assert claimed.logs[-1] == "Worker worker-a claimed job."


@pytest.mark.asyncio
async def test_recover_expired_running_job_marks_graph_resume(client):
    app = client._transport.app
    expired = datetime.now(UTC) - timedelta(minutes=10)
    async with app.state.session_factory() as session:
        session.add(
            Job(
                id="job-expired",
                type="index_document",
                target_id="doc-1",
                status=StageStatus.RUNNING.value,
                progress=75,
                logs=["Search ready: Lexical and metadata retrieval are ready."],
                result={"indexing_stage": {"stage": "search_ready"}},
                job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                worker_id="worker-old",
                lease_expires_at=expired,
                heartbeat_at=expired,
                attempts=1,
            )
        )
        await session.commit()

    async with app.state.session_factory() as session:
        recovered = await JobQueueService(session).recover_expired_jobs(now=expired + timedelta(minutes=11))
        await session.commit()
        job = await session.get(Job, "job-expired")

    assert recovered == 1
    assert job.status == StageStatus.READY.value
    assert job.worker_id is None
    assert job.lease_expires_at is None
    assert job.recovery_action == "resume_graph_projection"
    assert job.logs[-1] == "Recovered expired worker lease; graph projection will resume from persisted chunks."
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
./.venv/bin/pytest backend/tests/test_job_queue_service.py -q
```

Expected: FAIL because `JobQueueService` does not exist.

- [ ] **Step 3: Implement `JobQueueService`**

Create `backend/src/ragstudio/services/job_queue_service.py`:

```python
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from ragstudio.db.models import Job
from ragstudio.schemas.common import StageStatus, new_id, now_utc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class JobQueueService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def enqueue_index_document(
        self,
        *,
        document_id: str,
        options: dict[str, Any],
    ) -> Job:
        job = Job(
            id=new_id(),
            type="index_document",
            target_id=document_id,
            status=StageStatus.READY.value,
            progress=0,
            logs=["Indexing queued."],
            result={"document_id": document_id, "index_options": options},
            job_options=options,
            max_attempts=3,
            available_at=now_utc(),
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def claim_next(
        self,
        *,
        worker_id: str,
        job_types: Sequence[str],
        lease_seconds: int = 300,
    ) -> Job | None:
        now = now_utc()
        statement = (
            select(Job)
            .where(
                Job.type.in_(list(job_types)),
                Job.status == StageStatus.READY.value,
                Job.available_at <= now,
                Job.attempts < Job.max_attempts,
            )
            .order_by(Job.created_at.asc(), Job.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job = await self.session.scalar(statement)
        if job is None:
            return None
        job.status = StageStatus.RUNNING.value
        job.worker_id = worker_id
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.attempts += 1
        job.logs = [*(job.logs or []), f"Worker {worker_id} claimed job."][-20:]
        await self.session.flush()
        return job

    async def heartbeat(
        self,
        job: Job,
        *,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> None:
        if job.worker_id != worker_id:
            raise RuntimeError(f"Job {job.id} is leased by {job.worker_id}, not {worker_id}.")
        now = now_utc()
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        await self.session.flush()

    async def mark_succeeded(self, job: Job, *, log: str, result_patch: dict[str, Any]) -> None:
        job.status = StageStatus.SUCCEEDED.value
        job.progress = 100
        job.worker_id = None
        job.lease_expires_at = None
        job.heartbeat_at = now_utc()
        job.recovery_action = None
        job.logs = [*(job.logs or []), log][-20:]
        job.result = {**(job.result or {}), **result_patch}
        await self.session.flush()

    async def mark_failed(self, job: Job, *, reason: str) -> None:
        job.status = StageStatus.FAILED.value
        job.progress = 100
        job.worker_id = None
        job.lease_expires_at = None
        job.heartbeat_at = now_utc()
        job.logs = [*(job.logs or []), reason][-20:]
        job.result = {**(job.result or {}), "error": reason}
        await self.session.flush()

    async def recover_expired_jobs(self, *, now: datetime | None = None) -> int:
        timestamp = now or datetime.now(UTC)
        result = await self.session.execute(
            select(Job)
            .where(
                Job.status == StageStatus.RUNNING.value,
                Job.lease_expires_at.is_not(None),
                Job.lease_expires_at < timestamp,
            )
            .with_for_update(skip_locked=True)
        )
        recovered = 0
        for job in result.scalars().all():
            stage = (job.result or {}).get("indexing_stage")
            stage_name = stage.get("stage") if isinstance(stage, dict) else None
            job.status = StageStatus.READY.value
            job.worker_id = None
            job.lease_expires_at = None
            job.heartbeat_at = timestamp
            if stage_name in {"search_ready", "graph_enriching"}:
                job.recovery_action = "resume_graph_projection"
                message = (
                    "Recovered expired worker lease; graph projection will resume from "
                    "persisted chunks."
                )
            else:
                job.recovery_action = "retry_full_index"
                message = "Recovered expired worker lease; full indexing will retry."
            job.logs = [*(job.logs or []), message][-20:]
            recovered += 1
        await self.session.flush()
        return recovered
```

- [ ] **Step 4: Run queue tests**

Run:

```bash
./.venv/bin/pytest backend/tests/test_job_queue_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/job_queue_service.py backend/tests/test_job_queue_service.py
git commit -m "feat: add durable job queue service"
```

---

### Task 3: Persist Index Options From DocumentService

**Files:**
- Modify: `backend/src/ragstudio/services/document_service.py`
- Modify: `backend/src/ragstudio/services/job_worker.py`
- Test: `backend/tests/test_documents.py`

- [ ] **Step 1: Write failing API enqueue test**

Add this test near the existing upload/reindex tests in `backend/tests/test_documents.py`:

```python
@pytest.mark.asyncio
async def test_reindex_persists_job_options_for_worker(client, tmp_path, monkeypatch):
    await seed_product_runtime_profile(client)
    allow_product_readiness(monkeypatch)
    app = client._transport.app
    artifact = tmp_path / "uploads" / "durable-worker-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with app.state.session_factory() as session:
        document = Document(
            filename="worker-quran.pdf",
            content_type="application/pdf",
            sha256="durable-worker-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.commit()
        document_id = document.id

    response = await client.post(
        f"/api/documents/{document_id}/reindex",
        json={
            "parser_mode": "mineru_strict",
            "domain_metadata": {"domain": "quran", "tags": ["arabic"]},
        },
    )

    assert response.status_code == 202
    async with app.state.session_factory() as session:
        job = await session.get(Job, response.json()["job_id"])

    assert job is not None
    assert job.status == StageStatus.READY.value
    assert job.job_options == {
        "parser_mode": "mineru_strict",
        "domain_metadata": {"domain": "quran", "tags": ["arabic"]},
    }
    assert job.result["index_options"] == job.job_options
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./.venv/bin/pytest backend/tests/test_documents.py::test_reindex_persists_job_options_for_worker -q
```

Expected: FAIL because `create_index_job()` does not persist options into `Job.job_options`.

- [ ] **Step 3: Update `JobWorker.build()`**

In `backend/src/ragstudio/services/job_worker.py`, replace `build()` with:

```python
    @staticmethod
    def build(
        job_type: str,
        target_id: str | None,
        *,
        options: dict[str, object] | None = None,
    ) -> Job:
        job_options = dict(options or {})
        result = {"index_options": job_options} if job_options else {}
        return Job(
            id=new_id(),
            type=job_type,
            target_id=target_id,
            status=StageStatus.READY.value,
            progress=0,
            logs=[],
            result=result,
            job_options=job_options,
        )
```

- [ ] **Step 4: Update DocumentService job creation**

In `backend/src/ragstudio/services/document_service.py`, add this helper near `_parser_quality_warning()`:

```python
    def _job_options_payload(self, options: IndexDocumentIn | None) -> dict[str, Any]:
        effective = options or IndexDocumentIn()
        return effective.model_dump(mode="json", exclude_none=True)
```

Change `create_index_job()` and `_enqueue_index_job()` signatures:

```python
    async def create_index_job(
        self,
        document_id: str,
        options: IndexDocumentIn | None = None,
    ) -> Job | None:
        await self.lock_document_workflow(document_id)
        document = await self.session.get(Document, document_id)
        if document is None:
            return None
        if await self.active_index_job(document_id) is not None:
            raise ActiveIndexJobError("Document already has an active indexing job")
        return await self._enqueue_index_job(document, options)

    async def _enqueue_index_job(
        self,
        document: Document,
        options: IndexDocumentIn | None = None,
    ) -> Job:
        job = JobWorker.build(
            "index_document",
            document.id,
            options=self._job_options_payload(options),
        )
        self.session.add(job)
        document.status = StageStatus.RUNNING.value
        self.queued_index_job_id = job.id
        job.logs = [*(job.logs or []), "Indexing queued."]
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ActiveIndexJobError("Document already has an active indexing job") from exc
        await self.session.refresh(document)
        await self.session.refresh(job)
        return job
```

Update callers:

```python
await self._enqueue_index_job(document, options)
job = await service.create_index_job(document_id, options)
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
./.venv/bin/pytest backend/tests/test_documents.py::test_reindex_persists_job_options_for_worker -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/document_service.py backend/src/ragstudio/services/job_worker.py backend/tests/test_documents.py
git commit -m "feat: persist index options with jobs"
```

---

### Task 4: Move Upload And Reindex To Queue-Only API

**Files:**
- Modify: `backend/src/ragstudio/api/routes/documents.py`
- Modify: `backend/src/ragstudio/api/background.py`
- Test: `backend/tests/test_documents.py`

- [ ] **Step 1: Write failing no-background-task test**

Add this test to `backend/tests/test_documents.py`:

```python
@pytest.mark.asyncio
async def test_reindex_does_not_schedule_in_process_background_task(client, tmp_path, monkeypatch):
    await seed_product_runtime_profile(client)
    allow_product_readiness(monkeypatch)
    app = client._transport.app
    artifact = tmp_path / "uploads" / "no-background-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with app.state.session_factory() as session:
        document = Document(
            filename="no-background.pdf",
            content_type="application/pdf",
            sha256="no-background-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.commit()
        document_id = document.id

    called = False

    def fail_background_task(app, coroutine):
        nonlocal called
        called = True
        coroutine.close()
        raise AssertionError("route must not create an in-process indexing task")

    monkeypatch.setattr("ragstudio.api.routes.documents.create_background_task", fail_background_task)

    response = await client.post(
        f"/api/documents/{document_id}/reindex",
        json={"parser_mode": "mineru_strict", "domain_metadata": {}},
    )

    assert response.status_code == 202
    assert called is False
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./.venv/bin/pytest backend/tests/test_documents.py::test_reindex_does_not_schedule_in_process_background_task -q
```

Expected: FAIL because the route calls `create_background_task()`.

- [ ] **Step 3: Remove in-process scheduling from routes**

In `backend/src/ragstudio/api/routes/documents.py`, remove imports:

```python
import asyncio
import logging
from ragstudio.api.background import create_background_task
from ragstudio.db.engine import make_engine, make_session_factory
```

Delete `_run_index_job()` and `_mark_background_index_failed()` from this route module.

In `upload_document()`, replace the scheduling block:

```python
        return document
```

In `reindex_document()`, replace job creation and scheduling with:

```python
        try:
            job = await service.create_index_job(document_id, options)
        except ActiveIndexJobError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if job is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"document_id": document_id, "job_id": job.id, "status": job.status}
```

In `upload_document()`, keep returning the document. The UI can poll `/api/jobs`; the worker will claim the job.

- [ ] **Step 4: Keep `api/background.py` but mark it unused**

Leave `backend/src/ragstudio/api/background.py` in place for compatibility during this task. Do not delete it until a later cleanup confirms no imports remain:

```bash
rg "create_background_task" backend/src backend/tests
```

Expected after route edits: no references in runtime code.

- [ ] **Step 5: Run route tests**

Run:

```bash
./.venv/bin/pytest backend/tests/test_documents.py::test_reindex_does_not_schedule_in_process_background_task backend/tests/test_documents.py::test_reindex_persists_job_options_for_worker -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/api/routes/documents.py backend/tests/test_documents.py
git commit -m "feat: enqueue indexing without in-process background tasks"
```

---

### Task 5: Add Index Job Runner With Graph-Only Resume

**Files:**
- Create: `backend/src/ragstudio/services/index_job_runner.py`
- Test: `backend/tests/test_index_worker_recovery.py`

- [ ] **Step 1: Write failing graph-resume test**

Create `backend/tests/test_index_worker_recovery.py`:

```python
from pathlib import Path

import pytest
from ragstudio.db.models import Chunk, Document, GraphProjectionRecord, Job, SettingsProfile
from ragstudio.schemas.common import StageStatus
from ragstudio.services.index_job_runner import IndexJobRunner
from sqlalchemy import select


class FakeGraphProjectionRunner:
    def __init__(self, session, settings):
        self.session = session
        self.settings = settings

    async def materialize_pending(self, document_id: str):
        record = await self.session.scalar(
            select(GraphProjectionRecord).where(
                GraphProjectionRecord.document_id == document_id,
                GraphProjectionRecord.status == "pending",
            )
        )
        record.status = "succeeded"
        record.node_count = 2
        record.edge_count = 1
        return {"status": "succeeded", "node_count": 2, "edge_count": 1, "reason": None}


@pytest.mark.asyncio
async def test_index_job_runner_resumes_graph_projection_without_reindex(client, tmp_path, monkeypatch):
    app = client._transport.app
    artifact = tmp_path / "uploads" / "resume-graph-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="resume-graph.pdf",
            content_type="application/pdf",
            sha256="resume-graph-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="Quran 1:4",
                source_location={"page": 1},
                metadata_json={},
            )
        )
        session.add(
            GraphProjectionRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status="pending",
                node_count=0,
                edge_count=0,
            )
        )
        job = Job(
            id="job-resume-graph",
            type="index_document",
            target_id=document.id,
            status=StageStatus.RUNNING.value,
            progress=75,
            logs=["Search ready: Lexical and metadata retrieval are ready."],
            result={"indexing_stage": {"stage": "search_ready", "chunk_count": 1}},
            job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
            recovery_action="resume_graph_projection",
            worker_id="worker-a",
        )
        session.add(job)
        await session.commit()

    monkeypatch.setattr(
        "ragstudio.services.index_job_runner.GraphProjectionRunner",
        FakeGraphProjectionRunner,
    )

    async with app.state.session_factory() as session:
        job = await session.get(Job, "job-resume-graph")
        await IndexJobRunner(session, app.state.settings, worker_id="worker-a").run(job)
        await session.commit()
        refreshed = await session.get(Job, "job-resume-graph")

    assert refreshed.status == StageStatus.SUCCEEDED.value
    assert refreshed.progress == 100
    assert refreshed.recovery_action is None
    assert refreshed.result["graph_materialization"] == {
        "status": "succeeded",
        "node_count": 2,
        "edge_count": 1,
        "reason": None,
    }
    assert refreshed.result["indexing_stage"]["stage"] == "ready"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./.venv/bin/pytest backend/tests/test_index_worker_recovery.py::test_index_job_runner_resumes_graph_projection_without_reindex -q
```

Expected: FAIL because `IndexJobRunner` does not exist.

- [ ] **Step 3: Implement `IndexJobRunner`**

Create `backend/src/ragstudio/services/index_job_runner.py`:

```python
from __future__ import annotations

from typing import Any

from ragstudio.config import AppSettings
from ragstudio.db.models import Document, Job
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.document_service import DocumentService
from ragstudio.services.graph_projection_runner import GraphProjectionRunner
from ragstudio.services.index_progress import IndexStage, update_job_stage
from sqlalchemy.ext.asyncio import AsyncSession


class IndexJobRunner:
    def __init__(
        self,
        session: AsyncSession,
        settings: AppSettings,
        *,
        worker_id: str,
    ):
        self.session = session
        self.settings = settings
        self.worker_id = worker_id

    async def run(self, job: Job) -> None:
        if job.type != "index_document":
            raise RuntimeError(f"Unsupported job type: {job.type}")
        if job.target_id is None:
            raise RuntimeError(f"Index job {job.id} has no target document.")
        if job.recovery_action == "resume_graph_projection":
            await self._resume_graph_projection(job)
            return
        options = IndexDocumentIn.model_validate(job.job_options or {})
        await DocumentService(
            self.session,
            self.settings.data_dir,
            settings=self.settings,
        ).run_index_job(job.target_id, job.id, options)

    async def _resume_graph_projection(self, job: Job) -> None:
        document = await self.session.get(Document, job.target_id)
        if document is None:
            raise RuntimeError(f"Document {job.target_id} does not exist.")
        result = await GraphProjectionRunner(
            self.session,
            self.settings,
        ).materialize_pending(document.id)
        status = str(result.get("status") or "unknown")
        job.result = {
            **(job.result or {}),
            "document_id": document.id,
            "graph_materialization": result,
        }
        job.logs = [*(job.logs or []), f"Graph projection materialization {status}."][-20:]
        warning = self._graph_warning(result)
        stage = (job.result or {}).get("indexing_stage")
        chunk_count = stage.get("chunk_count") if isinstance(stage, dict) else None
        update_job_stage(
            job,
            IndexStage.READY_WITH_WARNINGS if warning else IndexStage.READY,
            detail=(
                f"Indexed {chunk_count} chunks with warnings."
                if warning and isinstance(chunk_count, int)
                else "Indexed chunks with warnings."
                if warning
                else f"Indexed {chunk_count} chunks."
                if isinstance(chunk_count, int)
                else "Indexed chunks."
            ),
            chunk_count=chunk_count if isinstance(chunk_count, int) else None,
            warning=warning,
        )
        document.status = StageStatus.SUCCEEDED.value
        job.status = StageStatus.SUCCEEDED.value
        job.progress = 100
        job.worker_id = None
        job.lease_expires_at = None
        job.recovery_action = None
        await self.session.flush()

    def _graph_warning(self, result: dict[str, Any]) -> str | None:
        status = result.get("status")
        if status not in {"failed", "skipped"}:
            return None
        return str(result.get("reason") or f"Graph materialization {status}.")
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
./.venv/bin/pytest backend/tests/test_index_worker_recovery.py::test_index_job_runner_resumes_graph_projection_without_reindex -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/index_job_runner.py backend/tests/test_index_worker_recovery.py
git commit -m "feat: resume graph projection from durable jobs"
```

---

### Task 6: Add Worker Process

**Files:**
- Create: `backend/src/ragstudio/workers/__init__.py`
- Create: `backend/src/ragstudio/workers/index_worker.py`
- Modify: `docker-compose.yml`
- Test: `backend/tests/test_index_worker_recovery.py`

- [ ] **Step 1: Write failing worker single-cycle test**

Add this test to `backend/tests/test_index_worker_recovery.py`:

```python
@pytest.mark.asyncio
async def test_worker_cycle_claims_and_runs_one_job(client, tmp_path, monkeypatch):
    app = client._transport.app
    artifact = tmp_path / "uploads" / "worker-cycle-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="worker-cycle.pdf",
            content_type="application/pdf",
            sha256="worker-cycle-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        job = Job(
            id="job-worker-cycle",
            type="index_document",
            target_id=document.id,
            status=StageStatus.READY.value,
            progress=0,
            logs=[],
            result={"index_options": {"parser_mode": "mineru_strict", "domain_metadata": {}}},
            job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
            recovery_action="resume_graph_projection",
        )
        session.add(job)
        await session.commit()

    ran = []

    class FakeIndexJobRunner:
        def __init__(self, session, settings, *, worker_id):
            self.session = session
            self.worker_id = worker_id

        async def run(self, job):
            ran.append(job.id)
            job.status = StageStatus.SUCCEEDED.value
            job.progress = 100
            job.worker_id = None
            job.lease_expires_at = None

    monkeypatch.setattr("ragstudio.workers.index_worker.IndexJobRunner", FakeIndexJobRunner)

    from ragstudio.workers.index_worker import run_once

    async with app.state.session_factory() as session:
        processed = await run_once(session, app.state.settings, worker_id="worker-test")
        await session.commit()

    assert processed == 1
    assert ran == ["job-worker-cycle"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./.venv/bin/pytest backend/tests/test_index_worker_recovery.py::test_worker_cycle_claims_and_runs_one_job -q
```

Expected: FAIL because `ragstudio.workers.index_worker` does not exist.

- [ ] **Step 3: Implement worker module**

Create empty package file:

```bash
touch backend/src/ragstudio/workers/__init__.py
```

Create `backend/src/ragstudio/workers/index_worker.py`:

```python
from __future__ import annotations

import asyncio
import logging
import os

from ragstudio.config import AppSettings
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Job
from ragstudio.services.index_job_runner import IndexJobRunner
from ragstudio.services.job_queue_service import JobQueueService
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def run_once(
    session: AsyncSession,
    settings: AppSettings,
    *,
    worker_id: str,
    lease_seconds: int = 300,
) -> int:
    queue = JobQueueService(session)
    await queue.recover_expired_jobs()
    job: Job | None = await queue.claim_next(
        worker_id=worker_id,
        job_types=["index_document"],
        lease_seconds=lease_seconds,
    )
    if job is None:
        await session.commit()
        return 0
    await session.commit()
    try:
        await IndexJobRunner(session, settings, worker_id=worker_id).run(job)
        await session.commit()
    except Exception as exc:
        logger.exception("Worker %s failed job %s", worker_id, job.id)
        await queue.mark_failed(job, reason=str(exc))
        await session.commit()
    return 1


async def run_forever(
    *,
    poll_seconds: float = 2.0,
    worker_id: str | None = None,
) -> None:
    settings = AppSettings()
    engine = make_engine(settings.resolved_database_url)
    await init_db(engine)
    session_factory = make_session_factory(engine)
    resolved_worker_id = worker_id or f"worker-{os.getpid()}"
    try:
        while True:
            async with session_factory() as session:
                processed = await run_once(
                    session,
                    settings,
                    worker_id=resolved_worker_id,
                )
            if processed == 0:
                await asyncio.sleep(poll_seconds)
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Add Docker Compose worker**

In `docker-compose.yml`, add:

```yaml
  worker:
    build:
      context: .
      dockerfile: backend/Dockerfile
    container_name: ragstudio-worker
    command: python -m ragstudio.workers.index_worker
    environment:
      RAGSTUDIO_DATABASE_URL: postgresql+asyncpg://ragstudio:ragstudio@postgres:5432/ragstudio
      RAGSTUDIO_NEO4J_URI: bolt://neo4j:7687
      RAGSTUDIO_NEO4J_USERNAME: neo4j
      RAGSTUDIO_NEO4J_PASSWORD: ragstudio-password
      RAGSTUDIO_DATA_DIR: /data
    volumes:
      - ./backend/src:/app/backend/src
      - ragstudio-backend-data:/data
    depends_on:
      postgres:
        condition: service_healthy
      neo4j:
        condition: service_healthy
```

- [ ] **Step 5: Run worker test**

Run:

```bash
./.venv/bin/pytest backend/tests/test_index_worker_recovery.py::test_worker_cycle_claims_and_runs_one_job -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/workers docker-compose.yml backend/tests/test_index_worker_recovery.py
git commit -m "feat: add durable indexing worker process"
```

---

### Task 7: Report Worker And Projection Health

**Files:**
- Modify: `backend/src/ragstudio/services/diagnostics_service.py`
- Modify: `backend/src/ragstudio/schemas/jobs.py`
- Test: `backend/tests/test_optimizer_graph_diagnostics.py`
- Test: `backend/tests/test_job_queue_service.py`

- [ ] **Step 1: Write diagnostics test**

Add this test to `backend/tests/test_optimizer_graph_diagnostics.py`:

```python
@pytest.mark.asyncio
async def test_diagnostics_reports_stale_running_jobs(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            Job(
                id="job-stale-diagnostic",
                type="index_document",
                target_id="doc-1",
                status=StageStatus.RUNNING.value,
                progress=75,
                logs=["Search ready"],
                result={},
                worker_id="worker-old",
                lease_expires_at=now_utc() - timedelta(minutes=5),
            )
        )
        await session.commit()

    response = await client.get("/api/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["dependency_status"]["stale_running_jobs"] == 1
    assert "1 indexing job has an expired worker lease." in body["warnings"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./.venv/bin/pytest backend/tests/test_optimizer_graph_diagnostics.py::test_diagnostics_reports_stale_running_jobs -q
```

Expected: FAIL because diagnostics does not inspect job leases.

- [ ] **Step 3: Add job fields to schema**

In `backend/src/ragstudio/schemas/jobs.py`, replace `JobOut` with:

```python
class JobOut(StudioModel):
    id: str
    type: str
    status: StageStatus
    target_id: str | None
    progress: int
    logs: list[str]
    result: dict[str, Any]
    worker_id: str | None = None
    lease_expires_at: Any | None = None
    heartbeat_at: Any | None = None
    attempts: int = 0
    max_attempts: int = 3
    recovery_action: str | None = None
```

- [ ] **Step 4: Add diagnostics query**

In `backend/src/ragstudio/services/diagnostics_service.py`, import `Job`, `StageStatus`, `func`, and `now_utc`:

```python
from ragstudio.db.models import GraphProjectionRecord, Job
from ragstudio.schemas.common import StageStatus, now_utc
from sqlalchemy import func, select
```

Add this method:

```python
    async def _job_worker_report(self, session: AsyncSession) -> dict[str, Any]:
        stale_running_jobs = await session.scalar(
            select(func.count(Job.id)).where(
                Job.status == StageStatus.RUNNING.value,
                Job.lease_expires_at.is_not(None),
                Job.lease_expires_at < now_utc(),
            )
        )
        ready_index_jobs = await session.scalar(
            select(func.count(Job.id)).where(
                Job.type == "index_document",
                Job.status == StageStatus.READY.value,
            )
        )
        return {
            "stale_running_jobs": int(stale_running_jobs or 0),
            "ready_index_jobs": int(ready_index_jobs or 0),
        }
```

In `_get_diagnostics_async()`, after `dependency_report.update(await self._graph_projection_report(...))`, add:

```python
        dependency_report.update(await self._job_worker_report(session))
```

Then add warning logic:

```python
        stale_running_jobs = int(dependency_report.get("stale_running_jobs") or 0)
        if stale_running_jobs == 1:
            warnings.append("1 indexing job has an expired worker lease.")
        elif stale_running_jobs > 1:
            warnings.append(f"{stale_running_jobs} indexing jobs have expired worker leases.")
```

In `_dependency_status()`, include:

```python
            "stale_running_jobs": report.get("stale_running_jobs", 0),
            "ready_index_jobs": report.get("ready_index_jobs", 0),
```

- [ ] **Step 5: Run diagnostics test**

Run:

```bash
./.venv/bin/pytest backend/tests/test_optimizer_graph_diagnostics.py::test_diagnostics_reports_stale_running_jobs -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/diagnostics_service.py backend/src/ragstudio/schemas/jobs.py backend/tests/test_optimizer_graph_diagnostics.py
git commit -m "feat: report durable worker health"
```

---

### Task 8: Document The RAG Architecture And Evaluation Gates

**Files:**
- Create: `docs/architecture/durable-rag-indexing.md`

- [ ] **Step 1: Create architecture document**

Create `docs/architecture/durable-rag-indexing.md` with:

````markdown
# Durable RAG Indexing Architecture

## Goal

Ragstudio keeps the API responsive while long document indexing runs. Upload and reindex requests persist work in Postgres. A separate worker process claims jobs, writes heartbeats, and resumes graph projection from persisted chunks after restart.

## Ingestion Pipeline

```mermaid
flowchart LR
  Upload["Upload or reindex request"] --> Job["Postgres jobs row"]
  Job --> Worker["ragstudio-worker"]
  Worker --> MinerU["MinerU strict parse"]
  MinerU --> Chunker["ChunkSplitter and relationship metadata"]
  Chunker --> Postgres["Postgres chunks and index_records"]
  Worker --> Runtime["RAG-Anything runtime indexing"]
  Runtime --> Pgvector["pgvector dense index"]
  Postgres --> Projection["GraphProjectionRunner"]
  Projection --> Neo4j["Neo4j rebuildable projection"]
```

## Vector Store Decision

Ragstudio uses Postgres plus pgvector because documents, chunks, index records, jobs, and retrieval metadata need transactional consistency. This matches the product's local-first operational model and avoids a second vector database while still supporting SQL metadata filters, trigram lexical search, token search, and embedding search. Neo4j is not a source of truth; it is a projection built from `relationship_metadata.graph_relationships`.

## Chunking Strategy

MinerU strict parsing remains the ingestion gate. `ChunkSplitter` creates canonical chunks with `source_location`, `metadata_json`, `text_search_ar`, `tokens_ar`, `runtime_source_id`, and parser quality metadata. Ragstudio does not use a blind default chunk size; it uses profile settings from `SettingsProfile.chunk_token_size` and `SettingsProfile.chunk_overlap_token_size`, then records parser quality warnings on the job result.

## Retrieval Pipeline

1. Apply selected-document metadata filters.
2. Retrieve lexical/token candidates from canonical chunks.
3. Retrieve dense candidates from the runtime pgvector index.
4. Fuse candidates in the retrieval orchestrator.
5. Use reranker settings from the active runtime profile when enabled.
6. Expand with Neo4j only when the latest graph projection is `succeeded`.
7. Degrade explicitly to metadata fallback when runtime or graph projection is unavailable.

## Evaluation Gates

Use the existing evaluation set workflow to track:

- `precision@10 >= 0.70`
- `recall@10 >= 0.60`
- `mrr@10 >= 0.60`
- graph projection status is `succeeded` for documents with relationship metadata
- p95 `/api/query` latency stays within the profile target for the selected model and reranker settings

Every indexing job stores:

- parser mode and domain metadata
- runtime profile id and embedding dimensions
- canonical chunk count
- parser quality warnings
- graph node and edge counts
- recovery action used after interrupted workers

## Restart Behavior

If the worker dies before chunks are persisted, the expired lease returns the job to `ready` with `recovery_action=retry_full_index`. If the worker dies after `search_ready`, the expired lease returns the job to `ready` with `recovery_action=resume_graph_projection`; the worker finishes Neo4j projection from persisted chunks without rerunning MinerU.
````

- [ ] **Step 2: Confirm document exists**

Run:

```bash
test -f docs/architecture/durable-rag-indexing.md && rg -n "precision@10|resume_graph_projection|pgvector" docs/architecture/durable-rag-indexing.md
```

Expected: output includes all three terms.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/durable-rag-indexing.md
git commit -m "docs: describe durable rag indexing architecture"
```

---

### Task 9: End-To-End Verification

**Files:**
- No source changes unless verification exposes a defect.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
./.venv/bin/pytest \
  backend/tests/test_job_queue_service.py \
  backend/tests/test_index_worker_recovery.py \
  backend/tests/test_documents.py::test_reindex_persists_job_options_for_worker \
  backend/tests/test_documents.py::test_reindex_does_not_schedule_in_process_background_task \
  backend/tests/test_db_engine.py::test_init_db_adds_durable_job_worker_columns \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run graph materialization regression tests**

Run:

```bash
./.venv/bin/pytest backend/tests/test_graph_materialization_service.py -q
```

Expected: PASS.

- [ ] **Step 3: Run lint on changed backend files**

Run:

```bash
./.venv/bin/ruff check \
  backend/src/ragstudio/api/routes/documents.py \
  backend/src/ragstudio/db/models.py \
  backend/src/ragstudio/db/engine.py \
  backend/src/ragstudio/services/document_service.py \
  backend/src/ragstudio/services/job_queue_service.py \
  backend/src/ragstudio/services/index_job_runner.py \
  backend/src/ragstudio/services/diagnostics_service.py \
  backend/src/ragstudio/workers/index_worker.py \
  backend/tests/test_job_queue_service.py \
  backend/tests/test_index_worker_recovery.py
```

Expected: `All checks passed!`

- [ ] **Step 4: Rebuild and start local stack**

Run:

```bash
docker compose up -d --build backend worker frontend postgres neo4j
docker compose ps
```

Expected: `ragstudio-backend`, `ragstudio-worker`, `ragstudio-frontend`, `ragstudio-postgres`, and `ragstudio-neo4j` are running. Postgres and Neo4j are healthy.

- [ ] **Step 5: Verify API remains responsive while worker exists**

Run:

```bash
curl -sS http://127.0.0.1:8000/api/health
curl -sS http://127.0.0.1:8000/api/diagnostics | jq '{overall_status, warnings, stale_jobs:.dependency_status.stale_running_jobs}'
```

Expected:

```json
{"status":"ok","service":"rag-anything-studio"}
```

Diagnostics expected: `overall_status` is `ready` or `degraded` for external dependency warnings, `stale_jobs` is `0`, and there is no worker lease warning.

- [ ] **Step 6: Commit verification note if docs changed**

If verification required doc updates, commit them:

```bash
git add docs/architecture/durable-rag-indexing.md
git commit -m "docs: record durable worker verification"
```

If no docs changed, do not create an empty commit.

---

## Self-Review

**Spec coverage:** This plan covers the requested architecture change and the `rag-architect` checklist: durable ingestion, vector-store boundary, chunking preservation, retrieval pipeline, graph projection recovery, and evaluation thresholds.

**Placeholder scan:** The plan avoids placeholder markers, avoids generic edge-case language, and does not ask for tests without concrete test code.

**Type consistency:** `Job.job_options`, `Job.recovery_action`, `Job.worker_id`, `Job.lease_expires_at`, `JobQueueService.claim_next()`, `IndexJobRunner.run()`, and `resume_graph_projection` are introduced before later tasks consume them.

**Architecture decision:** This is a durable worker refactor, not a new RAG stack. Postgres/pgvector remains the retrieval source of truth, Neo4j remains a rebuildable graph projection, and the web backend stops owning long-running indexing work.
