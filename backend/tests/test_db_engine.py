import pytest
from ragstudio.config import AppSettings
from ragstudio.db.engine import init_db, is_postgres_url, make_engine, make_session_factory
from ragstudio.services.diagnostics_service import DiagnosticsService
from ragstudio.services.runtime_profile_service import RuntimeProfileService
from ragstudio.services.settings_service import SettingsService
from sqlalchemy import inspect, text


def test_is_postgres_url_detects_asyncpg_url():
    assert is_postgres_url("postgresql+asyncpg://ragstudio:ragstudio@127.0.0.1/ragstudio")


def test_is_postgres_url_rejects_sqlite_url():
    assert not is_postgres_url("sqlite+aiosqlite:////tmp/ragstudio.sqlite3")


def test_make_engine_rejects_sqlite_url():
    with pytest.raises(ValueError, match="requires PostgreSQL"):
        make_engine("sqlite+aiosqlite:////tmp/ragstudio.sqlite3")


@pytest.mark.asyncio
async def test_init_db_adds_durable_job_worker_columns(database_url):
    engine = make_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                CREATE TABLE jobs (
                    id VARCHAR PRIMARY KEY,
                    type VARCHAR NOT NULL,
                    status VARCHAR DEFAULT 'ready' NOT NULL,
                    target_id VARCHAR,
                    progress INTEGER DEFAULT 0 NOT NULL,
                    logs JSONB DEFAULT '[]'::jsonb NOT NULL,
                    result JSONB DEFAULT '{}'::jsonb NOT NULL,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO jobs (
                    id, type, status, target_id, progress, logs, result,
                    created_at, updated_at
                )
                VALUES (
                    'job-1',
                    'index_document',
                    'ready',
                    'doc-1',
                    0,
                    '[]'::jsonb,
                    '{}'::jsonb,
                    NOW(),
                    NOW()
                )
                """
            )
        )

    await init_db(engine)

    async with engine.connect() as connection:
        columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"] for column in inspect(sync_connection).get_columns("jobs")
            }
        )
        job_row = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT worker_id, lease_expires_at, heartbeat_at, attempts,
                               max_attempts, available_at, job_options, recovery_action
                        FROM jobs
                        WHERE id = 'job-1'
                        """
                    )
                )
            )
            .mappings()
            .one()
        )

    assert {
        "worker_id",
        "lease_expires_at",
        "heartbeat_at",
        "attempts",
        "max_attempts",
        "available_at",
        "job_options",
        "recovery_action",
    }.issubset(columns)
    assert job_row["worker_id"] is None
    assert job_row["lease_expires_at"] is None
    assert job_row["heartbeat_at"] is None
    assert job_row["attempts"] == 0
    assert job_row["max_attempts"] == 3
    assert job_row["available_at"] is not None
    assert job_row["job_options"] == {}
    assert job_row["recovery_action"] is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_backfills_runtime_columns_for_existing_postgres_tables(
    tmp_path,
    database_url,
):
    engine = make_engine(database_url)
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
                    neo4j_uri VARCHAR,
                    neo4j_username VARCHAR,
                    neo4j_password VARCHAR,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO settings_profiles (
                    id, provider, llm_model, embedding_model, storage_backend,
                    neo4j_uri, neo4j_username, neo4j_password
                )
                VALUES (
                    'default',
                    'legacy',
                    'legacy-llm',
                    'legacy-embedding',
                    'local',
                    'bolt://legacy-neo4j.test:7687',
                    'legacy-user',
                    'legacy-password'
                )
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
                    source_location JSONB DEFAULT '{}'::jsonb NOT NULL,
                    metadata_json JSONB DEFAULT '{}'::jsonb NOT NULL,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
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
                    sources JSONB DEFAULT '[]'::jsonb NOT NULL,
                    chunk_traces JSONB DEFAULT '[]'::jsonb NOT NULL,
                    timings JSONB DEFAULT '{}'::jsonb NOT NULL,
                    error TEXT,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
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
        await connection.execute(
            text(
                """
                CREATE TABLE graph_projection_records (
                    id VARCHAR PRIMARY KEY,
                    document_id VARCHAR NOT NULL,
                    runtime_profile_id VARCHAR NOT NULL,
                    status VARCHAR DEFAULT 'succeeded' NOT NULL,
                    projection_run_id VARCHAR,
                    node_count INTEGER DEFAULT 1 NOT NULL,
                    edge_count INTEGER DEFAULT 0 NOT NULL,
                    error TEXT,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO graph_projection_records (
                    id, document_id, runtime_profile_id, status, node_count, edge_count,
                    created_at, updated_at
                )
                VALUES (
                    'projection-1',
                    'doc-1',
                    'default',
                    'succeeded',
                    1,
                    0,
                    NOW(),
                    NOW()
                )
                """
            )
        )

    await init_db(engine)

    async with engine.connect() as connection:
        columns = await connection.run_sync(
            lambda sync_connection: {
                table: {column["name"] for column in inspect(sync_connection).get_columns(table)}
                for table in (
                    "settings_profiles",
                    "chunks",
                    "runs",
                    "index_records",
                    "graph_projection_records",
                )
            }
        )
        settings_row = (
            (
                await connection.execute(
                    text(
                        """
                    SELECT runtime_mode, storage_backend, pgvector_schema,
                           enable_image_processing, mineru_timeout_ms,
                           mineru_require_hpc
                    FROM settings_profiles WHERE id = 'default'
                    """
                    )
                )
            )
            .mappings()
            .one()
        )
        chunk_row = (
            (await connection.execute(text("SELECT content_type FROM chunks WHERE id = 'chunk-1'")))
            .mappings()
            .one()
        )
        run_row = (
            (
                await connection.execute(
                    text("SELECT document_ids, query_config FROM runs WHERE id = 'run-1'")
                )
            )
            .mappings()
            .one()
        )
        projection_row = (
            (
                await connection.execute(
                    text(
                        """
                    SELECT graph_workspace_label, graph_storage_uri,
                           graph_storage_username, graph_storage_password
                    FROM graph_projection_records WHERE id = 'projection-1'
                    """
                    )
                )
            )
            .mappings()
            .one()
        )

    assert "runtime_mode" in columns["settings_profiles"]
    assert "neo4j_uri" in columns["settings_profiles"]
    assert "content_type" in columns["chunks"]
    assert "runtime_profile_id" in columns["runs"]
    assert "document_id" in columns["index_records"]
    assert "graph_workspace_label" in columns["graph_projection_records"]
    assert "graph_storage_uri" in columns["graph_projection_records"]
    assert "graph_storage_username" in columns["graph_projection_records"]
    assert "graph_storage_password" in columns["graph_projection_records"]
    assert "cleanup_status" in columns["graph_projection_records"]
    assert "cleanup_error" in columns["graph_projection_records"]
    assert "cleanup_attempted_at" in columns["graph_projection_records"]
    assert settings_row["runtime_mode"] == "runtime"
    assert settings_row["storage_backend"] == "local"
    assert settings_row["pgvector_schema"] == "public"
    assert settings_row["enable_image_processing"] is True
    assert settings_row["mineru_timeout_ms"] == 14400000
    assert settings_row["mineru_require_hpc"] is True
    assert chunk_row["content_type"] == "text"
    assert run_row["document_ids"] == []
    assert run_row["query_config"] == {}
    assert projection_row["graph_workspace_label"] == "ragstudio_default"
    assert projection_row["graph_storage_uri"] == "bolt://legacy-neo4j.test:7687"
    assert projection_row["graph_storage_username"] == "legacy-user"
    assert projection_row["graph_storage_password"] is None

    settings_obj = AppSettings(
        data_dir=tmp_path,
        database_url=database_url,
    )
    factory = make_session_factory(engine)
    async with factory() as session:
        with pytest.raises(ValueError, match="supported product storage backend"):
            await SettingsService(session).get_default()
        with pytest.raises(ValueError, match="supported product storage backend"):
            await RuntimeProfileService(session, settings_obj).get_active_profile()
        diagnostics = await DiagnosticsService(session, settings_obj).get_diagnostics()

    assert diagnostics.capabilities["indexing"] is False
    assert diagnostics.capabilities["query"] is False
    assert diagnostics.overall_status in {"ready", "degraded", "failed"}

    await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_clears_graph_projection_password_snapshots(database_url):
    engine = make_engine(database_url)
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
                    neo4j_uri VARCHAR,
                    neo4j_username VARCHAR,
                    neo4j_password VARCHAR,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO settings_profiles (
                    id, provider, llm_model, embedding_model, storage_backend,
                    neo4j_uri, neo4j_username, neo4j_password
                )
                VALUES (
                    'default',
                    'legacy',
                    'legacy-llm',
                    'legacy-embedding',
                    'local',
                    'bolt://profile-neo4j.test:7687',
                    'profile-user',
                    'profile-password'
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                CREATE TABLE graph_projection_records (
                    id VARCHAR PRIMARY KEY,
                    document_id VARCHAR NOT NULL,
                    runtime_profile_id VARCHAR NOT NULL,
                    status VARCHAR DEFAULT 'succeeded' NOT NULL,
                    projection_run_id VARCHAR,
                    graph_workspace_label VARCHAR,
                    graph_storage_uri VARCHAR,
                    graph_storage_username VARCHAR,
                    graph_storage_password VARCHAR,
                    node_count INTEGER DEFAULT 1 NOT NULL,
                    edge_count INTEGER DEFAULT 0 NOT NULL,
                    error TEXT,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO graph_projection_records (
                    id, document_id, runtime_profile_id, status,
                    graph_workspace_label, graph_storage_uri, graph_storage_username,
                    graph_storage_password, node_count, edge_count,
                    created_at, updated_at
                )
                VALUES (
                    'projection-legacy-password',
                    'doc-1',
                    'default',
                    'succeeded',
                    'ragstudio_default',
                    'bolt://stored-neo4j.test:7687',
                    'stored-user',
                    'legacy-password',
                    1,
                    0,
                    NOW(),
                    NOW()
                ),
                (
                    'projection-passwordless',
                    'doc-2',
                    'default',
                    'succeeded',
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    1,
                    0,
                    NOW(),
                    NOW()
                )
                """
            )
        )

    await init_db(engine)

    async with engine.connect() as connection:
        rows = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT id, graph_workspace_label, graph_storage_uri,
                               graph_storage_username, graph_storage_password
                        FROM graph_projection_records
                        ORDER BY id
                        """
                    )
                )
            )
            .mappings()
            .all()
        )
        rows = [dict(row) for row in rows]

    assert rows == [
        {
            "id": "projection-legacy-password",
            "graph_workspace_label": "ragstudio_default",
            "graph_storage_uri": "bolt://stored-neo4j.test:7687",
            "graph_storage_username": "stored-user",
            "graph_storage_password": None,
        },
        {
            "id": "projection-passwordless",
            "graph_workspace_label": "ragstudio_default",
            "graph_storage_uri": "bolt://profile-neo4j.test:7687",
            "graph_storage_username": "profile-user",
            "graph_storage_password": None,
        },
    ]

    await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_does_not_rewrite_authless_graph_projection_targets(database_url):
    engine = make_engine(database_url)
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
                    neo4j_uri VARCHAR,
                    neo4j_username VARCHAR,
                    neo4j_password VARCHAR,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO settings_profiles (
                    id, provider, llm_model, embedding_model, storage_backend,
                    neo4j_uri, neo4j_username, neo4j_password
                )
                VALUES
                    (
                        'authless',
                        'legacy',
                        'legacy-llm',
                        'legacy-embedding',
                        'local',
                        'bolt://authless-neo4j.test:7687',
                        NULL,
                        NULL
                    ),
                    (
                        'authed',
                        'legacy',
                        'legacy-llm',
                        'legacy-embedding',
                        'local',
                        'bolt://authed-neo4j.test:7687',
                        'neo4j',
                        'secret'
                    )
                """
            )
        )
        await connection.execute(
            text(
                """
                CREATE TABLE graph_projection_records (
                    id VARCHAR PRIMARY KEY,
                    document_id VARCHAR NOT NULL,
                    runtime_profile_id VARCHAR NOT NULL,
                    status VARCHAR DEFAULT 'succeeded' NOT NULL,
                    projection_run_id VARCHAR,
                    graph_workspace_label VARCHAR,
                    graph_storage_uri VARCHAR,
                    graph_storage_username VARCHAR,
                    graph_storage_password VARCHAR,
                    node_count INTEGER DEFAULT 1 NOT NULL,
                    edge_count INTEGER DEFAULT 0 NOT NULL,
                    error TEXT,
                    update_count INTEGER DEFAULT 0 NOT NULL,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                CREATE OR REPLACE FUNCTION graph_projection_update_count()
                RETURNS trigger AS $$
                BEGIN
                    NEW.update_count = OLD.update_count + 1;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        await connection.execute(
            text(
                """
                CREATE TRIGGER graph_projection_update_count_trigger
                BEFORE UPDATE ON graph_projection_records
                FOR EACH ROW
                EXECUTE FUNCTION graph_projection_update_count()
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO graph_projection_records (
                    id, document_id, runtime_profile_id, graph_workspace_label,
                    graph_storage_uri, graph_storage_username, graph_storage_password,
                    created_at, updated_at
                )
                VALUES
                    (
                        'authless-projection',
                        'doc-1',
                        'authless',
                        'ragstudio_authless',
                        'bolt://authless-neo4j.test:7687',
                        NULL,
                        NULL,
                        NOW(),
                        NOW()
                    ),
                    (
                        'authed-projection',
                        'doc-2',
                        'authed',
                        'ragstudio_authed',
                        'bolt://authed-neo4j.test:7687',
                        NULL,
                        NULL,
                        NOW(),
                        NOW()
                    )
                """
            )
        )

    await init_db(engine)

    async with engine.connect() as connection:
        rows = {
            row["id"]: row
            for row in (
                await connection.execute(
                    text(
                        """
                        SELECT id, graph_storage_uri, graph_storage_username,
                               graph_storage_password, update_count
                        FROM graph_projection_records
                        ORDER BY id
                        """
                    )
                )
            )
            .mappings()
            .all()
        }

    assert rows["authless-projection"]["graph_storage_username"] is None
    assert rows["authless-projection"]["graph_storage_password"] is None
    assert rows["authless-projection"]["update_count"] == 0
    assert rows["authed-projection"]["graph_storage_uri"] == "bolt://authed-neo4j.test:7687"
    assert rows["authed-projection"]["graph_storage_username"] == "neo4j"
    assert rows["authed-projection"]["graph_storage_password"] is None
    assert rows["authed-projection"]["update_count"] == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_backfills_projection_target_from_settings_defaults_and_clears_password(
    tmp_path,
    database_url,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RAGSTUDIO_NEO4J_URI", raising=False)
    monkeypatch.delenv("RAGSTUDIO_NEO4J_USERNAME", raising=False)
    engine = make_engine(database_url)
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
                    neo4j_uri VARCHAR,
                    neo4j_username VARCHAR,
                    neo4j_password VARCHAR,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO settings_profiles (
                    id, provider, llm_model, embedding_model, storage_backend,
                    neo4j_uri, neo4j_username, neo4j_password
                )
                VALUES (
                    'default',
                    'legacy',
                    'legacy-llm',
                    'legacy-embedding',
                    'local',
                    NULL,
                    NULL,
                    'legacy-profile-password'
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                CREATE TABLE graph_projection_records (
                    id VARCHAR PRIMARY KEY,
                    document_id VARCHAR NOT NULL,
                    runtime_profile_id VARCHAR NOT NULL,
                    status VARCHAR DEFAULT 'succeeded' NOT NULL,
                    projection_run_id VARCHAR,
                    graph_workspace_label VARCHAR,
                    graph_storage_uri VARCHAR,
                    graph_storage_username VARCHAR,
                    graph_storage_password VARCHAR,
                    node_count INTEGER DEFAULT 1 NOT NULL,
                    edge_count INTEGER DEFAULT 0 NOT NULL,
                    error TEXT,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO graph_projection_records (
                    id, document_id, runtime_profile_id, status,
                    graph_workspace_label, graph_storage_uri, graph_storage_username,
                    graph_storage_password, node_count, edge_count,
                    created_at, updated_at
                )
                VALUES (
                    'projection-settings-defaults',
                    'doc-1',
                    'default',
                    'succeeded',
                    NULL,
                    NULL,
                    NULL,
                    'legacy-projection-password',
                    1,
                    0,
                    NOW(),
                    NOW()
                )
                """
            )
        )

    await init_db(engine)

    async with engine.connect() as connection:
        projection_row = (
            (
                await connection.execute(
                    text(
                        """
                        SELECT graph_workspace_label, graph_storage_uri,
                               graph_storage_username, graph_storage_password
                        FROM graph_projection_records
                        WHERE id = 'projection-settings-defaults'
                        """
                    )
                )
            )
            .mappings()
            .one()
        )

    assert projection_row["graph_workspace_label"] == "ragstudio_default"
    assert projection_row["graph_storage_uri"] == "bolt://127.0.0.1:57687"
    assert projection_row["graph_storage_username"] == "neo4j"
    assert projection_row["graph_storage_password"] is None

    await engine.dispose()
