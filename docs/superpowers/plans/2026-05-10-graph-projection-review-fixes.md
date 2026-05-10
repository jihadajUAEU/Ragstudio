# Graph Projection Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the graph projection cleanup review findings: missing fallback auth during legacy cleanup, plaintext Neo4j password duplication, and retry-unsafe external graph cleanup.

**Architecture:** Keep graph projection records as durable cleanup targets for workspace and URI, but stop creating new plaintext password snapshots and clear legacy snapshots during schema maintenance. Resolve cleanup credentials at runtime from the active or archived profile plus `AppSettings` fallback, and persist per-record cleanup state before external Neo4j deletion so retries do not repeat already-successful external work.

**Tech Stack:** Python 3.12+, FastAPI service layer, SQLAlchemy async ORM, PostgreSQL metadata DB, Neo4j driver, pytest/pytest-asyncio.

---

## File Structure

- Modify: `backend/src/ragstudio/db/models.py`
  - Add `cleanup_status`, `cleanup_error`, and `cleanup_attempted_at` columns to `GraphProjectionRecord`.
  - Keep `graph_storage_password` only as a legacy nullable column for compatibility; new code must not populate it.

- Modify: `backend/src/ragstudio/db/engine.py`
  - Add migration/backfill support for cleanup columns.
  - Backfill workspace/URI/username with `AppSettings` fallbacks when the profile leaves raw DB fields null.
  - Clear legacy `graph_storage_password` values after target metadata is backfilled.

- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
  - Stop storing `profile.neo4j_password` on new `GraphProjectionRecord` rows.

- Modify: `backend/src/ragstudio/services/graph_projection_runner.py`
  - Resolve cleanup profiles with fallback auth instead of treating label + URI as a complete auth target.
  - Stop storing passwords during rematerialization and target repair.
  - Persist `cleanup_status` before and after external Neo4j deletes.
  - Skip external deletion for records whose cleanup already succeeded.

- Modify: `backend/src/ragstudio/services/document_service.py`
  - Move Job/IndexRecord deletion until after graph cleanup succeeds.
  - Leave graph cleanup status committed if artifact/SQL document deletion fails afterward.

- Test: `backend/tests/test_db_engine.py`
  - Cover fallback target backfill and password clearing.

- Test: `backend/tests/test_index_lifecycle_service.py`
  - Cover no new password snapshots, cleanup auth fallback, cleanup status transitions, and no repeated external delete after cleanup already succeeded.

- Test: `backend/tests/test_documents.py`
  - Cover document delete retry after artifact unlink failure.

---

### Task 1: Stop Creating New Plaintext Password Snapshots

**Files:**
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py:163-170`
- Modify: `backend/src/ragstudio/services/graph_projection_runner.py:73-82`
- Modify: `backend/src/ragstudio/services/graph_projection_runner.py:221-245`
- Test: `backend/tests/test_index_lifecycle_service.py`

- [ ] **Step 1: Write the failing lifecycle test**

Add this test near the existing lifecycle graph projection tests in `backend/tests/test_index_lifecycle_service.py`:

```python
@pytest.mark.asyncio
async def test_lifecycle_does_not_snapshot_neo4j_password(client):
    app = client._transport.app
    runtime = FakeRuntime()
    artifact_path = app.state.settings.data_dir / "graph-no-password.txt"
    artifact_path.write_text("Graph password snapshot", encoding="utf-8")

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
                neo4j_username="neo4j",
                neo4j_password="do-not-copy",
            )
        )
        document = Document(
            filename="graph-no-password.txt",
            content_type="text/plain",
            sha256="graph-no-password",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.flush()

        result = await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeRuntimeFactory(runtime),
            health_service=PassingHealthService(),
        ).reindex_document(document.id)

        projection_record = await session.scalar(
            select(GraphProjectionRecord).where(GraphProjectionRecord.document_id == document.id)
        )

    assert result is not None
    assert projection_record is not None
    assert projection_record.graph_storage_uri == "bolt://neo4j.test:7687"
    assert projection_record.graph_storage_username == "neo4j"
    assert projection_record.graph_storage_password is None
