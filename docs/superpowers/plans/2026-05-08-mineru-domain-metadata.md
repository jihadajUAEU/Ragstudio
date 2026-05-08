# MinerU Domain Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MinerU parsing through the Meeting Copilot API contract and apply reviewed domain-aware metadata to both MinerU and local fallback chunks.

**Architecture:** Extend the existing Settings profile with MinerU connection fields, add focused parser/domain schemas, and keep the current `chunks` table as the retrieval source of truth. A new MinerU client handles `POST /parse-async`, `GET /parse-jobs/{job_id}`, artifact download, safe extraction, and artifact normalization; `ChunkService` chooses between local fallback, MinerU strict, and MinerU with fallback. The frontend adds MinerU settings, metadata profile review controls on upload/index, and provenance badges on chunk cards.

**Tech Stack:** FastAPI, SQLAlchemy async SQLite, Pydantic v2, httpx, pytest, React, TypeScript, TanStack Query, Vitest, Vite.

---

## File Structure

Backend files:

- Modify `backend/src/ragstudio/db/models.py`: add MinerU fields to `SettingsProfile`.
- Modify `backend/src/ragstudio/db/engine.py`: add SQLite column backfill for MinerU fields.
- Modify `backend/src/ragstudio/schemas/settings.py`: include MinerU settings and `MinerUConnectionTestOut`.
- Create `backend/src/ragstudio/schemas/parsing.py`: parser mode, domain metadata, index request, domain profile, and metadata suggestion schemas.
- Create `backend/src/ragstudio/services/domain_metadata_service.py`: built-in profiles, heuristic suggestions, profile JSON persistence.
- Create `backend/src/ragstudio/services/mineru_client.py`: Meeting Copilot MinerU contract, artifact download, safe extraction, artifact-to-chunk normalization.
- Modify `backend/src/ragstudio/services/settings_service.py`: round-trip MinerU settings.
- Modify `backend/src/ragstudio/services/chunk_service.py`: accept parser mode and domain metadata, merge metadata into chunks, call MinerU client.
- Modify `backend/src/ragstudio/services/document_service.py`: pass parser mode/domain metadata from uploads into indexing jobs.
- Modify `backend/src/ragstudio/api/routes/settings.py`: add `/default/test-mineru`.
- Modify `backend/src/ragstudio/api/routes/chunks.py`: accept JSON body for parser mode/domain metadata.
- Modify `backend/src/ragstudio/api/routes/documents.py`: accept metadata fields in multipart upload.
- Create `backend/src/ragstudio/api/routes/domain_profiles.py`: list built-ins/saved profiles and suggest metadata.
- Modify `backend/src/ragstudio/api/routes/__init__.py`: include domain profile router.
- Test `backend/tests/test_settings.py`: MinerU settings and connection tests.
- Test `backend/tests/test_domain_metadata.py`: built-in profiles and heuristic/LLM-free suggestions.
- Test `backend/tests/test_mineru_client.py`: fake MinerU service, artifact normalization, unsafe zip rejection.
- Test `backend/tests/test_chunks.py`: local metadata copy, MinerU strict, MinerU fallback.

Frontend files:

- Modify `frontend/src/api/client.ts`: add MinerU settings test, domain profiles, metadata suggest, upload/index payloads.
- Regenerate or edit `frontend/src/api/generated.ts`: include new schemas if generation is available.
- Create `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`: shared parser mode/profile/review UI.
- Modify `frontend/src/features/settings/settings-page.tsx`: add MinerU parser section.
- Modify `frontend/src/features/documents/documents-page.tsx`: collect parser mode/domain metadata on upload.
- Modify `frontend/src/features/chunks/chunk-inspector.tsx`: collect parser mode/domain metadata for Index and show provenance badges.
- Test `frontend/tests/settings-page.test.tsx`: MinerU settings render/test states.
- Test `frontend/tests/domain-metadata-panel.test.tsx`: built-in profile selection and metadata JSON validation.
- Test `frontend/tests/chunk-inspector.test.tsx`: parser mode passed to index and badges shown.

Docs:

- Modify `docs/user-guide.md`: MinerU settings, metadata profiles, upload/index behavior.
- Modify `docs/workflows.md`: MinerU API contract and fallback semantics.

---

### Task 1: MinerU Settings Schema And Connection Test

**Files:**
- Modify: `backend/src/ragstudio/db/models.py`
- Modify: `backend/src/ragstudio/db/engine.py`
- Modify: `backend/src/ragstudio/schemas/settings.py`
- Modify: `backend/src/ragstudio/services/settings_service.py`
- Modify: `backend/src/ragstudio/api/routes/settings.py`
- Test: `backend/tests/test_settings.py`

- [ ] **Step 1: Write failing settings tests**

Append these tests to `backend/tests/test_settings.py`:

```python
@pytest.mark.asyncio
async def test_settings_profile_saves_mineru_config(client):
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "sqlite",
        "mineru_enabled": True,
        "mineru_base_url": "http://127.0.0.1:8765/",
        "mineru_timeout_ms": 1800000,
        "mineru_poll_interval_ms": 1000,
    }

    response = await client.put("/api/settings/default", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["mineru_enabled"] is True
    assert body["mineru_base_url"] == "http://127.0.0.1:8765"
    assert body["mineru_timeout_ms"] == 1800000
    assert body["mineru_poll_interval_ms"] == 1000


@pytest.mark.asyncio
async def test_mineru_connection_test_calls_health(client, monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ready": True, "detail": "MinerU ready"}

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

    monkeypatch.setattr(
        "ragstudio.api.routes.settings.httpx.AsyncClient",
        FakeAsyncClient,
    )
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "sqlite",
        "mineru_enabled": True,
        "mineru_base_url": "http://127.0.0.1:8765",
        "mineru_timeout_ms": 5000,
        "mineru_poll_interval_ms": 250,
    }

    response = await client.post("/api/settings/default/test-mineru", json=payload)

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "base_url": "http://127.0.0.1:8765",
        "detail": "MinerU ready",
    }
    assert requests == [{"url": "http://127.0.0.1:8765/health", "timeout": 5.0}]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_settings.py -q
```

Expected: FAIL because `SettingsProfileIn` has no MinerU fields and `/api/settings/default/test-mineru` does not exist.

- [ ] **Step 3: Add database columns**

In `backend/src/ragstudio/db/models.py`, add these fields to `SettingsProfile` after embedding fields:

```python
    mineru_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mineru_base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    mineru_timeout_ms: Mapped[int] = mapped_column(Integer, default=1800000)
    mineru_poll_interval_ms: Mapped[int] = mapped_column(Integer, default=1000)
```

In `backend/src/ragstudio/db/engine.py`, add these entries to `_ensure_settings_profile_columns.additions`:

```python
        "mineru_enabled": "BOOLEAN DEFAULT 0 NOT NULL",
        "mineru_base_url": "VARCHAR",
        "mineru_timeout_ms": "INTEGER DEFAULT 1800000 NOT NULL",
        "mineru_poll_interval_ms": "INTEGER DEFAULT 1000 NOT NULL",
```

- [ ] **Step 4: Add Pydantic settings fields**

