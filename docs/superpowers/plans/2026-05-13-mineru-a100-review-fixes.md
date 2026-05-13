# MinerU A100 Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three review findings from the MinerU A100 optimization feature: missing capacity visibility for legacy sidecars, duplicate Settings health output, and silent domain metadata overrides of Settings parser values.

**Architecture:** Settings/provider sync provide the default MinerU parse options. Upload and reindex requests may carry explicit per-document MinerU overrides that are visible before submission; those overrides are the only way document metadata can change operational parser knobs. Treat sidecar health capacity as reported evidence only: when the sidecar does not report backend/device/concurrency, the Settings test must show an explicit warning instead of pretending capacity is confirmed.

**Tech Stack:** FastAPI, Pydantic v2, httpx, SQLAlchemy, pytest, React, TypeScript, TanStack Query, Vitest.

---

## File Structure

- `backend/src/ragstudio/schemas/settings.py`: add a typed MinerU optimization health payload so callers can distinguish requested settings, sidecar-reported capacity, and warning state.
- `backend/src/ragstudio/api/routes/settings.py`: build the MinerU health detail from requested Settings values plus sidecar-reported values; warn when capacity fields are absent.
- `backend/src/ragstudio/services/mineru_client.py`: keep sidecar health parsing focused on reported sidecar fields.
- `backend/src/ragstudio/schemas/parsing.py`: add typed per-document MinerU parse override fields on `IndexDocumentIn`.
- `backend/src/ragstudio/api/routes/documents.py`: parse `mineru_parse_options` from multipart uploads and validate it for reindex requests.
- `backend/src/ragstudio/services/document_parser_service.py`: resolve parse options from Settings defaults plus explicit `IndexDocumentIn.mineru_parse_options`; stop applying `domain_metadata.custom_json.mineru_parse_options` silently.
- `frontend/src/api/client.ts`: include per-document MinerU overrides in multipart uploads and reindex JSON.
- `frontend/src/api/generated.ts`: mirror the new per-document `MinerUParseOptionsIn` and `IndexDocumentIn.mineru_parse_options` shape.
- `frontend/src/features/documents/documents-page.tsx`: surface per-document MinerU override controls in the upload/reindex control area.
- `frontend/src/features/documents/mineru-parse-options-panel.tsx`: create a focused control panel for document-level parser overrides.
- `backend/tests/test_settings.py`: cover legacy sidecar health, reported capacity health, and the non-duplicated backend detail.
- `backend/tests/test_document_parser_service.py`: prove explicit per-document overrides apply and hidden metadata overrides do not.
- `backend/tests/test_documents_api.py` or existing document route tests: prove multipart uploads accept `mineru_parse_options`.
- `frontend/src/api/generated.ts`: mirror the typed MinerU optimization health payload.
- `frontend/src/features/settings/settings-page.tsx`: stop appending structured optimization details to an already formatted backend detail.
- `frontend/tests/settings-page.test.tsx`: assert the MinerU health message appears once and legacy-capacity warnings render.
- `frontend/tests/documents-page.test.tsx`: assert per-document overrides are visible before upload and are included in upload/reindex requests.
- `docs/user-guide.md` and `docs/workflows.md`: document Settings defaults, explicit document-level overrides, and non-hidden domain metadata behavior.

## Contract Decisions

1. Settings/provider sync provide defaults for actual parse request options:

```text
mineru_backend
mineru_device
mineru_lang
mineru_formula
mineru_table
mineru_source
mineru_max_concurrent_files
parser
parse_method
```

2. Explicit per-document upload/reindex overrides can replace those defaults for a single indexing job. Hidden `domain_metadata.custom_json.mineru_parse_options` must not change parser behavior unless the user has surfaced and accepted those values through the document override controls.

3. Sidecar health capacity is evidence from `/health`, not a guarantee inferred by Ragstudio. If `/health` only returns:

```json
{"ready": true, "hpcMineru": {"enabled": true, "mode": "coordinator"}}
```

the Settings test should still pass connection, but show a warning that capacity is not reported by the sidecar.

4. The frontend displays the backend `detail` sentence as-is. It does not append `backend=...` or `device=...` a second time.

---

### Task 1: Make MinerU Health Capacity Explicit For Legacy Sidecars

**Files:**
- Modify: `backend/src/ragstudio/schemas/settings.py`
- Modify: `backend/src/ragstudio/api/routes/settings.py`
- Test: `backend/tests/test_settings.py`

