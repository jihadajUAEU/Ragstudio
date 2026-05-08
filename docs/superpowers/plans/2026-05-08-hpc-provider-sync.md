# HPC Provider Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Settings workflow that previews Cloudflare-hosted HPC provider manifest updates for LLM generation, embeddings, and MinerU, then lets the user save the reviewed runtime profile.

**Architecture:** Add first-class LLM runtime fields to the persisted settings profile, a backend manifest sync-preview service that maps Meeting Copilot `providers.json` sections into a typed patch, and a small OpenAI-compatible LLM connection tester. The frontend adds a Provider sync section and an LLM generation section while preserving the existing Save boundary.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async, httpx, pytest, React, TanStack Query, Vitest, Testing Library, Tailwind.

---

## File Structure

- Modify `backend/src/ragstudio/db/models.py`: add LLM runtime columns to `SettingsProfile`.
- Modify `backend/src/ragstudio/db/engine.py`: add compatibility `ALTER TABLE` entries for the new settings columns.
- Modify `backend/src/ragstudio/schemas/settings.py`: add LLM provider/capability types, manifest sync request/response schemas, and LLM connection test response schema.
- Modify `backend/src/ragstudio/services/settings_service.py`: preserve `llm_api_key`, expose LLM fields, resolve saved key for tests.
- Create `backend/src/ragstudio/services/provider_manifest_service.py`: fetch and validate the provider manifest, infer capabilities, and build preview patches.
- Create `backend/src/ragstudio/services/llm_connection_service.py`: test OpenAI-compatible `/chat/completions` endpoints.
- Modify `backend/src/ragstudio/api/routes/settings.py`: add `/sync-provider-preview` and `/test-llm`.
- Modify `backend/tests/test_settings.py`: add backend coverage for persistence, sync preview, errors, partial manifests, and LLM connection testing.
- Modify `frontend/src/api/generated.ts`: add generated-compatible settings types for the new backend schemas.
- Modify `frontend/src/api/client.ts`: add API client calls for provider sync preview and LLM testing.
- Modify `frontend/src/features/settings/settings-page.tsx`: add Provider sync and LLM generation UI, form patching, badges, and status messages.
- Modify `frontend/tests/settings-page.test.tsx`: add UI tests for sync preview and LLM controls.
- Modify `docs/user-guide.md` and `docs/workflows.md`: document the hosted provider manifest workflow.

---

### Task 1: Persist LLM Runtime Settings

**Files:**
- Modify: `backend/src/ragstudio/db/models.py`
- Modify: `backend/src/ragstudio/db/engine.py`
- Modify: `backend/src/ragstudio/schemas/settings.py`
- Modify: `backend/src/ragstudio/services/settings_service.py`
- Test: `backend/tests/test_settings.py`

- [ ] **Step 1: Write the failing backend persistence test**

Append this test to `backend/tests/test_settings.py`:

```python
@pytest.mark.asyncio
async def test_settings_profile_saves_llm_config_without_returning_secret(client):
    payload = {
        "provider": "openai",
        "llm_provider": "openai_compatible",
        "llm_model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
        "llm_base_url": "http://10.10.9.195:8004/v1/",
        "llm_api_key": "llm-secret-token",
        "llm_timeout_ms": 15000,
        "llm_capabilities": ["text", "vision", "reasoning"],
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "sqlite",
    }

    create_response = await client.put("/api/settings/default", json=payload)

    assert create_response.status_code == 200
    body = create_response.json()
    assert body["llm_provider"] == "openai_compatible"
    assert body["llm_base_url"] == "http://10.10.9.195:8004/v1"
    assert body["llm_timeout_ms"] == 15000
    assert body["llm_capabilities"] == ["text", "vision", "reasoning"]
    assert body["has_llm_api_key"] is True
    assert "llm_api_key" not in body
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_settings.py::test_settings_profile_saves_llm_config_without_returning_secret -q
```

Expected: FAIL with validation errors or missing response fields for `llm_provider`, `llm_base_url`, `llm_timeout_ms`, `llm_capabilities`, and `has_llm_api_key`.

- [ ] **Step 3: Add LLM settings schemas**

In `backend/src/ragstudio/schemas/settings.py`, add imports and types near the existing provider aliases:

```python
from typing import Literal

EmbeddingProvider = Literal["fallback", "vllm_openai"]
LlmProvider = Literal["openai_compatible"]
LlmCapability = Literal["text", "vision", "reasoning"]
```

Add these fields to `SettingsProfileIn` after `llm_model`:

```python
    llm_provider: LlmProvider = "openai_compatible"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_timeout_ms: int = Field(default=10000, ge=100, le=1_800_000)
    llm_capabilities: list[LlmCapability] = Field(default_factory=list)
```

Add validators to `SettingsProfileIn`:

```python
    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_base_url(cls, value: str | None) -> str | None:
        return cls._validate_http_base_url(value, "LLM base URL")

    @field_validator("llm_api_key")
    @classmethod
    def normalize_llm_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("llm_capabilities")
    @classmethod
    def normalize_llm_capabilities(
        cls, value: list[LlmCapability]
    ) -> list[LlmCapability]:
        ordered: list[LlmCapability] = []
        for capability in value:
            if capability not in ordered:
                ordered.append(capability)
        return ordered
```

Add these fields to `SettingsProfileOut` after `llm_model`:

```python
    llm_provider: LlmProvider
    llm_base_url: str | None
    has_llm_api_key: bool
    llm_timeout_ms: int
    llm_capabilities: list[LlmCapability]
```

- [ ] **Step 4: Add database columns and compatibility migration hook**