In `backend/src/ragstudio/schemas/settings.py`, add fields to `SettingsProfileIn`:

```python
    mineru_enabled: bool = False
    mineru_base_url: str | None = None
    mineru_timeout_ms: int = Field(default=1_800_000, ge=1_000, le=86_400_000)
    mineru_poll_interval_ms: int = Field(default=1_000, ge=100, le=60_000)
```

Add a validator:

```python
    @field_validator("mineru_base_url")
    @classmethod
    def validate_mineru_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        if not normalized:
            return None
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("MinerU base URL must be an http or https URL")
        if parsed.username or parsed.password:
            raise ValueError("MinerU base URL must not include credentials")
        return normalized
```

Add the same MinerU fields to `SettingsProfileOut`.

Add this response schema:

```python
class MinerUConnectionTestOut(StudioModel):
    ok: bool
    base_url: str
    detail: str
```

- [ ] **Step 5: Return MinerU settings from service**

In `backend/src/ragstudio/services/settings_service.py`, add these properties in `_to_out`:

```python
            mineru_enabled=bool(profile.mineru_enabled),
            mineru_base_url=profile.mineru_base_url,
            mineru_timeout_ms=profile.mineru_timeout_ms or 1_800_000,
            mineru_poll_interval_ms=profile.mineru_poll_interval_ms or 1_000,
```

- [ ] **Step 6: Add `/test-mineru` route**

In `backend/src/ragstudio/api/routes/settings.py`, import `httpx` and `MinerUConnectionTestOut`, then add:

```python
@router.post("/default/test-mineru", response_model=MinerUConnectionTestOut)
async def test_mineru_settings(payload: SettingsProfileIn) -> MinerUConnectionTestOut:
    if not payload.mineru_base_url:
        return MinerUConnectionTestOut(ok=False, base_url="", detail="MinerU base URL is required.")
    timeout = payload.mineru_timeout_ms / 1000
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{payload.mineru_base_url}/health")
    except httpx.HTTPError as exc:
        return MinerUConnectionTestOut(
            ok=False,
            base_url=payload.mineru_base_url,
            detail=f"Could not connect to MinerU service: {exc}",
        )
    if response.status_code >= 400:
        return MinerUConnectionTestOut(
            ok=False,
            base_url=payload.mineru_base_url,
            detail=f"MinerU health check returned HTTP {response.status_code}.",
        )
    data = response.json()
    detail = str(data.get("detail") or data.get("status") or "MinerU service is reachable.")
    return MinerUConnectionTestOut(ok=True, base_url=payload.mineru_base_url, detail=detail)
```

- [ ] **Step 7: Run tests and commit**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_settings.py -q
```

Expected: PASS.

Commit:

```bash
git add backend/src/ragstudio/db/models.py backend/src/ragstudio/db/engine.py backend/src/ragstudio/schemas/settings.py backend/src/ragstudio/services/settings_service.py backend/src/ragstudio/api/routes/settings.py backend/tests/test_settings.py
git commit -m "feat: add mineru settings"
```

---

### Task 2: Domain Metadata Profiles And Suggestions

**Files:**
- Create: `backend/src/ragstudio/schemas/parsing.py`
- Create: `backend/src/ragstudio/services/domain_metadata_service.py`
- Create: `backend/src/ragstudio/api/routes/domain_profiles.py`
- Modify: `backend/src/ragstudio/api/routes/__init__.py`
- Test: `backend/tests/test_domain_metadata.py`

- [ ] **Step 1: Write failing domain metadata tests**

Create `backend/tests/test_domain_metadata.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_domain_profiles_include_general_and_islamic_builtins(client):
    response = await client.get("/api/domain-profiles")

    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"]]
    assert "Generic document" in names
    assert "Research paper" in names
    assert "Policy/admin document" in names
    assert "Table/spreadsheet" in names
    assert "Hadith" in names
    assert "Quran/Tafseer" in names
    assert "Fatwa/Fiqh" in names


@pytest.mark.asyncio
async def test_domain_metadata_suggestion_uses_filename_and_profile(client):
    response = await client.post(
        "/api/domain-profiles/suggest",
        json={
            "filename": "hadith_bukhari.pdf",
            "content_type": "application/pdf",
            "profile_id": "hadith",
            "sample_text": "Sahih al-Bukhari\nBook 1, Hadith 1",
        },
    )

    assert response.status_code == 200
    metadata = response.json()["domain_metadata"]
    assert metadata["domain"] == "hadith"
    assert metadata["document_type"] == "collection"
    assert metadata["collection"] == "Sahih al-Bukhari"
    assert "profile" in metadata["metadata_sources"]
    assert "heuristic" in metadata["metadata_sources"]


@pytest.mark.asyncio
async def test_saved_domain_profile_round_trip(client):
    payload = {
        "id": "uaeu_policy",
        "name": "UAEU policy",
        "description": "Local policy profile",
        "metadata": {
            "domain": "policy",
            "document_type": "admin_document",
            "tags": ["uaeu", "policy"],
            "metadata_sources": ["user"],
        },
    }

    create_response = await client.put("/api/domain-profiles/uaeu_policy", json=payload)
    list_response = await client.get("/api/domain-profiles")

    assert create_response.status_code == 200
    assert any(item["id"] == "uaeu_policy" for item in list_response.json()["items"])
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_domain_metadata.py -q
```

Expected: FAIL because the route and schemas do not exist.

- [ ] **Step 3: Add parsing schemas**

Create `backend/src/ragstudio/schemas/parsing.py`:

```python
from typing import Any, Literal

from pydantic import Field

from ragstudio.schemas.common import StudioModel

ParserMode = Literal["local_fallback", "mineru_strict", "mineru_with_fallback"]


class DomainMetadata(StudioModel):
    domain: str = "generic"
    document_type: str = "document"
    language: str = "unknown"
    tags: list[str] = Field(default_factory=list)
    authority: str | None = None
    source: str | None = None
    collection: str | None = None
    citation_style: str | None = None
    expected_structure: str | None = None
    custom_json: dict[str, Any] = Field(default_factory=dict)
    reference_pattern: str | None = None
    script: str | None = None
    content_role: str | None = None
    metadata_sources: list[str] = Field(default_factory=list)


class DomainProfileOut(StudioModel):
    id: str
    name: str
    description: str
    metadata: DomainMetadata


class DomainProfileListOut(StudioModel):
    items: list[DomainProfileOut]
    total: int


class DomainProfileIn(StudioModel):
    id: str
    name: str
    description: str = ""
    metadata: DomainMetadata


class DomainMetadataSuggestIn(StudioModel):
    filename: str
    content_type: str = "application/octet-stream"
    profile_id: str | None = None
    sample_text: str = ""


class DomainMetadataSuggestOut(StudioModel):
    domain_metadata: DomainMetadata


class IndexDocumentIn(StudioModel):
    parser_mode: ParserMode = "local_fallback"
    domain_metadata: DomainMetadata = Field(default_factory=DomainMetadata)
```

- [ ] **Step 4: Add domain metadata service**

Create `backend/src/ragstudio/services/domain_metadata_service.py`:

```python
from __future__ import annotations

