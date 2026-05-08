import pytest
from ragstudio.db.engine import init_db, is_postgres_url, make_engine, make_session_factory
from ragstudio.services.settings_service import SettingsService
from sqlalchemy import inspect, text


def test_is_postgres_url_detects_asyncpg_url():
    assert is_postgres_url("postgresql+asyncpg://ragstudio:ragstudio@127.0.0.1/ragstudio")


def test_is_postgres_url_rejects_sqlite_url():
    assert not is_postgres_url("sqlite+aiosqlite:////tmp/ragstudio.sqlite3")


@pytest.mark.asyncio
async def test_init_db_backfills_runtime_columns_for_existing_sqlite_tables(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.sqlite3'}")
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                CREATE TABLE settings_profiles (
                    id VARCHAR PRIMARY KEY,
                    provider VARCHAR NOT NULL,
                    llm_model VARCHAR NOT NULL,
                    embedding_model VARCHAR NOT NULL,
                    storage_backend VARCHAR NOT NULL,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO settings_profiles (
                    id, provider, llm_model, embedding_model, storage_backend
                )
                VALUES ('default', 'legacy', 'legacy-llm', 'legacy-embedding', 'local')
                """
            )
        )
        await connection.execute(
            text(
                """
                CREATE TABLE chunks (
                    id VARCHAR PRIMARY KEY,
                    document_id VARCHAR NOT NULL,
                    text TEXT NOT NULL,
                    source_location JSON DEFAULT '{}' NOT NULL,
                    metadata_json JSON DEFAULT '{}' NOT NULL,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO chunks (id, document_id, text)
                VALUES ('chunk-1', 'doc-1', 'legacy chunk')
                """
            )
        )
        await connection.execute(
            text(
                """
                CREATE TABLE runs (
                    id VARCHAR PRIMARY KEY,
                    variant_id VARCHAR NOT NULL,
                    experiment_id VARCHAR,
                    query TEXT NOT NULL,
                    status VARCHAR DEFAULT 'ready' NOT NULL,
                    answer TEXT DEFAULT '' NOT NULL,
                    sources JSON DEFAULT '[]' NOT NULL,
                    chunk_traces JSON DEFAULT '[]' NOT NULL,
                    timings JSON DEFAULT '{}' NOT NULL,
                    error TEXT,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO runs (id, variant_id, query)
                VALUES ('run-1', 'variant-1', 'legacy query')
                """
            )
        )

    await init_db(engine)

    async with engine.connect() as connection:
        columns = await connection.run_sync(
            lambda sync_connection: {
                table: {
                    column["name"]
                    for column in inspect(sync_connection).get_columns(table)
                }
                for table in ("settings_profiles", "chunks", "runs", "index_records")
            }
        )
        settings_row = (
            await connection.execute(
                text(
                    """
                    SELECT runtime_mode, storage_backend, pgvector_schema, enable_image_processing
                    FROM settings_profiles WHERE id = 'default'
                    """
                )
            )
        ).mappings().one()
        chunk_row = (
            await connection.execute(
                text("SELECT content_type FROM chunks WHERE id = 'chunk-1'")
            )
        ).mappings().one()
        run_row = (
            await connection.execute(
                text("SELECT document_ids, query_config FROM runs WHERE id = 'run-1'")
            )
        ).mappings().one()

    await engine.dispose()

    assert "runtime_mode" in columns["settings_profiles"]
    assert "neo4j_uri" in columns["settings_profiles"]
    assert "content_type" in columns["chunks"]
    assert "runtime_profile_id" in columns["runs"]
    assert "document_id" in columns["index_records"]
    assert settings_row["runtime_mode"] == "runtime"
    assert settings_row["storage_backend"] == "fallback_local"
    assert settings_row["pgvector_schema"] == "public"
    assert settings_row["enable_image_processing"] in (1, True)
    assert chunk_row["content_type"] == "text"
    assert run_row["document_ids"] == "[]"
    assert run_row["query_config"] == "{}"

    factory = make_session_factory(engine)
    async with factory() as session:
        settings = await SettingsService(session).get_default()

    assert settings is not None
    assert settings.storage_backend == "fallback_local"