```

- [ ] **Step 2: Run the failing lifecycle test**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_index_lifecycle_service.py::test_lifecycle_does_not_snapshot_neo4j_password -q
```

Expected: FAIL because `projection_record.graph_storage_password` is currently `"do-not-copy"`.

- [ ] **Step 3: Write the failing rematerialization test**

Add this test near `test_graph_projection_runner_rematerializes_from_mirrored_chunks` in `backend/tests/test_index_lifecycle_service.py`:

```python
@pytest.mark.asyncio
async def test_graph_projection_runner_rematerialize_does_not_snapshot_neo4j_password(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
                neo4j_username="neo4j",
                neo4j_password="do-not-copy",
            )
        )
        document = Document(
            filename="graph-rematerialize-no-password.txt",
            content_type="text/plain",
            sha256="graph-rematerialize-no-password",
            artifact_path=str(app.state.settings.data_dir / "graph-rematerialize-no-password.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="Graph rematerialize no password chunk",
                source_location={},
                metadata_json={},
                runtime_profile_id="default",
            )
        )
        await session.flush()

        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=FakeGraphMaterializationService(),
        ).rematerialize_document(document.id)
        projection_record = await session.scalar(
            select(GraphProjectionRecord).where(GraphProjectionRecord.document_id == document.id)
        )

    assert result["status"] == "succeeded"
    assert projection_record is not None
    assert projection_record.graph_storage_uri == "bolt://neo4j.test:7687"
    assert projection_record.graph_storage_username == "neo4j"
    assert projection_record.graph_storage_password is None
```

- [ ] **Step 4: Run the failing rematerialization test**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_index_lifecycle_service.py::test_graph_projection_runner_rematerialize_does_not_snapshot_neo4j_password -q
```

Expected: FAIL because rematerialization currently copies `profile.neo4j_password` into the projection record.

- [ ] **Step 5: Stop writing graph_storage_password in lifecycle indexing**

In `backend/src/ragstudio/services/index_lifecycle_service.py`, replace the `GraphProjectionRecord` creation block with:

```python
        projection_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id=profile.id,
            status="pending",
            graph_workspace_label=workspace_label(profile),
            graph_storage_uri=profile.neo4j_uri,
            graph_storage_username=profile.neo4j_username,
            graph_storage_password=None,
            node_count=0,
            edge_count=0,
        )
```

- [ ] **Step 6: Stop writing graph_storage_password in rematerialization**

In `backend/src/ragstudio/services/graph_projection_runner.py`, replace the `GraphProjectionRecord` creation inside `rematerialize_document()` with:

```python
            record = GraphProjectionRecord(
                document_id=document_id,
                runtime_profile_id=profile.id,
                status="pending",
                projection_run_id=new_id(),
                graph_workspace_label=workspace_label(profile),
                graph_storage_uri=profile.neo4j_uri,
                graph_storage_username=profile.neo4j_username,
                graph_storage_password=None,
            )
```

- [ ] **Step 7: Stop target repair from repopulating passwords**

In `backend/src/ragstudio/services/graph_projection_runner.py`, update `_ensure_projection_target()` so it never copies `neo4j_password` into the record:

```python
    def _ensure_projection_target(
        self,
        record: GraphProjectionRecord,
        profile: Any,
    ) -> None:
        if not record.graph_workspace_label:
            record.graph_workspace_label = workspace_label(profile)
        if not record.graph_storage_uri:
            record.graph_storage_uri = getattr(profile, "neo4j_uri", None)
        if not record.graph_storage_username:
            record.graph_storage_username = getattr(profile, "neo4j_username", None)
        record.graph_storage_password = None