import json
import re
from pathlib import Path

from ragstudio.schemas.parsing import (
    DomainMetadata,
    DomainMetadataSuggestIn,
    DomainProfileIn,
    DomainProfileOut,
)


BUILTIN_PROFILES: list[DomainProfileOut] = [
    DomainProfileOut(
        id="generic",
        name="Generic document",
        description="General uploaded document.",
        metadata=DomainMetadata(domain="generic", document_type="document", tags=["document"]),
    ),
    DomainProfileOut(
        id="research_paper",
        name="Research paper",
        description="Academic or technical research paper.",
        metadata=DomainMetadata(
            domain="research",
            document_type="paper",
            tags=["research", "paper"],
            citation_style="academic",
        ),
    ),
    DomainProfileOut(
        id="policy_admin",
        name="Policy/admin document",
        description="Administrative, policy, procedure, or governance document.",
        metadata=DomainMetadata(
            domain="policy",
            document_type="admin_document",
            tags=["policy", "admin"],
            expected_structure="sections",
        ),
    ),
    DomainProfileOut(
        id="table_spreadsheet",
        name="Table/spreadsheet",
        description="Structured rows, sheets, registers, or tabular data.",
        metadata=DomainMetadata(
            domain="data",
            document_type="table",
            tags=["table", "spreadsheet"],
            expected_structure="rows",
        ),
    ),
    DomainProfileOut(
        id="hadith",
        name="Hadith",
        description="Hadith collection or commentary.",
        metadata=DomainMetadata(
            domain="hadith",
            document_type="collection",
            language="mixed",
            tags=["hadith", "arabic", "english"],
            citation_style="book_hadith",
            expected_structure="book_hadith_records",
            reference_pattern="Book N, Hadith N",
            script="mixed",
            content_role="hadith",
        ),
    ),
    DomainProfileOut(
        id="quran_tafseer",
        name="Quran/Tafseer",
        description="Quran translation, tafseer, or verse explanation.",
        metadata=DomainMetadata(
            domain="quran_tafseer",
            document_type="commentary",
            language="mixed",
            tags=["quran", "tafseer", "arabic", "english"],
            citation_style="surah_ayah",
            expected_structure="surah_ayah_sections",
            script="mixed",
            content_role="tafseer",
        ),
    ),
    DomainProfileOut(
        id="fatwa_fiqh",
        name="Fatwa/Fiqh",
        description="Fatwa, legal ruling, or jurisprudence material.",
        metadata=DomainMetadata(
            domain="fiqh",
            document_type="fatwa",
            language="mixed",
            tags=["fatwa", "fiqh", "ruling"],
            expected_structure="question_answer",
            script="mixed",
            content_role="fiqh ruling",
        ),
    ),
]


