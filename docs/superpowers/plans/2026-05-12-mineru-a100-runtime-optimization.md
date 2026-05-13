# MinerU A100 Runtime Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Ragstudio carry A100-oriented MinerU/RAG-Anything parser settings from provider sync and Settings into every strict MinerU parse request, then surface the active parser capacity in health checks and docs.

**Architecture:** Ragstudio remains MinerU-strict at ingestion and keeps Postgres chunks as the source of truth. The backend stores a small MinerU parser tuning profile on `SettingsProfile`, maps optional `hpcMineru` manifest hints into that profile, and serializes those hints into the existing `/parse-async` metadata body so the external HPC coordinator can run RAG-Anything/MinerU with `backend`, `device`, `formula`, `table`, `lang`, `source`, and concurrency settings. The frontend exposes only operational fields that map directly to upstream RAG-Anything/MinerU kwargs; it does not manage Slurm or GPU jobs directly.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy, Postgres, httpx, React, TypeScript, TanStack Query, Vitest, pytest, RAG-Anything 1.3.0, MinerU.

---

## Upstream And Local Facts

- Upstream RAG-Anything `main` exposes `RAGAnythingConfig.max_concurrent_files`, context settings, parser selection, and multimodal processing flags in `raganything/config.py`.
- Upstream MinerU parser kwargs include `backend`, `device`, `lang`, `start_page`, `end_page`, `formula`, `table`, `source`, `vlm_url`, and `timeout` in `raganything/parser.py`.
- Upstream README shows GPU MinerU parsing as `mineru -p input.pdf -o output_dir -m auto -b pipeline --device cuda`.
- Upstream batch docs recommend worker tuning, with lower worker counts for large files and explicit `timeout_per_file`.
- Ragstudio currently stores only `mineru_enabled`, `mineru_base_url`, `mineru_timeout_ms`, `mineru_poll_interval_ms`, and `mineru_require_hpc` for the strict MinerU sidecar.
- Ragstudio `MinerUClient.submit_parse()` already sends a JSON `metadata` form field. This plan extends that metadata and keeps the existing `domainMetadata` shape intact.

Sources:
- https://github.com/HKUDS/RAG-Anything
- https://raw.githubusercontent.com/HKUDS/RAG-Anything/main/docs/batch_processing.md
- https://raw.githubusercontent.com/HKUDS/RAG-Anything/main/docs/context_aware_processing.md
- https://raw.githubusercontent.com/HKUDS/RAG-Anything/main/docs/vllm_integration.md

## File Structure

- `backend/src/ragstudio/db/models.py`: owns persisted runtime profile columns. Add MinerU parser tuning columns here.
- `backend/src/ragstudio/db/engine.py`: owns lightweight in-place schema backfill for existing databases. Add the same columns and normalize old rows.
- `backend/src/ragstudio/schemas/settings.py`: owns public Settings API input/output types. Add typed MinerU tuning fields and strict value normalization.
- `backend/src/ragstudio/services/settings_service.py`: converts database rows to API responses and normalizes incoming values.
- `backend/src/ragstudio/services/provider_manifest_service.py`: maps hosted provider manifests to Settings preview patches. Extend `hpcMineru` parsing.
- `backend/src/ragstudio/services/mineru_client.py`: owns the HTTP contract to the sidecar. Add a focused `MinerUParseOptions` dataclass and serialize options into `metadata`.
- `backend/src/ragstudio/services/document_parser_service.py`: reads the active settings profile and passes parse options into `MinerUClient`.
- `backend/src/ragstudio/api/routes/settings.py`: formats MinerU health checks. Surface optimization/capacity details returned by the sidecar.
- `frontend/src/api/generated.ts`: manual API type mirror used by the frontend tests. Add Settings and health fields.
- `frontend/src/features/settings/settings-page.tsx`: Settings control surface. Add MinerU parser tuning inputs and preserve save/test behavior.
- `frontend/tests/settings-page.test.tsx`: UI regression coverage for sync, save, and health output.
- `backend/tests/test_settings.py`: backend Settings/provider-sync/MinerU-health tests.
- `backend/tests/test_mineru_client.py`: sidecar request metadata tests.
- `backend/tests/test_document_parser_service.py`: verifies profile settings flow into parse requests.
- `backend/tests/test_db_engine.py`: migration/backfill coverage for existing settings tables.
- `docs/user-guide.md` and `docs/workflows.md`: user-facing docs for A100/RAG-Anything settings.

## Parser Field Contract

Use these exact field names across backend, frontend, tests, docs, and manifest mapping:

```text
mineru_backend              string, default "pipeline"
mineru_device               string, default "cuda:0"
mineru_lang                 string | null, default null
mineru_formula              boolean, default true
mineru_table                boolean, default true
mineru_source               string | null, default null
mineru_max_concurrent_files integer, default 1, range 1..8
```

Use this exact sidecar metadata shape:

```json
{
  "mimeType": "application/pdf",
  "domainMetadata": {},
  "ragAnything": {
    "parser": "mineru",
    "parseMethod": "auto",
    "parserKwargs": {
      "backend": "pipeline",
      "device": "cuda:0",
      "formula": true,
      "table": true,
      "lang": "en",
      "source": "huggingface"
    },
    "maxConcurrentFiles": 2
  }
}
```

Omit `lang` and `source` from `parserKwargs` when they are blank. Keep `maxConcurrentFiles` inside `ragAnything` because upstream RAG-Anything treats it as a config/batch value, not a MinerU CLI kwarg.

### Task 1: Persist MinerU Parser Tuning In Settings

