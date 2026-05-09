# Require HPC MinerU Sidecar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make Ragstudio explicitly verify and use the configured MinerU sidecar in HPC/coordinator mode for strict MinerU parsing, instead of silently accepting a local-mode sidecar that can sit at 25%.

**Architecture:** Ragstudio already sends PDFs to `mineru_base_url` using the sidecar API (`POST /parse-async`, `GET /parse-jobs/{job_id}`, `GET /parse-jobs/{job_id}/artifacts`). This plan adds a typed sidecar health contract, stores a setting that requires HPC/coordinator mode by default, and preflights strict MinerU jobs before upload/reindex work is queued. If the sidecar reports `hpcMineru.enabled=false` or `mode=local`, Ragstudio fails early with an actionable message rather than creating a long-running job that appears stuck.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic, httpx, React, Vitest, pytest, Docker Compose.

---

## File Structure

- Modify `backend/src/ragstudio/services/mineru_client.py`
  - Owns the sidecar HTTP contract. Add `MinerUSidecarHealth` and `MinerUClient.health()` so every caller interprets `/health` consistently.
- Modify `backend/src/ragstudio/schemas/settings.py`
  - Add `mineru_require_hpc: bool = True` to input/output schemas.
- Modify `backend/src/ragstudio/db/models.py`
  - Persist `mineru_require_hpc` on `SettingsProfile`.
- Modify `backend/src/ragstudio/db/engine.py`
  - Backfill `mineru_require_hpc` for existing databases.
- Modify `backend/src/ragstudio/services/settings_service.py`
  - Round-trip the new setting and default it to `True`.
- Modify `backend/src/ragstudio/services/provider_manifest_service.py`
  - Keep `mineru_require_hpc=True` when applying an `hpcMineru` manifest section.
- Modify `backend/src/ragstudio/api/routes/settings.py`
  - Make `Test MinerU` show whether the endpoint is HPC/coordinator or local-only.
- Modify `backend/src/ragstudio/services/chunk_service.py`
  - Before submitting strict MinerU work, call the sidecar health check and block if HPC is required but unavailable.
- Modify `frontend/src/api/generated.ts`
  - Add `mineru_require_hpc` to generated/manual settings types.
- Modify `frontend/src/features/settings/settings-page.tsx`
  - Add a setting checkbox for requiring HPC/coordinator MinerU.
- Modify `frontend/tests/settings-page.test.tsx`
  - Cover the new setting in render and submit flows.
- Modify `backend/tests/test_mineru_client.py`
  - Add health contract tests.
- Modify `backend/tests/test_settings.py`
  - Cover settings round-trip, provider preview, and `Test MinerU` health messaging.
- Modify `backend/tests/test_mineru_reindex_jobs.py`
  - Cover strict MinerU blocking when the sidecar is local-only.
- Modify `docs/user-guide.md`
  - Explain that strict MinerU requires a sidecar reporting `hpcMineru.enabled=true` unless the user disables the guard.

---

### Task 1: Add Typed MinerU Sidecar Health Contract

**Files:**
- Modify: `backend/src/ragstudio/services/mineru_client.py`
- Test: `backend/tests/test_mineru_client.py`

- [x] **Step 1: Write failing health tests**

