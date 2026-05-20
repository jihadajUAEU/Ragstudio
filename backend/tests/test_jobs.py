import pytest
from ragstudio.db.models import Job
from ragstudio.schemas.common import StageStatus
from ragstudio.services.index_progress import IndexStage, update_job_stage


@pytest.mark.asyncio
async def test_jobs_openapi_uses_typed_job_page(client):
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    openapi = response.json()
    response_schema = openapi["paths"]["/api/jobs"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response_schema == {"$ref": "#/components/schemas/JobPage"}
    job_properties = openapi["components"]["schemas"]["JobOut"]["properties"]
    for field in (
        "worker_id",
        "lease_expires_at",
        "heartbeat_at",
        "attempts",
        "max_attempts",
        "recovery_action",
    ):
        assert field in job_properties


@pytest.mark.asyncio
async def test_job_events_streams_structured_indexing_stage_events(client):
    async with client._transport.app.state.session_factory() as session:
        job = Job(
            id="job-events-1",
            type="index_document",
            status=StageStatus.SUCCEEDED.value,
            target_id="doc-1",
            progress=0,
            logs=[],
            result={},
        )
        update_job_stage(
            job,
            IndexStage.MINERU_PARSING,
            detail="Parser started.",
        )
        update_job_stage(
            job,
            IndexStage.CHUNKS_PERSISTED,
            detail="Canonical chunks persisted.",
            chunk_count=12,
        )
        session.add(job)
        await session.commit()

    response = await client.get("/api/jobs/job-events-1/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: job_stage" in body
    assert "event: job_status" in body
    assert '"stage":"mineru_parsing"' in body
    assert '"stage":"chunks_persisted"' in body
    assert '"chunk_count":12' in body
    assert '"status":"succeeded"' in body


@pytest.mark.asyncio
async def test_job_events_returns_404_for_missing_job(client):
    response = await client.get("/api/jobs/missing/events")

    assert response.status_code == 404


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