class DomainMetadataService:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.profile_path = data_dir / "domain-profiles.json"

    def list_profiles(self) -> list[DomainProfileOut]:
        return [*BUILTIN_PROFILES, *self._saved_profiles()]

    def upsert_profile(self, profile: DomainProfileIn) -> DomainProfileOut:
        saved = DomainProfileOut.model_validate(profile.model_dump())
        profiles = {item.id: item for item in self._saved_profiles()}
        profiles[saved.id] = saved
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile_path.write_text(
            json.dumps([item.model_dump() for item in profiles.values()], indent=2),
            encoding="utf-8",
        )
        return saved

    def suggest(self, payload: DomainMetadataSuggestIn) -> DomainMetadata:
        profile = next(
            (item for item in self.list_profiles() if item.id == payload.profile_id),
            BUILTIN_PROFILES[0],
        )
        metadata = profile.metadata.model_copy(deep=True)
        sources = set(metadata.metadata_sources)
        sources.add("profile")
        filename_text = f"{payload.filename} {payload.sample_text}".casefold()
        if "bukhari" in filename_text:
            metadata.collection = "Sahih al-Bukhari"
            sources.add("heuristic")
        elif "tirmidhi" in filename_text:
            metadata.collection = "Jami at-Tirmidhi"
            sources.add("heuristic")
        elif "muslim" in filename_text:
            metadata.collection = "Sahih Muslim"
            sources.add("heuristic")
        if re.search(r"book\s+\d+\s*,?\s*hadith\s+\d+", filename_text):
            metadata.reference_pattern = "Book N, Hadith N"
            sources.add("heuristic")
        if payload.filename.lower().endswith((".csv", ".xlsx", ".xls")):
            metadata.domain = "data"
            metadata.document_type = "table"
            metadata.tags = sorted(set([*metadata.tags, "table"]))
            sources.add("heuristic")
        metadata.metadata_sources = sorted(sources)
        return metadata

    def _saved_profiles(self) -> list[DomainProfileOut]:
        if not self.profile_path.exists():
            return []
        data = json.loads(self.profile_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [DomainProfileOut.model_validate(item) for item in data]
```

- [ ] **Step 5: Add domain profile routes**

Create `backend/src/ragstudio/api/routes/domain_profiles.py`:

```python
from fastapi import APIRouter, Request

from ragstudio.schemas.parsing import (
    DomainProfileIn,
    DomainProfileOut,
    DomainMetadataSuggestIn,
    DomainMetadataSuggestOut,
    DomainProfileListOut,
)
from ragstudio.services.domain_metadata_service import DomainMetadataService

router = APIRouter(prefix="/api/domain-profiles", tags=["domain-profiles"])


@router.get("", response_model=DomainProfileListOut)
async def list_domain_profiles(request: Request) -> DomainProfileListOut:
    items = DomainMetadataService(request.app.state.settings.data_dir).list_profiles()
    return DomainProfileListOut(items=items, total=len(items))


@router.post("/suggest", response_model=DomainMetadataSuggestOut)
async def suggest_domain_metadata(
    payload: DomainMetadataSuggestIn,
    request: Request,
) -> DomainMetadataSuggestOut:
    metadata = DomainMetadataService(request.app.state.settings.data_dir).suggest(payload)
    return DomainMetadataSuggestOut(domain_metadata=metadata)


@router.put("/{profile_id}", response_model=DomainProfileOut)
async def upsert_domain_profile(
    profile_id: str,
    payload: DomainProfileIn,
    request: Request,
) -> DomainProfileOut:
    profile = payload.model_copy(update={"id": profile_id})
    return DomainMetadataService(request.app.state.settings.data_dir).upsert_profile(profile)
```

In `backend/src/ragstudio/api/routes/__init__.py`, import `domain_profiles` and append `domain_profiles.router` to the router list.

- [ ] **Step 6: Run tests and commit**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_domain_metadata.py -q
```

Expected: PASS.

Commit:

```bash
git add backend/src/ragstudio/schemas/parsing.py backend/src/ragstudio/services/domain_metadata_service.py backend/src/ragstudio/api/routes/domain_profiles.py backend/src/ragstudio/api/routes/__init__.py backend/tests/test_domain_metadata.py
git commit -m "feat: add domain metadata profiles"
```

---

### Task 3: MinerU Client And Artifact Normalization

**Files:**
- Create: `backend/src/ragstudio/services/mineru_client.py`
- Test: `backend/tests/test_mineru_client.py`

- [ ] **Step 1: Write failing MinerU client tests**

Create `backend/tests/test_mineru_client.py`:

```python
from pathlib import Path
from zipfile import ZipFile

import pytest

from ragstudio.services.mineru_client import MinerUArtifactError, MinerUClient


@pytest.mark.asyncio
async def test_mineru_client_parses_artifact_zip(tmp_path):
    artifact_zip = tmp_path / "artifact.zip"
    with ZipFile(artifact_zip, "w") as archive:
        archive.writestr(
            "manifest.json",
            '{"parseMethod":"auto","items":[{"path":"pages/page-1.md","pageNumber":1,"contentType":"text"}]}',
        )
        archive.writestr("pages/page-1.md", "Alpha page text")

    client = MinerUClient(base_url="http://mineru.test", timeout_ms=1000, poll_interval_ms=100)

    chunks = client.normalize_artifact_zip(
        artifact_zip=artifact_zip,
        extract_dir=tmp_path / "extract",
        document_id="doc-1",
        parser_mode="mineru_strict",
        parse_job_id="job-1",
    )

    assert len(chunks) == 1
    assert chunks[0].text == "Alpha page text"
    assert chunks[0].source_location == {"page": 1, "artifact": "pages/page-1.md"}
    assert chunks[0].metadata["parser_metadata"]["backend"] == "mineru"
    assert chunks[0].metadata["parser_metadata"]["content_type"] == "text"
    assert chunks[0].metadata["parser_metadata"]["parse_job_id"] == "job-1"


def test_mineru_client_rejects_unsafe_zip_paths(tmp_path):
    artifact_zip = tmp_path / "unsafe.zip"
    with ZipFile(artifact_zip, "w") as archive:
        archive.writestr("../escape.md", "bad")

    client = MinerUClient(base_url="http://mineru.test", timeout_ms=1000, poll_interval_ms=100)

    with pytest.raises(MinerUArtifactError):
        client.normalize_artifact_zip(
            artifact_zip=artifact_zip,
            extract_dir=tmp_path / "extract",
            document_id="doc-1",
            parser_mode="mineru_strict",
            parse_job_id="job-1",
        )
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_mineru_client.py -q
```

Expected: FAIL because `mineru_client.py` does not exist.

- [ ] **Step 3: Implement MinerU client artifact normalization**

Create `backend/src/ragstudio/services/mineru_client.py`:

```python
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import httpx

from ragstudio.schemas.parsing import ParserMode
from ragstudio.services.adapter import AdapterChunk


class MinerUArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class MinerUJobResult:
    parse_job_id: str
    artifact_zip: Path


class MinerUClient:
    def __init__(self, base_url: str, timeout_ms: int, poll_interval_ms: int):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_ms / 1000
        self.poll_interval_seconds = poll_interval_ms / 1000

    async def parse_document(
        self,
        *,
        artifact_path: str | Path,
        document_id: str,
        artifact_dir: Path,
    ) -> MinerUJobResult:
        parse_job_id = await self.submit_parse(artifact_path, document_id)
        ready_job = await self.poll_until_ready(parse_job_id)
        artifact_zip = await self.download_artifacts(
            str(ready_job.get("jobId") or parse_job_id),
            artifact_dir / "artifacts.zip",
        )
        return MinerUJobResult(parse_job_id=parse_job_id, artifact_zip=artifact_zip)

    async def submit_parse(self, artifact_path: str | Path, document_id: str) -> str:
        path = Path(artifact_path)
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            with path.open("rb") as file_obj:
                response = await client.post(
                    f"{self.base_url}/parse-async",
                    files={"file": (path.name, file_obj, "application/octet-stream")},
                    data={"sourceId": document_id, "sourceType": "uploaded_document", "title": path.name},
                )
        response.raise_for_status()
        payload = response.json()
        return str(payload["jobId"])

    async def poll_parse_job(self, parse_job_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f"{self.base_url}/parse-jobs/{parse_job_id}")
        response.raise_for_status()
        return response.json()

    async def poll_until_ready(self, parse_job_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            payload = await self.poll_parse_job(parse_job_id)
            status = str(payload.get("status") or "").lower()
            if status == "ready":
                return payload
            if status == "failed":
                detail = str(payload.get("error") or payload.get("detail") or "MinerU parse failed.")
                raise RuntimeError(detail)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"MinerU parse timed out for job {parse_job_id}.")
            await asyncio.sleep(self.poll_interval_seconds)

    async def download_artifacts(self, parse_job_id: str, target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f"{self.base_url}/parse-jobs/{parse_job_id}/artifacts")
        response.raise_for_status()
        target_path.write_bytes(response.content)
        return target_path

    def normalize_artifact_zip(
        self,
        *,
        artifact_zip: Path,
        extract_dir: Path,
        document_id: str,
        parser_mode: ParserMode,
        parse_job_id: str,
    ) -> list[AdapterChunk]:
        self._extract_safe(artifact_zip, extract_dir)
        manifest = self._read_manifest(extract_dir)
        chunks: list[AdapterChunk] = []
        for index, item in enumerate(manifest.get("items", [])):
            if not isinstance(item, dict):
                continue
            rel_path = str(item.get("path") or "")
            if not rel_path:
                continue
            artifact_path = extract_dir / rel_path
            if not artifact_path.exists() or artifact_path.is_dir():
                continue
            text = artifact_path.read_text(encoding="utf-8", errors="replace").strip()
            if not text:
                continue
            page_number = item.get("pageNumber")
            source_location = {"artifact": rel_path}
            if isinstance(page_number, int):
                source_location["page"] = page_number
            chunks.append(
                AdapterChunk(
                    text=text,
                    source_location=source_location,
                    metadata={
                        "parser_metadata": {
                            "backend": "mineru",
                            "parser_mode": parser_mode,
                            "parse_job_id": parse_job_id,
                            "artifact_ref": rel_path,
                            "content_type": str(item.get("contentType") or "text"),
                            "chunk_index": index,
                            "document_id": document_id,
                        }
                    },
                )
            )
        return chunks

    def _extract_safe(self, artifact_zip: Path, extract_dir: Path) -> None:
        extract_dir.mkdir(parents=True, exist_ok=True)
        root = extract_dir.resolve()
        with ZipFile(artifact_zip) as archive:
            for member in archive.infolist():
                target = (extract_dir / member.filename).resolve()
                if root not in target.parents and target != root:
                    raise MinerUArtifactError(f"Unsafe artifact path: {member.filename}")
            archive.extractall(extract_dir)

    def _read_manifest(self, extract_dir: Path) -> dict[str, Any]:
        manifest_path = extract_dir / "manifest.json"
        if not manifest_path.exists():
            return {
                "items": [
                    {"path": path.relative_to(extract_dir).as_posix(), "contentType": "text"}
                    for path in sorted(extract_dir.rglob("*.md"))
                ]
            }
        return json.loads(manifest_path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run tests and commit**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_mineru_client.py -q
```

Expected: PASS.

Commit:

```bash
git add backend/src/ragstudio/services/mineru_client.py backend/tests/test_mineru_client.py
git commit -m "feat: add mineru artifact client"
```

---

### Task 4: Chunk Indexing Parser Modes

**Files:**
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Modify: `backend/src/ragstudio/api/routes/chunks.py`
- Test: `backend/tests/test_chunks.py`

- [ ] **Step 1: Write failing chunk metadata tests**

Append to `backend/tests/test_chunks.py`:

```python
@pytest.mark.asyncio
async def test_index_local_chunks_copies_domain_metadata(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("hadith.txt", b"Book 1, Hadith 1\n", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    response = await client.post(
        f"/api/chunks/index/{document_id}",
        json={
            "parser_mode": "local_fallback",
            "domain_metadata": {
                "domain": "hadith",
                "document_type": "collection",
                "language": "mixed",
                "tags": ["hadith"],
                "collection": "Sahih al-Bukhari",
                "metadata_sources": ["profile", "user"],
            },
        },
    )

    assert response.status_code == 200
    metadata = response.json()[0]["metadata"]
    assert metadata["domain_metadata"]["domain"] == "hadith"
    assert metadata["domain_metadata"]["collection"] == "Sahih al-Bukhari"
    assert metadata["parser_metadata"]["backend"] == "fallback"
    assert metadata["parser_metadata"]["parser_mode"] == "local_fallback"


@pytest.mark.asyncio
async def test_index_mineru_strict_uses_adapter_chunks(client, monkeypatch):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("paper.pdf", b"%PDF fake", "application/pdf")},
    )
    document_id = upload_response.json()["id"]

    async def fake_index_document(self, document_id, *, options):
        from ragstudio.services.adapter import AdapterChunk

        return [
            AdapterChunk(
                text="MinerU text",
                source_location={"page": 1, "artifact": "pages/page-1.md"},
                metadata={
                    "parser_metadata": {
                        "backend": "mineru",
                        "parser_mode": "mineru_strict",
                        "parse_job_id": "job-1",
                        "content_type": "text",
                    }
                },
            )
        ]

    monkeypatch.setattr(
        "ragstudio.services.chunk_service.ChunkService._mineru_adapter_chunks",
        fake_index_document,
    )

    response = await client.post(
        f"/api/chunks/index/{document_id}",
        json={
            "parser_mode": "mineru_strict",
            "domain_metadata": {"domain": "research", "document_type": "paper"},
        },
    )

    assert response.status_code == 200
    chunk = response.json()[0]
    assert chunk["text"] == "MinerU text"
    assert chunk["metadata"]["domain_metadata"]["domain"] == "research"
    assert chunk["metadata"]["parser_metadata"]["backend"] == "mineru"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_chunks.py -q
```

Expected: FAIL because `/api/chunks/index/{document_id}` does not accept a JSON body and `ChunkService` does not accept parser mode/domain metadata.

- [ ] **Step 3: Update ChunkService signature and metadata merge**

In `backend/src/ragstudio/services/chunk_service.py`, import:

```python
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn, ParserMode
from ragstudio.services.mineru_client import MinerUClient
```

Change `index_document` signature:

```python
    async def index_document(
        self,
        document_id: str,
        *,
        options: IndexDocumentIn | None = None,
        commit: bool = True,
    ) -> list[ChunkOut] | None:
```

At the start of the method after document lookup:

```python
        options = options or IndexDocumentIn()
        adapter_chunks = await self._adapter_chunks(document, options)
```

Replace the current `adapter_chunks = await self.adapter.index_document(...)` line with the line above.

Add helper methods:

```python
    async def _adapter_chunks(self, document: Document, options: IndexDocumentIn) -> list[AdapterChunk]:
        if options.parser_mode == "local_fallback":
            return await self.adapter.index_document(document.artifact_path)
        try:
            return await self._mineru_adapter_chunks(document.id, options=options)
        except Exception as exc:
            if options.parser_mode == "mineru_strict":
                raise
            chunks = await self.adapter.index_document(document.artifact_path)
            return [
                AdapterChunk(
                    text=chunk.text,
                    source_location=chunk.source_location,
                    metadata={
                        **chunk.metadata,
                        "parser_metadata": {
                            "backend": "fallback",
                            "parser_mode": "mineru_with_fallback",
                            "mineru_error": str(exc),
                            "fallback_used": True,
                        },
                    },
                )
                for chunk in chunks
            ]

    async def _mineru_adapter_chunks(
        self,
        document_id: str,
        *,
        options: IndexDocumentIn,
    ) -> list[AdapterChunk]:
        document = await self.session.get(Document, document_id)
        if document is None:
            return []
        settings = await self.session.get(SettingsProfile, "default")
        if settings is None or not settings.mineru_base_url:
            raise RuntimeError("MinerU base URL is not configured.")
        client = MinerUClient(
            base_url=settings.mineru_base_url,
            timeout_ms=settings.mineru_timeout_ms or 1_800_000,
            poll_interval_ms=settings.mineru_poll_interval_ms or 1_000,
        )
        artifact_dir = self.data_dir / "mineru-artifacts" / document.id
        job_result = await client.parse_document(
            artifact_path=document.artifact_path,
            document_id=document.id,
            artifact_dir=artifact_dir,
        )
        return client.normalize_artifact_zip(
            artifact_zip=job_result.artifact_zip,
            extract_dir=artifact_dir / "extracted",
            document_id=document.id,
            parser_mode=options.parser_mode,
            parse_job_id=job_result.parse_job_id,
        )
```

Also import `SettingsProfile` and `AdapterChunk`.

Change chunk creation metadata:

```python
                metadata_json=self._safe_metadata(
                    self._merge_metadata(adapter_chunk.metadata, options.domain_metadata, options.parser_mode),
                    document.id,
                ),
```

Add helper:

```python
    def _merge_metadata(
        self,
        parser_metadata: dict[str, Any],
        domain_metadata: DomainMetadata,
        parser_mode: ParserMode,
    ) -> dict[str, Any]:
        metadata = dict(parser_metadata)
        metadata["domain_metadata"] = domain_metadata.model_dump(exclude_none=True)
        if "parser_metadata" not in metadata:
            metadata["parser_metadata"] = {
                "backend": metadata.get("backend", "fallback"),
                "parser_mode": parser_mode,
                "chunk_index": metadata.get("chunk_index"),
            }
        metadata.pop("backend", None)
        return metadata
```

- [ ] **Step 4: Accept body in chunks route**

In `backend/src/ragstudio/api/routes/chunks.py`, import `IndexDocumentIn` and change route signature:

```python
async def index_document_chunks(
    document_id: str,
    request: Request,
    options: IndexDocumentIn | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[ChunkOut]:
```

Pass options:

```python
    chunks = await ChunkService(session, request.app.state.settings.data_dir).index_document(
        document_id,
        options=options or IndexDocumentIn(),
    )
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_chunks.py -q
```

Expected: PASS.

Commit:

```bash
git add backend/src/ragstudio/services/chunk_service.py backend/src/ragstudio/api/routes/chunks.py backend/tests/test_chunks.py
git commit -m "feat: add parser modes to chunk indexing"
```

---

### Task 5: Document Upload Parser Options

**Files:**
- Modify: `backend/src/ragstudio/api/routes/documents.py`
- Modify: `backend/src/ragstudio/services/document_service.py`
- Test: `backend/tests/test_documents.py`

- [ ] **Step 1: Write failing upload metadata test**

Create `backend/tests/test_documents.py`:

```python
import json

import pytest


@pytest.mark.asyncio
async def test_upload_accepts_parser_mode_and_domain_metadata(client):
    response = await client.post(
        "/api/documents",
        data={
            "parser_mode": "local_fallback",
            "domain_metadata": json.dumps(
                {
                    "domain": "policy",
                    "document_type": "admin_document",
                    "tags": ["policy"],
                    "metadata_sources": ["user"],
                }
            ),
        },
        files={"file": ("policy.txt", b"Policy line\n", "text/plain")},
    )

    assert response.status_code == 201
    document_id = response.json()["id"]
    search_response = await client.post(
        "/api/chunks/search",
        json={"query": "Policy", "document_ids": [document_id], "limit": 10},
    )
    assert search_response.status_code == 200
    assert search_response.json()["items"][0]["metadata"]["domain_metadata"]["domain"] == "policy"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_documents.py -q
```

Expected: FAIL because upload route does not accept parser fields.

- [ ] **Step 3: Parse multipart parser options**

In `backend/src/ragstudio/api/routes/documents.py`, import `Form`, `json`, `DomainMetadata`, and `IndexDocumentIn`. Change the route signature:

```python
async def upload_document(
    request: Request,
    file: UploadFile,
    parser_mode: str = Form(default="local_fallback"),
    domain_metadata: str = Form(default="{}"),
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
```

Build options:

```python
    metadata = DomainMetadata.model_validate(json.loads(domain_metadata or "{}"))
    options = IndexDocumentIn(parser_mode=parser_mode, domain_metadata=metadata)
```

Pass options to `DocumentService.upload`.

- [ ] **Step 4: Pass options through DocumentService**

In `backend/src/ragstudio/services/document_service.py`, import `IndexDocumentIn`. Change `upload` signature:

```python
    async def upload(
        self,
        filename: str,
        content_type: str,
        content: bytes,
        *,
        options: IndexDocumentIn | None = None,
    ) -> DocumentOut:
```

In `_ensure_indexed`, accept options:

```python
    async def _ensure_indexed(self, document: Document, options: IndexDocumentIn | None = None) -> None:
```

Pass options into `_index_document_for_job` and `ChunkService.index_document`.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_documents.py backend/tests/test_chunks.py -q
```

Expected: PASS.

Commit:

```bash
git add backend/src/ragstudio/api/routes/documents.py backend/src/ragstudio/services/document_service.py backend/tests/test_documents.py
git commit -m "feat: apply parser metadata during upload"
```

---

### Task 6: Frontend API Client And Domain Metadata Panel

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/generated.ts`
- Create: `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`
- Test: `frontend/tests/domain-metadata-panel.test.tsx`

- [ ] **Step 1: Write failing component test**

Create `frontend/tests/domain-metadata-panel.test.tsx`:

```tsx
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DomainMetadataPanel } from "../src/features/domain-metadata/domain-metadata-panel";

describe("DomainMetadataPanel", () => {
  it("renders parser modes and applies a selected domain profile", async () => {
    const onChange = vi.fn();
    render(
      <DomainMetadataPanel
        profiles={[
          {
            id: "hadith",
            name: "Hadith",
            description: "Hadith collection",
            metadata: {
              domain: "hadith",
              document_type: "collection",
              language: "mixed",
              tags: ["hadith"],
              metadata_sources: ["profile"],
            },
          },
        ]}
        value={{
          parser_mode: "local_fallback",
          domain_metadata: { domain: "generic", document_type: "document", tags: [] },
        }}
        onChange={onChange}
      />,
    );

    await userEvent.selectOptions(screen.getByLabelText("Parser"), "mineru_with_fallback");
    await userEvent.selectOptions(screen.getByLabelText("Domain profile"), "hadith");

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        parser_mode: "mineru_with_fallback",
        domain_metadata: expect.objectContaining({ domain: "hadith", document_type: "collection" }),
      }),
    );
  });
});
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd frontend && npm test -- --run ../frontend/tests/domain-metadata-panel.test.tsx
```

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Add API client methods and types**

In `frontend/src/api/generated.ts`, add minimal exported types if OpenAPI generation is not run:

```ts
export type ParserMode = "local_fallback" | "mineru_strict" | "mineru_with_fallback";

export interface DomainMetadata {
  domain?: string;
  document_type?: string;
  language?: string;
  tags?: string[];
  authority?: string | null;
  source?: string | null;
  collection?: string | null;
  citation_style?: string | null;
  expected_structure?: string | null;
  custom_json?: Record<string, unknown>;
  reference_pattern?: string | null;
  script?: string | null;
  content_role?: string | null;
  metadata_sources?: string[];
}

export interface DomainProfileOut {
  id: string;
  name: string;
  description: string;
  metadata: DomainMetadata;
}

export interface IndexDocumentIn {
  parser_mode?: ParserMode;
  domain_metadata?: DomainMetadata;
}
```

In `frontend/src/api/client.ts`, add:

```ts
  domainProfiles: () => request<{ items: DomainProfileOut[]; total: number }>("/api/domain-profiles"),
  suggestDomainMetadata: (payload: {
    filename: string;
    content_type: string;
    profile_id?: string | null;
    sample_text?: string;
  }) =>
    request<{ domain_metadata: DomainMetadata }>("/api/domain-profiles/suggest", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
```

Update `indexDocumentChunks` to accept `IndexDocumentIn`:

```ts
  indexDocumentChunks: (documentId: string, payload: IndexDocumentIn = {}) =>
    request<ChunkOut[]>(`/api/chunks/index/${encodeURIComponent(documentId)}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
```

Update `uploadDocument` to accept options:

```ts
  uploadDocument: ({ file, options }: { file: File; options: IndexDocumentIn }) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("parser_mode", options.parser_mode ?? "local_fallback");
    formData.append("domain_metadata", JSON.stringify(options.domain_metadata ?? {}));
    return request<DocumentOut>("/api/documents", { method: "POST", body: formData });
  },