**Files:**
- Modify: `backend/src/ragstudio/db/models.py`
- Modify: `backend/src/ragstudio/db/engine.py`
- Modify: `backend/src/ragstudio/schemas/settings.py`
- Modify: `backend/src/ragstudio/services/settings_service.py`
- Test: `backend/tests/test_settings.py`
- Test: `backend/tests/test_db_engine.py`

- [ ] **Step 1: Write the failing Settings round-trip test**

Append this test to `backend/tests/test_settings.py` after `test_settings_profile_saves_mineru_config`:

```python
@pytest.mark.asyncio
async def test_settings_profile_saves_mineru_a100_parser_tuning(client):
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "postgres_pgvector_neo4j",
        "mineru_enabled": True,
        "mineru_base_url": "http://127.0.0.1:8765",
        "mineru_backend": "pipeline",
        "mineru_device": "cuda:0",
        "mineru_lang": "en",
        "mineru_formula": True,
        "mineru_table": True,
        "mineru_source": "huggingface",
        "mineru_max_concurrent_files": 2,
    }

    response = await client.put("/api/settings/default", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["mineru_backend"] == "pipeline"
    assert body["mineru_device"] == "cuda:0"
    assert body["mineru_lang"] == "en"
    assert body["mineru_formula"] is True
    assert body["mineru_table"] is True
    assert body["mineru_source"] == "huggingface"
    assert body["mineru_max_concurrent_files"] == 2
```

- [ ] **Step 2: Run the new Settings test and verify it fails**

Run:

```bash
./.venv/bin/pytest backend/tests/test_settings.py::test_settings_profile_saves_mineru_a100_parser_tuning -q
```

Expected: FAIL with a `422` response or missing `mineru_backend` response field because the API schema does not know the new fields yet.

- [ ] **Step 3: Add failing database migration coverage**

In `backend/tests/test_db_engine.py`, add these assertions to the existing legacy settings migration test that inspects `settings_profiles` columns. If the exact test name has shifted, use the test that creates an old `settings_profiles` table and calls `init_db(engine)`.

```python
assert row["mineru_backend"] == "pipeline"
assert row["mineru_device"] == "cuda:0"
assert row["mineru_formula"] is True
assert row["mineru_table"] is True
assert row["mineru_max_concurrent_files"] == 1
```

If the test currently selects an explicit column list, extend that SQL selection:

```sql
SELECT mineru_backend,
       mineru_device,
       mineru_formula,
       mineru_table,
       mineru_max_concurrent_files
FROM settings_profiles
WHERE id = 'default'
```

- [ ] **Step 4: Run the database migration test and verify it fails**

Run:

```bash
./.venv/bin/pytest backend/tests/test_db_engine.py -q
```

Expected: FAIL with a missing column such as `mineru_backend`.

- [ ] **Step 5: Add database columns**

In `backend/src/ragstudio/db/models.py`, add these columns immediately after `mineru_require_hpc`:

```python
    mineru_backend: Mapped[str] = mapped_column(String, default="pipeline")
    mineru_device: Mapped[str] = mapped_column(String, default="cuda:0")
    mineru_lang: Mapped[str | None] = mapped_column(String, nullable=True)
    mineru_formula: Mapped[bool] = mapped_column(Boolean, default=True)
    mineru_table: Mapped[bool] = mapped_column(Boolean, default=True)
    mineru_source: Mapped[str | None] = mapped_column(String, nullable=True)
    mineru_max_concurrent_files: Mapped[int] = mapped_column(Integer, default=1)
```

In `backend/src/ragstudio/db/engine.py`, add the same columns to the `_ensure_runtime_columns()` `settings_profiles` additions dictionary immediately after `mineru_require_hpc`:

```python
                "mineru_backend": "VARCHAR DEFAULT 'pipeline' NOT NULL",
                "mineru_device": "VARCHAR DEFAULT 'cuda:0' NOT NULL",
                "mineru_lang": "VARCHAR",
                "mineru_formula": _bool_column(connection, True),
                "mineru_table": _bool_column(connection, True),
                "mineru_source": "VARCHAR",
                "mineru_max_concurrent_files": "INTEGER DEFAULT 1 NOT NULL",
```

In `_normalize_settings_profile_values()`, add these updates immediately after the `mineru_require_hpc` normalization:

```python
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET mineru_backend = 'pipeline'
            WHERE mineru_backend IS NULL
               OR mineru_backend = ''
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET mineru_device = 'cuda:0'
            WHERE mineru_device IS NULL
               OR mineru_device = ''
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET mineru_formula = TRUE
            WHERE mineru_formula IS NULL
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET mineru_table = TRUE
            WHERE mineru_table IS NULL
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE settings_profiles
            SET mineru_max_concurrent_files = 1
            WHERE mineru_max_concurrent_files IS NULL
               OR mineru_max_concurrent_files < 1
            """
        )
    )
```

- [ ] **Step 6: Add Settings API fields and normalization**

In `backend/src/ragstudio/schemas/settings.py`, add these fields immediately after `mineru_require_hpc` in `SettingsProfileIn`:

```python
    mineru_backend: str = "pipeline"
    mineru_device: str = "cuda:0"
    mineru_lang: str | None = None
    mineru_formula: bool = True
    mineru_table: bool = True
    mineru_source: str | None = None
    mineru_max_concurrent_files: int = Field(default=1, ge=1, le=8)
```

Add the same output fields immediately after `mineru_require_hpc` in `SettingsProfileOut`:

```python
    mineru_backend: str
    mineru_device: str
    mineru_lang: str | None
    mineru_formula: bool
    mineru_table: bool
    mineru_source: str | None
    mineru_max_concurrent_files: int
```

