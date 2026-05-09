# AI Vision Domain Autosuggest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace rule-based metadata autosuggest with a pre-MinerU AI suggestion flow that samples 3-4 pages from the selected file, sends them to the configured vision LLM, validates strict `DomainMetadata`, and shows the existing review diff before upload/indexing.

**Architecture:** Keep built-in domain profiles as user-selectable defaults, but remove filename heuristics from autosuggest. Add a backend page sampler for uploaded files, a vision-capable metadata suggester that uses the saved default settings profile, and a multipart `/api/domain-profiles/suggest` endpoint. The Documents upload form sends the selected file for suggestion before upload; accepted metadata then flows unchanged into MinerU and shared chunking.

**Tech Stack:** FastAPI multipart uploads, SQLAlchemy settings profile lookup, httpx OpenAI-compatible chat completions, PyMuPDF for PDF page rendering/text fallback, Pydantic validation, React/TypeScript, Vitest, pytest.

---

## Scope Check

This plan is one subsystem: domain metadata autosuggest. It does not change MinerU parsing, chunk splitting, runtime indexing, or the settings UI except that autosuggest uses the already configured default vision/LLM profile.

---

## File Structure

- Modify: `backend/pyproject.toml`
  - Add `pymupdf` for deterministic PDF page sampling and rendering.
- Modify: `backend/src/ragstudio/schemas/parsing.py`
  - Extend `DomainMetadataSuggestOut` with AI evidence fields.
- Create: `backend/src/ragstudio/services/page_sampler.py`
  - Extract 3-4 representative pages from PDFs and text-like files before MinerU.
  - Render PDF pages to PNG data URLs for vision models.
  - Provide text fallback snippets for non-PDF/text files.
- Create: `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`
  - Build a strict prompt for honest domain metadata classification.
  - Call configured vision settings first, then LLM settings only if vision settings are absent but the LLM has `vision` capability.
  - Parse JSON from the model response and validate with `DomainMetadata`.
- Modify: `backend/src/ragstudio/services/domain_metadata_service.py`
  - Remove `suggest()` filename/profile heuristic logic.
  - Keep profile listing/upsert only.
- Modify: `backend/src/ragstudio/api/routes/domain_profiles.py`
  - Change `/api/domain-profiles/suggest` to multipart file upload.
  - Load the default settings profile and call the AI suggester.
- Modify: `backend/tests/test_domain_metadata.py`
  - Replace heuristic tests with multipart AI autosuggest tests.
- Create: `backend/tests/test_page_sampler.py`
  - Test representative page selection and safe fallbacks.
- Modify: `frontend/src/api/client.ts`
  - Change `suggestDomainMetadata` to accept a `File` and send `FormData`.
- Modify: `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`
  - Require a file in `suggestContext` before enabling AI autosuggest.
  - Display AI confidence/evidence text returned by the backend.
- Modify: `frontend/src/features/documents/documents-page.tsx`
  - Pass the selected `File` into `DomainMetadataPanel`.
- Modify: `frontend/src/features/chunks/chunk-inspector.tsx`
  - Do not show autosuggest for already indexed documents because no source `File` is available there.
- Modify: `frontend/tests/domain-metadata-panel.test.tsx`
  - Update mocks and add evidence/confidence coverage.
- Modify: `frontend/tests/documents-page.test.tsx`
  - Verify the Documents form sends the selected file to autosuggest.
- Modify: `docs/user-guide.md`
  - Document AI-based pre-MinerU autosuggest.

---

### Task 1: Add Schemas and Page Sampler

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/src/ragstudio/schemas/parsing.py`
- Create: `backend/src/ragstudio/services/page_sampler.py`
- Create: `backend/tests/test_page_sampler.py`

- [ ] **Step 1: Add the PDF sampling dependency**

Modify `backend/pyproject.toml` dependencies:

```toml
dependencies = [
  "fastapi>=0.136.1",
  "uvicorn>=0.46.0",
  "pydantic>=2.13.4",
  "sqlalchemy>=2.0.49",
  "alembic>=1.18.4",
  "asyncpg>=0.31.0",
  "python-multipart>=0.0.27",
  "httpx>=0.28.1",
  "pydantic-settings>=2.12.0",
  "pyyaml>=6.0.3",
  "torch>=2.11.0",
  "orjson>=3.11.9",
  "structlog>=25.5.0",
  "anyio>=4.13.0",
  "neo4j>=5.28.0",
  "pgvector>=0.4.1",
  "pymupdf>=1.26.6",
  "raganything[all]>=1.3.0",
]
```

- [ ] **Step 2: Extend autosuggest response schema**

In `backend/src/ragstudio/schemas/parsing.py`, replace `DomainMetadataSuggestOut` with:

```python
class DomainMetadataSuggestOut(StudioModel):
    domain_metadata: DomainMetadata
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_pages: list[int] = Field(default_factory=list)
    rationale: str = ""
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 3: Write failing sampler tests**

