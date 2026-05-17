# Query Pathway Performance Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the Query page `View pathway` drawer into a timeline-based performance diagnosis view without changing query behavior.

**Architecture:** Add a backend diagnostics builder that normalizes existing run `timings`, `chunk_traces`, `sources`, `token_metadata`, and `query_config` into ordered pathway rows. Expose those rows as an optional `RunOut.pathway_diagnostics` field and simplify the frontend drawer to render `Summary / Timeline / Raw`.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, React/TypeScript, Vitest, pytest.

---

## File Structure

- Create `backend/src/ragstudio/services/query_pathway_diagnostics_service.py`
  - Owns diagnostic row construction and deterministic diagnosis rules.
- Modify `backend/src/ragstudio/schemas/runs.py`
  - Adds `PathwayDiagnosticOut` and `pathway_diagnostics` to `RunOut`.
- Modify `backend/src/ragstudio/services/query_service.py`
  - Populates diagnostics while serializing `Run` records.
- Create `backend/tests/test_query_pathway_diagnostics_service.py`
  - Unit tests for timeline rows, timeout/warning diagnosis, missing trace handling.
- Modify `frontend/src/api/generated.ts`
  - Adds generated TypeScript shape for `PathwayDiagnosticOut` and `RunOut.pathway_diagnostics`.
- Modify `frontend/src/features/query/query-pathway-viewer.tsx`
  - Renders Summary, normalized Timeline, and Raw only.
  - Keeps fallback for old runs without `pathway_diagnostics`.
- Modify `frontend/tests/query-page.test.tsx`
  - Updates expectations for the simplified modal and richer timeline rows.
- Create `.planning/quick/260517-cy7-implement-query-pathway-performance-diag/260517-cy7-PLAN.md`
  - Records implementation tasks and verification.

## Task 1: Backend Diagnostic Model and Builder

**Files:**
- Create: `backend/src/ragstudio/services/query_pathway_diagnostics_service.py`
- Modify: `backend/src/ragstudio/schemas/runs.py`
- Test: `backend/tests/test_query_pathway_diagnostics_service.py`

- [ ] **Step 1: Write failing backend tests**

Create tests covering:

```python
def test_builds_complete_fast_mode_pathway_diagnostics():
    run = diagnostic_service.build(
        status="succeeded",
        error=None,
        error_type=None,
        timings={
            "total_ms": 7574.93,
            "planner_ms": 1915.076,
            "query_hypothesis_ms": 1543.2,
            "query_hypothesis_timeout_ms": 5000,
            "metadata_ms": 3.0,
            "native_stage_ms": 2500.1,
            "native_degraded": True,
            "native_error": "Native query timed out after 2500 ms.",
            "graph_ms": 159.3,
            "graph_hydration_ms": 3.2,
            "initial_fusion_ms": 0.05,
            "final_fusion_ms": 0.14,
            "context_assembly_ms": 0.08,
            "answer_ms": 3001.0,
            "answer_timeout_ms": 3000,
            "answer_fallback": True,
        },
        chunk_traces=[
            {
                "stage": "planner",
                "intent": "semantic",
                "retrieval_strategy": "reference_first_hybrid",
                "candidate_limit": 20,
                "query_hypothesis_status": "valid",
            },
            {
                "stage": "query_hypothesis",
                "status": "valid",
                "target_terms": [
                    {"surface": "offering"},
                    {"surface": "sacrifice"},
                    {"surface": "eid"},
                ],
                "possible_references": ["book:13:hadith:25"],
            },
            {
                "stage": "retrieval",
                "native_status": "degraded",
                "native_candidates": 0,
                "metadata_trace": {
                    "passes": [
                        {"name": "reference_exact", "candidate_count": 1},
                        {"name": "semantic_metadata", "candidate_count": 1},
                    ]
                },
            },
            {"stage": "seed_fusion", "seed_candidates": 1},
            {"stage": "graph_expansion", "status": "ok", "expanded_candidates": 2},
            {"stage": "graph_hydration", "status": "ok", "unique_hydrated_chunks": 2},
            {"stage": "final_fusion", "fused_candidates": 3},
            {
                "stage": "hypothesis_verification",
                "status": "confirmed",
                "possible_reference_results": [
                    {"reference": "book:13:hadith:25", "status": "confirmed"}
                ],
            },
            {"stage": "context_assembly", "included_candidates": 3, "dropped_candidates": 0},
            {"stage": "grounding_validation", "status": "grounded", "cited_labels": ["S1"]},
        ],
        sources=[
            {
                "chunk_id": "chunk-25",
                "source_location": {"reference": "Book 13, Hadith 25"},
                "metadata": {"canonical_reference": "book:13:hadith:25"},
            }
        ],
        token_metadata={
            "answer_mode": "evidence_first",
            "llm_answer_status": "timeout",
            "fallback_reason": "llm_timeout",
        },
        query_config={"response_mode": "fast", "answer_budget_ms": 3000},
    )
    assert [row["stage"] for row in run] == [
        "planner",
        "llm_planning",
        "metadata_retrieval",
        "native_retrieval",
        "seed_fusion",
        "graph_expansion",
        "graph_hydration",
        "final_fusion",
        "hypothesis_verification",
        "context_assembly",
        "answer_generation",
        "grounding_validation",
    ]
    assert row_for(run, "llm_planning")["output"] == (
        "target_terms: offering, sacrifice, eid; possible_references: book:13:hadith:25"
    )
    assert row_for(run, "native_retrieval")["status"] == "warning"
    assert "metadata fallback" in row_for(run, "native_retrieval")["diagnosis"]
    assert row_for(run, "answer_generation")["budget_ms"] == 3000
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
.venv/bin/pytest backend/tests/test_query_pathway_diagnostics_service.py -q
```