Add this field validator near the existing API key validators:

```python
    @field_validator("mineru_backend", "mineru_device", "mineru_lang", "mineru_source")
    @classmethod
    def normalize_mineru_parser_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
```

Then add this `model_validator` body immediately before `normalize_runtime_storage_pair()` returns:

```python
        self.mineru_backend = self.mineru_backend or "pipeline"
        self.mineru_device = self.mineru_device or "cuda:0"
        return self
```

The finished method should be:

```python
    @model_validator(mode="after")
    def normalize_runtime_storage_pair(self) -> Self:
        self.runtime_mode = normalize_runtime_mode(self.runtime_mode, self.storage_backend)
        self.mineru_backend = self.mineru_backend or "pipeline"
        self.mineru_device = self.mineru_device or "cuda:0"
        return self
```

- [ ] **Step 7: Return the new fields from SettingsService**

In `backend/src/ragstudio/services/settings_service.py`, add these arguments to `SettingsProfileOut(...)` immediately after `mineru_require_hpc`:

```python
            mineru_backend=profile.mineru_backend or "pipeline",
            mineru_device=profile.mineru_device or "cuda:0",
            mineru_lang=profile.mineru_lang,
            mineru_formula=default_bool(profile.mineru_formula, True),
            mineru_table=default_bool(profile.mineru_table, True),
            mineru_source=profile.mineru_source,
            mineru_max_concurrent_files=profile.mineru_max_concurrent_files or 1,
```

In `_normalize_runtime_values()`, add this block before `return values`:

```python
        values["mineru_backend"] = cast(str | None, values.get("mineru_backend")) or "pipeline"
        values["mineru_device"] = cast(str | None, values.get("mineru_device")) or "cuda:0"
        max_concurrent = values.get("mineru_max_concurrent_files")
        if isinstance(max_concurrent, int):
            values["mineru_max_concurrent_files"] = max(1, min(max_concurrent, 8))
```

- [ ] **Step 8: Run backend Settings and database tests**

Run:

```bash
./.venv/bin/pytest backend/tests/test_settings.py::test_settings_profile_saves_mineru_a100_parser_tuning backend/tests/test_settings.py::test_settings_profile_saves_mineru_config backend/tests/test_db_engine.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/src/ragstudio/db/models.py backend/src/ragstudio/db/engine.py backend/src/ragstudio/schemas/settings.py backend/src/ragstudio/services/settings_service.py backend/tests/test_settings.py backend/tests/test_db_engine.py
git commit -m "feat: persist mineru a100 parser profile"
```

### Task 2: Extend Provider Sync For A100 MinerU Hints

**Files:**
- Modify: `backend/src/ragstudio/services/provider_manifest_service.py`
- Test: `backend/tests/test_settings.py`

- [ ] **Step 1: Write the failing provider sync test**

In `backend/tests/test_settings.py`, update the fake manifest inside `test_provider_sync_preview_maps_manifest_without_persisting` so its `hpcMineru` section is:

```python
                "hpcMineru": {
                    "enabled": True,
                    "apiUrl": "http://10.10.9.19:8765",
                    "timeoutMs": 1800000,
                    "backend": "pipeline",
                    "device": "cuda:0",
                    "lang": "en",
                    "formula": True,
                    "table": True,
                    "source": "huggingface",
                    "maxConcurrentFiles": 2,
                },
```

Add these assertions after the existing `mineru_timeout_ms` assertion:

```python
    assert body["patch"]["mineru_backend"] == "pipeline"
    assert body["patch"]["mineru_device"] == "cuda:0"
    assert body["patch"]["mineru_lang"] == "en"
    assert body["patch"]["mineru_formula"] is True
    assert body["patch"]["mineru_table"] is True
    assert body["patch"]["mineru_source"] == "huggingface"
    assert body["patch"]["mineru_max_concurrent_files"] == 2
```

- [ ] **Step 2: Add invalid manifest field tests**

Extend the `@pytest.mark.parametrize` cases in `test_provider_sync_preview_rejects_invalid_supported_field_types` with:

```python
        ({"hpcMineru": {"backend": 42}}, "hpcMineru.backend"),
        ({"hpcMineru": {"device": False}}, "hpcMineru.device"),
        ({"hpcMineru": {"lang": 123}}, "hpcMineru.lang"),
        ({"hpcMineru": {"formula": "true"}}, "hpcMineru.formula"),
        ({"hpcMineru": {"table": "true"}}, "hpcMineru.table"),
        ({"hpcMineru": {"source": 123}}, "hpcMineru.source"),
        ({"hpcMineru": {"maxConcurrentFiles": 0}}, "hpcMineru.maxConcurrentFiles"),
        ({"hpcMineru": {"maxConcurrentFiles": 9}}, "hpcMineru.maxConcurrentFiles"),
```

- [ ] **Step 3: Run provider sync tests and verify they fail**

Run:

```bash
./.venv/bin/pytest backend/tests/test_settings.py::test_provider_sync_preview_maps_manifest_without_persisting backend/tests/test_settings.py::test_provider_sync_preview_rejects_invalid_supported_field_types -q
```

Expected: FAIL because `hpcMineru` parser tuning fields are ignored or accepted without field-specific validation.

- [ ] **Step 4: Validate manifest fields**

In `backend/src/ragstudio/services/provider_manifest_service.py`, inside the `if isinstance(mineru, dict):` block of `_validate_supported_fields()`, add:

