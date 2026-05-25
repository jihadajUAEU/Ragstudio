# Verified Vision Contract Upload Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Analyze with Vision produce the exact upload-ready contract package that upload/reindex use, so verified contracts enable canonical units and unverified contracts remain metadata-only.

**Architecture:** The vision model proposes metadata and executable contracts; Ragstudio executes candidates on sampled pages, normalizes the result into one upload-ready contract state, and validates the same package again at upload/reindex. The frontend displays that backend-derived state and submits the returned metadata unchanged, with a file-analysis fingerprint so stale analysis cannot be applied to a different file.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, pytest, React, TypeScript, TanStack Query, Vitest.

---

## Parallel Execution Notes

This plan is safe to split into three parallel work streams after Task 1 defines the response and metadata shape:

- Backend stream: Tasks 1, 2, and 3.
- Frontend stream: Task 4 after Task 2 names the response fields.
- Flow/timeline stream: Task 5 after Task 1 defines contract-state fields.

Task 6 is serial because it validates the integrated behavior.

## File Structure

- Modify `backend/src/ragstudio/schemas/parsing.py`
  - Add `AnalysisBinding`, `ContractStateSummary`, and optional fields on `DomainMetadataSuggestOut` and `IndexDocumentIn`.
- Create `backend/src/ragstudio/services/upload_contract_package.py`
  - Own upload-ready contract normalization, contract-state derivation, and file binding helpers.
- Modify `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`
  - Call the normalizer after generated execution and legacy validation paths.
  - Return derived contract state in `DomainMetadataSuggestOut`.
- Modify `backend/src/ragstudio/api/routes/domain_profiles.py`
  - Compute analysis binding from uploaded bytes and attach it to autosuggest responses.
- Modify `backend/src/ragstudio/api/routes/documents.py`
  - Accept `analysis_binding` in multipart upload.
  - Read file bytes before binding validation.
  - Reject stale/mismatched analysis before job creation.
- Modify `backend/src/ragstudio/services/document_pipeline_timeline_service.py`
  - Emit data-driven vision/contract/upload stages from existing metadata and new binding fields.
- Modify `frontend/src/api/generated.ts`
  - Add the generated-equivalent TypeScript interfaces for new schema fields if OpenAPI generation is not run in this task.
- Modify `frontend/src/api/client.ts`
  - Include `analysis_binding` when upload uses a vision suggestion.
- Modify `frontend/src/features/documents/documents-page.tsx`
  - Track selected-file fingerprint.
  - Ignore late analysis responses for previous files.
  - Render verified/metadata-only contract review.
  - Upload the exact returned `domain_metadata`.
- Modify tests:
  - `backend/tests/test_domain_metadata_ai_suggester.py`
  - `backend/tests/test_domain_metadata_contract_compiler.py`
  - `backend/tests/test_documents.py`
  - `backend/tests/test_document_pipeline_timeline.py`
  - `frontend/tests/documents-page.test.tsx`

---

### Task 1: Backend Upload-Ready Contract Normalizer

**Files:**
- Create: `backend/src/ragstudio/services/upload_contract_package.py`
- Modify: `backend/src/ragstudio/schemas/parsing.py`
- Modify: `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`
- Test: `backend/tests/test_domain_metadata_ai_suggester.py`

- [x] **Step 1: Add failing tests for verified and unverified normalization**

Add tests that assert verified execution contains a complete upload-ready package and unverified output is demoted to metadata-only:

```python
assert custom_json["reference_contract_validation"]["status"] == "verified"
assert custom_json["reference_resolution"]["enabled"] is True
assert custom_json["reference_resolution"]["build_canonical_units"] is True
assert result.contract_state.state == "verified"
assert result.contract_state.canonical_units is True

assert metadata_only.custom_json.get("reference_resolution", {}).get("build_canonical_units") is not True
assert metadata_only.custom_json.get("chunking", {}).get("unit") != "reference"
assert metadata_only_result.contract_state.state == "metadata_only"
```

- [x] **Step 2: Run the failing autosuggest tests**

Run:

```powershell
$env:PYTHONPATH = "backend/src"
python -m pytest backend/tests/test_domain_metadata_ai_suggester.py -q
```

Expected: at least one new assertion fails because `contract_state` and metadata-only demotion are not implemented yet.

- [x] **Step 3: Add schemas for contract state and analysis binding**

In `backend/src/ragstudio/schemas/parsing.py`, add:

```python
class AnalysisBinding(StudioModel):
    filename: str
    size_bytes: int = Field(ge=0)
    sha256: str


class ContractStateSummary(StudioModel):
    state: Literal["verified", "metadata_only", "generic"]
    canonical_units: bool = False
    reason: str = ""
    matched_units: int | None = None
    selected_strategy: str | None = None
    identity_fields: list[str] = Field(default_factory=list)
```

Extend `DomainMetadataSuggestOut`:

```python
analysis_binding: AnalysisBinding | None = None
contract_state: ContractStateSummary | None = None
```

Extend `IndexDocumentIn`:

```python
analysis_binding: AnalysisBinding | None = None
```

- [x] **Step 4: Implement the normalizer service**

Create `backend/src/ragstudio/services/upload_contract_package.py` with pure helpers:

```python
from __future__ import annotations

import copy
import hashlib
from typing import Any

from ragstudio.schemas.parsing import AnalysisBinding, ContractStateSummary, DomainMetadata


REFERENCE_CHUNK_UNITS = {"reference", "reference_unit", "canonical_reference"}


def build_analysis_binding(*, filename: str, content: bytes) -> AnalysisBinding:
    return AnalysisBinding(filename=filename, size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())


def normalize_upload_ready_domain_metadata(metadata: DomainMetadata) -> tuple[DomainMetadata, ContractStateSummary]:
    custom_json = copy.deepcopy(metadata.custom_json or {})
    state = derive_contract_state(custom_json)
    if state.state != "verified":
        _demote_reference_unit_chunking(custom_json)
        custom_json.setdefault("reference_resolution", {})
        custom_json["reference_resolution"]["enabled"] = False
        custom_json["reference_resolution"]["build_canonical_units"] = False
        state = derive_contract_state(custom_json)
    return metadata.model_copy(update={"custom_json": custom_json}), state


def derive_contract_state(custom_json: dict[str, Any]) -> ContractStateSummary:
    validation = _dict(custom_json.get("reference_contract_validation"))
    execution = _dict(custom_json.get("reference_contract_execution"))
    reference_resolution = _dict(custom_json.get("reference_resolution"))
    reference_schema = _dict(custom_json.get("reference_schema"))
    status = str(validation.get("status") or execution.get("status") or "").lower()
    canonical_units = bool(reference_resolution.get("enabled")) and bool(reference_resolution.get("build_canonical_units"))
    identity_fields = _identity_fields(reference_schema)
    matched_units = _int_value(validation.get("matched_units") or execution.get("matched_units"))
    selected_strategy = _str_value(validation.get("selected_strategy") or execution.get("selected_strategy"))
    if status == "verified" and canonical_units and identity_fields:
        return ContractStateSummary(
            state="verified",
            canonical_units=True,
            reason="Executable reference contract verified on sampled pages.",
            matched_units=matched_units,
            selected_strategy=selected_strategy,
            identity_fields=identity_fields,
        )
    if reference_schema or validation or execution:
        return ContractStateSummary(
            state="metadata_only",
            canonical_units=False,
            reason="Reference observations are kept as metadata hints because no executable canonical-unit contract is verified.",
            matched_units=matched_units,
            selected_strategy=selected_strategy,
            identity_fields=identity_fields,
        )
    return ContractStateSummary(state="generic", canonical_units=False, reason="No reference contract was detected.")
```

Add small private helpers in the same file:

```python
def _demote_reference_unit_chunking(custom_json: dict[str, Any]) -> None:
    chunking = custom_json.get("chunking")
    if isinstance(chunking, dict) and str(chunking.get("unit") or "").lower() in REFERENCE_CHUNK_UNITS:
        chunking.pop("unit", None)
        if not chunking:
            custom_json.pop("chunking", None)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _identity_fields(reference_schema: dict[str, Any]) -> list[str]:
    fields = reference_schema.get("identity_fields") or reference_schema.get("fields") or []
    if isinstance(fields, list):
        return [str(field) for field in fields if str(field).strip()]
    return []


def _int_value(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _str_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
```

- [x] **Step 5: Wire the normalizer into autosuggest**

In `DomainMetadataAiSuggester.suggest()`, after all execution/validation paths finish and before returning, call:

```python
metadata, contract_state = normalize_upload_ready_domain_metadata(metadata)
```

Return:

```python
return DomainMetadataSuggestOut(
    domain_metadata=metadata,
    raw_domain_metadata=raw_metadata,
    reference_contract_validation=validation_payload,
    confidence=confidence,
    evidence_pages=evidence_pages,
    rationale=rationale,
    warnings=warnings,
    contract_state=contract_state,
)
```

- [x] **Step 6: Run autosuggest tests**

Run:

```powershell
$env:PYTHONPATH = "backend/src"
python -m pytest backend/tests/test_domain_metadata_ai_suggester.py -q
```

Expected: tests pass.

---

### Task 2: File/Analysis Binding For Autosuggest And Upload

**Files:**
- Modify: `backend/src/ragstudio/api/routes/domain_profiles.py`
- Modify: `backend/src/ragstudio/api/routes/documents.py`
- Modify: `backend/src/ragstudio/services/upload_contract_package.py`
- Test: `backend/tests/test_documents.py`

- [x] **Step 1: Add failing upload binding tests**

In `backend/tests/test_documents.py`, add tests for:

```python
valid_binding = {
    "filename": "quran.pdf",
    "size_bytes": len(content),
    "sha256": hashlib.sha256(content).hexdigest(),
}
```

Assertions:

```python
assert response.status_code == 201
assert stored.latest_index_options["analysis_binding"]["sha256"] == valid_binding["sha256"]

assert stale_response.status_code == 422
assert "analysis does not match the uploaded file" in stale_response.json()["detail"]
```

- [x] **Step 2: Run the failing document tests**

Run:

```powershell
$env:PYTHONPATH = "backend/src"
python -m pytest backend/tests/test_documents.py -q
```

Expected: the new stale-binding test fails because upload does not accept or validate `analysis_binding`.

- [x] **Step 3: Attach binding to autosuggest**

In `backend/src/ragstudio/api/routes/domain_profiles.py`, after reading `data`, compute:

```python
analysis_binding = build_analysis_binding(filename=filename, content=data)
```

After `suggest()` returns, copy the response with the binding:

```python
suggestion = await DomainMetadataAiSuggester(...).suggest(...)
return suggestion.model_copy(update={"analysis_binding": analysis_binding})
```

- [x] **Step 4: Accept and validate binding on upload**

In `backend/src/ragstudio/api/routes/documents.py`, add a multipart form field:

```python
analysis_binding: str | None = Form(default=None),
```

Pass it to `_parse_index_options(...)`. Update `_parse_index_options` to decode it:

```python
analysis_binding_payload = _parse_json_form("analysis_binding", analysis_binding)
payload["analysis_binding"] = analysis_binding_payload
```

Read file content before binding validation:

```python
content = await read_upload_file(file)
_validate_analysis_binding(index_options.analysis_binding, filename=file.filename or "upload.bin", content=content)
```

Implement `_validate_analysis_binding` using a helper from `upload_contract_package.py`:

```python
def assert_analysis_binding_matches(binding: AnalysisBinding | None, *, filename: str, content: bytes) -> None:
    if binding is None:
        return
    actual = build_analysis_binding(filename=filename, content=content)
    if binding.size_bytes != actual.size_bytes or binding.sha256 != actual.sha256:
        raise ValueError("Vision analysis does not match the uploaded file. Run Analyze with Vision again.")
```

Convert `ValueError` to `HTTPException(status_code=422, detail=str(exc))`.

- [x] **Step 5: Preserve binding in stored latest index options**