- [ ] **Step 1: Add failing tests for legacy and capacity-reporting sidecars**

Append this test near the existing MinerU connection tests in `backend/tests/test_settings.py`:

```python
@pytest.mark.asyncio
async def test_mineru_connection_test_warns_when_sidecar_capacity_is_missing(
    client,
    monkeypatch,
):
    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def health(self):
            return MinerUSidecarHealth(
                ready=True,
                detail="RAG-Anything sidecar ready.",
                version="hybrid",
                hpc_enabled=True,
                hpc_mode="coordinator",
                raw={"hpcMineru": {"enabled": True, "mode": "coordinator"}},
            )

    monkeypatch.setattr("ragstudio.api.routes.settings.MinerUClient", FakeClient)
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "postgres_pgvector_neo4j",
        "mineru_enabled": True,
        "mineru_base_url": "http://127.0.0.1:8765",
        "mineru_backend": "pipeline",
        "mineru_device": "cuda:0",
        "mineru_formula": True,
        "mineru_table": True,
        "mineru_max_concurrent_files": 2,
    }

    response = await client.post("/api/settings/default/test-mineru", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["optimization"]["requested"]["backend"] == "pipeline"
    assert body["optimization"]["requested"]["device"] == "cuda:0"
    assert body["optimization"]["requested"]["max_concurrent_files"] == 2
    assert body["optimization"]["reported"] == {}
    assert body["optimization"]["capacity_reported"] is False
    assert "capacity not reported by sidecar" in body["detail"]
    assert "requested backend=pipeline" in body["detail"]
```

Update the existing `test_mineru_connection_test_reports_hpc_mode` assertions so they expect the nested shape:

```python
    assert body["optimization"] == {
        "requested": {
            "backend": "pipeline",
            "device": "cuda:0",
            "formula": True,
            "table": True,
            "max_concurrent_files": 1,
        },
        "reported": {
            "backend": "pipeline",
            "device": "cuda:0",
            "max_concurrent_files": 2,
        },
        "capacity_reported": True,
        "warning": None,
    }
```

- [ ] **Step 2: Run the backend MinerU settings tests and verify they fail**

Run:

```bash
./.venv/bin/pytest backend/tests/test_settings.py::test_mineru_connection_test_warns_when_sidecar_capacity_is_missing backend/tests/test_settings.py::test_mineru_connection_test_reports_hpc_mode -q
```

Expected: fail because `optimization` is currently flat and legacy sidecar health returns no warning.

- [ ] **Step 3: Add typed optimization response schemas**

In `backend/src/ragstudio/schemas/settings.py`, add this class above `MinerUConnectionTestOut`:

```python
class MinerUOptimizationOut(StudioModel):
    requested: dict[str, object] = Field(default_factory=dict)
    reported: dict[str, object] = Field(default_factory=dict)
    capacity_reported: bool = False
    warning: str | None = None
```

Then change `MinerUConnectionTestOut.optimization`:

```python
class MinerUConnectionTestOut(StudioModel):
    ok: bool
    base_url: str
    latency_ms: int
    detail: str
    optimization: MinerUOptimizationOut = Field(default_factory=MinerUOptimizationOut)
```

- [ ] **Step 4: Build requested/reported optimization details in the settings route**

In `backend/src/ragstudio/api/routes/settings.py`, replace `_mineru_optimization_detail()` with these helpers:

```python
def _mineru_requested_optimization(payload: SettingsProfileIn) -> dict[str, object]:
    requested: dict[str, object] = {
        "backend": payload.mineru_backend,
        "device": payload.mineru_device,
        "formula": payload.mineru_formula,
        "table": payload.mineru_table,
        "max_concurrent_files": payload.mineru_max_concurrent_files,
    }
    if payload.mineru_lang:
        requested["lang"] = payload.mineru_lang
    if payload.mineru_source:
        requested["source"] = payload.mineru_source
    return requested


def _mineru_optimization_detail(
    *,
    reported: dict[str, object],
    requested: dict[str, object],
) -> tuple[str, str | None]:
    if reported:
        parts: list[str] = []
        if reported.get("backend"):
            parts.append(f"reported backend={reported['backend']}")
        if reported.get("device"):
            parts.append(f"reported device={reported['device']}")
        if reported.get("max_concurrent_files"):
            parts.append(f"reported maxConcurrentFiles={reported['max_concurrent_files']}")
        return "; ".join(parts), None

    warning = (
        "capacity not reported by sidecar; requested "
        f"backend={requested['backend']}; "
        f"device={requested['device']}; "
        f"maxConcurrentFiles={requested['max_concurrent_files']}"
    )
    return warning, warning
```