```

- [ ] **Step 4: Create `DomainMetadataPanel`**

Create `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`:

```tsx
import type { DomainMetadata, DomainProfileOut, IndexDocumentIn, ParserMode } from "../../api/generated";

const parserOptions: Array<{ value: ParserMode; label: string }> = [
  { value: "local_fallback", label: "Local fallback" },
  { value: "mineru_strict", label: "MinerU strict" },
  { value: "mineru_with_fallback", label: "MinerU with fallback" },
];

export function DomainMetadataPanel({
  profiles,
  value,
  onChange,
  disabled = false,
}: {
  profiles: DomainProfileOut[];
  value: IndexDocumentIn;
  onChange: (value: IndexDocumentIn) => void;
  disabled?: boolean;
}) {
  const metadata = value.domain_metadata ?? {};
  const setMetadata = (patch: DomainMetadata) => {
    onChange({ ...value, domain_metadata: { ...metadata, ...patch } });
  };

  return (
    <section className="rounded-md border border-[#d6dde1] bg-white p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm font-medium text-[#3a4a53]">
          <span className="mb-1.5 block">Parser</span>
          <select
            aria-label="Parser"
            className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm"
            value={value.parser_mode ?? "local_fallback"}
            disabled={disabled}
            onChange={(event) => onChange({ ...value, parser_mode: event.target.value as ParserMode })}
          >
            {parserOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium text-[#3a4a53]">
          <span className="mb-1.5 block">Domain profile</span>
          <select
            aria-label="Domain profile"
            className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm"
            disabled={disabled}
            onChange={(event) => {
              const profile = profiles.find((item) => item.id === event.target.value);
              if (profile) {
                onChange({ ...value, domain_metadata: profile.metadata });
              }
            }}
          >
            <option value="">Choose profile</option>
            {profiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.name}
              </option>
            ))}
          </select>
        </label>
        <TextField label="Domain" value={metadata.domain ?? ""} disabled={disabled} onChange={(domain) => setMetadata({ domain })} />
        <TextField label="Document type" value={metadata.document_type ?? ""} disabled={disabled} onChange={(document_type) => setMetadata({ document_type })} />
        <TextField label="Language" value={metadata.language ?? ""} disabled={disabled} onChange={(language) => setMetadata({ language })} />
        <TextField label="Collection" value={metadata.collection ?? ""} disabled={disabled} onChange={(collection) => setMetadata({ collection })} />
        <TextField
          label="Tags"
          value={(metadata.tags ?? []).join(", ")}
          disabled={disabled}
          onChange={(tags) => setMetadata({ tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean) })}
        />
      </div>
    </section>
  );
}