Keep `IndexDocumentIn.analysis_binding` in the compiled options sent to `DocumentService.upload()` and `create_index_job()`. Do not store the binding inside `domain_metadata.custom_json`; it is upload provenance, not model metadata.

- [x] **Step 6: Run document tests**

Run:

```powershell
$env:PYTHONPATH = "backend/src"
python -m pytest backend/tests/test_documents.py -q
```

Expected: tests pass.

---

### Task 3: Compiler And Reindex Guardrails

**Files:**
- Modify: `backend/src/ragstudio/services/domain_metadata_contract_compiler.py`
- Modify: `backend/src/ragstudio/services/upload_contract_package.py`
- Test: `backend/tests/test_domain_metadata_contract_compiler.py`
- Test: `backend/tests/test_documents.py`

- [x] **Step 1: Add failing tests for incomplete copied payloads**

Add compiler tests proving this remains invalid:

```python
metadata = DomainMetadata(custom_json={"chunking": {"unit": "reference"}})
with pytest.raises(DomainMetadataContractError, match="Reference-unit chunking requires"):
    validate_executable_reference_contract(metadata)
```

Add reindex tests proving metadata-only options do not enable canonical units:

```python
payload = IndexDocumentIn(domain_metadata=metadata_only_domain_metadata)
response = await client.post(f"/api/documents/{document_id}/reindex", json=payload.model_dump(mode="json"))
assert response.status_code == 202
assert payload.domain_metadata.custom_json["reference_resolution"]["build_canonical_units"] is False
```

- [x] **Step 2: Run failing focused tests**

Run:

```powershell
$env:PYTHONPATH = "backend/src"
python -m pytest backend/tests/test_domain_metadata_contract_compiler.py backend/tests/test_documents.py -q
```

Expected: the reindex behavior fails if metadata-only normalization is not called consistently.

- [x] **Step 3: Normalize before upload/reindex validation**

In `compile_index_options()` or immediately after `compile_index_options()` in upload/reindex route code, call:

```python
compiled_metadata, _contract_state = normalize_upload_ready_domain_metadata(options.domain_metadata)
options = options.model_copy(update={"domain_metadata": compiled_metadata})
```

Preserve strict validation after normalization:

```python
validate_executable_reference_contract(options.domain_metadata)
```

Do not normalize payloads that contain `custom_json.chunking.unit="reference"` and `reference_contract_validation.status="verified"` but lack reference resolution; keep those invalid so partial UI copies still fail.

- [x] **Step 4: Run compiler and document tests**

Run:

```powershell
$env:PYTHONPATH = "backend/src"
python -m pytest backend/tests/test_domain_metadata_contract_compiler.py backend/tests/test_documents.py -q
```

Expected: tests pass.

---

### Task 4: Frontend Exact Handoff And Review Panel

**Files:**
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/features/documents/documents-page.tsx`
- Test: `frontend/tests/documents-page.test.tsx`

- [x] **Step 1: Add failing frontend tests**

Add tests asserting:

```typescript
expect(apiClient.uploadDocument).toHaveBeenCalledWith({
  file,
  options: {
    parser_mode: DEFAULT_PARSER_MODE,
    domain_metadata: suggestion.domain_metadata,
    analysis_binding: suggestion.analysis_binding,
  },
});
```

Add a stale-response test:

```typescript
const first = new File(["one"], "one.pdf", { type: "application/pdf" });
const second = new File(["two"], "two.pdf", { type: "application/pdf" });
// Resolve first analysis after second file is selected.
expect(screen.queryByText(/canonical units/i)).not.toBeInTheDocument();
expect(screen.getByRole("button", { name: /upload/i })).toBeDisabled();
```

- [x] **Step 2: Run failing frontend tests**

Run from `frontend/`:

```powershell
cmd /c npm test -- documents-page.test.tsx --run
```

Expected: tests fail because upload does not include `analysis_binding` and late responses are not guarded.

- [x] **Step 3: Update generated-equivalent types**

In `frontend/src/api/generated.ts`, add:

```typescript
export interface AnalysisBinding {
  filename: string;
  size_bytes: number;
  sha256: string;
}