In `test_mineru_settings()`, replace the existing optimization block with:

```python
        requested = _mineru_requested_optimization(payload)
        reported = health.optimization
        optimization_detail, warning = _mineru_optimization_detail(
            reported=reported,
            requested=requested,
        )
        detail_suffix = f"{mode_detail}; {optimization_detail}"
        return MinerUConnectionTestOut(
            ok=True,
            base_url=base_url,
            latency_ms=latency_ms,
            detail=f"{health.detail or 'MinerU health check succeeded.'} ({detail_suffix}).",
            optimization={
                "requested": requested,
                "reported": reported,
                "capacity_reported": bool(reported),
                "warning": warning,
            },
        )
```

- [ ] **Step 5: Run the focused tests**

Run:

```bash
./.venv/bin/pytest backend/tests/test_settings.py::test_mineru_connection_test_warns_when_sidecar_capacity_is_missing backend/tests/test_settings.py::test_mineru_connection_test_reports_hpc_mode -q
```

Expected: both tests pass.

---

### Task 2: Remove Duplicate Frontend MinerU Optimization Output

**Files:**
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/features/settings/settings-page.tsx`
- Test: `frontend/tests/settings-page.test.tsx`

- [ ] **Step 1: Update frontend API types**

In `frontend/src/api/generated.ts`, add this interface above `MinerUConnectionTestOut`:

```ts
export interface MinerUOptimizationOut {
  requested: Record<string, unknown>;
  reported: Record<string, unknown>;
  capacity_reported: boolean;
  warning: string | null;
}
```

Then change the MinerU connection type:

```ts
export interface MinerUConnectionTestOut {
  ok: boolean;
  base_url: string;
  latency_ms: number;
  detail: string;
  optimization: MinerUOptimizationOut;
}
```

- [ ] **Step 2: Write a failing duplicate-output regression test**

In `frontend/tests/settings-page.test.tsx`, update the mocked `testMinerUSettings` response to the nested shape:

```ts
vi.mocked(apiClient.testMinerUSettings).mockResolvedValue({
  ok: true,
  base_url: "http://127.0.0.1:8765",
  latency_ms: 12,
  detail:
    "RAG-Anything sidecar ready (HPC coordinator mode; reported backend=pipeline; reported device=cuda:0; reported maxConcurrentFiles=2).",
  optimization: {
    requested: {
      backend: "pipeline",
      device: "cuda:0",
      formula: true,
      table: true,
      max_concurrent_files: 1,
    },
    reported: {
      backend: "pipeline",
      device: "cuda:0",
      max_concurrent_files: 2,
    },
    capacity_reported: true,
    warning: null,
  },
});
```

Replace `it("shows MinerU sidecar optimization details after test", ...)` with:

```ts
it("shows MinerU sidecar optimization details once after test", async () => {
  renderSettings();

  await screen.findByDisplayValue("gpt-4.1");
  fireEvent.click(screen.getByRole("button", { name: /Test MinerU/i }));

  const status = await screen.findByText(/reported backend=pipeline/);
  expect(status).toBeVisible();
  const text = status.textContent ?? "";
  expect(text.match(/reported backend=pipeline/g)).toHaveLength(1);
  expect(text.match(/reported device=cuda:0/g)).toHaveLength(1);
  expect(text.match(/reported maxConcurrentFiles=2/g)).toHaveLength(1);
});
```

Add this legacy-capacity warning test:

```ts
it("shows when MinerU sidecar capacity is not reported", async () => {
  vi.mocked(apiClient.testMinerUSettings).mockResolvedValueOnce({
    ok: true,
    base_url: "http://127.0.0.1:8765",
    latency_ms: 12,
    detail:
      "RAG-Anything sidecar ready (HPC coordinator mode; capacity not reported by sidecar; requested backend=pipeline; device=cuda:0; maxConcurrentFiles=2).",
    optimization: {
      requested: {
        backend: "pipeline",
        device: "cuda:0",
        formula: true,
        table: true,
        max_concurrent_files: 2,
      },
      reported: {},
      capacity_reported: false,
      warning:
        "capacity not reported by sidecar; requested backend=pipeline; device=cuda:0; maxConcurrentFiles=2",
    },
  });
  renderSettings();

  await screen.findByDisplayValue("gpt-4.1");
  fireEvent.click(screen.getByRole("button", { name: /Test MinerU/i }));

  expect(await screen.findByText(/capacity not reported by sidecar/)).toBeVisible();
});
```

- [ ] **Step 3: Remove frontend-side optimization string concatenation**

In `frontend/src/features/settings/settings-page.tsx`, delete this block:

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
```

