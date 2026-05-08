from collections.abc import AsyncIterator

from ragstudio.db.base import Base
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, future=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    from ragstudio.db import models as _models  # noqa: F401

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_ensure_settings_profile_columns)


def _ensure_settings_profile_columns(connection) -> None:
    inspector = inspect(connection)
    if "settings_profiles" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("settings_profiles")}
    additions = {
        "llm_provider": "VARCHAR DEFAULT 'openai_compatible' NOT NULL",
        "llm_base_url": "VARCHAR",
        "llm_api_key": "VARCHAR",
        "llm_timeout_ms": "INTEGER DEFAULT 10000 NOT NULL",
        "llm_capabilities": "JSON DEFAULT '[]' NOT NULL",
        "embedding_provider": "VARCHAR DEFAULT 'fallback' NOT NULL",
        "embedding_base_url": "VARCHAR",
        "embedding_api_key": "VARCHAR",
        "embedding_timeout_ms": "INTEGER DEFAULT 10000 NOT NULL",
        "embedding_dimensions": "INTEGER DEFAULT 1536 NOT NULL",
        "embedding_batch_size": "INTEGER DEFAULT 16 NOT NULL",
        "embedding_tls_verify": "BOOLEAN DEFAULT 1 NOT NULL",
        "mineru_enabled": "BOOLEAN DEFAULT 0 NOT NULL",
        "mineru_base_url": "VARCHAR",
        "mineru_timeout_ms": "INTEGER DEFAULT 1800000 NOT NULL",
        "mineru_poll_interval_ms": "INTEGER DEFAULT 1000 NOT NULL",
    }
    for column, definition in additions.items():
        if column not in existing:
            connection.execute(
                text(f"ALTER TABLE settings_profiles ADD COLUMN {column} {definition}")
            )


async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session
