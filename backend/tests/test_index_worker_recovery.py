from datetime import UTC, datetime, timedelta

import pytest
from ragstudio.db.models import Chunk, Document, GraphProjectionRecord, Job, SettingsProfile
from ragstudio.schemas.common import StageStatus
from ragstudio.services.index_job_runner import IndexJobRunner
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
    assert refreshed.result["indexing_stage"]["stage"] == "ready"
    assert refreshed.result["indexing_stage"]["chunk_count"] == 1
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

    async def fake_run_index_job(self, document_id, job_id, options):
        assert options.parser_mode == "mineru_strict"
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