```python
            self._validate_optional_str(mineru, "backend", "hpcMineru.backend")
            self._validate_optional_str(mineru, "device", "hpcMineru.device")
            self._validate_optional_str(mineru, "lang", "hpcMineru.lang")
            if "formula" in mineru and not isinstance(mineru["formula"], bool):
                raise ProviderManifestError(
                    "Provider manifest field hpcMineru.formula must be a boolean."
                )
            if "table" in mineru and not isinstance(mineru["table"], bool):
                raise ProviderManifestError(
                    "Provider manifest field hpcMineru.table must be a boolean."
                )
            self._validate_optional_str(mineru, "source", "hpcMineru.source")
            self._validate_optional_int_range(
                mineru,
                "maxConcurrentFiles",
                "hpcMineru.maxConcurrentFiles",
                minimum=1,
                maximum=8,
            )
```

- [ ] **Step 5: Map manifest fields into the preview patch**

In `_build_patch()`, inside the `if isinstance(mineru, dict):` block, add this after the timeout mapping:

```python
            backend = self._optional_str(mineru.get("backend"))
            device = self._optional_str(mineru.get("device"))
            lang = self._optional_str(mineru.get("lang"))
            source = self._optional_str(mineru.get("source"))
            max_concurrent = self._optional_int(mineru.get("maxConcurrentFiles"))
            if backend:
                patch["mineru_backend"] = backend
            if device:
                patch["mineru_device"] = device
            if lang:
                patch["mineru_lang"] = lang
            if isinstance(mineru.get("formula"), bool):
                patch["mineru_formula"] = mineru["formula"]
            if isinstance(mineru.get("table"), bool):
                patch["mineru_table"] = mineru["table"]
            if source:
                patch["mineru_source"] = source
            if max_concurrent is not None:
                patch["mineru_max_concurrent_files"] = min(max(max_concurrent, 1), 8)
```

- [ ] **Step 6: Run provider sync tests**

Run:

```bash
./.venv/bin/pytest backend/tests/test_settings.py::test_provider_sync_preview_maps_manifest_without_persisting backend/tests/test_settings.py::test_provider_sync_preview_rejects_invalid_supported_field_types -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/provider_manifest_service.py backend/tests/test_settings.py
git commit -m "feat: sync mineru a100 provider hints"
```

### Task 3: Send MinerU Parser Options To The Sidecar

**Files:**
- Modify: `backend/src/ragstudio/services/mineru_client.py`
- Modify: `backend/src/ragstudio/services/document_parser_service.py`
- Test: `backend/tests/test_mineru_client.py`
- Test: `backend/tests/test_document_parser_service.py`

- [ ] **Step 1: Write the failing MinerU client metadata test**

In `backend/tests/test_mineru_client.py`, update `test_mineru_client_submits_pdf_mime_and_metadata` to pass parse options:

```python
    from ragstudio.services.mineru_client import MinerUParseOptions

    job_id = await client.submit_parse(
        pdf_path,
        document_id="doc-1",
        content_type="application/pdf",
        sha256="abc123",
        domain_metadata={"domain": "research"},
        parse_options=MinerUParseOptions(
            parser="mineru",
            parse_method="auto",
            backend="pipeline",
            device="cuda:0",
            lang="en",
            formula=True,
            table=True,
            source="huggingface",
            max_concurrent_files=2,
        ),
    )
```

Replace the metadata assertions at the end of the test with:

```python
    metadata = json.loads(requests[0]["data"]["metadata"])
    assert metadata["mimeType"] == "application/pdf"
    assert metadata["domainMetadata"]["domain"] == "research"
    assert metadata["ragAnything"] == {
        "parser": "mineru",
        "parseMethod": "auto",
        "parserKwargs": {
            "backend": "pipeline",
            "device": "cuda:0",
            "formula": True,
            "table": True,
            "lang": "en",
            "source": "huggingface",
        },
        "maxConcurrentFiles": 2,
    }
```

- [ ] **Step 2: Run the MinerU client test and verify it fails**

Run:

```bash
./.venv/bin/pytest backend/tests/test_mineru_client.py::test_mineru_client_submits_pdf_mime_and_metadata -q
```

Expected: FAIL with `ImportError` for `MinerUParseOptions` or `TypeError` for the new `parse_options` argument.

- [ ] **Step 3: Add MinerUParseOptions and serialize metadata**

In `backend/src/ragstudio/services/mineru_client.py`, add this dataclass after `MinerUJobResult`:

```python
@dataclass(frozen=True)
class MinerUParseOptions:
    parser: str = "mineru"
    parse_method: str = "auto"
    backend: str = "pipeline"
    device: str = "cuda:0"
    lang: str | None = None
    formula: bool = True
    table: bool = True
    source: str | None = None
    max_concurrent_files: int = 1

    def to_metadata(self) -> dict[str, Any]:
        parser_kwargs: dict[str, Any] = {
            "backend": self.backend or "pipeline",
            "device": self.device or "cuda:0",
            "formula": self.formula,
            "table": self.table,
        }
        if self.lang:
            parser_kwargs["lang"] = self.lang
        if self.source:
            parser_kwargs["source"] = self.source
        return {
            "parser": self.parser or "mineru",
            "parseMethod": self.parse_method or "auto",
            "parserKwargs": parser_kwargs,
            "maxConcurrentFiles": max(1, min(self.max_concurrent_files, 8)),
        }
```

Update `parse_document()` to accept and pass the option:

```python
        parse_options: MinerUParseOptions | None = None,
```

and update the `submit_parse()` call:

```python
            parse_options=parse_options,
```

Update `submit_parse()` to accept:

```python
        parse_options: MinerUParseOptions | None = None,
```

