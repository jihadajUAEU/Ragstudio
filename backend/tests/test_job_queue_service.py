from datetime import UTC, datetime, timedelta

import pytest
from ragstudio.db.models import Document, Job
from ragstudio.schemas.common import StageStatus
from ragstudio.services.job_queue_service import JobLeaseLostError, JobQueueService


@pytest.mark.asyncio
async def test_enqueue_persists_index_options(client):
    app = client._transport.app
    job_options = {
        "parser_mode": "mineru_strict",
        "domain_metadata": {"domain": "quran", "tags": ["arabic"]},
    }

    async with app.state.session_factory() as session:
        queue = JobQueueService(session)
        job = await queue.enqueue_index_document(
            document_id="doc-1",
            options=job_options,
        )
        await session.commit()

        refreshed = await session.get(Job, job.id)

    assert refreshed is not None
    assert refreshed.type == "index_document"
    assert refreshed.target_id == "doc-1"
    assert refreshed.status == StageStatus.READY.value
    assert refreshed.job_options == job_options
    assert refreshed.result["index_options"] == job_options


@pytest.mark.asyncio
async def test_claim_next_sets_lease_and_worker_id(client):
    app = client._transport.app
    created = datetime.now(UTC) - timedelta(hours=1)

    async with app.state.session_factory() as session:
        session.add_all(
            [
                Job(
                    id="job-wrong-type",
                    type="query",
                    target_id="query-1",
                    status=StageStatus.READY.value,
                    progress=0,
                    logs=[],
                    result={},
                    available_at=created,
                    created_at=created,
                    updated_at=created,
                ),
                Job(
                    id="job-oldest-eligible",
                    type="index_document",
                    target_id="doc-oldest",
                    status=StageStatus.READY.value,
                    progress=0,
                    logs=[],
                    result={},
                    job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                    available_at=created,
                    created_at=created + timedelta(seconds=1),
                    updated_at=created + timedelta(seconds=1),
                ),
                Job(
                    id="job-attempts-exhausted",
                    type="index_document",
                    target_id="doc-attempts",
                    status=StageStatus.READY.value,
                    progress=0,
                    logs=[],
                    result={},
                    job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                    attempts=3,
                    max_attempts=3,
                    available_at=created,
                    created_at=created + timedelta(seconds=2),
                    updated_at=created + timedelta(seconds=2),
                ),
                Job(
                    id="job-newer-eligible",
                    type="index_document",
                    target_id="doc-newer",
                    status=StageStatus.READY.value,
                    progress=0,
                    logs=[],
                    result={},
                    job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                    available_at=created,
                    created_at=created + timedelta(seconds=3),
                    updated_at=created + timedelta(seconds=3),
                ),
                Job(
                    id="job-future",
                    type="index_document",
                    target_id="doc-future",
                    status=StageStatus.READY.value,
                    progress=0,
                    logs=[],
                    result={},
                    job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                    available_at=created + timedelta(days=1),
                    created_at=created - timedelta(seconds=1),
                    updated_at=created - timedelta(seconds=1),
                ),
            ]
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
    assert claimed.id == "job-oldest-eligible"
    assert claimed.status == StageStatus.RUNNING.value
    assert claimed.worker_id == "worker-a"
    assert claimed.lease_expires_at is not None
    assert claimed.heartbeat_at is not None
    assert claimed.lease_expires_at - claimed.heartbeat_at == timedelta(seconds=120)
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
        recovered = await JobQueueService(session).recover_expired_jobs(
            now=expired + timedelta(minutes=11),
        )
        await session.commit()
        job = await session.get(Job, "job-expired")

    assert recovered == 1
    assert job.status == StageStatus.READY.value
    assert job.worker_id is None
    assert job.lease_expires_at is None
    assert job.recovery_action == "resume_graph_projection"
    assert (
        job.logs[-1]
        == "Recovered expired worker lease; graph projection will resume from persisted chunks."
    )


@pytest.mark.parametrize("action", ["heartbeat", "mark_succeeded", "mark_failed"])
@pytest.mark.asyncio
async def test_stale_worker_cannot_update_after_another_worker_owns_job(client, action):
    app = client._transport.app
    timestamp = datetime.now(UTC)

    async with app.state.session_factory() as session:
        session.add(
            Job(
                id=f"job-stale-owner-{action}",
                type="index_document",
                target_id=f"doc-stale-owner-{action}",
                status=StageStatus.RUNNING.value,
                progress=50,
                logs=["Worker worker-a claimed job."],
                result={},
                job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                worker_id="worker-a",
                lease_expires_at=timestamp + timedelta(minutes=5),
                heartbeat_at=timestamp,
                attempts=1,
            )
        )
        await session.commit()

    async with app.state.session_factory() as stale_session:
        stale_job = await stale_session.get(Job, f"job-stale-owner-{action}")

        async with app.state.session_factory() as current_session:
            current_job = await current_session.get(Job, f"job-stale-owner-{action}")
            current_job.worker_id = "worker-b"
            current_job.lease_expires_at = timestamp + timedelta(minutes=10)
            await current_session.commit()

        with pytest.raises(JobLeaseLostError):
            await _run_worker_action(
                JobQueueService(stale_session),
                stale_job,
                action,
                worker_id="worker-a",
            )

    async with app.state.session_factory() as session:
        job = await session.get(Job, f"job-stale-owner-{action}")

    assert job.status == StageStatus.RUNNING.value
    assert job.worker_id == "worker-b"
    assert job.lease_expires_at == timestamp + timedelta(minutes=10)
    assert job.progress == 50
    assert job.result == {}
    assert job.logs == ["Worker worker-a claimed job."]


@pytest.mark.parametrize("action", ["heartbeat", "mark_succeeded", "mark_failed"])
@pytest.mark.asyncio
async def test_worker_cannot_update_after_lease_expires(client, action):
    app = client._transport.app
    expired = datetime.now(UTC) - timedelta(minutes=1)

    async with app.state.session_factory() as session:
        session.add(
            Job(
                id=f"job-expired-lease-{action}",
                type="index_document",
                target_id=f"doc-expired-lease-{action}",
                status=StageStatus.RUNNING.value,
                progress=50,
                logs=["Worker worker-a claimed job."],
                result={},
                job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                worker_id="worker-a",
                lease_expires_at=expired,
                heartbeat_at=expired,
                attempts=1,
            )
        )
        await session.commit()

    async with app.state.session_factory() as session:
        job = await session.get(Job, f"job-expired-lease-{action}")
        with pytest.raises(JobLeaseLostError):
            await _run_worker_action(
                JobQueueService(session),
                job,
                action,
                worker_id="worker-a",
            )

    async with app.state.session_factory() as session:
        job = await session.get(Job, f"job-expired-lease-{action}")

    assert job.status == StageStatus.RUNNING.value
    assert job.worker_id == "worker-a"
    assert job.lease_expires_at == expired
    assert job.progress == 50
    assert job.result == {}
    assert job.logs == ["Worker worker-a claimed job."]


@pytest.mark.asyncio
async def test_recover_expired_running_job_fails_after_max_attempts(client):
    app = client._transport.app
    expired = datetime.now(UTC) - timedelta(minutes=10)

    async with app.state.session_factory() as session:
        session.add(
            Document(
                id="doc-exhausted",
                filename="exhausted.pdf",
                content_type="application/pdf",
                sha256="doc-exhausted-sha",
                artifact_path="/tmp/doc-exhausted.pdf",
                status=StageStatus.RUNNING.value,
            )
        )
        session.add(
            Job(
                id="job-exhausted",
                type="index_document",
                target_id="doc-exhausted",
                status=StageStatus.RUNNING.value,
                progress=75,
                logs=["Worker worker-old claimed job."],
                result={"indexing_stage": {"stage": "search_ready"}},
                job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                worker_id="worker-old",
                lease_expires_at=expired,
                heartbeat_at=expired,
                attempts=3,
                max_attempts=3,
            )
        )
        await session.commit()

    async with app.state.session_factory() as session:
        recovered = await JobQueueService(session).recover_expired_jobs(
            now=expired + timedelta(minutes=11),
        )
        await session.commit()
        job = await session.get(Job, "job-exhausted")
        document = await session.get(Document, "doc-exhausted")

    assert recovered == 1
    assert job.status == StageStatus.FAILED.value
    assert document.status == StageStatus.FAILED.value
    assert job.progress == 100
    assert job.worker_id is None
    assert job.lease_expires_at is None
    assert job.recovery_action is None
    assert (
        job.result["error"]
        == "Worker lease expired after maximum attempts; indexing failed."
    )
    assert job.logs[-1] == "Worker lease expired after maximum attempts; indexing failed."


@pytest.mark.asyncio
async def test_mark_failed_updates_target_document_status(client):
    app = client._transport.app
    timestamp = datetime.now(UTC)

    async with app.state.session_factory() as session:
        session.add(
            Document(
                id="doc-mark-failed",
                filename="mark-failed.pdf",
                content_type="application/pdf",
                sha256="doc-mark-failed-sha",
                artifact_path="/tmp/doc-mark-failed.pdf",
                status=StageStatus.RUNNING.value,
            )
        )
        session.add(
            Job(
                id="job-mark-failed",
                type="index_document",
                target_id="doc-mark-failed",
                status=StageStatus.RUNNING.value,
                progress=50,
                logs=["Worker worker-a claimed job."],
                result={},
                job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                worker_id="worker-a",
                lease_expires_at=timestamp + timedelta(minutes=5),
                heartbeat_at=timestamp,
                attempts=1,
            )
        )
        await session.commit()

    async with app.state.session_factory() as session:
        job = await session.get(Job, "job-mark-failed")
        await JobQueueService(session).mark_failed(
            job,
            worker_id="worker-a",
            reason="Indexing failed.",
        )
        await session.commit()
        document = await session.get(Document, "doc-mark-failed")
        refreshed_job = await session.get(Job, "job-mark-failed")

    assert document.status == StageStatus.FAILED.value
    assert refreshed_job.status == StageStatus.FAILED.value
    assert refreshed_job.result["error"] == "Indexing failed."


@pytest.mark.asyncio
async def test_recover_running_job_with_missing_lease_requeues_full_index(client):
    app = client._transport.app
    timestamp = datetime.now(UTC)

    async with app.state.session_factory() as session:
        session.add(
            Job(
                id="job-missing-lease",
                type="index_document",
                target_id="doc-missing-lease",
                status=StageStatus.RUNNING.value,
                progress=25,
                logs=["Worker worker-legacy claimed job without a durable lease."],
                result={},
                job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                worker_id="worker-legacy",
                lease_expires_at=None,
                heartbeat_at=None,
                attempts=1,
                max_attempts=3,
            )
        )
        await session.commit()

    async with app.state.session_factory() as session:
        recovered = await JobQueueService(session).recover_expired_jobs(now=timestamp)
        await session.commit()
        job = await session.get(Job, "job-missing-lease")

    assert recovered == 1
    assert job.status == StageStatus.READY.value
    assert job.worker_id is None
    assert job.lease_expires_at is None
    assert job.heartbeat_at == timestamp
    assert job.recovery_action == "retry_full_index"
    assert job.logs[-1] == "Recovered missing worker lease; full indexing will retry."


async def _run_worker_action(
    queue: JobQueueService,
    job: Job,
    action: str,
    *,
    worker_id: str,
) -> None:
    if action == "heartbeat":
        await queue.heartbeat(job, worker_id=worker_id)
    elif action == "mark_succeeded":
        await queue.mark_succeeded(
            job,
            worker_id=worker_id,
            log="Indexing complete.",
            result_patch={"done": True},
        )
    elif action == "mark_failed":
        await queue.mark_failed(job, worker_id=worker_id, reason="Indexing failed.")
    else:
        raise AssertionError(f"Unknown action: {action}")
