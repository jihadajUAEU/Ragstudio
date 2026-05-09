import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from ragstudio.app import create_app
from ragstudio.config import AppSettings
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