Then replace the current `metadata = ...` block with:

```python
        metadata = {
            "mimeType": content_type,
            "domainMetadata": domain_metadata or {},
        }
        if parse_options is not None:
            metadata["ragAnything"] = parse_options.to_metadata()
```

- [ ] **Step 4: Run the MinerU client test**

Run:

```bash
./.venv/bin/pytest backend/tests/test_mineru_client.py::test_mineru_client_submits_pdf_mime_and_metadata -q
```

Expected: PASS.

- [ ] **Step 5: Write a failing DocumentParserService option propagation test**

In `backend/tests/test_document_parser_service.py`, update `EventMinerUClient.parse_document()` to record kwargs:

```python
    async def parse_document(self, **kwargs):
        self.events.append(("parse", kwargs["parse_options"].to_metadata()))
        return MinerUJobResult(parse_job_id="job-1", artifact_zip=Path("artifact.zip"))
```

Update `EventSession.settings` in `EventSession.__init__()` with:

```python
            parser="mineru",
            parse_method="auto",
            mineru_backend="pipeline",
            mineru_device="cuda:0",
            mineru_lang="en",
            mineru_formula=True,
            mineru_table=True,
            mineru_source="huggingface",
            mineru_max_concurrent_files=2,
```

Replace the final `session.events` assertion in `test_commit_before_remote_parse_releases_session_before_parse` with:

```python
    assert session.events == [
        "get:SettingsProfile:default",
        "health",
        "commit",
        (
            "parse",
            {
                "parser": "mineru",
                "parseMethod": "auto",
                "parserKwargs": {
                    "backend": "pipeline",
                    "device": "cuda:0",
                    "formula": True,
                    "table": True,
                    "lang": "en",
                    "source": "huggingface",
                },
                "maxConcurrentFiles": 2,
            },
        ),
        "normalize",
    ]
```

- [ ] **Step 6: Run the DocumentParserService test and verify it fails**

Run:

```bash
./.venv/bin/pytest backend/tests/test_document_parser_service.py::test_commit_before_remote_parse_releases_session_before_parse -q
```

Expected: FAIL because `parse_options` is not passed to `parse_document()`.

- [ ] **Step 7: Build parse options from SettingsProfile**

In `backend/src/ragstudio/services/document_parser_service.py`, update the import:

```python
from ragstudio.services.mineru_client import MinerUClient, MinerUParseOptions
```

In `mineru_parse()`, change:

```python
        _, client = await self.validated_mineru_client()
```

to:

```python
        settings, client = await self.validated_mineru_client()
```

Add this argument to the `client.parse_document(...)` call:

```python
            parse_options=self._mineru_parse_options(settings),
```

Add this method before `_expected_language()`:

```python
    def _mineru_parse_options(self, settings: SettingsProfile) -> MinerUParseOptions:
        return MinerUParseOptions(
            parser=settings.parser or "mineru",
            parse_method=settings.parse_method or "auto",
            backend=settings.mineru_backend or "pipeline",
            device=settings.mineru_device or "cuda:0",
            lang=settings.mineru_lang,
            formula=True if settings.mineru_formula is None else bool(settings.mineru_formula),
            table=True if settings.mineru_table is None else bool(settings.mineru_table),
            source=settings.mineru_source,
            max_concurrent_files=settings.mineru_max_concurrent_files or 1,
        )
```

- [ ] **Step 8: Run MinerU client and parser service tests**

Run:

```bash
./.venv/bin/pytest backend/tests/test_mineru_client.py::test_mineru_client_submits_pdf_mime_and_metadata backend/tests/test_document_parser_service.py::test_commit_before_remote_parse_releases_session_before_parse -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/src/ragstudio/services/mineru_client.py backend/src/ragstudio/services/document_parser_service.py backend/tests/test_mineru_client.py backend/tests/test_document_parser_service.py
git commit -m "feat: send mineru parser options to sidecar"
```

### Task 4: Surface MinerU Health Capacity

**Files:**
- Modify: `backend/src/ragstudio/services/mineru_client.py`
- Modify: `backend/src/ragstudio/schemas/settings.py`
- Modify: `backend/src/ragstudio/api/routes/settings.py`
- Test: `backend/tests/test_settings.py`

- [ ] **Step 1: Write the failing health detail test**

In `backend/tests/test_settings.py`, update `test_mineru_connection_test_reports_hpc_mode` fake health `raw` value:

```python
                raw={
                    "hpcMineru": {
                        "enabled": True,
                        "mode": "coordinator",
                        "backend": "pipeline",
                        "device": "cuda:0",
                        "maxConcurrentFiles": 2,
                    }
                },
```

Add these assertions after the existing `ok` assertion:

```python
    body = response.json()
    assert body["optimization"] == {
        "backend": "pipeline",
        "device": "cuda:0",
        "max_concurrent_files": 2,
    }
    assert "backend=pipeline" in body["detail"]
    assert "device=cuda:0" in body["detail"]
    assert "maxConcurrentFiles=2" in body["detail"]
```

- [ ] **Step 2: Run the health test and verify it fails**

Run:

```bash
./.venv/bin/pytest backend/tests/test_settings.py::test_mineru_connection_test_reports_hpc_mode -q
```

Expected: FAIL because `MinerUConnectionTestOut` has no `optimization` field and the detail string omits capacity values.

- [ ] **Step 3: Add optimization output schema**

In `backend/src/ragstudio/schemas/settings.py`, add this field to `MinerUConnectionTestOut`:

```python
    optimization: dict[str, object] = Field(default_factory=dict)
```

- [ ] **Step 4: Add health optimization helpers**

