# Document Pipeline Stage Flow UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an A+C document stage UI that shows the actual ordered path a document passed through, with a compact stage rail, flow map, event ledger, and selected-stage inspector.

**Architecture:** Add a backend-owned document pipeline stage contract. The backend returns ordered stages, events, contract state, warning groups, and totals for each document; React renders that contract generically instead of owning a hardcoded stage list. Known stage ids may get custom icons/colors, but unknown ids must still render with neutral fallback UI so future stages can be added, omitted, skipped, or versioned without React changes.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Pydantic, pytest; React, TypeScript, TanStack Query, Testing Library, Vitest, Tailwind CSS v4, lucide-react.

---

## Current Behavior Verified

- `backend/src/ragstudio/services/index_progress.py` already records structured `Job.result["indexing_stage_events"]`.
- `frontend/src/features/documents/documents-page.tsx` already shows current job stage text in the Jobs & Warnings tab.
- `frontend/src/features/document-evidence/document-evidence-page.tsx` fetches parse evidence only and renders `EvidenceInspector`.
- The approved UI direction is A+C: compact rail plus flow map, event ledger, and selected-stage inspector.

## File Structure

- Create `backend/src/ragstudio/schemas/document_pipeline_timeline.py`
  - Typed response contract for dynamic stages, events, contract summary, warning groups, and totals.
- Create `backend/src/ragstudio/services/document_pipeline_timeline_service.py`
  - Assembles document stage flow from `Document`, `Job`, `Chunk`, `IndexRecord`, `GraphProjectionRecord`, and `Job.result["indexing_stage_events"]`.
- Modify `backend/src/ragstudio/api/routes/documents.py`
  - Adds `GET /api/documents/{document_id}/pipeline-timeline`.
- Create `backend/tests/test_document_pipeline_timeline.py`
  - Tests dynamic stages, contract summary, warning separation, endpoint behavior, and unknown-stage passthrough.
- Modify `frontend/src/api/generated.ts`
  - Adds `DocumentPipelineTimelineOut`, `DocumentPipelineStageOut`, `DocumentPipelineEventOut`, warning, contract, and totals interfaces.
- Modify `frontend/src/api/client.ts`
  - Adds `documentPipelineTimeline(documentId)`.
- Create `frontend/src/features/document-evidence/document-pipeline-stage-flow.tsx`
  - A+C UI: compact rail, flow map, event ledger, and selected-stage inspector.
- Modify `frontend/src/features/document-evidence/document-evidence-page.tsx`
  - Fetches stage flow in parallel with parse evidence and renders it above `EvidenceInspector`.
- Create `frontend/tests/document-pipeline-stage-flow.test.tsx`
  - Component tests for generic stage rendering, inspector selection, contract summary, warning groups, and unknown stages.
- Modify `frontend/tests/document-evidence-page.test.tsx`
  - Page tests for parallel fetch and independent degradation.
- Modify `frontend/tests/api-client.test.ts`
  - Client URL test for the new endpoint.

## Dynamic Stage Contract Rules

- Adding a stage: backend emits the new stage in `stages`; the frontend renders it with fallback UI if no custom renderer exists.
- Removing a stage: backend omits it; the frontend never assumes all baseline stages exist.
- Skipping a stage: backend may emit it with `state = "skipped"` and a detail explaining why.
- Renaming a stage: keep stable `id`, change only display `label`.
- Changing stage semantics: introduce a new `id` or increment `contract_version`.
- Historical documents: render the stage list reconstructed for that document/job, not the latest global pipeline definition.

---

### Task 1: Backend Stage Contract

**Files:**
- Create: `backend/src/ragstudio/schemas/document_pipeline_timeline.py`
- Test: `backend/tests/test_document_pipeline_timeline.py`

- [ ] **Step 1: Add contract serialization tests**

Create `backend/tests/test_document_pipeline_timeline.py` with tests that instantiate:

- `DocumentPipelineStageOut` using an unknown stage id `custom_future_stage`.
- `DocumentPipelineContractOut` with `contract_status="metadata_only"`, `verified=False`, `canonical_units=False`, `schema_type="chapter_verse"`, `repair_status="unverified"`, `validation_status="unverified"`, and `validation_matched_units=0`.
- `DocumentPipelineTimelineOut` with the unknown stage and contract summary.

Expected assertions:

- Unknown stage ids serialize without validation failure.
- Stage state serializes as `warning`, `running`, `complete`, `skipped`, or `metadata_only`.
- Contract summary fields serialize without reading raw metadata in React.

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `pytest backend/tests/test_document_pipeline_timeline.py::test_document_pipeline_timeline_contract_serializes_dynamic_stages -q`