function TextField({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="text-sm font-medium text-[#3a4a53]">
      <span className="mb-1.5 block">{label}</span>
      <input
        className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
```

- [ ] **Step 5: Run test and commit**

Run:

```bash
cd frontend && npm test -- --run ../frontend/tests/domain-metadata-panel.test.tsx
```

Expected: PASS.

Commit:

```bash
git add frontend/src/api/client.ts frontend/src/api/generated.ts frontend/src/features/domain-metadata/domain-metadata-panel.tsx frontend/tests/domain-metadata-panel.test.tsx
git commit -m "feat: add domain metadata panel"
```

---

### Task 7: Frontend Settings, Upload, Index, And Chunk Badges

**Files:**
- Modify: `frontend/src/features/settings/settings-page.tsx`
- Modify: `frontend/src/features/documents/documents-page.tsx`
- Modify: `frontend/src/features/chunks/chunk-inspector.tsx`
- Test: `frontend/tests/settings-page.test.tsx`
- Test: `frontend/tests/chunk-inspector.test.tsx`

- [ ] **Step 1: Write failing UI tests**

Create `frontend/tests/settings-page.test.tsx`:

```tsx
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SettingsPage } from "../src/features/settings/settings-page";

vi.mock("../src/api/client", () => ({
  apiClient: {
    defaultSettings: vi.fn().mockResolvedValue({
      provider: "openai",
      llm_model: "gpt-4.1",
      embedding_model: "text-embedding-3-large",
      storage_backend: "local",
      embedding_provider: "fallback",
      embedding_timeout_ms: 10000,
      embedding_dimensions: 1536,
      embedding_batch_size: 16,
      embedding_tls_verify: true,
      has_embedding_api_key: false,
      mineru_enabled: true,
      mineru_base_url: "http://127.0.0.1:8765",
      mineru_timeout_ms: 1800000,
      mineru_poll_interval_ms: 1000,
    }),
    updateDefaultSettings: vi.fn(),
    testEmbeddingSettings: vi.fn(),
    testMinerUSettings: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
}));

describe("SettingsPage MinerU", () => {
  it("renders MinerU parser settings", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <SettingsPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("MinerU parser")).toBeVisible();
    expect(screen.getByDisplayValue("http://127.0.0.1:8765")).toBeVisible();
    expect(screen.getByRole("button", { name: /Test MinerU/i })).toBeVisible();
  });
});
```

Create `frontend/tests/chunk-inspector.test.tsx`:

```tsx
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChunkInspector } from "../src/features/chunks/chunk-inspector";