In `backend/src/ragstudio/services/mineru_client.py`, add this property to `MinerUSidecarHealth` after `is_hpc_coordinator`:

```python
    @property
    def optimization(self) -> dict[str, object]:
        hpc = self.raw.get("hpcMineru")
        if not isinstance(hpc, dict):
            return {}
        result: dict[str, object] = {}
        backend = hpc.get("backend")
        device = hpc.get("device")
        max_concurrent = hpc.get("maxConcurrentFiles")
        if isinstance(backend, str) and backend:
            result["backend"] = backend
        if isinstance(device, str) and device:
            result["device"] = device
        if isinstance(max_concurrent, int) and not isinstance(max_concurrent, bool):
            result["max_concurrent_files"] = max_concurrent
        return result
```

- [ ] **Step 5: Return health optimization data**

In `backend/src/ragstudio/api/routes/settings.py`, add this helper near `_legacy_profile_detail()`:

```python
def _mineru_optimization_detail(optimization: dict[str, object]) -> str:
    parts: list[str] = []
    if optimization.get("backend"):
        parts.append(f"backend={optimization['backend']}")
    if optimization.get("device"):
        parts.append(f"device={optimization['device']}")
    if optimization.get("max_concurrent_files"):
        parts.append(f"maxConcurrentFiles={optimization['max_concurrent_files']}")
    return "; ".join(parts)
```

Inside `test_mineru_settings()`, after `mode_detail` is computed, add:

```python
        optimization = health.optimization
        optimization_detail = _mineru_optimization_detail(optimization)
        detail_suffix = (
            f"{mode_detail}; {optimization_detail}"
            if optimization_detail
            else mode_detail
        )
```

Then replace the success response with:

```python
        return MinerUConnectionTestOut(
            ok=True,
            base_url=base_url,
            latency_ms=latency_ms,
            detail=f"{health.detail or 'MinerU health check succeeded.'} ({detail_suffix}).",
            optimization=optimization,
        )
```

Add `optimization={}` to every other `MinerUConnectionTestOut(...)` return in this route.

- [ ] **Step 6: Run health tests**

Run:

```bash
./.venv/bin/pytest backend/tests/test_settings.py::test_mineru_connection_test_reports_hpc_mode backend/tests/test_settings.py::test_mineru_connection_test_rejects_local_mode_when_required backend/tests/test_settings.py::test_mineru_connection_test_reports_invalid_health_payload -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/mineru_client.py backend/src/ragstudio/schemas/settings.py backend/src/ragstudio/api/routes/settings.py backend/tests/test_settings.py
git commit -m "feat: report mineru hpc capacity"
```

### Task 5: Add Settings UI Controls

**Files:**
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/features/settings/settings-page.tsx`
- Test: `frontend/tests/settings-page.test.tsx`

- [ ] **Step 1: Update frontend API types**

In `frontend/src/api/generated.ts`, add these fields to `SettingsProfileIn` after `mineru_require_hpc?: boolean;`:

```ts
  mineru_backend?: string;
  mineru_device?: string;
  mineru_lang?: string | null;
  mineru_formula?: boolean;
  mineru_table?: boolean;
  mineru_source?: string | null;
  mineru_max_concurrent_files?: number;
```

Add these fields to `SettingsProfileOut` after `mineru_require_hpc: boolean;`:

```ts
  mineru_backend: string;
  mineru_device: string;
  mineru_lang: string | null;
  mineru_formula: boolean;
  mineru_table: boolean;
  mineru_source: string | null;
  mineru_max_concurrent_files: number;
```

Add this field to `MinerUConnectionTestOut`:

```ts
  optimization: Record<string, unknown>;
```

- [ ] **Step 2: Write failing UI tests**

In `frontend/tests/settings-page.test.tsx`, add the new fields to the shared `settings` object:

```ts
  mineru_backend: "pipeline",
  mineru_device: "cuda:0",
  mineru_lang: "en",
  mineru_formula: true,
  mineru_table: true,
  mineru_source: "huggingface",
  mineru_max_concurrent_files: 2,
```

Add these fields to the mocked provider sync `patch`:

```ts
        mineru_backend: "pipeline",
        mineru_device: "cuda:0",
        mineru_lang: "en",
        mineru_formula: true,
        mineru_table: true,
        mineru_source: "huggingface",
        mineru_max_concurrent_files: 2,