Expected: fail because the service and schema do not exist.

- [ ] **Step 3: Implement model and service**

Add a Pydantic model:

```python
class PathwayDiagnosticOut(StudioModel):
    stage: str
    label: str
    input: str = "not recorded"
    action: str = "not recorded"
    output: str = "not recorded"
    status: Literal["success", "warning", "failed", "skipped", "unknown"] = "unknown"
    time_ms: float | None = None
    budget_ms: int | None = None
    diagnosis: str = "not recorded"
    suggested_action: str = "None"
```

Add `pathway_diagnostics: list[PathwayDiagnosticOut] = Field(default_factory=list)` to `RunOut`.

The service should expose:

```python
class QueryPathwayDiagnosticsService:
    def build(
        self,
        *,
        status: str,
        error: str | None,
        error_type: str | None,
        timings: dict[str, Any],
        chunk_traces: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        token_metadata: dict[str, Any],
        query_config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            {
                "stage": "planner",
                "label": "Planner",
                "input": "query + selected documents",
                "action": "Build retrieval plan and pathway stages",
                "output": "strategy and candidate limit",
                "status": "success",
                "time_ms": 0.0,
                "budget_ms": None,
                "diagnosis": "Healthy.",
                "suggested_action": "None",
            }
        ]
```

- [ ] **Step 4: Run backend diagnostics tests**

Run:

```bash
.venv/bin/pytest backend/tests/test_query_pathway_diagnostics_service.py -q
```

Expected: all tests pass.

## Task 2: Wire Diagnostics Into RunOut

**Files:**
- Modify: `backend/src/ragstudio/services/query_service.py`
- Test: `backend/tests/test_runtime_query_service.py` or new unit coverage in `backend/tests/test_query_pathway_diagnostics_service.py`

- [ ] **Step 1: Add failing serialization test**

Test that `_run_snapshot` or `_run_out` includes `pathway_diagnostics` without mutating persisted run fields.

```python
assert out["pathway_diagnostics"]
assert out["pathway_diagnostics"][0]["stage"] == "planner"
assert "pathway_diagnostics" not in out["token_metadata"]
```

- [ ] **Step 2: Implement serialization**

In `QueryService._run_out`, call `QueryPathwayDiagnosticsService().build` with
`status`, `error`, `error_type`, `timings`, `chunk_traces`, `sources`,
`token_metadata`, and `query_config`, then include the result in the output dict
as `pathway_diagnostics`.