Append these tests to `backend/tests/test_mineru_client.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_mineru_client_health_reads_hpc_coordinator(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ready": True,
                "detail": "RAG-Anything sidecar ready",
                "version": "hybrid",
                "hpcMineru": {"enabled": True, "mode": "coordinator"},
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url):
            requests.append({"url": url, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr("ragstudio.services.mineru_client.httpx.AsyncClient", FakeAsyncClient)

    health = await MinerUClient(
        base_url="http://mineru.test",
        timeout_ms=2000,
        poll_interval_ms=100,
    ).health()

    assert requests == [{"url": "http://mineru.test/health", "timeout": 2.0}]
    assert health.ready is True
    assert health.detail == "RAG-Anything sidecar ready"
    assert health.hpc_enabled is True
    assert health.hpc_mode == "coordinator"
    assert health.is_hpc_coordinator is True


@pytest.mark.asyncio
async def test_mineru_client_health_reads_local_sidecar(monkeypatch):
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ready": True,
                "detail": "RAG-Anything sidecar ready",
                "hpcMineru": {"enabled": False, "mode": "local"},
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr("ragstudio.services.mineru_client.httpx.AsyncClient", FakeAsyncClient)

    health = await MinerUClient(
        base_url="http://mineru.test",
        timeout_ms=2000,
        poll_interval_ms=100,
    ).health()

    assert health.ready is True
    assert health.hpc_enabled is False
    assert health.hpc_mode == "local"
    assert health.is_hpc_coordinator is False
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
docker compose run --rm --no-deps -T \
  -v /Users/meet/Documents/Ragstudio/backend/src:/app/backend/src \
  -v /Users/meet/Documents/Ragstudio/backend/tests:/app/backend/tests \
  --entrypoint '' backend \
  python -m pytest backend/tests/test_mineru_client.py::test_mineru_client_health_reads_hpc_coordinator backend/tests/test_mineru_client.py::test_mineru_client_health_reads_local_sidecar -q
```

Expected: FAIL with `AttributeError: 'MinerUClient' object has no attribute 'health'`.

- [x] **Step 3: Implement the health contract**

In `backend/src/ragstudio/services/mineru_client.py`, add this dataclass after `MinerUJobResult`:

```python
@dataclass(frozen=True)
class MinerUSidecarHealth:
    ready: bool
    detail: str
    version: str | None
    hpc_enabled: bool
    hpc_mode: str | None
    raw: dict[str, Any]

    @property
    def is_hpc_coordinator(self) -> bool:
        return self.ready and self.hpc_enabled and self.hpc_mode == "coordinator"
```

Add this method inside `MinerUClient`:

```python
    async def health(self) -> MinerUSidecarHealth:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f"{self.base_url}/health")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            payload = {}
        hpc = payload.get("hpcMineru")
        hpc_payload = hpc if isinstance(hpc, dict) else {}
        return MinerUSidecarHealth(
            ready=bool(payload.get("ready")),
            detail=str(payload.get("detail") or payload.get("status") or ""),
            version=str(payload["version"]) if payload.get("version") is not None else None,
            hpc_enabled=bool(hpc_payload.get("enabled")),
            hpc_mode=str(hpc_payload["mode"]) if hpc_payload.get("mode") is not None else None,
            raw=payload,
        )
```

- [x] **Step 4: Run tests to verify they pass**

Run the same command from Step 2.

Expected: PASS with `2 passed`.

- [x] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/mineru_client.py backend/tests/test_mineru_client.py
git commit -m "feat: add mineru sidecar health contract"
```

---

### Task 2: Persist Require-HPC MinerU Setting

**Files:**
- Modify: `backend/src/ragstudio/schemas/settings.py`
- Modify: `backend/src/ragstudio/db/models.py`
- Modify: `backend/src/ragstudio/db/engine.py`
- Modify: `backend/src/ragstudio/services/settings_service.py`
- Test: `backend/tests/test_settings.py`
- Test: `backend/tests/test_db_engine.py`

- [x] **Step 1: Write failing settings round-trip test**

In `backend/tests/test_settings.py`, update `test_settings_profile_saves_mineru_config` payload and assertions:

```python
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "postgres_pgvector_neo4j",
        "mineru_enabled": True,
        "mineru_base_url": "http://127.0.0.1:8765/",
        "mineru_timeout_ms": 120000,
        "mineru_poll_interval_ms": 500,
        "mineru_require_hpc": True,
    }
```

Add this assertion:

```python
    assert body["mineru_require_hpc"] is True