export interface ContractStateSummary {
  state: "verified" | "metadata_only" | "generic";
  canonical_units?: boolean;
  reason?: string;
  matched_units?: number | null;
  selected_strategy?: string | null;
  identity_fields?: string[];
}
```

Extend `DomainMetadataSuggestOut` and `IndexDocumentIn` with optional `analysis_binding`, and extend `DomainMetadataSuggestOut` with optional `contract_state`.

- [x] **Step 4: Submit binding from the API client**

In `frontend/src/api/client.ts`, keep `uploadDocument` accepting `IndexDocumentIn`, and add:

```typescript
if (options.analysis_binding) {
  formData.set("analysis_binding", JSON.stringify(options.analysis_binding));
}
```

- [x] **Step 5: Guard stale analysis responses**

In `frontend/src/features/documents/documents-page.tsx`, derive a local file key:

```typescript
function fileKey(file: File | null): string | null {
  return file ? `${file.name}:${file.size}:${file.lastModified}` : null;
}
```

Store the key when analysis starts and only apply a response if it still matches the selected file:

```typescript
const requestedFileKey = fileKey(selectedFile);
setVisionRequestFileKey(requestedFileKey);
const response = await apiClient.suggestDomainMetadata({ file: selectedFile });
if (requestedFileKey === fileKey(selectedFile)) {
  setVisionSuggestion(response);
}
```

Use mutation callbacks or a wrapper function so the guard sees the current selected file.

- [x] **Step 6: Render compact contract review**

Render these fields near the existing vision suggestion panel:

```typescript
const contractState = visionSuggestion.contract_state?.state ?? "generic";
const canonicalUnits = Boolean(visionSuggestion.contract_state?.canonical_units);
```

Visible labels:

```text
Contract: verified
Canonical units: on
Matched units: 120
Identity fields: chapter, verse
```

For metadata-only:

```text
Contract: metadata-only
Canonical units: off
Reference observations will be used as hints, not enforced as reference-unit chunks.
```

- [x] **Step 7: Disable upload without current-file analysis**

Disable upload when there is a selected file but no `visionSuggestion` whose `analysis_binding` exists for that file:

```typescript
const uploadDisabled = !selectedFile || !visionSuggestion || analyzeWithVision.isPending || uploadMutation.isPending;
```

Keep the domain metadata object exact:

```typescript
domain_metadata: visionSuggestion.domain_metadata
```

- [x] **Step 8: Run frontend tests**

Run from `frontend/`:

```powershell
cmd /c npm test -- documents-page.test.tsx --run
```

Expected: tests pass.

---

### Task 5: Document Flow Contract Stages

**Files:**
- Modify: `backend/src/ragstudio/services/document_pipeline_timeline_service.py`
- Test: `backend/tests/test_document_pipeline_timeline.py`

- [x] **Step 1: Add failing timeline tests**

Add a document timeline test with `latest_index_options.domain_metadata.custom_json` containing:

```python
"reference_contract_execution": {"status": "verified", "matched_units": 12, "matched_pages": [1, 2]},
"reference_contract_validation": {"status": "verified", "selected_strategy": "chapter_verse"},
"reference_resolution": {"enabled": True, "build_canonical_units": True},
"reference_schema": {"fields": ["chapter", "verse"], "canonical_ref_template": "{chapter}:{verse}"},
```

Assert the returned timeline includes:

```python
assert "vision_sampled" in stage_ids
assert "contract_proposed" in stage_ids
assert "contract_executed" in stage_ids
assert "contract_verified" in stage_ids
assert "upload_contract_applied" in stage_ids
assert "canonical_units_enabled" in stage_ids
```

- [x] **Step 2: Run failing timeline tests**

Run:

```powershell
$env:PYTHONPATH = "backend/src"
python -m pytest backend/tests/test_document_pipeline_timeline.py -q
```

Expected: the new stage assertions fail until the service maps the contract fields.

- [x] **Step 3: Add data-driven stage mapping**

In `DocumentPipelineTimelineService`, derive stage events from `document.latest_index_options` and document contract fields:

```python
if evidence_pages or analysis_binding:
    _append_stage("vision_sampled", "Vision sampled pages", "complete", {...})