Expected: FAIL because `ragstudio.schemas.document_pipeline_timeline` does not exist.

- [ ] **Step 3: Add the schema**

Create `backend/src/ragstudio/schemas/document_pipeline_timeline.py` with:

- `PipelineStageState = Literal["pending", "running", "complete", "warning", "blocked", "failed", "skipped", "metadata_only"]`
- `PipelineEventSource = Literal["document", "structured_event", "inferred_log", "job", "chunk", "index_record", "graph_projection", "contract", "warning"]`
- `DocumentPipelineStageOut`
- `DocumentPipelineEventOut`
- `DocumentPipelineWarningGroupOut`
- `DocumentPipelineContractOut`
- `DocumentPipelineTotalsOut`
- `DocumentPipelineTimelineOut`

All models inherit `StudioModel`, forbid extra fields through the base config, and use `Field(default_factory=...)` for list/dict defaults.

- [ ] **Step 4: Run the focused contract test**

Run: `pytest backend/tests/test_document_pipeline_timeline.py::test_document_pipeline_timeline_contract_serializes_dynamic_stages -q`

Expected: PASS.

### Task 2: Backend Timeline Service And Route

**Files:**
- Create: `backend/src/ragstudio/services/document_pipeline_timeline_service.py`
- Modify: `backend/src/ragstudio/api/routes/documents.py`
- Test: `backend/tests/test_document_pipeline_timeline.py`

- [ ] **Step 1: Add service and route tests**

Add tests that create a document, a related index job with structured events, chunks with parser warnings, an index record, and a graph projection record.

Required assertions:

- `DocumentPipelineTimelineService.get_timeline(document_id)` returns ordered stages and events.
- `uploaded`, `contract`, dynamic structured event stages, `quality_gates`, and materialization stages appear only when supported by document/job data.
- An unknown structured event stage is included in `stages` and `events`.
- Unverified `metadata_only` reference contract becomes a contract stage with `state="metadata_only"` and does not become a failed verified-contract stage.
- Warning groups keep `reference_unit_unresolved` separate from independent `reference_unit_missing_expected_script` and `equation_missing_latex` warnings.
- `GET /api/documents/{document_id}/pipeline-timeline` returns the timeline.
- Missing document returns 404.

- [ ] **Step 2: Run the backend tests and confirm failure**

Run: `pytest backend/tests/test_document_pipeline_timeline.py -q`

Expected: FAIL because the service and route do not exist.

- [ ] **Step 3: Implement `DocumentPipelineTimelineService`**

Implement a service that:

- Fetches the document by id.
- Fetches all `index_document` jobs for the document, newest last for event assembly.
- Counts chunks and scans `Chunk.extraction_quality["parser_warnings"]` for grouped warnings.
- Fetches index records and graph projection records for materialization counts.
- Extracts contract summary from `Document.index_contract` and nested `domain_metadata.custom_json`.
- Builds stages from actual evidence, not a frontend baseline list.
- Adds unknown structured event stages as-is using their event `stage` and `label`.
- Marks running/current stage from latest running job stage.
- Adds `missing_sections` when jobs, chunks, or parse evidence are absent.

- [ ] **Step 4: Add route**

Import `DocumentPipelineTimelineOut`, `DocumentPipelineTimelineNotFoundError`, and `DocumentPipelineTimelineService` in `backend/src/ragstudio/api/routes/documents.py`.

Add:

`GET /api/documents/{document_id}/pipeline-timeline`

The route returns the service timeline and maps not-found to HTTP 404.

- [ ] **Step 5: Run backend timeline tests**

Run: `pytest backend/tests/test_document_pipeline_timeline.py -q`

Expected: PASS.

### Task 3: Frontend API Contract