```

- [ ] **Step 8: Run both new tests**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_index_lifecycle_service.py::test_lifecycle_does_not_snapshot_neo4j_password backend/tests/test_index_lifecycle_service.py::test_graph_projection_runner_rematerialize_does_not_snapshot_neo4j_password -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/src/ragstudio/services/index_lifecycle_service.py backend/src/ragstudio/services/graph_projection_runner.py backend/tests/test_index_lifecycle_service.py
git commit -m "fix: stop snapshotting neo4j passwords"
```

---

### Task 2: Resolve Projection Cleanup Auth With Runtime Fallbacks

**Files:**
- Modify: `backend/src/ragstudio/services/graph_projection_runner.py:137-245`
- Test: `backend/tests/test_index_lifecycle_service.py`

- [ ] **Step 1: Write the failing fallback-auth cleanup test**

Add this test near `test_graph_projection_runner_deletes_using_recorded_target_after_profile_drift` in `backend/tests/test_index_lifecycle_service.py`:

```python
@pytest.mark.asyncio
async def test_graph_projection_runner_uses_settings_auth_for_stored_target_without_password(
    client,
):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
                neo4j_username=None,
                neo4j_password=None,
            )
        )
        document = Document(
            filename="graph-delete-settings-auth.txt",
            content_type="text/plain",
            sha256="graph-delete-settings-auth",
            artifact_path=str(app.state.settings.data_dir / "graph-delete-settings-auth.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            GraphProjectionRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status="succeeded",
                graph_workspace_label="ragstudio_default",
                graph_storage_uri="bolt://neo4j.test:7687",
                graph_storage_username=None,
                graph_storage_password=None,
                node_count=2,
                edge_count=1,
            )
        )
        await session.flush()

        fake = FakeGraphMaterializationService()
        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=fake,
        ).delete_document_graph(document.id)

    assert result["status"] == "succeeded"
    assert fake.delete_calls == [
        {
            "document_id": document.id,
            "profile_id": "default",
            "neo4j_uri": "bolt://neo4j.test:7687",
            "neo4j_username": app.state.settings.neo4j_username,
            "neo4j_password": app.state.settings.neo4j_password,
            "graph_workspace_label": "ragstudio_default",
        }
    ]
```

- [ ] **Step 2: Run the failing fallback-auth test**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_index_lifecycle_service.py::test_graph_projection_runner_uses_settings_auth_for_stored_target_without_password -q
```

Expected: FAIL because `_has_stored_graph_target()` currently bypasses `RuntimeProfileService.get_profile()` and `_profile_for_record()` receives no fallback password.

- [ ] **Step 3: Implement cleanup profile resolution**

In `backend/src/ragstudio/services/graph_projection_runner.py`, replace the `for runtime_profile_id in cleanup_profile_ids:` loop body in `delete_document_graph()` with:

```python
        for runtime_profile_id in cleanup_profile_ids:
            profile_records = [
                record
                for record in records
                if record.runtime_profile_id == runtime_profile_id
                and _needs_graph_cleanup(record)
            ]
            targets = {_target_key(record): record for record in profile_records}
            live_profile = await self._cleanup_live_profile(profile_service, runtime_profile_id)
            for target_record in targets.values():
                if live_profile is None and not _has_stored_graph_target(target_record):
                    raise GraphProjectionCleanupError(
                        f"Runtime profile '{runtime_profile_id}' is not configured."
                    )
                if live_profile is not None:
                    self._ensure_projection_target(target_record, live_profile)
                result = await self.materialization_service.delete_document_graph(
                    document_id=document_id,
                    profile=self._profile_for_record(live_profile, target_record),
                )
                if result.status != "succeeded":
                    detail = f": {result.reason}" if result.reason else ""
                    raise GraphProjectionCleanupError(
                        f"Graph projection cleanup {result.status}{detail}"
                    )
                node_count += result.node_count
                edge_count += result.edge_count
