import json
from collections.abc import AsyncIterator

from ragstudio.config import AppSettings
from ragstudio.db.base import Base
from ragstudio.services.arabic_text import arabic_tokens, normalize_arabic_text
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
    if not is_postgres_url(database_url):
        raise ValueError("Ragstudio requires PostgreSQL for the metadata database.")
    return create_async_engine(database_url, future=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    from ragstudio.db import models as _models  # noqa: F401

    async with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
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
                "embedding_provider": "VARCHAR DEFAULT 'vllm_openai' NOT NULL",
                "embedding_base_url": "VARCHAR",
                "embedding_api_key": "VARCHAR",
                "embedding_timeout_ms": "INTEGER DEFAULT 10000 NOT NULL",
                "embedding_dimensions": "INTEGER DEFAULT 1536 NOT NULL",
                "embedding_batch_size": "INTEGER DEFAULT 16 NOT NULL",
                "embedding_tls_verify": _bool_column(connection, True),
                "mineru_enabled": _bool_column(connection, False),
                "mineru_base_url": "VARCHAR",
                "mineru_timeout_ms": "INTEGER DEFAULT 14400000 NOT NULL",
                "mineru_poll_interval_ms": "INTEGER DEFAULT 1000 NOT NULL",
                "mineru_require_hpc": _bool_column(connection, True),
                "runtime_mode": "VARCHAR DEFAULT 'runtime' NOT NULL",
                "vision_model": "VARCHAR",
                "vision_base_url": "VARCHAR",
                "vision_api_key": "VARCHAR",
                "vision_timeout_ms": "INTEGER DEFAULT 10000 NOT NULL",
                "reranker_provider": "VARCHAR DEFAULT 'disabled' NOT NULL",
                "reranker_fallback_provider": "VARCHAR DEFAULT 'disabled' NOT NULL",
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
                "text_search_ar": "TEXT DEFAULT '' NOT NULL",
                "tokens_ar": _json_array_column(connection),
                "extraction_quality": _json_object_column(connection),
            },
        )
        _backfill_chunk_search_columns(connection)
        _ensure_chunk_search_indexes(connection)
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
    if "jobs" in table_names:
        _ensure_columns(
            connection,
            inspector,
            "jobs",
            {
                "worker_id": "VARCHAR",
                "lease_expires_at": _datetime_column(connection),
                "heartbeat_at": _datetime_column(connection),
                "attempts": "INTEGER DEFAULT 0 NOT NULL",
                "max_attempts": "INTEGER DEFAULT 3 NOT NULL",
                "available_at": _datetime_now_column(connection),
                "job_options": _json_object_column(connection),
                "recovery_action": "VARCHAR",
            },
        )
        _backfill_job_runtime_columns(connection)
        _ensure_job_runtime_indexes(connection)
    if "graph_projection_records" in table_names:
        _ensure_columns(
            connection,
            inspector,
            "graph_projection_records",
            {
                "graph_workspace_label": "VARCHAR",
                "graph_storage_uri": "VARCHAR",
                "graph_storage_username": "VARCHAR",
                "graph_storage_password": "VARCHAR",
                "cleanup_status": "VARCHAR",
                "cleanup_error": "TEXT",
                "cleanup_attempted_at": _datetime_column(connection),
            },
        )
        if "settings_profiles" in table_names:
            _backfill_graph_projection_targets(connection)


def _ensure_columns(connection, inspector, table_name: str, additions: dict[str, str]) -> None:
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    for column, definition in additions.items():
        if column not in existing:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}"))


def _backfill_job_runtime_columns(connection) -> None:
    available_at_default = (
        "NOW()" if connection.dialect.name == "postgresql" else "CURRENT_TIMESTAMP"
    )
    job_options_default = (
        "CAST('{}' AS JSONB)" if connection.dialect.name == "postgresql" else "'{}'"
    )
    connection.execute(
        text(
            f"""
            UPDATE jobs
            SET attempts = COALESCE(attempts, 0),
                max_attempts = COALESCE(max_attempts, 3),
                available_at = COALESCE(available_at, created_at, {available_at_default}),
                job_options = COALESCE(job_options, {job_options_default})
            WHERE attempts IS NULL
               OR max_attempts IS NULL
               OR available_at IS NULL
               OR job_options IS NULL
            """
        )
    )