```

- [x] **Step 2: Write failing DB backfill assertion**

In `backend/tests/test_db_engine.py`, update the settings row query:

```python
                    SELECT runtime_mode, storage_backend, pgvector_schema,
                           enable_image_processing, mineru_timeout_ms,
                           mineru_require_hpc
                    FROM settings_profiles WHERE id = 'default'
```

Add these assertions:

```python
    assert settings_row["mineru_require_hpc"] in (1, True)
    assert settings.mineru_require_hpc is True
```

- [x] **Step 3: Run tests to verify they fail**

Run:

```bash
docker compose run --rm --no-deps -T \
  -v /Users/meet/Documents/Ragstudio/backend/src:/app/backend/src \
  -v /Users/meet/Documents/Ragstudio/backend/tests:/app/backend/tests \
  --entrypoint '' backend \
  python -m pytest backend/tests/test_settings.py::test_settings_profile_saves_mineru_config backend/tests/test_db_engine.py::test_init_db_backfills_runtime_columns_for_existing_sqlite_tables -q
```

Expected: FAIL because `mineru_require_hpc` does not exist in schemas/models.

- [x] **Step 4: Add schema/model/DB field**

In `backend/src/ragstudio/schemas/settings.py`, add to `SettingsProfileIn` after `mineru_poll_interval_ms`:

```python
    mineru_require_hpc: bool = True
```

Add to `SettingsProfileOut` after `mineru_poll_interval_ms`:

```python
    mineru_require_hpc: bool
```

In `backend/src/ragstudio/db/models.py`, add to `SettingsProfile` after `mineru_poll_interval_ms`:

```python
    mineru_require_hpc: Mapped[bool] = mapped_column(Boolean, default=True)
```

In `backend/src/ragstudio/db/engine.py`, add to the `settings_profiles` additions dict after `mineru_poll_interval_ms`:

```python
                "mineru_require_hpc": _bool_column(connection, True),
