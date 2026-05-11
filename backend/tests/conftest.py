import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from ragstudio.app import create_app
from ragstudio.config import AppSettings
from ragstudio.db.models import Job
from ragstudio.schemas.common import StageStatus
from sqlalchemy import select
from sqlalchemy.engine import make_url


def _admin_connection_kwargs(database_url: str, database: str) -> dict[str, object]:
    url = make_url(database_url)
    return {
        "user": url.username,
        "password": url.password,
        "host": url.host or "127.0.0.1",
        "port": url.port or 5432,
        "database": database,
    }


@pytest_asyncio.fixture
async def database_url() -> AsyncIterator[str]:
    base_url = os.environ.get("RAGSTUDIO_TEST_DATABASE_URL") or AppSettings().database_url
    url = make_url(base_url)
    if url.get_backend_name() != "postgresql":
        pytest.fail("Backend tests require a PostgreSQL RAGSTUDIO_TEST_DATABASE_URL.")

    database_name = f"ragstudio_test_{uuid.uuid4().hex}"
    admin_kwargs = _admin_connection_kwargs(base_url, "postgres")
    try:
        admin = await asyncpg.connect(**admin_kwargs)
    except OSError as exc:
        pytest.fail(
            "Backend tests require PostgreSQL. Start Docker with "
            "`docker compose up -d postgres` and retry."
        )
        raise AssertionError from exc

    await admin.execute(f'CREATE DATABASE "{database_name}"')
    await admin.close()

    test_url = url.set(database=database_name).render_as_string(hide_password=False)
    try:
        yield test_url
    finally:
        admin = await asyncpg.connect(**admin_kwargs)
        await admin.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = $1
              AND pid <> pg_backend_pid()
            """,
            database_name,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await admin.close()


@pytest_asyncio.fixture
async def client(tmp_path, database_url: str) -> AsyncIterator[AsyncClient]:
    app = create_app(data_dir=tmp_path, database_url=database_url)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as test_client:
            yield test_client


@pytest.fixture
def reindex_document(client):
    async def _active_index_job(document_id: str) -> Job | None:
        async with client._transport.app.state.session_factory() as session:
            return await session.scalar(
                select(Job)
                .where(
                    Job.type == "index_document",
                    Job.target_id == document_id,
                    Job.status.in_([StageStatus.READY.value, StageStatus.RUNNING.value]),
                )
                .order_by(Job.created_at.desc())
                .limit(1)
            )

    async def _wait_for_job(job_id: str) -> dict:
        for _ in range(50):
            async with client._transport.app.state.session_factory() as session:
                job = await session.get(Job, job_id)
                if job is not None and job.status == StageStatus.SUCCEEDED.value:
                    return {"job_id": job.id, "status": job.status, "document_id": job.target_id}
                if job is not None and job.status == StageStatus.FAILED.value:
                    pytest.fail(f"Reindex job failed: {job.result}")
            await asyncio.sleep(0.02)

        pytest.fail(f"Timed out waiting for reindex job {job_id}")

    async def _reindex_document(document_id: str, options: dict[str, object] | None = None) -> dict:
        existing_job = await _active_index_job(document_id)
        if existing_job is not None:
            return await _wait_for_job(existing_job.id)

        response = await client.post(
            f"/api/documents/{document_id}/reindex",
            json=options or {"parser_mode": "mineru_strict", "domain_metadata": {}},
        )
        if response.status_code == 409 and "active indexing job" in response.text:
            active_job = await _active_index_job(document_id)
            if active_job is not None:
                return await _wait_for_job(active_job.id)
        assert response.status_code == 202, response.text
        body = response.json()
        await _wait_for_job(body["job_id"])
        return body

    return _reindex_document