**Files:**
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/tests/api-client.test.ts`

- [ ] **Step 1: Add API client test**

Add a test that stubs `fetch`, calls `apiClient.documentPipelineTimeline("doc/with spaces")`, and asserts the URL is:

`/api/documents/doc%2Fwith%20spaces/pipeline-timeline`

- [ ] **Step 2: Run the client test and confirm failure**

Run: `cd frontend; npx.cmd vitest run tests/api-client.test.ts`

Expected: FAIL because `documentPipelineTimeline` does not exist.

- [ ] **Step 3: Add generated TypeScript interfaces**

Add interfaces that mirror the backend schema:

- `PipelineStageState`
- `PipelineEventSource`
- `DocumentPipelineStageOut`
- `DocumentPipelineEventOut`
- `DocumentPipelineWarningGroupOut`
- `DocumentPipelineContractOut`
- `DocumentPipelineTotalsOut`
- `DocumentPipelineTimelineOut`

- [ ] **Step 4: Add API client method**

Add `documentPipelineTimeline(documentId)` to `frontend/src/api/client.ts` and import `DocumentPipelineTimelineOut`.

- [ ] **Step 5: Run the client test**

Run: `cd frontend; npx.cmd vitest run tests/api-client.test.ts`

Expected: PASS.

### Task 4: A+C Stage Flow Component

**Files:**
- Create: `frontend/src/features/document-evidence/document-pipeline-stage-flow.tsx`
- Create: `frontend/tests/document-pipeline-stage-flow.test.tsx`

- [ ] **Step 1: Add component tests**

Create tests that render a `DocumentPipelineTimelineOut` for the Quran shape:

- stage rail includes `Vision`, `Contract`, and `Chunks`.
- selected default stage is the running stage when present.
- selecting `Contract` shows `metadata_only`, `verified=false`, `canonical_units=false`, repair/validation unverified, and matched units `0`.
- warning groups show `reference_unit_missing_expected_script` and `equation_missing_latex`.
- `reference_unit_unresolved` appears as its own group when present.
- unknown stage id `custom_future_stage` renders with its label and neutral fallback.

- [ ] **Step 2: Run the component test and confirm failure**

Run: `cd frontend; npx.cmd vitest run tests/document-pipeline-stage-flow.test.tsx`

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement component**

Build `DocumentPipelineStageFlow` with:

- Compact rail across the top from `timeline.stages`.
- Flow map list from `timeline.stages`.
- Event ledger from `timeline.events`.
- Selected-stage inspector from `timeline.stages`, `timeline.contract`, `timeline.warning_groups`, and selected stage details.
- Generic fallback for unknown stage ids.
- No frontend assumption that baseline stages always exist.

- [ ] **Step 4: Run component tests**

Run: `cd frontend; npx.cmd vitest run tests/document-pipeline-stage-flow.test.tsx`

Expected: PASS.

### Task 5: Evidence Page Integration

**Files:**
- Modify: `frontend/src/features/document-evidence/document-evidence-page.tsx`
- Modify: `frontend/tests/document-evidence-page.test.tsx`

- [ ] **Step 1: Add page tests**

Update the API mock to include `documentPipelineTimeline`.

Add tests that assert:

- The page requests parse evidence and pipeline timeline for the same document id.
- Timeline renders above evidence.
- Timeline failure shows `Pipeline stage flow unavailable` without hiding parse evidence.

- [ ] **Step 2: Run page tests and confirm failure**

Run: `cd frontend; npx.cmd vitest run tests/document-evidence-page.test.tsx`

Expected: FAIL because the page does not request the timeline.

- [ ] **Step 3: Integrate query and component**

Fetch `apiClient.documentPipelineTimeline(documentId)` with TanStack Query using key `["document-pipeline-timeline", documentId]`.

Render `DocumentPipelineStageFlow` above `EvidenceInspector` when data is available. If the timeline query fails, show an alert section and keep parse evidence visible.

- [ ] **Step 4: Run page tests**

Run: `cd frontend; npx.cmd vitest run tests/document-evidence-page.test.tsx`

Expected: PASS.

### Task 6: Verification

**Files:**
- Modify this plan as tasks are completed.

- [ ] **Step 1: Backend verification**

Run: `pytest backend/tests/test_document_pipeline_timeline.py -q`

Expected: PASS.

- [ ] **Step 2: Frontend verification**

Run: `cd frontend; npx.cmd vitest run tests/document-pipeline-stage-flow.test.tsx tests/document-evidence-page.test.tsx tests/api-client.test.ts`

Expected: PASS.

- [ ] **Step 3: OpenAPI generation**

Run: `bash scripts/generate-openapi.sh`

Expected: OpenAPI generation succeeds and includes `/api/documents/{document_id}/pipeline-timeline`.

- [ ] **Step 4: Static hygiene**

Run: `git diff --check`

Expected: PASS.

## Self-Review

Spec coverage:

- A+C direction is covered by Task 4 and Task 5.
- Dynamic stage contract and add/remove/skip compatibility are covered by Task 1, Task 2, and Task 4.
- Contract metadata-only behavior is covered by Task 1, Task 2, and Task 4.
- Warning separation is covered by Task 2 and Task 4.
- Evidence-page integration is covered by Task 5.

Design limitations:

- This first implementation adds the full A+C stage flow to Document Evidence. The Documents table rail is explicitly deferred to a follow-up plan because the evidence page is the first surface with complete document context.
- Historical jobs with no structured `indexing_stage_events` can only be represented from document/job status and logs. Those events must be marked `source="inferred_log"` when inferred.
- The backend may include baseline product vocabulary, but React must not hardcode the stage list.

Placeholder scan:

- No placeholder tasks are included.
- Every verification step includes an exact command and expected result.