if reference_schema or domain_structure:
    _append_stage("contract_proposed", "Contract proposed", "complete", {...})
if reference_contract_execution:
    _append_stage("contract_executed", "Contract executed", execution_status, {...})
if reference_contract_validation:
    _append_stage("contract_verified", "Contract verified", validation_status, {...})
if latest_custom_json:
    _append_stage("upload_contract_applied", "Upload contract applied", "complete", {...})
if reference_contract.verified and reference_contract.canonical_units:
    _append_stage("canonical_units_enabled", "Canonical units enabled", "complete", {...})
```

Use an unavailable/metadata-only status when fields are present but not verified. Do not classify missing fields as failures.

- [x] **Step 4: Run timeline tests**

Run:

```powershell
$env:PYTHONPATH = "backend/src"
python -m pytest backend/tests/test_document_pipeline_timeline.py -q
```

Expected: tests pass.

---

### Task 6: Integrated Validation And Branch Finish

**Files:**
- Verify only unless fixes are needed.

- [x] **Step 1: Run focused backend validation**

Run:

```powershell
$env:PYTHONPATH = "backend/src"
python -m pytest backend/tests/test_domain_metadata_ai_suggester.py backend/tests/test_domain_metadata_contract_compiler.py backend/tests/test_documents.py backend/tests/test_document_pipeline_timeline.py -q
```

Expected: all selected tests pass.

- [x] **Step 2: Run focused frontend validation**

Run from `frontend/`:

```powershell
cmd /c npm test -- documents-page.test.tsx --run
```

Expected: selected frontend tests pass.

- [x] **Step 3: Run lint on touched backend modules**

Run:

```powershell
$env:PYTHONPATH = "backend/src"
python -m ruff check backend/src/ragstudio/schemas/parsing.py backend/src/ragstudio/services/upload_contract_package.py backend/src/ragstudio/services/domain_metadata_ai_suggester.py backend/src/ragstudio/api/routes/domain_profiles.py backend/src/ragstudio/api/routes/documents.py backend/src/ragstudio/services/document_pipeline_timeline_service.py backend/tests/test_domain_metadata_ai_suggester.py backend/tests/test_domain_metadata_contract_compiler.py backend/tests/test_documents.py backend/tests/test_document_pipeline_timeline.py
```

Expected: ruff passes.

- [x] **Step 4: Review diff**

Run:

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only plan-related files and implementation files changed.

- [x] **Step 5: Commit**

Run:

```powershell
git add docs/superpowers/plans/2026-05-25-verified-vision-contract-upload-handoff.md backend/src/ragstudio/schemas/parsing.py backend/src/ragstudio/services/upload_contract_package.py backend/src/ragstudio/services/domain_metadata_ai_suggester.py backend/src/ragstudio/api/routes/domain_profiles.py backend/src/ragstudio/api/routes/documents.py backend/src/ragstudio/services/document_pipeline_timeline_service.py backend/tests/test_domain_metadata_ai_suggester.py backend/tests/test_domain_metadata_contract_compiler.py backend/tests/test_documents.py backend/tests/test_document_pipeline_timeline.py frontend/src/api/generated.ts frontend/src/api/client.ts frontend/src/features/documents/documents-page.tsx frontend/tests/documents-page.test.tsx
git commit -m "feat: hand off verified vision contracts to upload"
```

Expected: commit succeeds.

---

## Self-Review

- Spec coverage: The plan covers upload-ready autosuggest output, shared normalization, file binding, upload/reindex guardrails, frontend stale-response handling, exact metadata handoff, review panel display, and flow stages.
- Placeholder scan: No task depends on unspecified future work; each test, implementation point, and validation command is concrete.
- Type consistency: `AnalysisBinding`, `ContractStateSummary`, `analysis_binding`, and `contract_state` are used consistently across backend schemas, API client, and frontend behavior.
