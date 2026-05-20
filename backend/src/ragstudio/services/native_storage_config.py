from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import unquote

from ragstudio.config import AppSettings
from ragstudio.schemas.runtime import RuntimeProfile
from ragstudio.services.graph_workspace import workspace_label
from sqlalchemy.engine import make_url


class AsyncThreadLock:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    async def __aenter__(self) -> AsyncThreadLock:
        while not self._lock.acquire(blocking=False):
            await asyncio.sleep(0)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self._lock.release()

    def locked(self) -> bool:
        return self._lock.locked()


@dataclass(frozen=True)
class NativeStorageConfig:
    postgres_host: str
    postgres_port: str
    postgres_user: str
    postgres_password: str
    postgres_database: str
    workspace: str
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str

    def env_updates(self) -> dict[str, str]:
        return {
            "POSTGRES_HOST": self.postgres_host,
            "POSTGRES_PORT": self.postgres_port,
            "POSTGRES_USER": self.postgres_user,
            "POSTGRES_PASSWORD": self.postgres_password,
            "POSTGRES_DATABASE": self.postgres_database,
            "POSTGRES_WORKSPACE": self.workspace,
            "NEO4J_URI": self.neo4j_uri,
            "NEO4J_USERNAME": self.neo4j_username,
            "NEO4J_PASSWORD": self.neo4j_password,
            "NEO4J_WORKSPACE": self.workspace,
        }


NATIVE_STORAGE_ENV_LOCK = AsyncThreadLock()


def derive_native_storage_config(
    profile: RuntimeProfile,
    settings: AppSettings,
) -> NativeStorageConfig:
    url = make_url(settings.resolved_database_url)
    return NativeStorageConfig(
        postgres_host=url.host or "127.0.0.1",
        postgres_port=str(url.port or 5432),
        postgres_user=unquote(url.username or "postgres"),
        postgres_password=unquote(url.password or ""),
        postgres_database=url.database or "ragstudio",
        workspace=workspace_label(profile),
        neo4j_uri=profile.neo4j_uri or "",
        neo4j_username=profile.neo4j_username or "",
        neo4j_password=profile.neo4j_password or "",
    )


@asynccontextmanager
async def scoped_native_storage_env(
    config: NativeStorageConfig,
) -> AsyncIterator[None]:
    updates = config.env_updates()
    async with NATIVE_STORAGE_ENV_LOCK:
        previous = {key: os.environ.get(key) for key in updates}
        try:
            for key, value in updates.items():
                if value:
                    os.environ[key] = value
                else:
                    os.environ.pop(key, None)
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