Then simplify `mineruTestMessage`:

```ts
const mineruTestMessage = testMinerU.error
  ? testMinerU.error.message
  : testMinerU.data
    ? `${testMinerU.data.ok ? "Connected" : "Failed"}: ${testMinerU.data.detail}`
    : "";
```

- [ ] **Step 4: Run the frontend settings tests**

Run:

```bash
cd frontend
npm test -- tests/settings-page.test.tsx
```

Expected: all settings-page tests pass and the optimization strings appear once.

---

### Task 3: Add Visible Per-Document MinerU Overrides Before Upload/Reindex

**Files:**
- Modify: `backend/src/ragstudio/schemas/parsing.py`
- Modify: `backend/src/ragstudio/api/routes/documents.py`
- Modify: `backend/src/ragstudio/services/document_parser_service.py`
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/features/documents/mineru-parse-options-panel.tsx`
- Modify: `frontend/src/features/documents/documents-page.tsx`
- Test: `backend/tests/test_document_parser_service.py`
- Test: `backend/tests/test_documents_api.py` if present, otherwise the existing document route test module
- Test: `frontend/tests/documents-page.test.tsx`

- [ ] **Step 1: Add the backend schema for explicit per-document overrides**

In `backend/src/ragstudio/schemas/parsing.py`, add this class above `IndexDocumentIn`:

```python
class MinerUParseOptionsIn(StudioModel):
    parser: str | None = None
    parse_method: str | None = None
    backend: str | None = None
    device: str | None = None
    lang: str | None = None
    formula: bool | None = None
    table: bool | None = None
    source: str | None = None
    max_concurrent_files: int | None = Field(default=None, ge=1, le=8)
```

Then update `IndexDocumentIn`:

```python
class IndexDocumentIn(StudioModel):
    parser_mode: ParserMode = DEFAULT_PARSER_MODE
    domain_metadata: DomainMetadata = Field(default_factory=DomainMetadata)
    mineru_parse_options: MinerUParseOptionsIn | None = None
```

- [ ] **Step 2: Add failing parser resolution tests**

In `backend/tests/test_document_parser_service.py`, replace `test_mineru_parse_options_use_ai_metadata_overrides` with:

```python
def test_mineru_parse_options_apply_explicit_document_overrides(tmp_path):
    settings = SettingsProfile(
        id="default",
        provider="openai-compatible",
        llm_model="gpt-4o",
        embedding_model="fallback",
        storage_backend="postgres_pgvector_neo4j",
        runtime_mode="runtime",
        mineru_enabled=True,
        mineru_base_url="http://10.10.9.19:8765",
        parser="mineru",
        parse_method="auto",
        mineru_backend="pipeline",
        mineru_device="cuda:1",
        mineru_lang="en",
        mineru_formula=True,
        mineru_table=True,
        mineru_source="huggingface",
        mineru_max_concurrent_files=2,
    )
    options = IndexDocumentIn(
        domain_metadata=DomainMetadata(domain="quran_tafseer"),
        mineru_parse_options={
            "parse_method": "ocr",
            "lang": "arabic",
            "formula": False,
            "table": False,
            "device": "cuda:0",
            "max_concurrent_files": 1,
        },
    )

    parse_options = DocumentParserService(EventSession(), tmp_path)._mineru_parse_options(
        settings,
        options,
    )

    assert parse_options.to_metadata() == {
        "parser": "mineru",
        "parseMethod": "ocr",
        "parserKwargs": {
            "backend": "pipeline",
            "device": "cuda:0",
            "formula": False,
            "table": False,
            "lang": "arabic",
            "source": "huggingface",
        },
        "maxConcurrentFiles": 1,
    }