```

Add this method inside `GraphProjectionRunner` below `_projection_records()`:

```python
    async def _cleanup_live_profile(
        self,
        profile_service: RuntimeProfileService,
        runtime_profile_id: str,
    ) -> Any | None:
        try:
            return await profile_service.get_profile(runtime_profile_id)
        except RuntimeProfileNotConfiguredError:
            return None
```

Replace `_profile_for_record()` with:

```python
    def _profile_for_record(
        self,
        profile: Any | None,
        record: GraphProjectionRecord,
    ) -> Any:
        fallback_username = getattr(profile, "neo4j_username", None)
        fallback_password = getattr(profile, "neo4j_password", None)
        return SimpleNamespace(
            id=getattr(profile, "id", record.runtime_profile_id),
            graph_workspace_label=record.graph_workspace_label,
            neo4j_uri=record.graph_storage_uri or getattr(profile, "neo4j_uri", None),
            neo4j_username=record.graph_storage_username or fallback_username,
            neo4j_password=record.graph_storage_password or fallback_password,
        )
```

- [ ] **Step 4: Run the fallback-auth test**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_index_lifecycle_service.py::test_graph_projection_runner_uses_settings_auth_for_stored_target_without_password -q
```

Expected: PASS.

- [ ] **Step 5: Run existing graph projection cleanup tests**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_index_lifecycle_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/graph_projection_runner.py backend/tests/test_index_lifecycle_service.py
git commit -m "fix: resolve graph cleanup auth from runtime profile"
```

---

### Task 3: Backfill Durable Targets Without Retaining Passwords

**Files:**
- Modify: `backend/src/ragstudio/db/engine.py:135-215`
- Test: `backend/tests/test_db_engine.py`

- [ ] **Step 1: Write the failing migration test**

Add this test after the existing graph projection migration test in `backend/tests/test_db_engine.py`:

```python
@pytest.mark.asyncio
async def test_init_db_backfills_projection_target_from_settings_defaults_and_clears_password(
    tmp_path,
):
    database_url = (
        "postgresql+asyncpg://ragstudio:ragstudio@127.0.0.1:55432/"
        "ragstudio_test_graph_projection_backfill"
    )
    engine = make_engine(database_url)

    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS graph_projection_records"))
        await connection.execute(text("DROP TABLE IF EXISTS settings_profiles"))
        await connection.execute(
            text(
                """
                CREATE TABLE settings_profiles (
                    id VARCHAR PRIMARY KEY,
                    provider VARCHAR,
                    llm_model VARCHAR,
                    embedding_model VARCHAR,
                    neo4j_uri VARCHAR,
                    neo4j_username VARCHAR,
                    neo4j_password VARCHAR
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
                    status VARCHAR NOT NULL,
                    node_count INTEGER NOT NULL,
                    edge_count INTEGER NOT NULL,
                    graph_workspace_label VARCHAR,
                    graph_storage_uri VARCHAR,
                    graph_storage_username VARCHAR,
                    graph_storage_password VARCHAR
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO settings_profiles (
                    id, provider, llm_model, embedding_model,
                    neo4j_uri, neo4j_username, neo4j_password
                )
                VALUES (
                    'default', 'openai-compatible', 'gpt-4o', 'text-embedding-3-large',
                    NULL, NULL, NULL
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO graph_projection_records (
                    id, document_id, runtime_profile_id, status,
                    node_count, edge_count, graph_storage_password
                )
                VALUES (
                    'projection-1', 'document-1', 'default', 'succeeded',
                    2, 1, 'legacy-secret'
                )
                """
            )
        )

    await init_db(engine)

    async with engine.begin() as connection:
        row = (
            await connection.execute(
                text(
                    """
                    SELECT graph_workspace_label,
                           graph_storage_uri,
                           graph_storage_username,
                           graph_storage_password
                    FROM graph_projection_records
                    WHERE id = 'projection-1'
                    """
                )
            )
        ).mappings().one()

    assert row["graph_workspace_label"] == "ragstudio_default"
    assert row["graph_storage_uri"] == "bolt://127.0.0.1:57687"
    assert row["graph_storage_username"] == "neo4j"
    assert row["graph_storage_password"] is None
    await engine.dispose()