```

Add this test after `submits the MinerU HPC requirement setting`:

```ts
  it("submits MinerU A100 parser tuning fields", async () => {
    renderSettings();

    await screen.findByDisplayValue("gpt-4.1");
    expect(screen.getByLabelText("MinerU backend")).toHaveValue("pipeline");
    expect(screen.getByLabelText("MinerU device")).toHaveValue("cuda:0");
    expect(screen.getByLabelText("MinerU language")).toHaveValue("en");
    expect(screen.getByLabelText("MinerU source")).toHaveValue("huggingface");
    expect(screen.getByLabelText("MinerU max concurrent files")).toHaveValue(2);
    expect(screen.getByLabelText("Parse formulas")).toBeChecked();
    expect(screen.getByLabelText("Parse tables")).toBeChecked();

    fireEvent.change(screen.getByLabelText("MinerU device"), {
      target: { value: "cuda:1" },
    });
    fireEvent.change(screen.getByLabelText("MinerU max concurrent files"), {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByLabelText("Parse formulas"));
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    await waitFor(() => expect(apiClient.updateDefaultSettings).toHaveBeenCalled());
    expect(vi.mocked(apiClient.updateDefaultSettings).mock.calls[0][0]).toEqual(
      expect.objectContaining({
        mineru_backend: "pipeline",
        mineru_device: "cuda:1",
        mineru_lang: "en",
        mineru_formula: false,
        mineru_table: true,
        mineru_source: "huggingface",
        mineru_max_concurrent_files: 3,
      }),
    );
  });
```

- [ ] **Step 3: Run the UI test and verify it fails**

Run:

```bash
cd frontend && npm test -- settings-page.test.tsx --run
```

Expected: FAIL because the UI labels do not exist.

- [ ] **Step 4: Add frontend defaults and numeric constraints**

In `frontend/src/features/settings/settings-page.tsx`, add `"mineru_max_concurrent_files"` to `NumberFieldName`:

```ts
  | "mineru_max_concurrent_files"
```

Add this constraint to `NUMBER_CONSTRAINTS`:

```ts
  mineru_max_concurrent_files: { min: 1, max: 8 },
```

Add these values to `DEFAULT_FORM_VALUES` after `mineru_require_hpc`:

```ts
  mineru_backend: "pipeline",
  mineru_device: "cuda:0",
  mineru_lang: "",
  mineru_formula: true,
  mineru_table: true,
  mineru_source: "",
  mineru_max_concurrent_files: 1,
```

In `buildPayload()`, add these values after `mineru_require_hpc`:

```ts
      mineru_backend: formValues.mineru_backend || "pipeline",
      mineru_device: formValues.mineru_device || "cuda:0",
      mineru_lang: formValues.mineru_lang || null,
      mineru_formula: formValues.mineru_formula ?? true,
      mineru_table: formValues.mineru_table ?? true,
      mineru_source: formValues.mineru_source || null,
      mineru_max_concurrent_files: constrainNumber(
        formValues.mineru_max_concurrent_files ?? 1,
        NUMBER_CONSTRAINTS.mineru_max_concurrent_files,
      ),
```

In `settingsToFormValues()`, add these mappings after `mineru_require_hpc`:

```ts
    mineru_backend: settings.mineru_backend,
    mineru_device: settings.mineru_device,
    mineru_lang: settings.mineru_lang ?? "",
    mineru_formula: settings.mineru_formula,
    mineru_table: settings.mineru_table,
    mineru_source: settings.mineru_source ?? "",
    mineru_max_concurrent_files: settings.mineru_max_concurrent_files,
```

- [ ] **Step 5: Add UI controls in the MinerU parser section**

In the `MinerU parser` section of `frontend/src/features/settings/settings-page.tsx`, insert these controls immediately after `Require HPC MinerU coordinator`:

```tsx
            <Field
              label="MinerU backend"
              name="mineru_backend"
              value={formValues?.mineru_backend ?? "pipeline"}
              placeholder="pipeline"
              disabled={busy}
              onChange={(value) => updateField("mineru_backend", value)}
            />
            <Field
              label="MinerU device"
              name="mineru_device"
              value={formValues?.mineru_device ?? "cuda:0"}
              placeholder="cuda:0"
              disabled={busy}
              onChange={(value) => updateField("mineru_device", value)}
            />
            <Field
              label="MinerU language"
              name="mineru_lang"
              value={formValues?.mineru_lang ?? ""}
              placeholder="optional"
              disabled={busy}
              required={false}
              onChange={(value) => updateField("mineru_lang", value)}
            />
            <Field
              label="MinerU source"
              name="mineru_source"
              value={formValues?.mineru_source ?? ""}
              placeholder="optional"
              disabled={busy}
              required={false}
              onChange={(value) => updateField("mineru_source", value)}
            />
            <Field
              label="MinerU max concurrent files"
              name="mineru_max_concurrent_files"
              value={numberValue("mineru_max_concurrent_files", 1)}
              placeholder="1"
              disabled={busy}
              type="number"
              {...NUMBER_CONSTRAINTS.mineru_max_concurrent_files}
              onChange={(value) => updateNumberField("mineru_max_concurrent_files", value)}
              onBlur={() => commitNumberField("mineru_max_concurrent_files", 1)}
            />
            <CheckboxField
              label="Parse formulas"
              name="mineru_formula"
              checked={formValues?.mineru_formula ?? true}
              disabled={busy}
              onChange={(checked) => updateField("mineru_formula", checked)}
            />
            <CheckboxField
              label="Parse tables"
              name="mineru_table"
              checked={formValues?.mineru_table ?? true}
              disabled={busy}
              onChange={(checked) => updateField("mineru_table", checked)}
            />
```

- [ ] **Step 6: Show health optimization output**

Update the `mineruTestMessage` expression so connected health output appends compact optimization values:

```ts
  const mineruOptimization = testMinerU.data?.optimization ?? {};
  const mineruOptimizationMessage = [
    mineruOptimization.backend ? `backend=${String(mineruOptimization.backend)}` : "",
    mineruOptimization.device ? `device=${String(mineruOptimization.device)}` : "",
    mineruOptimization.max_concurrent_files
      ? `maxConcurrentFiles=${String(mineruOptimization.max_concurrent_files)}`
      : "",
  ]
    .filter(Boolean)
    .join("; ");
  const mineruTestMessage = testMinerU.error
    ? testMinerU.error.message
    : testMinerU.data
      ? `${testMinerU.data.ok ? "Connected" : "Failed"}: ${testMinerU.data.detail}${
          mineruOptimizationMessage ? ` ${mineruOptimizationMessage}` : ""
        }`
      : "";
```

- [ ] **Step 7: Run UI tests**

Run:

```bash
cd frontend && npm test -- settings-page.test.tsx --run
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/generated.ts frontend/src/features/settings/settings-page.tsx frontend/tests/settings-page.test.tsx
git commit -m "feat: expose mineru a100 settings"
```

### Task 6: Document The A100 MinerU Workflow

**Files:**
- Modify: `docs/user-guide.md`
- Modify: `docs/workflows.md`

- [ ] **Step 1: Update user guide fields**

In `docs/user-guide.md`, under `MinerU parser fields:`, add these bullets after `MinerU poll interval (ms)`:

```markdown
- `MinerU backend`: parser backend passed to the RAG-Anything/MinerU sidecar. For A100 GPU parsing use `pipeline`.
- `MinerU device`: inference device passed to MinerU. For one A100 use `cuda:0`; for another GPU slot use the matching CUDA device such as `cuda:1`.
- `MinerU language`: optional OCR language hint passed as `lang`.
- `MinerU source`: optional model source hint such as `huggingface`, `modelscope`, or `local`.
- `MinerU max concurrent files`: sidecar capacity hint for parallel document parsing. Start with `1` for large PDFs and increase only after GPU memory is stable.
- `Parse formulas`: passes MinerU `formula=true` or `formula=false`.
- `Parse tables`: passes MinerU `table=true` or `table=false`.
```

In the `MinerU parser and domain metadata` section, add this paragraph after the HPC coordinator paragraph:

```markdown
For A100-backed parsing, keep `MinerU backend` set to `pipeline`, set `MinerU device` to the CUDA device used by the sidecar, and start `MinerU max concurrent files` at `1` for large PDFs. If GPU memory remains stable and jobs spend time waiting, raise it to `2`; larger values should be tested with the same document size mix you expect in production.
```

- [ ] **Step 2: Update workflow docs**

In `docs/workflows.md`, under `Provider sync`, replace the supported manifest sentence with:

```markdown
The supported manifest sections are `reasoning`, `embeddings`, `reranker`, and `hpcMineru`. `hpcMineru` can provide `enabled`, `apiUrl`, `timeoutMs`, `backend`, `device`, `lang`, `formula`, `table`, `source`, and `maxConcurrentFiles`; Settings previews these values before saving.
```

Under `MinerU Parsing Workflow`, add:

```markdown
Ragstudio sends RAG-Anything parser hints inside the existing `metadata` form field for `/parse-async`. The sidecar receives `ragAnything.parser`, `ragAnything.parseMethod`, `ragAnything.parserKwargs`, and `ragAnything.maxConcurrentFiles`. For A100 jobs, the expected parser kwargs are usually `backend=pipeline`, `device=cuda:0`, `formula=true`, and `table=true`.
```

- [ ] **Step 3: Verify docs mention the new fields**

Run:

```bash
rg -n "MinerU backend|MinerU device|maxConcurrentFiles|ragAnything.parserKwargs|A100" docs/user-guide.md docs/workflows.md
```

Expected: command prints matches in both docs.

- [ ] **Step 4: Commit**

```bash
git add docs/user-guide.md docs/workflows.md
git commit -m "docs: explain mineru a100 parser tuning"
```

### Task 7: Full Verification

**Files:**
- Verify: backend and frontend tests

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
./.venv/bin/pytest \
  backend/tests/test_settings.py \
  backend/tests/test_mineru_client.py \
  backend/tests/test_document_parser_service.py \
  backend/tests/test_db_engine.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run backend lint**

Run:

```bash
./.venv/bin/ruff check \
  backend/src/ragstudio/db/models.py \
  backend/src/ragstudio/db/engine.py \
  backend/src/ragstudio/schemas/settings.py \
  backend/src/ragstudio/services/settings_service.py \
  backend/src/ragstudio/services/provider_manifest_service.py \
  backend/src/ragstudio/services/mineru_client.py \
  backend/src/ragstudio/services/document_parser_service.py \
  backend/src/ragstudio/api/routes/settings.py \
  backend/tests/test_settings.py \
  backend/tests/test_mineru_client.py \
  backend/tests/test_document_parser_service.py \
  backend/tests/test_db_engine.py
```

Expected: PASS.

- [ ] **Step 3: Run frontend tests**

Run:

```bash
cd frontend && npm test -- settings-page.test.tsx --run
```

Expected: PASS.

- [ ] **Step 4: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 5: Inspect final diff**

Run:

```bash
git diff --stat HEAD~6..HEAD
git status --short
```

Expected: the diff contains the backend Settings/profile/client changes, frontend Settings page/types/tests, and docs. `git status --short` should be clean unless execution was intentionally left uncommitted.

## Self-Review

Spec coverage:
- A100/MinerU improvements are covered by persisted parser tuning fields, provider sync mapping, sidecar metadata propagation, health capacity display, Settings UI, and docs.
- Upstream RAG-Anything knobs are covered by `backend`, `device`, `lang`, `formula`, `table`, `source`, and `maxConcurrentFiles`.
- Existing Ragstudio boundaries are preserved: MinerU strict remains the ingestion gate, Postgres chunks remain source of truth, and the external HPC coordinator still owns actual GPU execution.

Placeholder scan:
- The plan uses concrete file paths, field names, tests, commands, expected results, and code snippets.
- No unspecified implementation steps remain.

Type consistency:
- Backend, frontend, manifest, sidecar metadata, docs, and tests consistently use `mineru_backend`, `mineru_device`, `mineru_lang`, `mineru_formula`, `mineru_table`, `mineru_source`, and `mineru_max_concurrent_files`.
- Sidecar JSON uses the intended camelCase wire names inside `ragAnything`: `parseMethod`, `parserKwargs`, and `maxConcurrentFiles`.