Create `backend/tests/test_page_sampler.py`:

```python
from ragstudio.services.page_sampler import PageSampler


def test_sample_text_file_uses_start_middle_end_excerpts():
    lines = [f"line {index}" for index in range(120)]
    pages = PageSampler().sample(
        b"\n".join(line.encode("utf-8") for line in lines),
        filename="notes.txt",
        content_type="text/plain",
    )

    assert [page.page_number for page in pages] == [1, 2, 3]
    assert "line 0" in pages[0].text
    assert "line 60" in pages[1].text
    assert "line 119" in pages[2].text
    assert all(page.image_data_url is None for page in pages)


def test_sample_pdf_returns_warning_for_invalid_pdf_bytes():
    sampler = PageSampler()

    pages = sampler.sample(
        b"%PDF invalid bytes",
        filename="broken.pdf",
        content_type="application/pdf",
    )

    assert pages == []
    assert sampler.warnings
    assert "Could not sample PDF pages" in sampler.warnings[0]
```

- [ ] **Step 4: Run sampler tests and verify they fail**

Run:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_page_sampler.py -q
```

Expected: FAIL because `ragstudio.services.page_sampler` does not exist.

- [ ] **Step 5: Implement page sampler**

Create `backend/src/ragstudio/services/page_sampler.py`:

```python
from __future__ import annotations

import base64
from dataclasses import dataclass


@dataclass(frozen=True)
class SampledPage:
    page_number: int
    text: str
    image_data_url: str | None = None