```

- [ ] **Step 2: Run the failing migration test**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_db_engine.py::test_init_db_backfills_projection_target_from_settings_defaults_and_clears_password -q
```

Expected: FAIL because current backfill leaves URI/username null when raw profile fields are null and preserves `legacy-secret`.

- [ ] **Step 3: Import AppSettings in the DB engine**

In `backend/src/ragstudio/db/engine.py`, add this import after `from collections.abc import AsyncIterator`:

```python
from ragstudio.config import AppSettings
```

- [ ] **Step 4: Update `_backfill_graph_projection_targets()`**

Replace `_backfill_graph_projection_targets()` with:

```python
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
                       g.graph_storage_password,
                       s.neo4j_uri,
                       s.neo4j_username
                FROM graph_projection_records g
                LEFT JOIN settings_profiles s ON s.id = g.runtime_profile_id
                WHERE g.graph_workspace_label IS NULL
                   OR g.graph_storage_uri IS NULL
                   OR g.graph_storage_username IS NULL
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
                    graph_storage_uri = COALESCE(
                        graph_storage_uri,
                        :graph_storage_uri
                    ),
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
```

- [ ] **Step 5: Run the migration test**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_db_engine.py::test_init_db_backfills_projection_target_from_settings_defaults_and_clears_password -q
```

Expected: PASS.

- [ ] **Step 6: Run DB engine tests**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_db_engine.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/db/engine.py backend/tests/test_db_engine.py
git commit -m "fix: backfill graph targets without retained passwords"
```

---

### Task 4: Add Durable Cleanup State Columns

**Files:**
- Modify: `backend/src/ragstudio/db/models.py:141-162`
- Modify: `backend/src/ragstudio/db/engine.py:135-145`
- Test: `backend/tests/test_db_engine.py`

- [ ] **Step 1: Write the failing schema test**

Add this assertion block to the existing test in `backend/tests/test_db_engine.py` that checks graph projection columns:

```python
    assert "cleanup_status" in columns["graph_projection_records"]
    assert "cleanup_error" in columns["graph_projection_records"]
    assert "cleanup_attempted_at" in columns["graph_projection_records"]
```

- [ ] **Step 2: Run the failing schema test**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_db_engine.py -q
```

Expected: FAIL because the cleanup columns do not exist yet.

- [ ] **Step 3: Add ORM columns**

In `backend/src/ragstudio/db/models.py`, add these fields after `error` on `GraphProjectionRecord`:

```python
    cleanup_status: Mapped[str | None] = mapped_column(String, nullable=True)
    cleanup_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleanup_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
```

Confirm `datetime` and `DateTime` are already imported in the file. If `DateTime` is not imported, update the SQLAlchemy import to include it:

```python
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
```

- [ ] **Step 4: Add migration columns**

In `backend/src/ragstudio/db/engine.py`, extend the `graph_projection_records` additions map:

```python
            {
                "graph_workspace_label": "VARCHAR",
                "graph_storage_uri": "VARCHAR",
                "graph_storage_username": "VARCHAR",
                "graph_storage_password": "VARCHAR",
                "cleanup_status": "VARCHAR",
                "cleanup_error": "TEXT",
                "cleanup_attempted_at": _datetime_column(connection),
            },
```

- [ ] **Step 5: Run the schema test**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_db_engine.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/db/models.py backend/src/ragstudio/db/engine.py backend/tests/test_db_engine.py
git commit -m "fix: track graph cleanup state"
```

---

### Task 5: Persist Cleanup State Around External Neo4j Deletes

**Files:**
- Modify: `backend/src/ragstudio/services/graph_projection_runner.py:108-174`
- Test: `backend/tests/test_index_lifecycle_service.py`

- [ ] **Step 1: Write the failing cleanup-state success test**