```

Add this second test to prove hidden metadata is ignored unless surfaced as an explicit override:

```python
def test_mineru_parse_options_ignore_hidden_domain_metadata_overrides(tmp_path):
    settings = SettingsProfile(
        id="default",
        provider="openai-compatible",
        llm_model="gpt-4o",
        embedding_model="fallback",
        storage_backend="postgres_pgvector_neo4j",
        runtime_mode="runtime",
        mineru_enabled=True,
        mineru_base_url="http://10.10.9.19:8765",
        parser="mineru",
        parse_method="auto",
        mineru_backend="pipeline",
        mineru_device="cuda:1",
        mineru_lang="en",
        mineru_formula=True,
        mineru_table=True,
        mineru_source="huggingface",
        mineru_max_concurrent_files=2,
    )
    options = IndexDocumentIn(
        domain_metadata=DomainMetadata(
            domain="quran_tafseer",
            custom_json={
                "mineru_parse_options": {
                    "parse_method": "ocr",
                    "lang": "arabic",
                    "formula": False,
                    "table": False,
                    "device": "cuda:0",
                    "max_concurrent_files": 1,
                },
            },
        ),
    )

    parse_options = DocumentParserService(EventSession(), tmp_path)._mineru_parse_options(
        settings,
        options,
    )

    assert parse_options.to_metadata() == {
        "parser": "mineru",
        "parseMethod": "auto",
        "parserKwargs": {
            "backend": "pipeline",
            "device": "cuda:1",
            "formula": True,
            "table": True,
            "lang": "en",
            "source": "huggingface",
        },
        "maxConcurrentFiles": 2,
    }
```

- [ ] **Step 3: Run the focused parser service tests and verify they fail**

Run:

```bash
./.venv/bin/pytest backend/tests/test_document_parser_service.py::test_mineru_parse_options_apply_explicit_document_overrides backend/tests/test_document_parser_service.py::test_mineru_parse_options_ignore_hidden_domain_metadata_overrides -q
```

Expected: fail because `IndexDocumentIn` does not have `mineru_parse_options` yet and the parser service currently reads hidden domain metadata.

- [ ] **Step 4: Resolve parse options from Settings plus explicit document overrides**

In `backend/src/ragstudio/services/document_parser_service.py`, remove this import:

```python
from dataclasses import replace
```

Change the parse call to pass the full `IndexDocumentIn`:

```python
parse_options=self._mineru_parse_options(settings, options),
```

Replace `_mineru_parse_options()` with:

```python
def _mineru_parse_options(
    self,
    settings: SettingsProfile,
    options: IndexDocumentIn | None = None,
) -> MinerUParseOptions:
    mineru_formula = getattr(settings, "mineru_formula", None)
    mineru_table = getattr(settings, "mineru_table", None)
    resolved = MinerUParseOptions(
        parser=getattr(settings, "parser", None) or "mineru",
        parse_method=getattr(settings, "parse_method", None) or "auto",
        backend=getattr(settings, "mineru_backend", None) or "pipeline",
        device=getattr(settings, "mineru_device", None) or "cuda:0",
        lang=getattr(settings, "mineru_lang", None),
        formula=True if mineru_formula is None else bool(mineru_formula),
        table=True if mineru_table is None else bool(mineru_table),
        source=getattr(settings, "mineru_source", None),
        max_concurrent_files=getattr(settings, "mineru_max_concurrent_files", None) or 1,
    )
    if options is None or options.mineru_parse_options is None:
        return resolved

    overrides = options.mineru_parse_options.model_dump(exclude_none=True)
    if "parse_method" in overrides:
        overrides["parse_method"] = str(overrides["parse_method"]).strip() or resolved.parse_method
    for key in ("parser", "backend", "device", "lang", "source"):
        if key in overrides:
            value = str(overrides[key]).strip()
            if value:
                overrides[key] = value
            else:
                overrides.pop(key)
    return replace(resolved, **overrides)
