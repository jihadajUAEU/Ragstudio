from datetime import UTC, datetime, timedelta

import pytest
from ragstudio.db.models import (
    Chunk,
    Document,
    GraphProjectionRecord,
    IndexRecord,
    Job,
    SettingsProfile,
)
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.document_service import DocumentService
from ragstudio.services.index_job_runner import IndexJobRunner
from ragstudio.services.index_lifecycle_service import IndexLifecycleResult, IndexLifecycleService
from ragstudio.services.job_queue_service import JobLeaseLostError
from sqlalchemy import select


class FakeGraphProjectionRunner:
    calls: list[str] = []

    def __init__(self, session, settings):
        self.session = session
        self.settings = settings

    async def materialize_pending(self, document_id: str):
        self.calls.append(document_id)
        record = await self.session.scalar(
            select(GraphProjectionRecord).where(
                GraphProjectionRecord.document_id == document_id,
                GraphProjectionRecord.status == "pending",
            )
        )
        assert record is not None
        record.status = "succeeded"
        record.node_count = 2
        record.edge_count = 1
        return {"status": "succeeded", "node_count": 2, "edge_count": 1, "reason": None}


@pytest.mark.asyncio
async def test_index_worker_healthcheck_queries_database(database_url, tmp_path):
    from ragstudio.config import AppSettings
    from ragstudio.workers.index_worker import healthcheck

    assert await healthcheck(AppSettings(database_url=database_url, data_dir=tmp_path))


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
        session.add(
            Job(
                id="job-worker-cycle",
                type="index_document",
                target_id=document.id,
                status=StageStatus.READY.value,
                progress=0,
                logs=[],
                result={"index_options": {"parser_mode": "mineru_strict", "domain_metadata": {}}},
                job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
            )
        )
        await session.commit()

    ran = []

    class FakeIndexJobRunner:
        def __init__(self, session, settings, *, worker_id, lease_seconds=300):
            self.session = session
            self.settings = settings
            self.worker_id = worker_id
            self.lease_seconds = lease_seconds

        async def run(self, job):
            ran.append((job.id, self.worker_id, self.lease_seconds))
            job.status = StageStatus.SUCCEEDED.value
            job.progress = 100
            job.worker_id = None
            job.lease_expires_at = None

    monkeypatch.setattr("ragstudio.workers.index_worker.IndexJobRunner", FakeIndexJobRunner)

    from ragstudio.workers.index_worker import run_once

    async with app.state.session_factory() as session:
        processed = await run_once(
            session,
            app.state.settings,
            worker_id="worker-test",
            lease_seconds=123,
        )

    assert processed == 1
    assert ran == [("job-worker-cycle", "worker-test", 123)]


@pytest.mark.asyncio
async def test_worker_cycle_recovers_expired_graph_projection_job(
    client,
    tmp_path,
    monkeypatch,
):
    app = client._transport.app
    artifact = tmp_path / "uploads" / "worker-recover-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with app.state.session_factory() as session:
        document = Document(
            filename="worker-recover.pdf",
            content_type="application/pdf",
            sha256="worker-recover-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Job(
                id="job-worker-recover",
                type="index_document",
                target_id=document.id,
                status=StageStatus.RUNNING.value,
                progress=75,
                logs=["Search ready: Lexical and metadata retrieval are ready."],
                result={"indexing_stage": {"stage": "search_ready", "chunk_count": 1}},
                job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                worker_id="worker-old",
                lease_expires_at=datetime.now(UTC) - timedelta(minutes=5),
                attempts=1,
            )
        )
        await session.commit()

    ran = []

    class FakeIndexJobRunner:
        def __init__(self, session, settings, *, worker_id, lease_seconds=300):
            self.session = session
            self.worker_id = worker_id

        async def run(self, job):
            ran.append((job.id, job.recovery_action, job.worker_id, job.attempts))
            job.status = StageStatus.SUCCEEDED.value
            job.progress = 100
            job.worker_id = None
            job.lease_expires_at = None
            job.recovery_action = None

    monkeypatch.setattr("ragstudio.workers.index_worker.IndexJobRunner", FakeIndexJobRunner)

    from ragstudio.workers.index_worker import run_once

    async with app.state.session_factory() as session:
        processed = await run_once(session, app.state.settings, worker_id="worker-test")

    async with app.state.session_factory() as session:
        job = await session.get(Job, "job-worker-recover")

    assert processed == 1
    assert ran == [("job-worker-recover", "resume_graph_projection", "worker-test", 2)]
    assert job.status == StageStatus.SUCCEEDED.value
    assert job.worker_id is None
    assert job.lease_expires_at is None
    assert job.recovery_action is None