Add this test near cleanup tests in `backend/tests/test_index_lifecycle_service.py`:

```python
@pytest.mark.asyncio
async def test_graph_projection_runner_marks_cleanup_succeeded(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
            )
        )
        document = Document(
            filename="graph-cleanup-state.txt",
            content_type="text/plain",
            sha256="graph-cleanup-state",
            artifact_path=str(app.state.settings.data_dir / "graph-cleanup-state.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        projection_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="default",
            status="succeeded",
            graph_workspace_label="ragstudio_default",
            graph_storage_uri="bolt://neo4j.test:7687",
            node_count=2,
            edge_count=1,
        )
        session.add(projection_record)
        await session.flush()

        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=FakeGraphMaterializationService(),
        ).delete_document_graph(document.id)
        refreshed = await session.get(GraphProjectionRecord, projection_record.id)

    assert result["status"] == "succeeded"
    assert refreshed is None
```

Add this second test to verify committed state survives when records are not removed by the caller:

```python
@pytest.mark.asyncio
async def test_graph_projection_runner_skips_already_cleaned_record(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        document = Document(
            filename="graph-cleaned-skip.txt",
            content_type="text/plain",
            sha256="graph-cleaned-skip",
            artifact_path=str(app.state.settings.data_dir / "graph-cleaned-skip.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        projection_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="removed-profile",
            status="succeeded",
            graph_workspace_label="ragstudio_removed_profile",
            graph_storage_uri="bolt://old-neo4j.test:7687",
            node_count=2,
            edge_count=1,
            cleanup_status="succeeded",
        )
        session.add(projection_record)
        await session.flush()

        fake = FakeGraphMaterializationService()
        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=fake,
        ).delete_document_graph(document.id)

    assert fake.delete_calls == []
    assert result == {
        "status": "succeeded",
        "node_count": 0,
        "edge_count": 0,
        "reason": None,
    }
```

- [ ] **Step 2: Run the cleanup-state tests**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_index_lifecycle_service.py::test_graph_projection_runner_marks_cleanup_succeeded backend/tests/test_index_lifecycle_service.py::test_graph_projection_runner_skips_already_cleaned_record -q
```

Expected: the second test fails because `cleanup_status="succeeded"` records are still considered for external deletion.

- [ ] **Step 3: Add cleanup helpers**

In `backend/src/ragstudio/services/graph_projection_runner.py`, add these imports:

```python
from datetime import UTC, datetime
```

Add these methods inside `GraphProjectionRunner` below `_delete_projection_records()`:

```python
    async def _mark_cleanup_running(self, record: GraphProjectionRecord) -> None:
        record.cleanup_status = "running"
        record.cleanup_error = None
        record.cleanup_attempted_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.commit()

    async def _mark_cleanup_succeeded(self, record: GraphProjectionRecord) -> None:
        record.cleanup_status = "succeeded"
        record.cleanup_error = None
        record.cleanup_attempted_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.commit()

    async def _mark_cleanup_failed(
        self,
        record: GraphProjectionRecord,
        error: str,
    ) -> None:
        record.cleanup_status = "failed"
        record.cleanup_error = error
        record.cleanup_attempted_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.commit()
```

Replace `_needs_graph_cleanup()` with:

```python
def _needs_graph_cleanup(record: GraphProjectionRecord) -> bool:
    if record.cleanup_status == "succeeded":
        return False
    if record.status == "succeeded":
        return True
    return record.node_count > 0 or record.edge_count > 0
```

- [ ] **Step 4: Mark records around external delete**

In `delete_document_graph()`, replace the external delete block:

```python
                result = await self.materialization_service.delete_document_graph(
                    document_id=document_id,
                    profile=self._profile_for_record(live_profile, target_record),
                )
                if result.status != "succeeded":
                    detail = f": {result.reason}" if result.reason else ""
                    raise GraphProjectionCleanupError(
                        f"Graph projection cleanup {result.status}{detail}"
                    )
                node_count += result.node_count
                edge_count += result.edge_count
