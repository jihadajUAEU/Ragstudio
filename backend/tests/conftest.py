from collections.abc import AsyncIterator
import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from ragstudio.app import create_app


@pytest_asyncio.fixture
async def client(tmp_path) -> AsyncIterator[AsyncClient]:
    database_url = os.environ.get(
        "RAGSTUDIO_TEST_DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}",
    )
    app = create_app(data_dir=tmp_path, database_url=database_url)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as test_client:
            yield test_client