In `backend/src/ragstudio/db/models.py`, add these columns to `SettingsProfile` after `llm_model`:

```python
    llm_provider: Mapped[str] = mapped_column(String, default="openai_compatible")
    llm_base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_timeout_ms: Mapped[int] = mapped_column(Integer, default=10000)
    llm_capabilities: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSON), default=list)
```

In `backend/src/ragstudio/db/engine.py`, add these entries to the `additions` map in `_ensure_settings_profile_columns`:

```python
        "llm_provider": "VARCHAR DEFAULT 'openai_compatible' NOT NULL",
        "llm_base_url": "VARCHAR",
        "llm_api_key": "VARCHAR",
        "llm_timeout_ms": "INTEGER DEFAULT 10000 NOT NULL",
        "llm_capabilities": "JSON DEFAULT '[]' NOT NULL",
```

- [ ] **Step 5: Preserve LLM secrets in the settings service**

In `backend/src/ragstudio/services/settings_service.py`, update imports:

```python
from ragstudio.schemas.settings import (
    EmbeddingProvider,
    LlmCapability,
    LlmProvider,
    SettingsProfileIn,
    SettingsProfileOut,
)
```

Change the first line of `upsert_default` from:

```python
        values = data.model_dump(exclude={"embedding_api_key"})
```

to:

```python
        values = data.model_dump(exclude={"embedding_api_key", "llm_api_key"})
```

After the existing embedding API key assignment, add:

```python
        if data.llm_api_key is not None:
            profile.llm_api_key = data.llm_api_key or None
```

Add this method below `resolve_embedding_test_payload`:

```python
    async def resolve_llm_test_payload(self, data: SettingsProfileIn) -> SettingsProfileIn:
        if data.llm_api_key:
            return data

        profile = await self.session.get(SettingsProfile, "default")
        if profile is None or not profile.llm_api_key:
            return data

        return data.model_copy(update={"llm_api_key": profile.llm_api_key})
```

Add these fields to `_to_out` after `llm_model=profile.llm_model`:

```python
            llm_provider=cast(
                LlmProvider,
                profile.llm_provider if profile.llm_provider else "openai_compatible",
            ),
            llm_base_url=profile.llm_base_url,
            has_llm_api_key=bool(profile.llm_api_key),
            llm_timeout_ms=profile.llm_timeout_ms or 10000,
            llm_capabilities=[
                cast(LlmCapability, capability)
                for capability in (profile.llm_capabilities or [])
                if capability in {"text", "vision", "reasoning"}
            ],
```

- [ ] **Step 6: Run the persistence test**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_settings.py::test_settings_profile_saves_llm_config_without_returning_secret -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add backend/src/ragstudio/db/models.py backend/src/ragstudio/db/engine.py backend/src/ragstudio/schemas/settings.py backend/src/ragstudio/services/settings_service.py backend/tests/test_settings.py
git commit -m "feat: persist llm runtime settings"
```

---

### Task 2: Add Provider Manifest Sync Preview

**Files:**
- Create: `backend/src/ragstudio/services/provider_manifest_service.py`
- Modify: `backend/src/ragstudio/schemas/settings.py`
- Modify: `backend/src/ragstudio/api/routes/settings.py`
- Test: `backend/tests/test_settings.py`

- [ ] **Step 1: Write failing sync preview tests**

Append these tests to `backend/tests/test_settings.py`:

```python
@pytest.mark.asyncio
async def test_provider_sync_preview_maps_manifest_without_persisting(client, monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "version": 2,
                "updatedAt": "2026-05-07T08:23:27.928Z",
                "reasoning": {
                    "apiUrl": "http://10.10.9.195:8004/v1",
                    "model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
                    "timeoutMs": 5000,
                },
                "embeddings": {
                    "apiUrl": "http://10.10.9.192:8001/v1",
                    "model": "Qwen/Qwen3-Embedding-8B",
                    "dimensions": 1536,
                    "timeoutMs": 10000,
                },
                "hpcMineru": {
                    "enabled": True,
                    "apiUrl": "http://10.10.9.19:8765",
                    "timeoutMs": 1800000,
                },
                "stt": {"apiUrl": "http://10.10.9.196:8002/v1"},
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url):
            assert url == "https://updates.jihadaj.com/providers.json"
            assert self.timeout == 5.0
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.provider_manifest_service.httpx.AsyncClient",
        FakeAsyncClient,
    )
    save_response = await client.put(
        "/api/settings/default",
        json={
            "provider": "openai",
            "llm_model": "gpt-4.1",
            "embedding_model": "text-embedding-3-large",
            "storage_backend": "sqlite",
        },
    )

    response = await client.post(
        "/api/settings/default/sync-provider-preview",
        json={"manifest_url": "https://updates.jihadaj.com/providers.json"},
    )
    read_response = await client.get("/api/settings/default")

    assert save_response.status_code == 200
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["manifest_version"] == 2
    assert body["updated_at"] == "2026-05-07T08:23:27.928Z"
    assert body["patch"]["llm_provider"] == "openai_compatible"
    assert body["patch"]["llm_base_url"] == "http://10.10.9.195:8004/v1"
    assert body["patch"]["llm_model"] == "QuantTrio/Qwen3-VL-32B-Instruct-AWQ"
    assert body["patch"]["llm_timeout_ms"] == 5000
    assert body["patch"]["llm_capabilities"] == ["text", "vision", "reasoning"]
    assert body["patch"]["embedding_provider"] == "vllm_openai"
    assert body["patch"]["embedding_base_url"] == "http://10.10.9.192:8001/v1"
    assert body["patch"]["embedding_model"] == "Qwen/Qwen3-Embedding-8B"
    assert body["patch"]["embedding_dimensions"] == 1536
    assert body["patch"]["embedding_timeout_ms"] == 10000
    assert body["patch"]["mineru_enabled"] is True
    assert body["patch"]["mineru_base_url"] == "http://10.10.9.19:8765"
    assert body["patch"]["mineru_timeout_ms"] == 1800000
    assert "llm_base_url" in body["changed_fields"]
    assert "stt" in body["ignored_sections"]
    assert read_response.json()["llm_model"] == "gpt-4.1"