vi.mock("../src/api/client", () => ({
  apiClient: {
    documents: vi.fn().mockResolvedValue({ items: [{ id: "doc-1", filename: "hadith.pdf", status: "ready" }], total: 1 }),
    domainProfiles: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    indexDocumentChunks: vi.fn(),
    searchChunks: vi.fn().mockResolvedValue({
      total: 1,
      items: [
        {
          id: "chunk-1",
          document_id: "doc-1",
          text: "Book 1, Hadith 1",
          source_location: { page: 1 },
          metadata: {
            score: 1,
            domain_metadata: { domain: "hadith" },
            parser_metadata: { backend: "mineru" },
          },
        },
      ],
    }),
  },
}));

describe("ChunkInspector metadata", () => {
  it("renders parser controls", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ChunkInspector />
      </QueryClientProvider>,
    );

    expect(await screen.findByLabelText("Parser")).toBeVisible();
    expect(screen.getByLabelText("Domain profile")).toBeVisible();
  });
});
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd frontend && npm test -- --run ../frontend/tests/settings-page.test.tsx ../frontend/tests/chunk-inspector.test.tsx
```

Expected: FAIL because UI does not render MinerU controls or domain metadata panel.

- [ ] **Step 3: Update Settings page**

In `frontend/src/features/settings/settings-page.tsx`:

Add MinerU fields to `buildPayload`:

```ts
      mineru_enabled: formData.get("mineru_enabled") === "on",
      mineru_base_url: String(formData.get("mineru_base_url") ?? ""),
      mineru_timeout_ms: Number(formData.get("mineru_timeout_ms") ?? 1800000),
      mineru_poll_interval_ms: Number(formData.get("mineru_poll_interval_ms") ?? 1000),
```

Add defaults:

```ts
    mineru_enabled: settingsQuery.data?.mineru_enabled ?? false,
    mineru_base_url: settingsQuery.data?.mineru_base_url ?? "",
    mineru_timeout_ms: settingsQuery.data?.mineru_timeout_ms ?? 1800000,
    mineru_poll_interval_ms: settingsQuery.data?.mineru_poll_interval_ms ?? 1000,
```

Add mutation:

```ts
  const testMinerU = useMutation({
    mutationFn: apiClient.testMinerUSettings,
  });