@pytest.mark.asyncio
async def test_index_job_runner_resumes_graph_projection_without_reindex(
    client,
    tmp_path,
    monkeypatch,
):
    app = client._transport.app
    artifact = tmp_path / "uploads" / "resume-graph-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    FakeGraphProjectionRunner.calls = []

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
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status=StageStatus.RUNNING.value,
                chunk_count=1,
                index_shape={},
            )
        )
        session.add(
            Job(
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
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        await session.commit()
        document_id = document.id

    async def fail_if_full_index_runs(*args, **kwargs):
        raise AssertionError("full indexing should not run during graph projection resume")

    monkeypatch.setattr(
        "ragstudio.services.index_job_runner.GraphProjectionRunner",
        FakeGraphProjectionRunner,
    )
    monkeypatch.setattr(
        "ragstudio.services.index_job_runner.DocumentService.run_index_job",
        fail_if_full_index_runs,
    )

    async with app.state.session_factory() as session:
        job = await session.get(Job, "job-resume-graph")
        await IndexJobRunner(session, app.state.settings, worker_id="worker-a").run(job)
        await session.commit()
        refreshed = await session.get(Job, "job-resume-graph")
        projection = await session.scalar(
            select(GraphProjectionRecord).where(
                GraphProjectionRecord.document_id == document_id,
            )
        )
        index_record = await session.scalar(
            select(IndexRecord).where(IndexRecord.document_id == document_id)
        )

    assert FakeGraphProjectionRunner.calls == [document_id]
    assert refreshed.status == StageStatus.SUCCEEDED.value
    assert refreshed.progress == 100
    assert refreshed.worker_id is None
    assert refreshed.lease_expires_at is None
    assert refreshed.recovery_action is None
    assert refreshed.result["graph_materialization"] == {
        "status": "succeeded",
        "node_count": 2,
        "edge_count": 1,
        "reason": None,
    }
    assert refreshed.result["parser_quality"] == {"warning_counts": {}, "affected_chunks": 0}
    quality_summary = refreshed.result["index_quality_report"]["summary"]
    assert quality_summary["quality_unknown_document_count"] == 1
    assert refreshed.result["indexing_stage"]["stage"] == "ready"
    assert refreshed.result["indexing_stage"]["chunk_count"] == 1
    assert projection.status == "succeeded"
    assert index_record.status == StageStatus.SUCCEEDED.value


@pytest.mark.asyncio
async def test_index_job_runner_materializes_pending_projection_before_succeeding_job(
    client,
    tmp_path,
    monkeypatch,
):
    app = client._transport.app
    artifact = tmp_path / "uploads" / "normal-graph-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    FakeGraphProjectionRunner.calls = []

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
            filename="normal-graph.pdf",
            content_type="application/pdf",
            sha256="normal-graph-sha",
            artifact_path=str(artifact),
            status=StageStatus.READY.value,
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
        session.add(
            Job(
                id="job-normal-graph",
                type="index_document",
                target_id=document.id,
                status=StageStatus.RUNNING.value,
                progress=50,
                logs=["Worker worker-a claimed job."],
                result={"index_options": {"parser_mode": "mineru_strict", "domain_metadata": {}}},
                job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                worker_id="worker-a",
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        await session.commit()
        document_id = document.id

    async def fake_reindex_document(
        self,
        document_id,
        *,
        options=None,
        on_mineru_status=None,
        on_stage=None,
    ):
        return IndexLifecycleResult(
            chunks=[object()],
            graph_projection_record_id="projection-normal-graph",
            graph_materialization={
                "status": "pending",
                "node_count": 0,
                "edge_count": 0,
                "reason": None,
            },
        )

    monkeypatch.setattr(IndexLifecycleService, "reindex_document", fake_reindex_document)
    monkeypatch.setattr(
        "ragstudio.services.document_service.GraphProjectionRunner",
        FakeGraphProjectionRunner,
    )

    async with app.state.session_factory() as session:
        job = await session.get(Job, "job-normal-graph")
        await IndexJobRunner(session, app.state.settings, worker_id="worker-a").run(job)
        refreshed = await session.get(Job, "job-normal-graph")
        projection = await session.scalar(
            select(GraphProjectionRecord).where(
                GraphProjectionRecord.document_id == document_id,
            )
        )

    assert FakeGraphProjectionRunner.calls == [document_id]
    assert refreshed.status == StageStatus.SUCCEEDED.value
    assert refreshed.worker_id is None
    assert refreshed.lease_expires_at is None
    assert refreshed.result["graph_materialization"] == {
        "status": "succeeded",
        "node_count": 2,
        "edge_count": 1,
        "reason": None,
    }
    assert refreshed.result["indexing_stage"]["stage"] == "ready"
    assert projection.status == "succeeded"


@pytest.mark.asyncio
async def test_index_job_runner_rejects_stale_worker_before_full_index(
    client,
    tmp_path,
    monkeypatch,
):
    app = client._transport.app
    artifact = tmp_path / "uploads" / "stale-worker-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with app.state.session_factory() as session:
        document = Document(
            filename="stale-worker.pdf",
            content_type="application/pdf",
            sha256="stale-worker-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Job(
                id="job-stale-worker",
                type="index_document",
                target_id=document.id,
                status=StageStatus.RUNNING.value,
                progress=1,
                logs=[],
                result={},
                job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                worker_id="worker-b",
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        await session.commit()

    async def fail_if_full_index_runs(*args, **kwargs):
        raise AssertionError("stale worker must not run full indexing")

    monkeypatch.setattr(
        "ragstudio.services.index_job_runner.DocumentService.run_index_job",
        fail_if_full_index_runs,
    )

    async with app.state.session_factory() as session:
        job = await session.get(Job, "job-stale-worker")
        with pytest.raises(JobLeaseLostError):
            await IndexJobRunner(session, app.state.settings, worker_id="worker-a").run(job)


@pytest.mark.asyncio
async def test_index_job_runner_clears_terminal_lease_after_document_service_commit(
    client,
    tmp_path,
    monkeypatch,
):
    app = client._transport.app
    artifact = tmp_path / "uploads" / "clear-lease-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with app.state.session_factory() as session:
        document = Document(
            filename="clear-lease.pdf",
            content_type="application/pdf",
            sha256="clear-lease-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Job(
                id="job-clear-lease",
                type="index_document",
                target_id=document.id,
                status=StageStatus.RUNNING.value,
                progress=1,
                logs=[],
                result={},
                job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                worker_id="worker-a",
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        await session.commit()

    async def fake_run_index_job(self, document_id, job_id, options, ensure_active_lease=None):
        assert options.parser_mode == "mineru_strict"
        assert ensure_active_lease is not None
        job = await self.session.get(Job, job_id)
        job.status = StageStatus.SUCCEEDED.value
        job.progress = 100
        job.result = {"document_id": document_id}
        await self.session.commit()

    monkeypatch.setattr(
        "ragstudio.services.index_job_runner.DocumentService.run_index_job",
        fake_run_index_job,
    )

    async with app.state.session_factory() as session:
        job = await session.get(Job, "job-clear-lease")
        await IndexJobRunner(session, app.state.settings, worker_id="worker-a").run(job)

    async with app.state.session_factory() as session:
        refreshed = await session.get(Job, "job-clear-lease")

    assert refreshed.status == StageStatus.SUCCEEDED.value
    assert refreshed.worker_id is None
    assert refreshed.lease_expires_at is None
    assert refreshed.recovery_action is None


@pytest.mark.asyncio
async def test_run_index_job_rolls_back_terminal_state_after_lease_loss(
    client,
    tmp_path,
    monkeypatch,
):
    app = client._transport.app
    artifact = tmp_path / "uploads" / "lease-guard-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with app.state.session_factory() as session:
        document = Document(
            filename="lease-guard.pdf",
            content_type="application/pdf",
            sha256="lease-guard-sha",
            artifact_path=str(artifact),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Job(
                id="job-lease-guard",
                type="index_document",
                target_id=document.id,
                status=StageStatus.RUNNING.value,
                progress=1,
                logs=[],
                result={},
                job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                worker_id="worker-a",
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        await session.commit()
        document_id = document.id

    async def fake_index_document(self, document_id, **kwargs):
        return [object()]

    monkeypatch.setattr(
        "ragstudio.services.document_service.ChunkService.index_document",
        fake_index_document,
    )

    guard_calls = 0

    async def ensure_active_lease():
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls > 1:
            raise JobLeaseLostError("Job job-lease-guard lease is no longer held by worker-a.")

    async with app.state.session_factory() as session:
        with pytest.raises(JobLeaseLostError):
            await DocumentService(session, tmp_path).run_index_job(
                document_id,
                "job-lease-guard",
                IndexDocumentIn(parser_mode="mineru_strict"),
                ensure_active_lease=ensure_active_lease,
            )

    async with app.state.session_factory() as session:
        refreshed_document = await session.get(Document, document_id)
        refreshed_job = await session.get(Job, "job-lease-guard")

    assert guard_calls == 2
    assert refreshed_document.status == StageStatus.RUNNING.value
    assert refreshed_job.status == StageStatus.RUNNING.value
    assert refreshed_job.progress == 1
    assert "chunk_count" not in refreshed_job.result