```

In `_normalize_settings_profile_values`, add:

```python
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET mineru_require_hpc = 1
            WHERE mineru_require_hpc IS NULL
            """
        )
    )
```

In `backend/src/ragstudio/services/settings_service.py`, add to `_to_out`:

```python
            mineru_require_hpc=default_bool(profile.mineru_require_hpc, True),
```

- [x] **Step 5: Run tests to verify they pass**

Run the same command from Step 3.

Expected: PASS with `2 passed`.

- [x] **Step 6: Commit**

```bash
git add backend/src/ragstudio/schemas/settings.py backend/src/ragstudio/db/models.py backend/src/ragstudio/db/engine.py backend/src/ragstudio/services/settings_service.py backend/tests/test_settings.py backend/tests/test_db_engine.py
git commit -m "feat: persist mineru hpc requirement"
```

---

### Task 3: Block Strict MinerU When Sidecar Is Local-Only

**Files:**
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Test: `backend/tests/test_mineru_reindex_jobs.py`

- [x] **Step 1: Write failing strict-mode guard test**

Append to `backend/tests/test_mineru_reindex_jobs.py`:

```python
@pytest.mark.asyncio
async def test_mineru_strict_blocks_when_sidecar_is_local_only(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}")
    await init_db(engine)
    factory = make_session_factory(engine)

    class LocalHealthClient:
        def __init__(self, base_url, timeout_ms, poll_interval_ms):
            self.base_url = base_url
            self.timeout_ms = timeout_ms
            self.poll_interval_ms = poll_interval_ms

        async def health(self):
            from ragstudio.services.mineru_client import MinerUSidecarHealth

            return MinerUSidecarHealth(
                ready=True,
                detail="RAG-Anything sidecar ready",
                version="hybrid",
                hpc_enabled=False,
                hpc_mode="local",
                raw={"hpcMineru": {"enabled": False, "mode": "local"}},
            )

        async def parse_document(self, **kwargs):
            raise AssertionError("parse_document must not be called when HPC is required")

    async with factory() as session:
        artifact = tmp_path / "quran.pdf"
        artifact.write_bytes(b"%PDF-1.4")
        document = Document(
            filename="quran.pdf",
            content_type="application/pdf",
            sha256="sha",
            artifact_path=str(artifact),
            status=StageStatus.READY.value,
        )
        settings = SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="gpt-4o",
            embedding_model="fallback",
            storage_backend="fallback_local",
            mineru_enabled=True,
            mineru_base_url="http://10.10.9.19:8765",
            mineru_require_hpc=True,
        )
        session.add_all([document, settings])
        await session.commit()

        with pytest.raises(RuntimeError, match="MinerU sidecar is not in HPC coordinator mode"):
            await ChunkService(
                session,
                tmp_path,
                mineru_client_factory=LocalHealthClient,
            ).index_document(
                document.id,
                options=IndexDocumentIn(parser_mode="mineru_strict"),
            )

    await engine.dispose()
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
docker compose run --rm --no-deps -T \
  -v /Users/meet/Documents/Ragstudio/backend/src:/app/backend/src \
  -v /Users/meet/Documents/Ragstudio/backend/tests:/app/backend/tests \
  --entrypoint '' backend \
  python -m pytest backend/tests/test_mineru_reindex_jobs.py::test_mineru_strict_blocks_when_sidecar_is_local_only -q
```

Expected: FAIL because `ChunkService` does not accept `mineru_client_factory` and does not preflight `/health`.

- [x] **Step 3: Add injectable MinerU client factory**

In `backend/src/ragstudio/services/chunk_service.py`, update `__init__`:

```python
    def __init__(
        self,
        session: AsyncSession,
        data_dir: Path,
        adapter: RAGAnythingAdapter | None = None,
        mineru_client_factory: type[MinerUClient] = MinerUClient,
    ):
        self.session = session
        self.data_dir = data_dir
        self.adapter = adapter or RAGAnythingAdapter()
        self.mineru_client_factory = mineru_client_factory
```

Replace `client = MinerUClient(` with:

```python
        client = self.mineru_client_factory(
            base_url=settings.mineru_base_url,
            timeout_ms=settings.mineru_timeout_ms or 14_400_000,
            poll_interval_ms=settings.mineru_poll_interval_ms or 1_000,
        )
```

- [x] **Step 4: Add HPC preflight before parse submission**

In `_mineru_adapter_chunks`, after constructing `client`, add:

```python
        health = await client.health()
        if settings.mineru_require_hpc and not health.is_hpc_coordinator:
            mode = health.hpc_mode or "unknown"
            raise RuntimeError(
                "MinerU sidecar is not in HPC coordinator mode. "
                f"Health detail: {health.detail or 'no detail'}; "
                f"hpcMineru.enabled={health.hpc_enabled}; mode={mode}. "
                "Start the HPC MinerU sidecar/coordinator or disable 'Require HPC MinerU coordinator' in Settings."
            )
```

- [x] **Step 5: Run test to verify it passes**

Run the same command from Step 2.

Expected: PASS with `1 passed`.

- [x] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/chunk_service.py backend/tests/test_mineru_reindex_jobs.py
git commit -m "feat: require hpc mineru sidecar for strict parsing"
```

---

### Task 4: Surface HPC/Local Sidecar Status in Settings Test MinerU

**Files:**
- Modify: `backend/src/ragstudio/api/routes/settings.py`
- Test: `backend/tests/test_settings.py`

- [x] **Step 1: Write failing route tests**

Append to `backend/tests/test_settings.py`:

```python
@pytest.mark.asyncio
async def test_mineru_connection_test_reports_hpc_mode(client, monkeypatch):
    class FakeClient:
        def __init__(self, base_url, timeout_ms, poll_interval_ms):
            self.base_url = base_url

        async def health(self):
            from ragstudio.services.mineru_client import MinerUSidecarHealth

            return MinerUSidecarHealth(
                ready=True,
                detail="RAG-Anything sidecar ready",
                version="hybrid",
                hpc_enabled=True,
                hpc_mode="coordinator",
                raw={},
            )

    monkeypatch.setattr("ragstudio.api.routes.settings.MinerUClient", FakeClient)
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "postgres_pgvector_neo4j",
        "mineru_enabled": True,
        "mineru_base_url": "http://10.10.9.19:8765",
        "mineru_require_hpc": True,
    }

    response = await client.post("/api/settings/default/test-mineru", json=payload)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "HPC coordinator mode" in response.json()["detail"]


@pytest.mark.asyncio
async def test_mineru_connection_test_rejects_local_mode_when_required(client, monkeypatch):
    class FakeClient:
        def __init__(self, base_url, timeout_ms, poll_interval_ms):
            self.base_url = base_url

        async def health(self):
            from ragstudio.services.mineru_client import MinerUSidecarHealth

            return MinerUSidecarHealth(
                ready=True,
                detail="RAG-Anything sidecar ready",
                version="hybrid",
                hpc_enabled=False,
                hpc_mode="local",
                raw={},
            )

    monkeypatch.setattr("ragstudio.api.routes.settings.MinerUClient", FakeClient)
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "postgres_pgvector_neo4j",
        "mineru_enabled": True,
        "mineru_base_url": "http://10.10.9.19:8765",
        "mineru_require_hpc": True,
    }

    response = await client.post("/api/settings/default/test-mineru", json=payload)

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "local mode" in response.json()["detail"]
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
docker compose run --rm --no-deps -T \
  -v /Users/meet/Documents/Ragstudio/backend/src:/app/backend/src \
  -v /Users/meet/Documents/Ragstudio/backend/tests:/app/backend/tests \
  --entrypoint '' backend \
  python -m pytest backend/tests/test_settings.py::test_mineru_connection_test_reports_hpc_mode backend/tests/test_settings.py::test_mineru_connection_test_rejects_local_mode_when_required -q
```

Expected: FAIL because the settings route uses raw `httpx` and does not know `mineru_require_hpc`.

- [x] **Step 3: Update settings route to use MinerUClient.health**

In `backend/src/ragstudio/api/routes/settings.py`, add:

```python
from ragstudio.services.mineru_client import MinerUClient
```

Replace the body of `test_mineru_settings` after the empty URL check with:

```python
    started = time.perf_counter()
    try:
        health = await MinerUClient(
            base_url=base_url,
            timeout_ms=payload.mineru_timeout_ms,
            poll_interval_ms=payload.mineru_poll_interval_ms,
        ).health()
        latency_ms = int((time.perf_counter() - started) * 1000)
        if not health.ready:
            return MinerUConnectionTestOut(
                ok=False,
                base_url=base_url,
                latency_ms=latency_ms,
                detail=health.detail or "MinerU sidecar is not ready.",
            )
        if payload.mineru_require_hpc and not health.is_hpc_coordinator:
            return MinerUConnectionTestOut(
                ok=False,
                base_url=base_url,
                latency_ms=latency_ms,
                detail=(
                    "MinerU sidecar is reachable but reports local mode. "
                    f"hpcMineru.enabled={health.hpc_enabled}; mode={health.hpc_mode or 'unknown'}. "
                    "Start the HPC coordinator sidecar or disable the HPC requirement."
                ),
            )
        mode_detail = (
            "HPC coordinator mode"
            if health.is_hpc_coordinator
            else f"{health.hpc_mode or 'unknown'} mode"
        )
        return MinerUConnectionTestOut(
            ok=True,
            base_url=base_url,
            latency_ms=latency_ms,
            detail=f"{health.detail or 'MinerU health check succeeded.'} ({mode_detail}).",
        )
    except httpx.HTTPError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return MinerUConnectionTestOut(
            ok=False,
            base_url=base_url,
            latency_ms=latency_ms,
            detail=f"MinerU health check failed: {exc}",
        )
```

- [x] **Step 4: Run tests to verify they pass**

Run the same command from Step 2.

Expected: PASS with `2 passed`.

- [x] **Step 5: Commit**

```bash
git add backend/src/ragstudio/api/routes/settings.py backend/tests/test_settings.py
git commit -m "feat: report mineru sidecar mode in settings"
```

---

### Task 5: Wire Require-HPC Setting in Frontend

**Files:**
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/features/settings/settings-page.tsx`
- Test: `frontend/tests/settings-page.test.tsx`

- [x] **Step 1: Write failing frontend test**

In `frontend/tests/settings-page.test.tsx`, add `mineru_require_hpc: true` to the `settings` object.

Append this test:

```tsx
  it("submits the MinerU HPC requirement setting", async () => {
    renderSettings();

    const checkbox = await screen.findByLabelText("Require HPC MinerU coordinator");
    expect(checkbox).toBeChecked();

    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(apiClient.updateDefaultSettings).toHaveBeenCalledWith(
        expect.objectContaining({ mineru_require_hpc: false }),
      ),
    );
  });
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
docker compose run --rm --no-deps -T \
  -v /Users/meet/Documents/Ragstudio/frontend/src:/app/frontend/src \
  -v /Users/meet/Documents/Ragstudio/frontend/tests:/app/frontend/tests \
  frontend npm run test -- --run tests/settings-page.test.tsx
```

Expected: FAIL because the checkbox does not exist.

- [x] **Step 3: Update frontend types/defaults**

In `frontend/src/api/generated.ts`, add to `SettingsProfileIn` and `SettingsProfileOut`:

```ts
  mineru_require_hpc: boolean;
```

In `frontend/src/features/settings/settings-page.tsx`, add to `DEFAULT_FORM_VALUES`:

```ts
  mineru_require_hpc: true,
```

In `toFormValues`, add:

```ts
    mineru_require_hpc: settings.mineru_require_hpc,
```

In the save payload builder near the other MinerU fields, add:

```ts
      mineru_require_hpc: formValues.mineru_require_hpc ?? true,
```

- [x] **Step 4: Add the checkbox below poll interval**

In the MinerU parser settings grid in `frontend/src/features/settings/settings-page.tsx`, after the poll interval `Field`, add:

```tsx
            <label className="flex h-10 items-center gap-2 self-end rounded-md border border-[#cfd8dd] px-3 text-sm font-medium text-[#3a4a53]">
              <input
                name="mineru_require_hpc"
                type="checkbox"
                checked={formValues?.mineru_require_hpc ?? true}
                onChange={(event) => updateField("mineru_require_hpc", event.target.checked)}
                disabled={busy}
              />
              Require HPC MinerU coordinator
            </label>
```

- [x] **Step 5: Run frontend tests**

Run the same command from Step 2.

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add frontend/src/api/generated.ts frontend/src/features/settings/settings-page.tsx frontend/tests/settings-page.test.tsx
git commit -m "feat: expose mineru hpc requirement setting"
```

---

### Task 6: Provider Manifest Keeps HPC Requirement Enabled

**Files:**
- Modify: `backend/src/ragstudio/services/provider_manifest_service.py`
- Test: `backend/tests/test_settings.py`

- [x] **Step 1: Write failing provider preview assertion**

In `backend/tests/test_settings.py`, inside `test_provider_sync_preview_maps_manifest_without_persisting`, add:

```python
    assert body["patch"]["mineru_require_hpc"] is True
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
docker compose run --rm --no-deps -T \
  -v /Users/meet/Documents/Ragstudio/backend/src:/app/backend/src \
  -v /Users/meet/Documents/Ragstudio/backend/tests:/app/backend/tests \
  --entrypoint '' backend \
  python -m pytest backend/tests/test_settings.py::test_provider_sync_preview_maps_manifest_without_persisting -q
```

Expected: FAIL because the patch does not include `mineru_require_hpc`.

- [x] **Step 3: Set the patch value when `hpcMineru` is enabled**

In `backend/src/ragstudio/services/provider_manifest_service.py`, inside the `if isinstance(mineru, dict):` block after `if isinstance(enabled, bool):`, add:

```python
                if enabled:
                    patch["mineru_require_hpc"] = True
```

- [x] **Step 4: Run test to verify it passes**

Run the same command from Step 2.

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/provider_manifest_service.py backend/tests/test_settings.py
git commit -m "feat: preserve hpc mineru requirement from manifest"
```

---

### Task 7: Update User Guide and Run Full Verification

**Files:**
- Modify: `docs/user-guide.md`
- Test: backend and frontend targeted suites

- [x] **Step 1: Update docs**

In `docs/user-guide.md`, replace the MinerU settings paragraph with:

```markdown
Settings includes a `MinerU parser` section for connecting to an already running MinerU/RAG-Anything sidecar. Set the base URL, normally `http://127.0.0.1:8765` when using an SSH tunnel or local sidecar, then click `Test MinerU`.

For `MinerU strict`, Ragstudio requires the sidecar health response to report `hpcMineru.enabled=true` and `hpcMineru.mode=coordinator` by default. If the sidecar reports `mode=local`, strict parsing is blocked before a job is queued because large PDFs can appear stuck at `25%` while local MinerU parsing runs inside the sidecar process. Disable `Require HPC MinerU coordinator` only when you intentionally want the sidecar to parse locally and accept the longer single-process runtime.
```

- [x] **Step 2: Run backend tests**

Run:

```bash
docker compose run --rm --no-deps -T \
  -v /Users/meet/Documents/Ragstudio/backend/src:/app/backend/src \
  -v /Users/meet/Documents/Ragstudio/backend/tests:/app/backend/tests \
  --entrypoint '' backend \
  python -m pytest \
    backend/tests/test_mineru_client.py \
    backend/tests/test_mineru_reindex_jobs.py \
    backend/tests/test_settings.py \
    backend/tests/test_db_engine.py \
    backend/tests/test_documents.py \
    -q
```

Expected: PASS.

- [x] **Step 3: Run frontend tests**

Run:

```bash
docker compose run --rm --no-deps -T \
  -v /Users/meet/Documents/Ragstudio/frontend/src:/app/frontend/src \
  -v /Users/meet/Documents/Ragstudio/frontend/tests:/app/frontend/tests \
  frontend npm run test -- --run tests/settings-page.test.tsx tests/documents-page.test.tsx
```

Expected: PASS.

- [x] **Step 4: Run live sidecar check**

With the current sidecar at `http://10.10.9.19:8765`, run:

```bash
curl -sS http://10.10.9.19:8765/health
```

Expected while the current issue exists:

```json
{"ready":true,"detail":"RAG-Anything sidecar ready at /home/jihadaj/ModelTraining/data/rag-anything-hpc","version":"hybrid","hpcMineru":{"enabled":false,"mode":"local"}}
```

Then run `Test MinerU` in Settings with `Require HPC MinerU coordinator` enabled.

Expected: UI reports reachable but local mode, and strict uploads/reindexing are blocked before queuing.

- [x] **Step 5: Commit docs and verification note**

```bash
git add docs/user-guide.md
git commit -m "docs: explain hpc mineru sidecar requirement"
```

---

## Self-Review

**Spec coverage:** The plan addresses the observed question, “Ragstudio to use the sidecar?”, by clarifying that Ragstudio already uses the configured sidecar API and adding a guard that requires the sidecar to be the HPC/coordinator sidecar for strict MinerU. It covers backend health contract, DB/schema persistence, settings test UX, strict indexing behavior, provider sync, frontend controls, and docs.

**Placeholder scan:** No task contains placeholder implementation text. Every code step includes concrete snippets and exact commands.

**Type consistency:** The plan consistently uses `mineru_require_hpc`, `MinerUSidecarHealth`, `health.is_hpc_coordinator`, `hpc_enabled`, and `hpc_mode` across backend, frontend, and tests.