- [ ] **Step 3: Run focused backend query tests**

Run:

```bash
.venv/bin/pytest backend/tests/test_query_pathway_diagnostics_service.py backend/tests/test_runtime_query_service.py::test_query_service_fast_mode_defaults_include_mandatory_planner_budget -q
```

Expected: pass.

## Task 3: Frontend Timeline Rendering

**Files:**
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/features/query/query-pathway-viewer.tsx`
- Test: `frontend/tests/query-page.test.tsx`

- [ ] **Step 1: Update frontend test**

Change the pathway test fixture to include `pathway_diagnostics` rows and assert:

```ts
expect(screen.getByText("Summary", { selector: "summary" })).toBeVisible();
expect(screen.getByText("Timeline", { selector: "summary" })).toBeVisible();
expect(screen.getByText("Raw", { selector: "summary" })).toBeVisible();
expect(screen.queryByText("Planner", { selector: "summary" })).not.toBeInTheDocument();
expect(screen.queryByText("Retrieval", { selector: "summary" })).not.toBeInTheDocument();
expect(screen.queryByText("Answer", { selector: "summary" })).not.toBeInTheDocument();
expect(screen.getByText("Input")).toBeVisible();
expect(screen.getByText("Action")).toBeVisible();
expect(screen.getByText("Output")).toBeVisible();
expect(screen.getByText("Diagnosis")).toBeVisible();
expect(screen.getByText("Suggested action")).toBeVisible();
```

- [ ] **Step 2: Update generated API type**

Add:

```ts
export interface PathwayDiagnosticOut {
  stage: string;
  label: string;
  input: string;
  action: string;
  output: string;
  status: "success" | "warning" | "failed" | "skipped" | "unknown";
  time_ms?: number | null;
  budget_ms?: number | null;
  diagnosis: string;
  suggested_action: string;
}
```

Add `pathway_diagnostics: PathwayDiagnosticOut[];` to `RunOut`.

- [ ] **Step 3: Simplify QueryPathwayViewer**

Render only:

- `Summary`
- `Timeline`
- `Raw`

Use `run.pathway_diagnostics` when present. Keep a fallback builder for old runs.

- [ ] **Step 4: Run frontend test**

Run:

```bash
npm test -- query-page.test.tsx
```

Expected: pass.

## Task 4: Verification and Commit

**Files:**
- Modify: `.planning/quick/260517-cy7-implement-query-pathway-performance-diag/260517-cy7-PLAN.md`

- [ ] **Step 1: Run backend focused suite**

Run:

```bash
.venv/bin/pytest backend/tests/test_query_pathway_diagnostics_service.py backend/tests/test_runtime_query_service.py::test_query_service_fast_mode_defaults_include_mandatory_planner_budget -q
```

Expected: pass.

- [ ] **Step 2: Run backend lint**

Run:

```bash
.venv/bin/ruff check backend/src/ragstudio/services/query_pathway_diagnostics_service.py backend/src/ragstudio/services/query_service.py backend/src/ragstudio/schemas/runs.py backend/tests/test_query_pathway_diagnostics_service.py
```

Expected: pass.

- [ ] **Step 3: Run frontend checks**

Run:

```bash
cd frontend
npm test -- query-page.test.tsx
npm run lint
npm run build
```

Expected: tests/lint/build pass. The existing Vite large-chunk warning is acceptable.

- [ ] **Step 4: Commit**

Run:

```bash
git add backend/src/ragstudio/services/query_pathway_diagnostics_service.py backend/src/ragstudio/schemas/runs.py backend/src/ragstudio/services/query_service.py backend/tests/test_query_pathway_diagnostics_service.py frontend/src/api/generated.ts frontend/src/features/query/query-pathway-viewer.tsx frontend/tests/query-page.test.tsx .planning/quick/260517-cy7-implement-query-pathway-performance-diag/260517-cy7-PLAN.md docs/superpowers/plans/2026-05-17-query-pathway-performance-diagnostics.md
git commit -m "Implement query pathway performance diagnostics"
```
