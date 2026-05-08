from collections.abc import AsyncIterator

from ragstudio.db.base import Base
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def is_postgres_url(database_url: str) -> bool:
    return make_url(database_url).get_backend_name() == "postgresql"


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, future=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    from ragstudio.db import models as _models  # noqa: F401

    async with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_ensure_runtime_columns)


def _ensure_runtime_columns(connection) -> None:
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "settings_profiles" in table_names:
        _ensure_columns(
            connection,
            inspector,
            "settings_profiles",
            {
                "llm_provider": "VARCHAR DEFAULT 'openai_compatible' NOT NULL",
                "llm_base_url": "VARCHAR",
                "llm_api_key": "VARCHAR",
                "llm_timeout_ms": "INTEGER DEFAULT 10000 NOT NULL",
                "llm_capabilities": _json_array_column(connection),
                "embedding_provider": "VARCHAR DEFAULT 'fallback' NOT NULL",
                "embedding_base_url": "VARCHAR",
                "embedding_api_key": "VARCHAR",
                "embedding_timeout_ms": "INTEGER DEFAULT 10000 NOT NULL",
                "embedding_dimensions": "INTEGER DEFAULT 1536 NOT NULL",
                "embedding_batch_size": "INTEGER DEFAULT 16 NOT NULL",
                "embedding_tls_verify": _bool_column(connection, True),
                "mineru_enabled": _bool_column(connection, False),
                "mineru_base_url": "VARCHAR",
                "mineru_timeout_ms": "INTEGER DEFAULT 1800000 NOT NULL",
                "mineru_poll_interval_ms": "INTEGER DEFAULT 1000 NOT NULL",
                "runtime_mode": "VARCHAR DEFAULT 'runtime' NOT NULL",
                "vision_model": "VARCHAR",
                "vision_base_url": "VARCHAR",
                "vision_api_key": "VARCHAR",
                "vision_timeout_ms": "INTEGER DEFAULT 10000 NOT NULL",
                "reranker_provider": "VARCHAR DEFAULT 'disabled' NOT NULL",
                "reranker_model": "VARCHAR",
                "reranker_base_url": "VARCHAR",
                "reranker_api_key": "VARCHAR",
                "reranker_timeout_ms": "INTEGER DEFAULT 10000 NOT NULL",
                "pgvector_schema": "VARCHAR DEFAULT 'public' NOT NULL",
                "pgvector_table_prefix": "VARCHAR DEFAULT 'ragstudio' NOT NULL",
                "neo4j_uri": "VARCHAR",
                "neo4j_username": "VARCHAR",
                "neo4j_password": "VARCHAR",
                "parser": "VARCHAR DEFAULT 'mineru' NOT NULL",
                "parse_method": "VARCHAR DEFAULT 'auto' NOT NULL",
                "chunk_token_size": "INTEGER DEFAULT 1200 NOT NULL",
                "chunk_overlap_token_size": "INTEGER DEFAULT 100 NOT NULL",
                "enable_image_processing": _bool_column(connection, True),
                "enable_table_processing": _bool_column(connection, True),
                "enable_equation_processing": _bool_column(connection, True),
                "context_window": "INTEGER DEFAULT 1 NOT NULL",
                "context_mode": "VARCHAR DEFAULT 'page' NOT NULL",
                "max_context_tokens": "INTEGER DEFAULT 2000 NOT NULL",
                "include_headers": _bool_column(connection, True),
                "include_captions": _bool_column(connection, True),
                "query_mode": "VARCHAR DEFAULT 'mix' NOT NULL",
                "top_k": "INTEGER DEFAULT 40 NOT NULL",
                "chunk_top_k": "INTEGER DEFAULT 20 NOT NULL",
                "enable_rerank": _bool_column(connection, True),
                "cosine_better_than_threshold": "FLOAT DEFAULT 0.2 NOT NULL",
                "max_total_tokens": "INTEGER DEFAULT 30000 NOT NULL",
                "max_entity_tokens": "INTEGER DEFAULT 6000 NOT NULL",
                "max_relation_tokens": "INTEGER DEFAULT 8000 NOT NULL",
                "enable_llm_cache": _bool_column(connection, True),
                "enable_llm_cache_for_entity_extract": _bool_column(connection, True),
                "llm_model_max_async": "INTEGER DEFAULT 4 NOT NULL",
                "embedding_func_max_async": "INTEGER DEFAULT 8 NOT NULL",
                "max_parallel_insert": "INTEGER DEFAULT 2 NOT NULL",
            },
        )
        _normalize_settings_profile_values(connection)
    if "chunks" in table_names:
        _ensure_columns(
            connection,
            inspector,
            "chunks",
            {
                "runtime_profile_id": "VARCHAR",
                "runtime_source_id": "VARCHAR",
                "content_type": "VARCHAR DEFAULT 'text' NOT NULL",
                "preview_ref": "VARCHAR",
                "indexed_at": _datetime_column(connection),
            },
        )
    if "runs" in table_names:
        _ensure_columns(
            connection,
            inspector,
            "runs",
            {
                "runtime_profile_id": "VARCHAR",
                "document_ids": _json_array_column(connection),
                "query_config": _json_object_column(connection),
                "reranker_traces": _json_array_column(connection),
                "token_metadata": _json_object_column(connection),
                "error_type": "VARCHAR",
            },
        )


def _ensure_columns(connection, inspector, table_name: str, additions: dict[str, str]) -> None:
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    for column, definition in additions.items():
        if column not in existing:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}"))


def _normalize_settings_profile_values(connection) -> None:
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET runtime_mode = 'fallback'
            WHERE storage_backend IS NULL
               OR storage_backend = ''
               OR storage_backend = 'fallback_local'
               OR storage_backend NOT IN ('postgres_pgvector_neo4j', 'fallback_local')
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET storage_backend = 'fallback_local'
            WHERE storage_backend IS NULL
               OR storage_backend = ''
               OR storage_backend NOT IN ('postgres_pgvector_neo4j', 'fallback_local')
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET runtime_mode = 'fallback'
            WHERE storage_backend = 'fallback_local'
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET runtime_mode = 'fallback'
            WHERE runtime_mode IS NULL
               OR runtime_mode = ''
               OR runtime_mode NOT IN ('runtime', 'fallback', 'degraded')
            """
        )
    )


def _json_array_column(connection) -> str:
    if connection.dialect.name == "postgresql":
        return "JSONB DEFAULT CAST('[]' AS JSONB) NOT NULL"
    return "JSON DEFAULT '[]' NOT NULL"


def _json_object_column(connection) -> str:
    if connection.dialect.name == "postgresql":
        return "JSONB DEFAULT CAST('{}' AS JSONB) NOT NULL"
    return "JSON DEFAULT '{}' NOT NULL"


def _bool_column(connection, default: bool) -> str:
    if connection.dialect.name == "postgresql":
        return f"BOOLEAN DEFAULT {'TRUE' if default else 'FALSE'} NOT NULL"
    return f"BOOLEAN DEFAULT {1 if default else 0} NOT NULL"


def _datetime_column(connection) -> str:
    if connection.dialect.name == "postgresql":
        return "TIMESTAMP WITH TIME ZONE"
    return "DATETIME"


async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session