```

Delete these hidden domain metadata methods from the same file:

```python
def _mineru_parse_overrides(...)
def _metadata_inferred_mineru_overrides(...)
def _metadata_prefers_arabic_ocr(...)
def _metadata_mentions_tables(...)
def _metadata_tokens(...)
```

- [ ] **Step 5: Accept per-document overrides in upload requests**

In `backend/src/ragstudio/api/routes/documents.py`, add a multipart form field:

```python
mineru_parse_options: str | None = Form(default=None),
```

Update the upload option parsing condition:

```python
options = (
    _parse_index_options(parser_mode, domain_metadata, mineru_parse_options)
    if parser_mode is not None
    or domain_metadata is not None
    or mineru_parse_options is not None
    else None
)
```

Update `_parse_index_options()`:

```python
def _parse_index_options(
    parser_mode: str | None,
    domain_metadata: str | None,
    mineru_parse_options: str | None,
) -> IndexDocumentIn:
    try:
        metadata_payload = json.loads(domain_metadata or "{}")
        mineru_payload = json.loads(mineru_parse_options or "null")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"index options must be valid JSON: {exc.msg}",
        ) from exc
    try:
        return IndexDocumentIn.model_validate(
            {
                "parser_mode": parser_mode or DEFAULT_PARSER_MODE,
                "domain_metadata": metadata_payload,
                "mineru_parse_options": mineru_payload,
            }
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
```

- [ ] **Step 6: Add an upload route regression test**

In the existing document API route test module, add a unit-level test for `_parse_index_options()`:

```python
def test_parse_index_options_accepts_mineru_parse_options_form_json():
    options = _parse_index_options(
        "mineru_strict",
        '{"domain":"quran_tafseer"}',
        '{"device":"cuda:0","max_concurrent_files":2,"formula":false}',
    )

    assert options.mineru_parse_options is not None
    assert options.mineru_parse_options.device == "cuda:0"
    assert options.mineru_parse_options.max_concurrent_files == 2
    assert options.mineru_parse_options.formula is False
```

If importing the private helper does not match the local test style, cover the same behavior through `POST /api/documents` with mocked runtime readiness and `ChunkService.validate_strict_mineru_sidecar`.

- [ ] **Step 7: Update frontend API types and upload client**

In `frontend/src/api/generated.ts`, add:

```ts
export interface MinerUParseOptionsIn {
  parser?: string | null;
  parse_method?: string | null;
  backend?: string | null;
  device?: string | null;
  lang?: string | null;
  formula?: boolean | null;
  table?: boolean | null;
  source?: string | null;
  max_concurrent_files?: number | null;
}
```

Update `IndexDocumentIn`:

```ts
export interface IndexDocumentIn {
  parser_mode?: ParserMode;
  domain_metadata?: DomainMetadata;
  mineru_parse_options?: MinerUParseOptionsIn | null;
}
```

In `frontend/src/api/client.ts`, update `uploadDocument`:

```ts
if (options.mineru_parse_options) {
  formData.set("mineru_parse_options", JSON.stringify(options.mineru_parse_options));
}
```

- [ ] **Step 8: Create the per-document MinerU override panel**

Create `frontend/src/features/documents/mineru-parse-options-panel.tsx`. The override panel must be opt-in: when disabled, `value.mineru_parse_options` stays `null` or `undefined` and Settings defaults are used.

```tsx
import type { IndexDocumentIn, MinerUParseOptionsIn } from "../../api/generated";

interface MinerUParseOptionsPanelProps {
  value: IndexDocumentIn;
  onChange: (value: IndexDocumentIn) => void;
  disabled?: boolean;
}

const DEFAULT_OPTIONS: MinerUParseOptionsIn = {
  parser: "mineru",
  parse_method: "auto",
  backend: "pipeline",
  device: "cuda:0",
  lang: "",
  formula: true,
  table: true,
  source: "",
  max_concurrent_files: 1,
};

export function MinerUParseOptionsPanel({
  value,
  onChange,
  disabled = false,
}: MinerUParseOptionsPanelProps) {
  const enabled = value.mineru_parse_options != null;
  const options = { ...DEFAULT_OPTIONS, ...(value.mineru_parse_options ?? {}) };
  const setEnabled = (nextEnabled: boolean) => {
    onChange({
      ...value,
      mineru_parse_options: nextEnabled ? options : null,
    });
  };
  const update = <K extends keyof MinerUParseOptionsIn>(
    key: K,
    nextValue: MinerUParseOptionsIn[K],
  ) => {
    onChange({
      ...value,
      mineru_parse_options: {
        ...options,
        [key]: nextValue,
      },
    });
  };

  return (
    <section className="rounded-md border border-[#d6dde1] bg-white p-4">
      <label className="mb-3 flex h-10 items-center gap-2 text-sm font-medium text-[#3a4a53]">
        <input
          type="checkbox"
          checked={enabled}
          disabled={disabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        Use document-specific MinerU options
      </label>
      <div className="grid gap-3 sm:grid-cols-2" aria-disabled={!enabled}>
        <label className="grid gap-1 text-sm font-medium text-[#3a4a53]">
          MinerU backend
          <input
            className="h-10 rounded-md border border-[#cfd8dd] px-3"
            value={options.backend ?? ""}
            disabled={disabled || !enabled}
            onChange={(event) => update("backend", event.target.value)}
          />
        </label>
        <label className="grid gap-1 text-sm font-medium text-[#3a4a53]">
          MinerU device
          <input
            className="h-10 rounded-md border border-[#cfd8dd] px-3"
            value={options.device ?? ""}
            disabled={disabled || !enabled}
            onChange={(event) => update("device", event.target.value)}
          />
        </label>
        <label className="grid gap-1 text-sm font-medium text-[#3a4a53]">
          Parse method
          <input
            className="h-10 rounded-md border border-[#cfd8dd] px-3"
            value={options.parse_method ?? ""}
            disabled={disabled || !enabled}
            onChange={(event) => update("parse_method", event.target.value)}
          />
        </label>
        <label className="grid gap-1 text-sm font-medium text-[#3a4a53]">
          Language
          <input
            className="h-10 rounded-md border border-[#cfd8dd] px-3"
            value={options.lang ?? ""}
            disabled={disabled || !enabled}
            onChange={(event) => update("lang", event.target.value || null)}
          />
        </label>
        <label className="grid gap-1 text-sm font-medium text-[#3a4a53]">
          Max concurrent files
          <input
            className="h-10 rounded-md border border-[#cfd8dd] px-3"
            type="number"
            min={1}
            max={8}
            value={options.max_concurrent_files ?? 1}
            disabled={disabled || !enabled}
            onChange={(event) => {
              const value = Number.parseInt(event.target.value, 10);
              update("max_concurrent_files", Number.isFinite(value) ? value : 1);
            }}
          />
        </label>
        <label className="flex h-10 items-center gap-2 self-end text-sm font-medium text-[#3a4a53]">
          <input
            type="checkbox"
            checked={options.formula ?? true}
            disabled={disabled || !enabled}
            onChange={(event) => update("formula", event.target.checked)}
          />
          Parse formulas
        </label>
        <label className="flex h-10 items-center gap-2 self-end text-sm font-medium text-[#3a4a53]">
          <input
            type="checkbox"
            checked={options.table ?? true}
            disabled={disabled || !enabled}
            onChange={(event) => update("table", event.target.checked)}
          />
          Parse tables
        </label>
      </div>
    </section>
  );
}
```

- [ ] **Step 9: Render the override panel before upload and reuse values for reindex**

In `frontend/src/features/documents/documents-page.tsx`, import the new panel:

```ts
import { MinerUParseOptionsPanel } from "./mineru-parse-options-panel";
```

Render it next to the existing domain metadata controls before the submit button:

```tsx
<MinerUParseOptionsPanel
  value={indexOptions}
  onChange={setIndexOptions}
  disabled={uploadDocument.isPending || reindexDocument.isPending}
/>
```

The existing `reindexExistingDocument(document)` call already sends `indexOptions`, so the same visible overrides apply to reindex.

- [ ] **Step 10: Add frontend upload and reindex tests**

In `frontend/tests/documents-page.test.tsx`, add an upload test:

```ts
it("uploads with visible per-document MinerU overrides", async () => {
  renderDocumentsPage();

  const file = new File(["pdf"], "sample.pdf", { type: "application/pdf" });
  await userEvent.upload(await screen.findByLabelText(/Upload file/i), file);
  fireEvent.click(screen.getByLabelText("Use document-specific MinerU options"));
  fireEvent.change(screen.getByLabelText("MinerU device"), { target: { value: "cuda:0" } });
  fireEvent.change(screen.getByLabelText("Max concurrent files"), { target: { value: "2" } });
  fireEvent.click(screen.getByLabelText("Parse formulas"));
  fireEvent.click(screen.getByRole("button", { name: /Upload/i }));

  await waitFor(() => expect(apiClient.uploadDocument).toHaveBeenCalled());
  expect(vi.mocked(apiClient.uploadDocument).mock.calls[0][0].options.mineru_parse_options).toEqual(
    expect.objectContaining({
      device: "cuda:0",
      max_concurrent_files: 2,
      formula: false,
    }),
  );
});
```

Add a reindex test:

```ts
it("reindexes with visible per-document MinerU overrides", async () => {
  renderDocumentsPage();

  fireEvent.click(await screen.findByLabelText("Use document-specific MinerU options"));
  fireEvent.change(screen.getByLabelText("MinerU device"), {
    target: { value: "cuda:1" },
  });
  fireEvent.change(screen.getByLabelText("Max concurrent files"), {
    target: { value: "3" },
  });
  fireEvent.click(await screen.findByRole("button", { name: /Reindex/i }));

  await waitFor(() => expect(apiClient.createDocumentReindexJob).toHaveBeenCalled());
  expect(vi.mocked(apiClient.createDocumentReindexJob).mock.calls[0][1]).toEqual(
    expect.objectContaining({
      mineru_parse_options: expect.objectContaining({
        device: "cuda:1",
        max_concurrent_files: 3,
      }),
    }),
  );
});
```

- [ ] **Step 11: Run focused backend and frontend tests**

Run:

```bash
./.venv/bin/pytest backend/tests/test_document_parser_service.py -q
cd frontend
npm test -- tests/documents-page.test.tsx
```

Expected: all focused tests pass.

- [ ] **Step 12: Keep domain metadata suggestions visible but non-authoritative**

Do not remove `custom_json.mineru_parse_options` validation in this plan. It can remain as an advisory/suggestion payload for future UI hydration, but `DocumentParserService` must not read it directly. The implementation boundary is: only `IndexDocumentIn.mineru_parse_options` affects the parse request.

Add this assertion to the hidden metadata backend test if it is not already present:

```python
assert options.domain_metadata.custom_json["mineru_parse_options"]["device"] == "cuda:0"
```

Expected: metadata is preserved, but actual parse options still use Settings unless explicit `IndexDocumentIn.mineru_parse_options` is present.

---

### Task 4: Update Docs And Run Full Verification

**Files:**
- Modify: `docs/user-guide.md`
- Modify: `docs/workflows.md`

- [ ] **Step 1: Update user-facing docs**

In `docs/workflows.md`, keep the existing description of `/parse-async` metadata, then add:

```markdown
Settings and provider sync provide the default MinerU parser options sent to the sidecar. Upload and reindex screens can override those defaults for a single document before the job is queued. Domain profiles can describe reference structure, chunking, retrieval, and parser normalization, but hidden `domain_metadata.custom_json.mineru_parse_options` values do not affect parsing unless they are surfaced and accepted as explicit `IndexDocumentIn.mineru_parse_options`.
```

In `docs/user-guide.md`, add this near the MinerU Settings section:

```markdown
The MinerU health test distinguishes requested settings from capacity reported by the sidecar. If the sidecar only reports HPC coordinator mode, Ragstudio shows that parsing can use the HPC path but also warns that backend, device, and concurrency capacity were not reported by `/health`.

Document upload and reindex can use per-document MinerU overrides for one job. These overrides are visible before submission and are stored in the job's latest index options, so a document can use `cuda:1`, OCR, disabled formula parsing, or a different concurrency value without changing global Settings.
```

- [ ] **Step 2: Run backend tests for the touched areas**

Run:

```bash
./.venv/bin/pytest backend/tests/test_settings.py backend/tests/test_mineru_client.py backend/tests/test_document_parser_service.py backend/tests/test_domain_metadata.py backend/tests/test_documents_api.py -q
```

Expected: all tests pass. If the repo does not have `backend/tests/test_documents_api.py`, replace that path with the existing document route test module that contains `_parse_index_options` coverage.

- [ ] **Step 3: Run frontend tests**

Run:

```bash
cd frontend
npm test -- tests/settings-page.test.tsx tests/documents-page.test.tsx
```

Expected: all tests pass.

- [ ] **Step 4: Run lint and build**

Run:

```bash
./.venv/bin/ruff check backend/src/ragstudio backend/tests
cd frontend
npm run lint
npm run build
```

Expected: ruff and lint pass. Frontend build may keep the existing Vite chunk-size warning, but it must complete successfully.

- [ ] **Step 5: Re-check the three review findings manually**

Run:

```bash
rg -n "mineruOptimizationMessage|reported backend=|capacity not reported|mineru_parse_options" \
  backend/src/ragstudio frontend/src docs backend/tests frontend/tests
```

Expected:
- no `mineruOptimizationMessage` in the frontend
- `capacity not reported` appears in backend/frontend tests and route detail handling
- no active parser-resolution code applies `custom_json.mineru_parse_options`
- `IndexDocumentIn.mineru_parse_options` appears in schemas, upload/reindex client code, and parser resolution
- docs explain Settings defaults plus explicit per-document override behavior

## Self-Review

- Spec coverage: Task 1 fixes missing health capacity visibility; Task 2 fixes duplicate UI output; Task 3 fixes silent metadata overrides by adding visible per-document upload/reindex overrides; Task 4 verifies and documents all three.
- Placeholder scan: no placeholder steps or undefined test commands remain.
- Type consistency: backend `MinerUOptimizationOut` maps to frontend `MinerUOptimizationOut`; field names are `requested`, `reported`, `capacity_reported`, and `warning` in both layers.