```

with:

```python
                await self._mark_cleanup_running(target_record)
                result = await self.materialization_service.delete_document_graph(
                    document_id=document_id,
                    profile=self._profile_for_record(live_profile, target_record),
                )
                if result.status != "succeeded":
                    detail = f": {result.reason}" if result.reason else ""
                    message = f"Graph projection cleanup {result.status}{detail}"
                    await self._mark_cleanup_failed(target_record, message)
                    raise GraphProjectionCleanupError(message)
                await self._mark_cleanup_succeeded(target_record)
                node_count += result.node_count
                edge_count += result.edge_count
```

- [ ] **Step 5: Run cleanup-state tests**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_index_lifecycle_service.py::test_graph_projection_runner_marks_cleanup_succeeded backend/tests/test_index_lifecycle_service.py::test_graph_projection_runner_skips_already_cleaned_record -q
```

Expected: PASS.

- [ ] **Step 6: Run all graph projection runner tests**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_index_lifecycle_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/graph_projection_runner.py backend/tests/test_index_lifecycle_service.py
git commit -m "fix: persist graph cleanup progress"
```

---

### Task 6: Make Document Delete Retry-Safe After Local Deletion Failures

**Files:**
- Modify: `backend/src/ragstudio/services/document_service.py:137-158`
- Test: `backend/tests/test_documents.py`

- [ ] **Step 1: Write the failing document delete retry test**

Add this test near `test_delete_document_blocks_when_graph_projection_cleanup_fails` in `backend/tests/test_documents.py`:

```python
@pytest.mark.asyncio
async def test_delete_document_does_not_repeat_graph_cleanup_after_artifact_unlink_failure(
    client,
    tmp_path,
    monkeypatch,
):
    session_factory = client._transport.app.state.session_factory
    artifact = tmp_path / "uploads" / "graph-delete-unlink-fails"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("alpha", encoding="utf-8")
    async with session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
            )
        )
        document = Document(
            filename="graph-delete-unlink-fails.txt",
            content_type="text/plain",
            sha256="graph-delete-unlink-fails",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            GraphProjectionRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status="succeeded",
                graph_workspace_label="ragstudio_default",
                graph_storage_uri="bolt://neo4j.test:7687",
                node_count=1,
                edge_count=0,
            )
        )
        await session.commit()
        document_id = document.id

    original_unlink = Path.unlink
    calls = {"count": 0}

    def flaky_unlink(self, *args, **kwargs):
        if self == artifact and calls["count"] == 0:
            calls["count"] += 1
            raise OSError("unlink failed once")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    first_response = await client.delete(f"/api/documents/{document_id}")

    assert first_response.status_code == 500
    async with session_factory() as session:
        projection_record = await session.scalar(
            select(GraphProjectionRecord).where(GraphProjectionRecord.document_id == document_id)
        )
    assert projection_record is not None
    assert projection_record.cleanup_status == "succeeded"

    second_response = await client.delete(f"/api/documents/{document_id}")

    assert second_response.status_code == 204
    assert not artifact.exists()
```

If `Path` is not imported in `backend/tests/test_documents.py`, add:

```python
from pathlib import Path
```

- [ ] **Step 2: Run the failing document retry test**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_documents.py::test_delete_document_does_not_repeat_graph_cleanup_after_artifact_unlink_failure -q
```

Expected: FAIL until graph cleanup commits `cleanup_status="succeeded"` before artifact unlink and document delete preserves that state on rollback.

- [ ] **Step 3: Move SQL deletes after graph cleanup**

In `backend/src/ragstudio/services/document_service.py`, replace `delete_document()` with:

```python
    async def delete_document(self, document_id: str) -> DeleteDocumentResult:
        document = await self.session.get(Document, document_id)
        if document is None:
            return "not_found"

        artifact_path = Path(document.artifact_path)
        try:
            if self.settings is not None:
                await GraphProjectionRunner(
                    self.session,
                    self.settings,
                ).delete_document_graph(document.id)
            else:
                await self.session.execute(
                    delete(GraphProjectionRecord).where(
                        GraphProjectionRecord.document_id == document.id
                    )
                )
            await self.session.execute(
                delete(Job).where(Job.type == "index_document", Job.target_id == document.id)
            )
            await self.session.execute(
                delete(IndexRecord).where(IndexRecord.document_id == document.id)
            )
            await self.session.execute(
                delete(GraphProjectionRecord).where(
                    GraphProjectionRecord.document_id == document.id
                )
            )
            artifact_path.unlink(missing_ok=True)
            await self.session.delete(document)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return "deleted"
```

- [ ] **Step 4: Run the document retry test**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_documents.py::test_delete_document_does_not_repeat_graph_cleanup_after_artifact_unlink_failure -q
```

Expected: PASS.

- [ ] **Step 5: Run document deletion tests**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_documents.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/document_service.py backend/tests/test_documents.py
git commit -m "fix: make document graph cleanup retry safe"
```

---

### Task 7: Final Regression And Review Sweep

**Files:**
- Verify: `backend/src/ragstudio/services/graph_projection_runner.py`
- Verify: `backend/src/ragstudio/services/document_service.py`
- Verify: `backend/src/ragstudio/db/engine.py`
- Verify: `backend/src/ragstudio/db/models.py`
- Verify: `backend/tests/test_db_engine.py`
- Verify: `backend/tests/test_documents.py`
- Verify: `backend/tests/test_index_lifecycle_service.py`

- [ ] **Step 1: Run focused backend regression**

Run:

```bash
/Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_graph_materialization_service.py backend/tests/test_index_lifecycle_service.py backend/tests/test_retrieval_orchestrator.py backend/tests/test_documents.py backend/tests/test_optimizer_graph_diagnostics.py backend/tests/test_db_engine.py -q
```

Expected: PASS with at least the previously observed `102 passed` plus the new tests added in this plan.

- [ ] **Step 2: Run static diff checks**

Run:

```bash
git diff --check HEAD
```

Expected: no output.

- [ ] **Step 3: Inspect password storage references**

Run:

```bash
rg -n "graph_storage_password=profile.neo4j_password|graph_storage_password = COALESCE|graph_storage_password=\"old-password\"|graph_storage_password=\"do-not-copy\"" backend/src backend/tests
```

Expected: no matches for production password writes. Test fixtures may still contain legacy password values only in tests whose names explicitly cover legacy behavior.

- [ ] **Step 4: Inspect cleanup status references**

Run:

```bash
rg -n "cleanup_status|cleanup_error|cleanup_attempted_at" backend/src/ragstudio backend/tests
```

Expected: matches in `models.py`, `engine.py`, `graph_projection_runner.py`, and the new regression tests.

- [ ] **Step 5: Commit final adjustments if any**

If Step 1, Step 2, Step 3, or Step 4 required code or test corrections, commit them:

```bash
git add backend/src/ragstudio backend/tests
git commit -m "test: cover graph projection cleanup review fixes"
```

If no files changed after Step 4, do not create an empty commit.

---

## Self-Review

**Spec coverage:**
P1 fallback auth is covered by Task 2 and Task 3. P2 plaintext password duplication is covered by Task 1 and Task 3. P2 cleanup inconsistency is covered by Task 4, Task 5, and Task 6.

**Placeholder scan:**
No deferred-work markers or vague edge-case instructions are present. Every code-changing step includes concrete code.

**Type consistency:**
New ORM fields are consistently named `cleanup_status`, `cleanup_error`, and `cleanup_attempted_at`. Cleanup helper names are consistently `_mark_cleanup_running`, `_mark_cleanup_succeeded`, and `_mark_cleanup_failed`. Existing `graph_storage_password` remains nullable and legacy-only.