```

Add a `submitMinerUForTest` handler mirroring `submitForTest`.

Render a section after Embeddings:

```tsx
        <section className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
          <div className="mb-5 flex items-center gap-2">
            <PlugZap className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
            <h3 className="truncate text-base font-semibold text-[#1f2933]">MinerU parser</h3>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="flex h-10 items-center gap-2 self-end rounded-md border border-[#cfd8dd] px-3 text-sm font-medium text-[#3a4a53]">
              <input name="mineru_enabled" type="checkbox" defaultChecked={defaults.mineru_enabled} />
              Enable MinerU
            </label>
            <Field label="MinerU base URL" name="mineru_base_url" defaultValue={defaults.mineru_base_url ?? ""} placeholder="http://127.0.0.1:8765" required={false} />
            <Field label="MinerU timeout (ms)" name="mineru_timeout_ms" defaultValue={String(defaults.mineru_timeout_ms ?? 1800000)} type="number" />
            <Field label="MinerU poll interval (ms)" name="mineru_poll_interval_ms" defaultValue={String(defaults.mineru_poll_interval_ms ?? 1000)} type="number" />
          </div>
          <div className="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="min-h-5 text-sm text-[#62717a]" role="status">
              {testMinerU.error?.message || (testMinerU.data ? `${testMinerU.data.ok ? "Connected" : "Failed"}: ${testMinerU.data.detail}` : "")}
            </p>
            <Button type="button" variant="secondary" onClick={submitMinerUForTest} disabled={testMinerU.isPending}>
              {testMinerU.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <PlugZap className="h-4 w-4" aria-hidden="true" />}
              Test MinerU
            </Button>
          </div>
        </section>
```

- [ ] **Step 4: Update Documents page**

In `frontend/src/features/documents/documents-page.tsx`:

Import `DomainMetadataPanel` and `IndexDocumentIn`.

Add state:

```ts
  const [indexOptions, setIndexOptions] = useState<IndexDocumentIn>({
    parser_mode: "local_fallback",
    domain_metadata: { domain: "generic", document_type: "document", tags: [] },
  });
  const profilesQuery = useQuery({ queryKey: ["domain-profiles"], queryFn: apiClient.domainProfiles });
```

Change mutation call:

```ts
uploadDocument.mutate({ file, options: indexOptions });
```

Render `DomainMetadataPanel` inside the upload section before the submit button.

- [ ] **Step 5: Update Chunk Inspector**

In `frontend/src/features/chunks/chunk-inspector.tsx`:

Import `DomainMetadataPanel` and `IndexDocumentIn`.

Add state:

```ts
  const [indexOptions, setIndexOptions] = useState<IndexDocumentIn>({
    parser_mode: "local_fallback",
    domain_metadata: { domain: "generic", document_type: "document", tags: [] },
  });
  const profilesQuery = useQuery({ queryKey: ["domain-profiles"], queryFn: apiClient.domainProfiles });
```

Change index mutation:

```ts
  const indexDocument = useMutation({
    mutationFn: (documentId: string) => apiClient.indexDocumentChunks(documentId, indexOptions),
```

Render `DomainMetadataPanel` above the search form.

Add badges in `ChunkCard`:

```tsx
        <div className="flex flex-wrap gap-2">
          <Badge>{String(chunk.metadata.parser_metadata?.backend ?? "fallback")}</Badge>
          <Badge>{String(chunk.metadata.domain_metadata?.domain ?? "generic")}</Badge>
        </div>
```

Add helper:

```tsx
function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-md bg-[#eef4f6] px-2 py-1 text-xs font-medium text-[#174657]">
      {children}
    </span>
  );
}
```

- [ ] **Step 6: Run tests and commit**

Run:

```bash
cd frontend && npm test -- --run ../frontend/tests/settings-page.test.tsx ../frontend/tests/chunk-inspector.test.tsx ../frontend/tests/domain-metadata-panel.test.tsx
```

Expected: PASS.

Commit:

```bash
git add frontend/src/features/settings/settings-page.tsx frontend/src/features/documents/documents-page.tsx frontend/src/features/chunks/chunk-inspector.tsx frontend/tests/settings-page.test.tsx frontend/tests/chunk-inspector.test.tsx
git commit -m "feat: wire mineru metadata UI"
```

---

### Task 8: Documentation And Full Verification

**Files:**
- Modify: `docs/user-guide.md`
- Modify: `docs/workflows.md`

- [ ] **Step 1: Update user guide**

In `docs/user-guide.md`, add a `MinerU parser and domain metadata` subsection under Settings:

```markdown
### MinerU parser and domain metadata

Settings includes a `MinerU parser` section for connecting to an already running MinerU/RAG-Anything service. Set the base URL, normally `http://127.0.0.1:8765` when using an SSH tunnel or local sidecar, then click `Test MinerU`.

Upload and Index actions support three parser modes:

- `Local fallback`: uses Ragstudio's local line splitter.
- `MinerU strict`: sends the document to MinerU and fails indexing if MinerU fails.
- `MinerU with fallback`: tries MinerU first, then indexes locally if MinerU fails.

Before parsing, choose or review domain metadata. This metadata is copied onto every resulting chunk, including local fallback chunks. MinerU adds parser metadata such as page numbers, artifact references, content type, and parse job id.
```

- [ ] **Step 2: Update workflows**

In `docs/workflows.md`, add a MinerU workflow:

```markdown
## MinerU parsing workflow

Ragstudio targets the Meeting Copilot MinerU contract:

1. `POST /parse-async`
2. `GET /parse-jobs/{job_id}`
3. `GET /parse-jobs/{job_id}/artifacts`

Artifacts are stored under `.ragstudio/mineru-artifacts/<document_id>/`. Ragstudio extracts the artifact zip safely, rejects unsafe paths, normalizes text/table/media entries into chunks, and keeps the `chunks` table as the source of truth for search, query, experiments, and comparison.

Domain metadata is applied before parsing. Parser metadata is added after parsing. Chunk metadata therefore has two top-level groups: `domain_metadata` and `parser_metadata`.
```

- [ ] **Step 3: Run backend tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH pytest backend/tests/test_settings.py backend/tests/test_domain_metadata.py backend/tests/test_mineru_client.py backend/tests/test_chunks.py backend/tests/test_documents.py -q
```

Expected: PASS.

- [ ] **Step 4: Run full verification**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH ./scripts/test-all.sh
```

Expected:

- Backend pytest passes.
- Ruff passes.
- Pyright has 0 errors. The existing warning in `backend/src/ragstudio/db/repositories.py` may remain.
- Frontend lint passes.
- Frontend tests pass.
- Frontend build passes.

- [ ] **Step 5: Browser QA smoke**

Start or reuse the servers:

```bash
PATH=$PWD/.venv/bin:$PATH python -m uvicorn ragstudio.app:create_app --factory --app-dir backend/src --host 127.0.0.1 --port 8000
cd frontend && npm run dev -- --host 127.0.0.1
```

In the browser:

1. Open `http://127.0.0.1:5174/settings`.
2. Save MinerU base URL `http://127.0.0.1:8765`.
3. Click `Test MinerU`.
4. Open Documents.
5. Select parser `Local fallback`.
6. Select profile `Hadith`.
7. Upload a text file with `Book 1, Hadith 1`.
8. Open Chunks and search `Hadith`.
9. Confirm the chunk card shows parser badge `fallback` and domain badge `hadith`.

- [ ] **Step 6: Commit docs**

Commit:

```bash
git add docs/user-guide.md docs/workflows.md
git commit -m "docs: explain mineru metadata workflow"
```

- [ ] **Step 7: Push branch**

Run:

```bash
git status --porcelain
git push
```

Expected: clean working tree before push and push succeeds.