def _ensure_job_runtime_indexes(connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    _resolve_duplicate_active_index_jobs(connection)
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_jobs_claimable
            ON jobs (type, status, available_at)
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_active_index_document_job
            ON jobs (target_id)
            WHERE type = 'index_document'
              AND status IN ('ready', 'running')
              AND target_id IS NOT NULL
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_jobs_lease_expires_at
            ON jobs (lease_expires_at)
            """
        )
    )


def _resolve_duplicate_active_index_jobs(connection) -> None:
    connection.execute(
        text(
            """
            WITH ranked AS (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY target_id
                           ORDER BY
                               CASE WHEN status = 'running' THEN 0 ELSE 1 END,
                               created_at ASC NULLS LAST,
                               id ASC
                       ) AS active_rank
                FROM jobs
                WHERE type = 'index_document'
                  AND status IN ('ready', 'running')
                  AND target_id IS NOT NULL
            )
            UPDATE jobs AS job
            SET status = 'failed',
                progress = 100,
                worker_id = NULL,
                lease_expires_at = NULL,
                recovery_action = NULL,
                logs = COALESCE(job.logs, CAST('[]' AS JSONB))
                    || CAST(
                        '["Duplicate active index_document job resolved during DB initialization."]'
                        AS JSONB
                    ),
                result = COALESCE(job.result, CAST('{}' AS JSONB))
                    || CAST(
                        '{"error": "Duplicate active index_document job resolved during DB initialization."}'
                        AS JSONB
                    ),
                updated_at = NOW()
            FROM ranked
            WHERE job.id = ranked.id
              AND ranked.active_rank > 1
            """
        )
    )


def _backfill_chunk_search_columns(connection) -> None:
    connection.execute(
        text(
            """
            UPDATE chunks
            SET text_search_ar = COALESCE(text_search_ar, ''),
                tokens_ar = COALESCE(tokens_ar, CAST('[]' AS JSONB)),
                extraction_quality = COALESCE(extraction_quality, CAST('{}' AS JSONB))
            WHERE text_search_ar IS NULL
               OR tokens_ar IS NULL
               OR extraction_quality IS NULL
            """
        )
    )
    rows = (
        connection.execute(
            text(
                """
                SELECT id, text
                FROM chunks
                WHERE COALESCE(text_search_ar, '') = ''
                   OR tokens_ar IS NULL
                   OR tokens_ar = CAST('[]' AS JSONB)
                """
            )
        )
        .mappings()
        .all()
        if connection.dialect.name == "postgresql"
        else []
    )
    for row in rows:
        normalized = normalize_arabic_text(row["text"] or "")
        tokens = arabic_tokens(row["text"] or "")
        connection.execute(
            text(
                """
                UPDATE chunks
                SET text_search_ar = :text_search_ar,
                    tokens_ar = CAST(:tokens_ar AS JSONB)
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "text_search_ar": normalized,
                "tokens_ar": json.dumps(tokens, ensure_ascii=False),
            },
        )


def _ensure_chunk_search_indexes(connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_chunks_text_search_ar_trgm
            ON chunks USING gin (text_search_ar gin_trgm_ops)
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_chunks_tokens_ar_gin
            ON chunks USING gin (tokens_ar)
            """
        )
    )


def _backfill_graph_projection_targets(connection) -> None:
    settings = AppSettings()
    rows = (
        connection.execute(
            text(
                """
                SELECT g.id,
                       g.runtime_profile_id,
                       g.graph_workspace_label,
                       g.graph_storage_uri,
                       g.graph_storage_username,
                       s.neo4j_uri,
                       s.neo4j_username
                FROM graph_projection_records g
                LEFT JOIN settings_profiles s ON s.id = g.runtime_profile_id
                WHERE g.graph_workspace_label IS NULL
                   OR g.graph_storage_uri IS NULL
                   OR (
                       g.graph_storage_username IS NULL
                       AND s.neo4j_username IS NOT NULL
                   )
                   OR g.graph_storage_password IS NOT NULL
                """
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        connection.execute(
            text(
                """
                UPDATE graph_projection_records
                SET graph_workspace_label = COALESCE(
                        graph_workspace_label,
                        :graph_workspace_label
                    ),
                    graph_storage_uri = COALESCE(graph_storage_uri, :graph_storage_uri),
                    graph_storage_username = COALESCE(
                        graph_storage_username,
                        :graph_storage_username
                    ),
                    graph_storage_password = NULL
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "graph_workspace_label": _workspace_label(row["runtime_profile_id"]),
                "graph_storage_uri": row["neo4j_uri"] or settings.neo4j_uri,
                "graph_storage_username": row["neo4j_username"] or settings.neo4j_username,
            },
        )


def _workspace_label(profile_id: str | None) -> str:
    raw = f"ragstudio_{profile_id or 'default'}"
    safe = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_" for character in raw
    ).strip("_")
    return (safe or "ragstudio_default").replace("`", "``")


def _normalize_settings_profile_values(connection) -> None:
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET mineru_timeout_ms = 14400000
            WHERE mineru_timeout_ms IS NULL
               OR mineru_timeout_ms < 14400000
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET mineru_require_hpc = TRUE
            WHERE mineru_require_hpc IS NULL
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET runtime_mode = 'runtime'
            WHERE storage_backend IS NULL
               OR storage_backend = ''
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET storage_backend = 'postgres_pgvector_neo4j'
            WHERE storage_backend IS NULL
               OR storage_backend = ''
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET runtime_mode = 'runtime'
            WHERE runtime_mode IS NULL
               OR runtime_mode = ''
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET embedding_provider = 'vllm_openai'
            WHERE embedding_provider IS NULL
               OR embedding_provider = ''
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET reranker_fallback_provider = 'disabled'
            WHERE reranker_fallback_provider IS NULL
               OR reranker_fallback_provider = ''
               OR reranker_fallback_provider NOT IN ('disabled', 'llm')
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


def _datetime_now_column(connection) -> str:
    if connection.dialect.name == "postgresql":
        return "TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL"
    return "DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL"


async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session