@pytest.mark.asyncio
async def test_provider_sync_preview_accepts_partial_manifest(client, monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"version": 3, "embeddings": {"model": "Qwen/Qwen3-Embedding-8B"}}

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.provider_manifest_service.httpx.AsyncClient",
        FakeAsyncClient,
    )

    response = await client.post(
        "/api/settings/default/sync-provider-preview",
        json={"manifest_url": "https://updates.jihadaj.com/providers.json"},
    )

    assert response.status_code == 200
    assert response.json()["patch"] == {
        "embedding_provider": "vllm_openai",
        "embedding_model": "Qwen/Qwen3-Embedding-8B",
    }


@pytest.mark.asyncio
async def test_provider_sync_preview_rejects_invalid_manifest_url(client):
    response = await client.post(
        "/api/settings/default/sync-provider-preview",
        json={"manifest_url": "ftp://updates.jihadaj.com/providers.json"},
    )

    assert response.status_code == 422
    assert "manifest_url" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_settings.py -q
```

Expected: FAIL because `ProviderSyncPreviewIn`, the service, and the route do not exist.

- [ ] **Step 3: Add sync preview schemas**

In `backend/src/ragstudio/schemas/settings.py`, add these classes after `MinerUConnectionTestOut`:

```python
class ProviderSyncPreviewIn(StudioModel):
    manifest_url: str

    @field_validator("manifest_url")
    @classmethod
    def validate_manifest_url(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Provider manifest URL must be an http or https URL")
        if parsed.username or parsed.password:
            raise ValueError("Provider manifest URL must not include credentials")
        return normalized


class ProviderSyncPreviewOut(StudioModel):
    ok: bool
    manifest_url: str
    manifest_version: int | None = None
    updated_at: str | None = None
    patch: dict[str, object]
    changed_fields: list[str]
    ignored_sections: list[str]
    detail: str
```

- [ ] **Step 4: Implement the provider manifest service**

Create `backend/src/ragstudio/services/provider_manifest_service.py`:

```python
from typing import Any

import httpx

from ragstudio.schemas.settings import ProviderSyncPreviewOut, SettingsProfileOut

SUPPORTED_SECTIONS = {"reasoning", "embeddings", "hpcMineru"}
KNOWN_SECTIONS = {"stt", "reasoning", "embeddings", "ragAnything", "hpcMineru"}
CAPABILITIES = {"text", "vision", "reasoning"}


class ProviderManifestError(Exception):
    pass


class ProviderManifestService:
    async def preview(
        self,
        manifest_url: str,
        current: SettingsProfileOut | None,
        timeout_s: float = 5.0,
    ) -> ProviderSyncPreviewOut:
        manifest = await self._fetch_manifest(manifest_url, timeout_s)
        patch = self._build_patch(manifest)
        ignored_sections = sorted(
            key for key in manifest if key in KNOWN_SECTIONS and key not in SUPPORTED_SECTIONS
        )
        changed_fields = self._changed_fields(patch, current)
        return ProviderSyncPreviewOut(
            ok=True,
            manifest_url=manifest_url,
            manifest_version=manifest.get("version") if isinstance(manifest.get("version"), int) else None,
            updated_at=manifest.get("updatedAt") if isinstance(manifest.get("updatedAt"), str) else None,
            patch=patch,
            changed_fields=changed_fields,
            ignored_sections=ignored_sections,
            detail="Provider manifest preview generated.",
        )

    async def _fetch_manifest(self, manifest_url: str, timeout_s: float) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.get(manifest_url)
            if response.status_code >= 400:
                raise ProviderManifestError(
                    f"Provider manifest returned HTTP {response.status_code}."
                )
            payload = response.json()
        except ProviderManifestError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderManifestError(str(exc)) from exc
        except ValueError as exc:
            raise ProviderManifestError("Provider manifest must be valid JSON.") from exc

        if not isinstance(payload, dict):
            raise ProviderManifestError("Provider manifest must be a JSON object.")

        for section in SUPPORTED_SECTIONS:
            if section in payload and not isinstance(payload[section], dict):
                raise ProviderManifestError(f"Provider manifest section {section} must be an object.")
        return payload

    def _build_patch(self, manifest: dict[str, Any]) -> dict[str, object]:
        patch: dict[str, object] = {}
        reasoning = manifest.get("reasoning")
        if isinstance(reasoning, dict):
            api_url = self._optional_str(reasoning.get("apiUrl"))
            model = self._optional_str(reasoning.get("model"))
            timeout_ms = self._optional_int(reasoning.get("timeoutMs"))
            if api_url:
                patch["llm_provider"] = "openai_compatible"
                patch["llm_base_url"] = api_url.rstrip("/")
            if model:
                patch["llm_model"] = model
            if timeout_ms is not None:
                patch["llm_timeout_ms"] = timeout_ms
            capabilities = self._capabilities(reasoning.get("capabilities"), model)
            if capabilities:
                patch["llm_capabilities"] = capabilities

        embeddings = manifest.get("embeddings")
        if isinstance(embeddings, dict):
            api_url = self._optional_str(embeddings.get("apiUrl"))
            model = self._optional_str(embeddings.get("model"))
            dimensions = self._optional_int(embeddings.get("dimensions"))
            timeout_ms = self._optional_int(embeddings.get("timeoutMs"))
            if api_url:
                patch["embedding_provider"] = "vllm_openai"
                patch["embedding_base_url"] = api_url.rstrip("/")
            if model:
                patch["embedding_provider"] = "vllm_openai"
                patch["embedding_model"] = model
            if dimensions is not None:
                patch["embedding_dimensions"] = dimensions
            if timeout_ms is not None:
                patch["embedding_timeout_ms"] = timeout_ms

        mineru = manifest.get("hpcMineru")
        if isinstance(mineru, dict):
            enabled = mineru.get("enabled")
            api_url = self._optional_str(mineru.get("apiUrl"))
            timeout_ms = self._optional_int(mineru.get("timeoutMs"))
            if isinstance(enabled, bool):
                patch["mineru_enabled"] = enabled
            if api_url:
                patch["mineru_base_url"] = api_url.rstrip("/")
            if timeout_ms is not None:
                patch["mineru_timeout_ms"] = timeout_ms

        return patch

    def _capabilities(self, raw: object, model: str | None) -> list[str]:
        if isinstance(raw, list):
            explicit = [item for item in raw if isinstance(item, str) and item in CAPABILITIES]
            if explicit:
                return self._ordered_capabilities(explicit)

        inferred = ["text", "reasoning"]
        model_text = (model or "").lower()
        if "vl" in model_text or "vision" in model_text or "multimodal" in model_text:
            inferred.append("vision")
        return self._ordered_capabilities(inferred)

    def _ordered_capabilities(self, values: list[str]) -> list[str]:
        return [capability for capability in ["text", "vision", "reasoning"] if capability in values]

    def _changed_fields(
        self, patch: dict[str, object], current: SettingsProfileOut | None
    ) -> list[str]:
        if current is None:
            return sorted(patch)
        current_map = current.model_dump()
        return sorted(
            key for key, value in patch.items() if current_map.get(key) != value
        )

    def _optional_str(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None

    def _optional_int(self, value: object) -> int | None:
        if isinstance(value, int) and value > 0:
            return value
        return None
```

- [ ] **Step 5: Add the sync preview route**

In `backend/src/ragstudio/api/routes/settings.py`, update imports:

```python
from ragstudio.schemas.settings import (
    EmbeddingConnectionTestOut,
    MinerUConnectionTestOut,
    ProviderSyncPreviewIn,
    ProviderSyncPreviewOut,
    SettingsProfileIn,
    SettingsProfileOut,
)
from ragstudio.services.provider_manifest_service import (
    ProviderManifestError,
    ProviderManifestService,
)
```

Add this route after `put_default_settings`:

```python
@router.post("/default/sync-provider-preview", response_model=ProviderSyncPreviewOut)
async def sync_provider_preview(
    payload: ProviderSyncPreviewIn,
    session: AsyncSession = Depends(get_session),
) -> ProviderSyncPreviewOut:
    settings_service = SettingsService(session)
    current = await settings_service.get_default()
    try:
        return await ProviderManifestService().preview(payload.manifest_url, current)
    except ProviderManifestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
```

- [ ] **Step 6: Run backend settings tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_settings.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add backend/src/ragstudio/services/provider_manifest_service.py backend/src/ragstudio/schemas/settings.py backend/src/ragstudio/api/routes/settings.py backend/tests/test_settings.py
git commit -m "feat: preview provider manifest sync"
```

---

### Task 3: Add OpenAI-Compatible LLM Connection Test

**Files:**
- Create: `backend/src/ragstudio/services/llm_connection_service.py`
- Modify: `backend/src/ragstudio/schemas/settings.py`
- Modify: `backend/src/ragstudio/api/routes/settings.py`
- Modify: `backend/src/ragstudio/services/settings_service.py`
- Test: `backend/tests/test_settings.py`

- [ ] **Step 1: Write failing LLM connection tests**

Append these tests to `backend/tests/test_settings.py`:

```python
@pytest.mark.asyncio
async def test_llm_connection_test_calls_chat_completions(client, monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, headers, json):
            requests.append({"url": url, "headers": headers, "json": json, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.llm_connection_service.httpx.AsyncClient",
        FakeAsyncClient,
    )
    payload = {
        "provider": "openai",
        "llm_provider": "openai_compatible",
        "llm_model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
        "llm_base_url": "http://10.10.9.195:8004/v1",
        "llm_api_key": "secret-token",
        "llm_timeout_ms": 5000,
        "llm_capabilities": ["text", "vision", "reasoning"],
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "sqlite",
    }

    response = await client.post("/api/settings/default/test-llm", json=payload)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert requests == [
        {
            "url": "http://10.10.9.195:8004/v1/chat/completions",
            "headers": {
                "content-type": "application/json",
                "authorization": "Bearer secret-token",
            },
            "json": {
                "model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
                "messages": [{"role": "user", "content": "Ragstudio LLM connection test"}],
                "max_tokens": 8,
                "temperature": 0,
            },
            "timeout": 5.0,
        }
    ]


@pytest.mark.asyncio
async def test_llm_connection_test_uses_saved_api_key_when_blank(client, monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, headers, json):
            requests.append({"headers": headers})
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.llm_connection_service.httpx.AsyncClient",
        FakeAsyncClient,
    )
    saved_payload = {
        "provider": "openai",
        "llm_provider": "openai_compatible",
        "llm_model": "Qwen/Qwen3-32B",
        "llm_base_url": "http://10.10.9.195:8004/v1",
        "llm_api_key": "saved-llm-secret",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "sqlite",
    }
    test_payload = {key: value for key, value in saved_payload.items() if key != "llm_api_key"}

    save_response = await client.put("/api/settings/default", json=saved_payload)
    response = await client.post("/api/settings/default/test-llm", json=test_payload)

    assert save_response.status_code == 200
    assert response.status_code == 200
    assert requests == [
        {
            "headers": {
                "content-type": "application/json",
                "authorization": "Bearer saved-llm-secret",
            }
        }
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_settings.py::test_llm_connection_test_calls_chat_completions backend/tests/test_settings.py::test_llm_connection_test_uses_saved_api_key_when_blank -q
```

Expected: FAIL because `/api/settings/default/test-llm` and `llm_connection_service` do not exist.

- [ ] **Step 3: Add LLM connection response schema**

In `backend/src/ragstudio/schemas/settings.py`, add:

```python
class LlmConnectionTestOut(StudioModel):
    ok: bool
    provider: str
    model: str
    latency_ms: int
    detail: str
```

- [ ] **Step 4: Implement the LLM connection service**

Create `backend/src/ragstudio/services/llm_connection_service.py`:

```python
import time

import httpx

from ragstudio.schemas.settings import LlmConnectionTestOut, SettingsProfileIn


class LlmConnectionService:
    async def test(self, settings: SettingsProfileIn) -> LlmConnectionTestOut:
        base_url = (settings.llm_base_url or "").rstrip("/")
        if not base_url:
            return LlmConnectionTestOut(
                ok=False,
                provider=settings.llm_provider,
                model=settings.llm_model,
                latency_ms=0,
                detail="LLM base URL is not configured.",
            )

        headers = {"content-type": "application/json"}
        if settings.llm_api_key:
            headers["authorization"] = f"Bearer {settings.llm_api_key}"

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=settings.llm_timeout_ms / 1000) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json={
                        "model": settings.llm_model,
                        "messages": [
                            {"role": "user", "content": "Ragstudio LLM connection test"}
                        ],
                        "max_tokens": 8,
                        "temperature": 0,
                    },
                )
            latency_ms = int((time.perf_counter() - started) * 1000)
            if response.status_code >= 400:
                return LlmConnectionTestOut(
                    ok=False,
                    provider=settings.llm_provider,
                    model=settings.llm_model,
                    latency_ms=latency_ms,
                    detail=f"LLM connection test returned HTTP {response.status_code}.",
                )
            payload = response.json()
            choices = payload.get("choices") if isinstance(payload, dict) else None
            if not isinstance(choices, list) or not choices:
                return LlmConnectionTestOut(
                    ok=False,
                    provider=settings.llm_provider,
                    model=settings.llm_model,
                    latency_ms=latency_ms,
                    detail="LLM response did not include choices.",
                )
            return LlmConnectionTestOut(
                ok=True,
                provider=settings.llm_provider,
                model=settings.llm_model,
                latency_ms=latency_ms,
                detail="LLM chat completions test succeeded.",
            )
        except (httpx.HTTPError, ValueError) as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return LlmConnectionTestOut(
                ok=False,
                provider=settings.llm_provider,
                model=settings.llm_model,
                latency_ms=latency_ms,
                detail=str(exc),
            )
```

- [ ] **Step 5: Add the LLM test route**

In `backend/src/ragstudio/api/routes/settings.py`, import `LlmConnectionTestOut` and `LlmConnectionService`, then add this route after `test_embedding_settings`:

```python
@router.post("/default/test-llm", response_model=LlmConnectionTestOut)
async def test_llm_settings(
    payload: SettingsProfileIn,
    session: AsyncSession = Depends(get_session),
) -> LlmConnectionTestOut:
    resolved_payload = await SettingsService(session).resolve_llm_test_payload(payload)
    return await LlmConnectionService().test(resolved_payload)
```

- [ ] **Step 6: Run LLM tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_settings.py::test_llm_connection_test_calls_chat_completions backend/tests/test_settings.py::test_llm_connection_test_uses_saved_api_key_when_blank -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add backend/src/ragstudio/services/llm_connection_service.py backend/src/ragstudio/schemas/settings.py backend/src/ragstudio/api/routes/settings.py backend/src/ragstudio/services/settings_service.py backend/tests/test_settings.py
git commit -m "feat: test llm runtime connection"
```

---

### Task 4: Add Provider Sync And LLM Controls To Settings UI

**Files:**
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/features/settings/settings-page.tsx`
- Test: `frontend/tests/settings-page.test.tsx`

- [ ] **Step 1: Write failing frontend tests**

Replace `frontend/tests/settings-page.test.tsx` with:

```tsx
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../src/api/client";
import { SettingsPage } from "../src/features/settings/settings-page";

vi.mock("../src/api/client", () => ({
  apiClient: {
    defaultSettings: vi.fn(),
    updateDefaultSettings: vi.fn(),
    testEmbeddingSettings: vi.fn(),
    testMinerUSettings: vi.fn(),
    testLlmSettings: vi.fn(),
    syncProviderPreview: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status = 500;
  },
}));

const settings = {
  id: "default",
  provider: "openai",
  llm_provider: "openai_compatible",
  llm_model: "gpt-4.1",
  llm_base_url: "",
  llm_timeout_ms: 10000,
  llm_capabilities: [],
  has_llm_api_key: false,
  embedding_model: "text-embedding-3-large",
  storage_backend: "local",
  embedding_provider: "fallback",
  embedding_base_url: "",
  embedding_timeout_ms: 10000,
  embedding_dimensions: 1536,
  embedding_batch_size: 16,
  embedding_tls_verify: true,
  has_embedding_api_key: false,
  mineru_enabled: true,
  mineru_base_url: "http://127.0.0.1:8765",
  mineru_timeout_ms: 1800000,
  mineru_poll_interval_ms: 1000,
};

function renderSettings() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <SettingsPage />
    </QueryClientProvider>,
  );
}

describe("SettingsPage provider sync", () => {
  beforeEach(() => {
    vi.mocked(apiClient.defaultSettings).mockResolvedValue(settings);
    vi.mocked(apiClient.updateDefaultSettings).mockResolvedValue(settings);
    vi.mocked(apiClient.syncProviderPreview).mockResolvedValue({
      ok: true,
      manifest_url: "https://updates.jihadaj.com/providers.json",
      manifest_version: 2,
      updated_at: "2026-05-07T08:23:27.928Z",
      patch: {
        llm_provider: "openai_compatible",
        llm_base_url: "http://10.10.9.195:8004/v1",
        llm_model: "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
        llm_timeout_ms: 5000,
        llm_capabilities: ["text", "vision", "reasoning"],
        embedding_provider: "vllm_openai",
        embedding_base_url: "http://10.10.9.192:8001/v1",
        embedding_model: "Qwen/Qwen3-Embedding-8B",
        embedding_dimensions: 1536,
        embedding_timeout_ms: 10000,
        mineru_enabled: true,
        mineru_base_url: "http://10.10.9.19:8765",
        mineru_timeout_ms: 1800000,
      },
      changed_fields: ["llm_base_url", "llm_model", "embedding_base_url", "mineru_base_url"],
      ignored_sections: ["stt"],
      detail: "Provider manifest preview generated.",
    });
  });

  it("renders MinerU and LLM settings", async () => {
    renderSettings();

    expect(await screen.findByText("MinerU parser")).toBeVisible();
    expect(screen.getByText("LLM generation")).toBeVisible();
    expect(screen.getByRole("button", { name: /Test LLM/i })).toBeVisible();
    expect(await screen.findByDisplayValue("http://127.0.0.1:8765")).toBeVisible();
  });

  it("previews provider sync changes without saving", async () => {
    renderSettings();

    fireEvent.change(await screen.findByLabelText("Provider manifest URL"), {
      target: { value: "https://updates.jihadaj.com/providers.json" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Sync/i }));

    expect(await screen.findByDisplayValue("http://10.10.9.195:8004/v1")).toBeVisible();
    expect(screen.getByDisplayValue("QuantTrio/Qwen3-VL-32B-Instruct-AWQ")).toBeVisible();
    expect(screen.getByDisplayValue("http://10.10.9.192:8001/v1")).toBeVisible();
    expect(screen.getByDisplayValue("http://10.10.9.19:8765")).toBeVisible();
    expect(screen.getByText("Vision")).toBeVisible();
    expect(screen.getByText(/Synced preview/i)).toBeVisible();
    expect(apiClient.updateDefaultSettings).not.toHaveBeenCalled();
  });

  it("saves the synced form values after preview", async () => {
    renderSettings();

    fireEvent.change(await screen.findByLabelText("Provider manifest URL"), {
      target: { value: "https://updates.jihadaj.com/providers.json" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Sync/i }));
    await screen.findByDisplayValue("http://10.10.9.195:8004/v1");
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    await waitFor(() =>
      expect(apiClient.updateDefaultSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          llm_provider: "openai_compatible",
          llm_base_url: "http://10.10.9.195:8004/v1",
          llm_model: "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
          llm_timeout_ms: 5000,
          llm_capabilities: ["text", "vision", "reasoning"],
          embedding_provider: "vllm_openai",
          embedding_base_url: "http://10.10.9.192:8001/v1",
          mineru_base_url: "http://10.10.9.19:8765",
        }),
      ),
    );
  });
});
```

- [ ] **Step 2: Run frontend tests to verify they fail**

Run:

```bash
cd frontend && npm test -- settings-page.test.tsx --run
```

Expected: FAIL because `syncProviderPreview`, `testLlmSettings`, and LLM UI fields do not exist.

- [ ] **Step 3: Add frontend API types and client calls**

In `frontend/src/api/generated.ts`, extend `SettingsProfileIn` and `SettingsProfileOut` with:

```ts
llm_provider?: "openai_compatible";
llm_base_url?: string | null;
llm_api_key?: string | null;
llm_timeout_ms?: number;
llm_capabilities?: Array<"text" | "vision" | "reasoning">;
```

and:

```ts
llm_provider: "openai_compatible";
llm_base_url: string | null;
has_llm_api_key: boolean;
llm_timeout_ms: number;
llm_capabilities: Array<"text" | "vision" | "reasoning">;
```

Add exported types:

```ts
export interface ProviderSyncPreviewIn {
  manifest_url: string;
}

export interface ProviderSyncPreviewOut {
  ok: boolean;
  manifest_url: string;
  manifest_version?: number | null;
  updated_at?: string | null;
  patch: Partial<SettingsProfileIn>;
  changed_fields: string[];
  ignored_sections: string[];
  detail: string;
}

export interface LlmConnectionTestOut {
  ok: boolean;
  provider: string;
  model: string;
  latency_ms: number;
  detail: string;
}
```

In `frontend/src/api/client.ts`, add imports for `ProviderSyncPreviewIn`, `ProviderSyncPreviewOut`, and `LlmConnectionTestOut`, then add:

```ts
  syncProviderPreview: (payload: ProviderSyncPreviewIn) =>
    request<ProviderSyncPreviewOut>("/api/settings/default/sync-provider-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  testLlmSettings: (payload: SettingsProfileIn) =>
    request<LlmConnectionTestOut>("/api/settings/default/test-llm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
```

- [ ] **Step 4: Refactor SettingsPage fields to controlled form state**

In `frontend/src/features/settings/settings-page.tsx`, replace `key={JSON.stringify(defaults)}` and uncontrolled `defaultValue` handling with a `useState<SettingsProfileIn>` called `formValues`. Initialize it from `settingsQuery.data` in `useEffect`:

```tsx
const [formValues, setFormValues] = useState<SettingsProfileIn | null>(null);
const [manifestUrl, setManifestUrl] = useState("https://updates.jihadaj.com/providers.json");
const [syncMessage, setSyncMessage] = useState("");

useEffect(() => {
  if (!settingsQuery.data) {
    return;
  }
  setFormValues({
    provider: settingsQuery.data.provider,
    llm_provider: settingsQuery.data.llm_provider,
    llm_model: settingsQuery.data.llm_model,
    llm_base_url: settingsQuery.data.llm_base_url ?? "",
    llm_timeout_ms: settingsQuery.data.llm_timeout_ms,
    llm_capabilities: settingsQuery.data.llm_capabilities,
    embedding_model: settingsQuery.data.embedding_model,
    storage_backend: settingsQuery.data.storage_backend,
    embedding_provider: settingsQuery.data.embedding_provider,
    embedding_base_url: settingsQuery.data.embedding_base_url ?? "",
    embedding_timeout_ms: settingsQuery.data.embedding_timeout_ms,
    embedding_dimensions: settingsQuery.data.embedding_dimensions,
    embedding_batch_size: settingsQuery.data.embedding_batch_size,
    embedding_tls_verify: settingsQuery.data.embedding_tls_verify,
    mineru_enabled: settingsQuery.data.mineru_enabled,
    mineru_base_url: settingsQuery.data.mineru_base_url ?? "",
    mineru_timeout_ms: settingsQuery.data.mineru_timeout_ms,
    mineru_poll_interval_ms: settingsQuery.data.mineru_poll_interval_ms,
  });
}, [settingsQuery.data]);
```

Use helper setters:

```tsx
const updateField = <K extends keyof SettingsProfileIn>(key: K, value: SettingsProfileIn[K]) => {
  setFormValues((current) => (current ? { ...current, [key]: value } : current));
};
```

Change `submit`, `submitForTest`, and `submitMinerUForTest` to use `formValues` instead of reading `FormData`. Preserve `embedding_api_key` and `llm_api_key` by reading those two password inputs from the form inside submit/test handlers and only setting them on the payload when non-empty.

- [ ] **Step 5: Add sync and LLM mutations**

In `SettingsPage`, add:

```tsx
const syncProvider = useMutation({
  mutationFn: apiClient.syncProviderPreview,
  onSuccess: (result) => {
    setFormValues((current) => (current ? { ...current, ...result.patch } : current));
    const changed = result.changed_fields.length ? result.changed_fields.join(", ") : "no saved values changed";
    setSyncMessage(`Synced preview: ${changed}`);
  },
  onError: (error) => {
    setSyncMessage(error instanceof Error ? error.message : "Provider sync failed");
  },
});

const testLlm = useMutation({
  mutationFn: apiClient.testLlmSettings,
});
```

Add handler:

```tsx
const syncFromManifest = () => {
  setSyncMessage("");
  syncProvider.mutate({ manifest_url: manifestUrl });
};
```

- [ ] **Step 6: Add Provider sync and LLM generation sections**

Add a Provider sync section before Runtime profile:

```tsx
<section className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
  <div className="mb-5 flex items-center gap-2">
    <RefreshCcw className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
    <h3 className="truncate text-base font-semibold text-[#1f2933]">Provider sync</h3>
  </div>
  <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
    <label className="min-w-0 text-sm font-medium text-[#3a4a53]">
      <span className="mb-1.5 block truncate">Provider manifest URL</span>
      <input
        className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20 disabled:bg-[#f4f7f8]"
        value={manifestUrl}
        onChange={(event) => setManifestUrl(event.target.value)}
        placeholder="https://updates.jihadaj.com/providers.json"
        disabled={syncProvider.isPending || updateSettings.isPending}
      />
    </label>
    <Button
      type="button"
      variant="secondary"
      onClick={syncFromManifest}
      disabled={syncProvider.isPending || updateSettings.isPending}
    >
      {syncProvider.isPending ? (
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
      ) : (
        <RefreshCcw className="h-4 w-4" aria-hidden="true" />
      )}
      Sync
    </Button>
  </div>
  <p className="mt-3 min-h-5 text-sm text-[#62717a]" role="status">
    {syncMessage}
  </p>
</section>
```

Add an LLM generation section between Runtime profile and MinerU:

```tsx
<section className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
  <div className="mb-5 flex items-center gap-2">
    <PlugZap className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
    <h3 className="truncate text-base font-semibold text-[#1f2933]">LLM generation</h3>
  </div>
  <div className="grid gap-4 sm:grid-cols-2">
    <SelectField
      label="LLM provider"
      name="llm_provider"
      value={formValues.llm_provider ?? "openai_compatible"}
      disabled={updateSettings.isPending}
      onChange={(value) => updateField("llm_provider", value as "openai_compatible")}
      options={[{ value: "openai_compatible", label: "OpenAI-compatible" }]}
    />
    <Field
      label="LLM model"
      name="llm_model"
      value={formValues.llm_model}
      placeholder="QuantTrio/Qwen3-VL-32B-Instruct-AWQ"
      disabled={updateSettings.isPending}
      onChange={(value) => updateField("llm_model", value)}
    />
    <Field
      label="LLM base URL"
      name="llm_base_url"
      value={formValues.llm_base_url ?? ""}
      placeholder="http://10.10.9.195:8004/v1"
      disabled={updateSettings.isPending}
      required={false}
      onChange={(value) => updateField("llm_base_url", value)}
    />
    <Field
      label="LLM API key"
      name="llm_api_key"
      value=""
      placeholder={settingsQuery.data?.has_llm_api_key ? "Saved key present" : "optional"}
      disabled={updateSettings.isPending}
      required={false}
      type="password"
    />
    <Field
      label="LLM timeout (ms)"
      name="llm_timeout_ms"
      value={String(formValues.llm_timeout_ms ?? 10000)}
      placeholder="10000"
      disabled={updateSettings.isPending}
      type="number"
      onChange={(value) => updateField("llm_timeout_ms", Number(value))}
    />
    <div className="min-w-0 text-sm font-medium text-[#3a4a53]">
      <span className="mb-1.5 block truncate">Capabilities</span>
      <div className="flex min-h-10 flex-wrap items-center gap-2 rounded-md border border-[#cfd8dd] px-3 py-2">
        {(formValues.llm_capabilities ?? []).map((capability) => (
          <span key={capability} className="rounded bg-[#e8f3f6] px-2 py-1 text-xs font-semibold text-[#176b87]">
            {capability === "text" ? "Text" : capability === "vision" ? "Vision" : "Reasoning"}
          </span>
        ))}
      </div>
    </div>
  </div>
</section>
```

Update `Field` and `SelectField` props to support controlled `value` and `onChange` while still allowing the password field to omit `onChange`.

- [ ] **Step 7: Run frontend tests**

Run:

```bash
cd frontend && npm test -- settings-page.test.tsx --run
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add frontend/src/api/generated.ts frontend/src/api/client.ts frontend/src/features/settings/settings-page.tsx frontend/tests/settings-page.test.tsx
git commit -m "feat: add provider sync settings ui"
```

---

### Task 5: Document And Verify The Full Workflow

**Files:**
- Modify: `docs/user-guide.md`
- Modify: `docs/workflows.md`

- [ ] **Step 1: Update user-facing docs**

In `docs/user-guide.md`, add this section under Settings:

```markdown
### Provider Sync

Use **Settings -> Provider sync** to preview a hosted HPC provider manifest before saving runtime changes. Enter a manifest URL such as `https://updates.jihadaj.com/providers.json`, click **Sync**, and review the updated LLM, embeddings, and MinerU fields. Sync only updates the form preview. Click **Save** to persist the reviewed settings.

The supported manifest sections are `reasoning`, `embeddings`, and `hpcMineru`. `reasoning` configures the OpenAI-compatible LLM endpoint and shows read-only capability badges for Text, Vision, and Reasoning.
```

In `docs/workflows.md`, add this workflow:

```markdown
### Rotate HPC Runtime Endpoints

1. Publish or refresh the Cloudflare-hosted provider manifest after the HPC services are running behind stable aliases.
2. Open Ragstudio Settings.
3. Enter the manifest URL in **Provider sync**.
4. Click **Sync** and review the changed fields.
5. Click **Test LLM**, **Test connection** for embeddings, and **Test MinerU** as needed.
6. Click **Save** after the preview matches the intended runtime profile.
```

- [ ] **Step 2: Run targeted verification**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_settings.py -q
cd frontend && npm test -- settings-page.test.tsx --run
```

Expected: all targeted tests PASS.

- [ ] **Step 3: Run full verification**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH ./scripts/test-all.sh
```

Expected: backend tests, ruff, pyright, frontend lint, frontend tests, and frontend build PASS. The existing pyright warning in `backend/src/ragstudio/db/repositories.py` may still appear if it is unchanged from the baseline.

- [ ] **Step 4: Commit docs and any verification fixes**

Run:

```bash
git add docs/user-guide.md docs/workflows.md
git commit -m "docs: document hpc provider sync workflow"
```

---

## Self-Review

Spec coverage:

- Manifest URL sync preview is covered in Task 2 and Task 4.
- LLM runtime fields, API key preservation, read-only capabilities, and LLM testing are covered in Task 1, Task 3, and Task 4.
- Embeddings and MinerU manifest mapping are covered in Task 2 and Task 4.
- Preview-before-save behavior is covered by backend non-persistence assertions and frontend save assertions.
- Error handling for invalid URLs and malformed fetches is covered by Task 2 service behavior and tests.
- Documentation and full verification are covered in Task 5.

Placeholder scan:

- The plan contains no `TBD`, `TODO`, incomplete sections, or unassigned edge handling.

Type consistency:

- Backend field names match the design: `llm_provider`, `llm_base_url`, `llm_api_key`, `llm_timeout_ms`, `llm_capabilities`.
- Manifest field names match Meeting Copilot: `reasoning.apiUrl`, `reasoning.model`, `reasoning.timeoutMs`, `embeddings.apiUrl`, `embeddings.model`, `embeddings.dimensions`, `embeddings.timeoutMs`, `hpcMineru.enabled`, `hpcMineru.apiUrl`, `hpcMineru.timeoutMs`.
- Frontend API methods match routes: `syncProviderPreview` -> `/api/settings/default/sync-provider-preview`, `testLlmSettings` -> `/api/settings/default/test-llm`.