class PageSampler:
    def __init__(self, max_pages: int = 4, max_text_chars: int = 4000):
        self.max_pages = max_pages
        self.max_text_chars = max_text_chars
        self.warnings: list[str] = []

    def sample(self, data: bytes, *, filename: str, content_type: str) -> list[SampledPage]:
        self.warnings = []
        lower_name = filename.lower()
        if content_type == "application/pdf" or lower_name.endswith(".pdf"):
            return self._sample_pdf(data)
        return self._sample_text(data)

    def _sample_pdf(self, data: bytes) -> list[SampledPage]:
        try:
            import fitz

            document = fitz.open(stream=data, filetype="pdf")
            indexes = self._representative_indexes(document.page_count)
            pages: list[SampledPage] = []
            for index in indexes:
                page = document.load_page(index)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                image_data = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
                pages.append(
                    SampledPage(
                        page_number=index + 1,
                        text=page.get_text("text")[: self.max_text_chars].strip(),
                        image_data_url=f"data:image/png;base64,{image_data}",
                    )
                )
            document.close()
            return pages
        except Exception as exc:
            self.warnings.append(f"Could not sample PDF pages: {exc}")
            return []

    def _sample_text(self, data: bytes) -> list[SampledPage]:
        text = data.decode("utf-8", errors="replace")
        if not text.strip():
            return []
        segment_length = max(len(text) // 3, 1)
        starts = [0, max((len(text) - segment_length) // 2, 0), max(len(text) - segment_length, 0)]
        pages: list[SampledPage] = []
        seen: set[int] = set()
        for page_number, start in enumerate(starts, start=1):
            if start in seen:
                continue
            seen.add(start)
            pages.append(
                SampledPage(
                    page_number=page_number,
                    text=text[start : start + self.max_text_chars].strip(),
                )
            )
        return pages

    def _representative_indexes(self, page_count: int) -> list[int]:
        if page_count <= 0:
            return []
        candidates = [0, 1, page_count // 2, page_count - 1]
        indexes: list[int] = []
        for candidate in candidates:
            bounded = min(max(candidate, 0), page_count - 1)
            if bounded not in indexes:
                indexes.append(bounded)
            if len(indexes) == self.max_pages:
                break
        return indexes
```

- [ ] **Step 6: Run sampler tests and commit**

Run:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_page_sampler.py -q
```

Expected: PASS.

Commit:

```bash
git add backend/pyproject.toml backend/src/ragstudio/schemas/parsing.py backend/src/ragstudio/services/page_sampler.py backend/tests/test_page_sampler.py
git commit -m "feat: add autosuggest page sampler"
```

---

### Task 2: Add AI Metadata Suggester

**Files:**
- Create: `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`
- Modify: `backend/tests/test_domain_metadata.py`

- [ ] **Step 1: Add failing service test for vision chat completions**

Append to `backend/tests/test_domain_metadata.py`:

```python
from ragstudio.db.models import SettingsProfile


async def test_ai_domain_metadata_suggest_uses_vision_model(client, monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """{
                              "domain_metadata": {
                                "domain": "quran_tafseer",
                                "document_type": "commentary",
                                "language": "mixed",
                                "tags": ["quran", "tafseer"],
                                "citation_style": "surah_ayah",
                                "expected_structure": "surah_ayah_sections",
                                "script": "mixed",
                                "content_role": "tafseer",
                                "metadata_sources": ["ai_vision"]
                              },
                              "confidence": 0.92,
                              "rationale": "Sample pages show Quran verses and commentary.",
                              "warnings": []
                            }"""
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            calls.append({"url": url, "headers": headers, "json": json})
            return FakeResponse()

    monkeypatch.setattr("ragstudio.services.domain_metadata_ai_suggester.httpx.AsyncClient", FakeClient)

    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="text-model",
                llm_base_url="http://llm.test/v1",
                vision_model="vision-model",
                vision_base_url="http://vision.test/v1",
                vision_api_key="vision-secret",
            )
        )
        await session.commit()

    response = await client.post(
        "/api/domain-profiles/suggest",
        data={"profile_id": "generic"},
        files={"file": ("tafseer.pdf", b"%PDF invalid", "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["domain_metadata"]["domain"] == "quran_tafseer"
    assert body["domain_metadata"]["metadata_sources"] == ["ai_vision"]
    assert body["confidence"] == 0.92
    assert calls[0]["url"] == "http://vision.test/v1/chat/completions"
    assert calls[0]["headers"]["authorization"] == "Bearer vision-secret"
    assert calls[0]["json"]["model"] == "vision-model"
    assert calls[0]["json"]["temperature"] == 0
```

- [ ] **Step 2: Add failing test that old filename heuristics are gone**

Append to `backend/tests/test_domain_metadata.py`:

```python
async def test_domain_metadata_suggest_does_not_use_filename_heuristics(client):
    response = await client.post(
        "/api/domain-profiles/suggest",
        json={
            "filename": "hadith_bukhari.pdf",
            "content_type": "application/pdf",
            "profile_id": "hadith",
            "sample_text": "Book 1, Hadith 1",
        },
    )

    assert response.status_code in {400, 422}
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_domain_metadata.py -q
```

Expected: FAIL because the endpoint is still JSON/rule based and AI service does not exist.

- [ ] **Step 4: Implement the AI suggester service**

Create `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx
from ragstudio.db.models import SettingsProfile
from ragstudio.schemas.parsing import DomainMetadata, DomainMetadataSuggestOut
from ragstudio.services.page_sampler import SampledPage


@dataclass(frozen=True)
class LlmTarget:
    base_url: str
    model: str
    api_key: str | None
    timeout_ms: int
    source: str


class DomainMetadataAiSuggester:
    async def suggest(
        self,
        *,
        settings_profile: SettingsProfile,
        filename: str,
        content_type: str,
        pages: list[SampledPage],
        sampler_warnings: list[str],
    ) -> DomainMetadataSuggestOut:
        target = self._target(settings_profile)
        payload = self._payload(
            target=target,
            filename=filename,
            content_type=content_type,
            pages=pages,
        )
        headers = {"content-type": "application/json"}
        if target.api_key:
            headers["authorization"] = f"Bearer {target.api_key}"

        async with httpx.AsyncClient(timeout=target.timeout_ms / 1000) as client:
            response = await client.post(
                f"{target.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
        if response.status_code >= 400:
            raise ValueError(f"Metadata autosuggest LLM returned HTTP {response.status_code}.")
        raw = self._message_content(response.json())
        parsed = self._parse_json(raw)
        metadata = DomainMetadata.model_validate(parsed["domain_metadata"])
        metadata.metadata_sources = ["ai_vision" if target.source == "vision" else "ai_llm"]
        return DomainMetadataSuggestOut(
            domain_metadata=metadata,
            confidence=float(parsed.get("confidence", 0.0)),
            evidence_pages=[page.page_number for page in pages],
            rationale=str(parsed.get("rationale", "")),
            warnings=[*sampler_warnings, *list(parsed.get("warnings", []))],
        )

    def _target(self, profile: SettingsProfile) -> LlmTarget:
        if profile.vision_base_url and profile.vision_model:
            return LlmTarget(
                base_url=profile.vision_base_url,
                model=profile.vision_model,
                api_key=profile.vision_api_key,
                timeout_ms=profile.vision_timeout_ms or profile.llm_timeout_ms or 10000,
                source="vision",
            )
        if profile.llm_base_url and profile.llm_model and "vision" in (profile.llm_capabilities or []):
            return LlmTarget(
                base_url=profile.llm_base_url,
                model=profile.llm_model,
                api_key=profile.llm_api_key,
                timeout_ms=profile.llm_timeout_ms or 10000,
                source="llm",
            )
        raise ValueError("Vision model is not configured for AI metadata autosuggest.")

    def _payload(
        self,
        *,
        target: LlmTarget,
        filename: str,
        content_type: str,
        pages: list[SampledPage],
    ) -> dict[str, object]:
        content: list[dict[str, object]] = [
            {
                "type": "text",
                "text": self._prompt(filename=filename, content_type=content_type, pages=pages),
            }
        ]
        if target.source == "vision":
            for page in pages:
                if page.image_data_url:
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": page.image_data_url},
                        }
                    )
        return {
            "model": target.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "max_tokens": 900,
        }

    def _prompt(self, *, filename: str, content_type: str, pages: list[SampledPage]) -> str:
        page_text = "\n\n".join(
            f"Page {page.page_number} text excerpt:\n{page.text or '[no extracted text]'}"
            for page in pages
        )
        return f"""You classify documents for a RAG indexing system.
Be honest. Use only the sampled pages and filename as evidence. Do not guess a specific collection unless the pages show it.
Return JSON only with this shape:
{{
  "domain_metadata": {{
    "domain": "short_domain",
    "document_type": "short_type",
    "language": "unknown|english|arabic|mixed|other",
    "tags": ["short", "tags"],
    "authority": null,
    "source": null,
    "collection": null,
    "citation_style": null,
    "expected_structure": null,
    "custom_json": {{}},
    "reference_pattern": null,
    "script": null,
    "content_role": null,
    "metadata_sources": ["ai_vision"]
  }},
  "confidence": 0.0,
  "rationale": "one sentence explaining evidence",
  "warnings": []
}}

Filename: {filename}
Content type: {content_type}

{page_text}
"""

    def _message_content(self, payload: object) -> str:
        if not isinstance(payload, dict):
            raise ValueError("LLM response was not a JSON object.")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("LLM response did not include choices.")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ValueError("LLM response message content was not text.")
        return content

    def _parse_json(self, content: str) -> dict[str, object]:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
            stripped = re.sub(r"```$", "", stripped).strip()
        data = json.loads(stripped)
        if not isinstance(data, dict):
            raise ValueError("LLM metadata suggestion was not a JSON object.")
        if "domain_metadata" not in data:
            raise ValueError("LLM metadata suggestion omitted domain_metadata.")
        return data
```

- [ ] **Step 5: Run tests and leave failures for route wiring**

Run:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_domain_metadata.py -q
```

Expected: still FAIL because the API route has not been wired to the new service.

---

### Task 3: Replace Suggest Route With Multipart AI Flow

**Files:**
- Modify: `backend/src/ragstudio/api/routes/domain_profiles.py`
- Modify: `backend/src/ragstudio/services/domain_metadata_service.py`
- Modify: `backend/tests/test_domain_metadata.py`

- [ ] **Step 1: Remove rule-based suggest code from service**

In `backend/src/ragstudio/services/domain_metadata_service.py`, remove `import re` and delete the `suggest()` method. The class should keep only `list_profiles()`, `upsert_profile()`, and `_saved_profiles()`.

- [ ] **Step 2: Replace the suggest API route**

In `backend/src/ragstudio/api/routes/domain_profiles.py`, replace the current `suggest_domain_metadata` route with:

```python
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.db.models import SettingsProfile
from ragstudio.schemas.parsing import (
    DomainMetadataSuggestOut,
    DomainProfileIn,
    DomainProfileListOut,
    DomainProfileOut,
)
from ragstudio.services.domain_metadata_ai_suggester import DomainMetadataAiSuggester
from ragstudio.services.domain_metadata_service import DomainMetadataService
from ragstudio.services.page_sampler import PageSampler
```

Then define the route:

```python
@router.post("/suggest", response_model=DomainMetadataSuggestOut)
async def suggest_domain_metadata(
    request: Request,
    session: AsyncSession = Depends(get_session),
    file: UploadFile = File(...),
    profile_id: str | None = Form(default=None),
) -> DomainMetadataSuggestOut:
    del profile_id
    settings_profile = await session.get(SettingsProfile, "default")
    if settings_profile is None:
        raise HTTPException(
            status_code=409,
            detail="Default settings profile is required for AI metadata autosuggest.",
        )

    data = await file.read()
    sampler = PageSampler()
    pages = sampler.sample(
        data,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
    )
    if not pages:
        raise HTTPException(
            status_code=422,
            detail="Could not sample pages from this file for AI metadata autosuggest.",
        )
    try:
        return await DomainMetadataAiSuggester().suggest(
            settings_profile=settings_profile,
            filename=file.filename or "upload",
            content_type=file.content_type or "application/octet-stream",
            pages=pages,
            sampler_warnings=sampler.warnings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
```

- [ ] **Step 3: Run backend domain metadata tests**

Run:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_domain_metadata.py backend/tests/test_page_sampler.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit backend AI autosuggest**

Commit:

```bash
git add backend/src/ragstudio/api/routes/domain_profiles.py backend/src/ragstudio/services/domain_metadata_service.py backend/src/ragstudio/services/domain_metadata_ai_suggester.py backend/tests/test_domain_metadata.py
git commit -m "feat: replace metadata autosuggest with AI vision"
```

---

### Task 4: Update Frontend Autosuggest to Send the Selected File

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`
- Modify: `frontend/src/features/documents/documents-page.tsx`
- Modify: `frontend/src/features/chunks/chunk-inspector.tsx`
- Modify: `frontend/tests/domain-metadata-panel.test.tsx`
- Modify: `frontend/tests/documents-page.test.tsx`

- [ ] **Step 1: Update API client**

Replace `suggestDomainMetadata` in `frontend/src/api/client.ts` with:

```ts
  suggestDomainMetadata: (payload: {
    file: File;
    profile_id?: string | null;
  }) => {
    const formData = new FormData();
    formData.set("file", payload.file);
    if (payload.profile_id) {
      formData.set("profile_id", payload.profile_id);
    }
    return request<{
      domain_metadata: DomainMetadata;
      confidence: number;
      evidence_pages: number[];
      rationale: string;
      warnings: string[];
    }>("/api/domain-profiles/suggest", {
      method: "POST",
      body: formData,
    });
  },
```

- [ ] **Step 2: Update DomainMetadataPanel types and suggest call**

In `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`, change `suggestContext` to:

```ts
  suggestContext?: {
    filename: string;
    content_type: string;
    file?: File;
  };
```

Add state near `autosuggestChanges`:

```ts
  const [autosuggestEvidence, setAutosuggestEvidence] = useState<{
    confidence: number;
    evidencePages: number[];
    rationale: string;
    warnings: string[];
  } | null>(null);
```

Replace the start of `suggest()` with:

```ts
    if (!suggestContext?.file) {
      return;
    }
```

Replace the API call body with:

```ts
      const response = await apiClient.suggestDomainMetadata({
        file: suggestContext.file,
        profile_id: selectedProfileId || null,
      });
```

After `setAutosuggestChanges(...)`, add:

```ts
      setAutosuggestEvidence({
        confidence: response.confidence,
        evidencePages: response.evidence_pages,
        rationale: response.rationale,
        warnings: response.warnings,
      });
```

When the user edits any field and clears all changes, also clear evidence:

```ts
  useEffect(() => {
    if (autosuggestChanges.length === 0) {
      setAutosuggestEvidence(null);
    }
  }, [autosuggestChanges.length]);
```

- [ ] **Step 3: Show evidence under the existing diff panel**

Inside the existing `autosuggestChanges.length > 0` panel, after the change list, render:

```tsx
            {autosuggestEvidence ? (
              <div className="mt-2 rounded border border-[#cfe3ea] bg-white/70 p-2 text-xs text-[#3a4a53]">
                <p>
                  Confidence {Math.round(autosuggestEvidence.confidence * 100)}%
                  {autosuggestEvidence.evidencePages.length > 0
                    ? ` from pages ${autosuggestEvidence.evidencePages.join(", ")}`
                    : ""}
                </p>
                {autosuggestEvidence.rationale ? <p>{autosuggestEvidence.rationale}</p> : null}
                {autosuggestEvidence.warnings.map((warning) => (
                  <p key={warning}>{warning}</p>
                ))}
              </div>
            ) : null}
```

- [ ] **Step 4: Pass file from DocumentsPage**

In `frontend/src/features/documents/documents-page.tsx`, update `suggestContext`:

```tsx
              suggestContext={
                file
                  ? {
                      filename: file.name,
                      content_type: file.type || "application/octet-stream",
                      file,
                    }
                  : undefined
              }
```

- [ ] **Step 5: Disable autosuggest outside upload form**

In `frontend/src/features/chunks/chunk-inspector.tsx`, remove the `suggestContext={...}` prop from `DomainMetadataPanel`. The Chunks page can still edit metadata manually, but AI autosuggest is upload-file based.

- [ ] **Step 6: Update frontend tests**

In `frontend/tests/domain-metadata-panel.test.tsx`, update autosuggest expectations from:

```ts
    expect(mocks.suggestDomainMetadata).toHaveBeenCalledWith({
      filename: "policy.pdf",
      content_type: "application/pdf",
      profile_id: null,
      sample_text: "",
    });
```

to:

```ts
    const file = new File(["pdf"], "policy.pdf", { type: "application/pdf" });
    expect(mocks.suggestDomainMetadata).toHaveBeenCalledWith({
      file,
      profile_id: null,
    });
```

For mocked responses, include:

```ts
      confidence: 0.91,
      evidence_pages: [1, 2, 10, 20],
      rationale: "The sampled pages show policy headings.",
      warnings: [],
```

Add an assertion in the review test:

```ts
    expect(screen.getByText("Confidence 91% from pages 1, 2, 10, 20")).toBeVisible();
    expect(screen.getByText("The sampled pages show policy headings.")).toBeVisible();
```

- [ ] **Step 7: Run frontend tests and commit**

Run:

```bash
docker compose run --rm frontend npm test -- --run frontend/tests/domain-metadata-panel.test.tsx frontend/tests/documents-page.test.tsx
```

Expected: PASS.

Commit:

```bash
git add frontend/src/api/client.ts frontend/src/features/domain-metadata/domain-metadata-panel.tsx frontend/src/features/documents/documents-page.tsx frontend/src/features/chunks/chunk-inspector.tsx frontend/tests/domain-metadata-panel.test.tsx frontend/tests/documents-page.test.tsx
git commit -m "feat: send upload file to AI metadata autosuggest"
```

---

### Task 5: Add Documentation and End-to-End Verification

**Files:**
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Document AI autosuggest**

In `docs/user-guide.md`, under the MinerU parser/domain metadata section, add:

```markdown
Auto-suggest uses the configured vision model before upload indexing starts. Ragstudio samples up to four representative pages from the selected file, asks the model for strict domain metadata JSON, validates the response, and shows changed fields before applying them. Filename-only heuristics are not used for autosuggest.
```

- [ ] **Step 2: Run backend verification**

Run:

```bash
docker compose run --rm -v "$PWD/backend/src:/app/backend/src" -v "$PWD/backend/tests:/app/backend/tests:ro" backend python -m pytest backend/tests/test_domain_metadata.py backend/tests/test_page_sampler.py backend/tests/test_documents.py backend/tests/test_chunks.py -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend verification**

Run:

```bash
docker compose run --rm frontend npm test -- --run frontend/tests/domain-metadata-panel.test.tsx frontend/tests/documents-page.test.tsx frontend/tests/chunk-inspector.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Run build**

Run:

```bash
docker compose run --rm frontend npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit docs**

Commit:

```bash
git add docs/user-guide.md
git commit -m "docs: explain AI metadata autosuggest"
```

---

## Self-Review

- Spec coverage: The plan covers vision-first autosuggest, 3-4 sampled pages, pre-MinerU flow, removal of rule-based heuristics, strict metadata validation, review diff preservation, and evidence display.
- Placeholder scan: No placeholder tasks remain; every code-changing task includes exact file paths, snippets, commands, and expected results.
- Type consistency: Backend response fields are `domain_metadata`, `confidence`, `evidence_pages`, `rationale`, and `warnings`; frontend maps them to `domain_metadata`, `confidence`, `evidence_pages`, `rationale`, and `warnings` from the API client and camel-cases only local state.
