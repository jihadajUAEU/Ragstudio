# Jobs and Warnings Tab Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved Jobs & Warnings tab design as a dense operational queue with metrics, filters, auto-refresh controls, a redesigned jobs table, and a selected-job warning inspector.

**Architecture:** Keep the behavior inside `DocumentsPage` because the existing documents/jobs workflow is already co-located there. Add small local helper components for the job metrics, warning-only toggle, redesigned job table cells, and warning inspector sections rather than introducing a new global table abstraction. Continue to use the shared `DataTable` pagination footer added earlier.

**Tech Stack:** React, TypeScript, TanStack Query, TanStack Table through `DataTable`, Tailwind CSS v4 utilities, local `Button`, `StatusBadge`, `EmptyState`, and lucide-react icons.

---

### Task 1: Plan and Test Surface

**Files:**
- Create: `.planning/quick/260522-qdf-implement-jobs-and-warnings-tab-redesign/260522-qdf-PLAN.md`
- Modify: `frontend/tests/documents-page.test.tsx`
- Modify: `frontend/src/features/documents/documents-page.tsx`

- [x] **Step 1: Save the GSD quick plan**

Create `.planning/quick/260522-qdf-implement-jobs-and-warnings-tab-redesign/260522-qdf-PLAN.md` with the scope, implementation tasks, and verification commands.

- [x] **Step 2: Add focused tests for the new Jobs tab surface**

Append or update tests in `frontend/tests/documents-page.test.tsx` to verify:

```tsx
expect(screen.getByText("Total Jobs")).toBeVisible();
expect(screen.getByText("Running")).toBeVisible();
expect(screen.getByText("Succeeded")).toBeVisible();
expect(screen.getByText("Failed")).toBeVisible();
expect(screen.getByText("Warning Jobs")).toBeVisible();
expect(screen.getByLabelText("Warning only")).toBeVisible();
expect(screen.getByText("Auto refresh")).toBeVisible();
```

- [x] **Step 3: Run the test to confirm it fails before implementation**

Run: `npx.cmd vitest run tests/documents-page.test.tsx`

Expected before implementation: FAIL because the redesigned Jobs tab labels are missing.

### Task 2: Jobs Tab State and Filtering

**Files:**
- Modify: `frontend/src/features/documents/documents-page.tsx`

- [x] **Step 1: Add state**

Add state near the existing job filters:

```tsx
const [jobWarningOnly, setJobWarningOnly] = useState(false);
const [jobsAutoRefresh, setJobsAutoRefresh] = useState(true);
const [jobsRefreshIntervalMs, setJobsRefreshIntervalMs] = useState(10_000);
```

- [x] **Step 2: Update query refetch interval**

Change `jobsQuery` refetch behavior to use auto-refresh or active job polling:

```tsx
refetchInterval: (query) => {
  const hasActive = hasActiveJobs(query.state.data?.items ?? []);
  return jobsAutoRefresh || hasActive ? jobsRefreshIntervalMs : false;
},
```

- [x] **Step 3: Extend filtering**

Change `filterJobs` signature and call site to accept `warningOnly`, and filter to warning-capable jobs when enabled:

```tsx
const filteredJobs = useMemo(
  () => filterJobs(jobs, documentsById, jobSearch, jobStatusFilter, jobWarningOnly, liveJobEventsById),
  [documentsById, jobSearch, jobStatusFilter, jobWarningOnly, jobs, liveJobEventsById],
);
```

- [x] **Step 4: Reset page and selection when warning-only changes**

In the warning-only toggle handler, call:

```tsx
setJobWarningOnly(checked);
setJobsPage(1);
setSelectedWarningJobId(null);
```

### Task 3: Metrics and Filter Toolbar

**Files:**
- Modify: `frontend/src/features/documents/documents-page.tsx`

- [x] **Step 1: Add metrics computation**

Add values before render:

```tsx
const jobMetrics = useMemo(() => summarizeJobs(jobs), [jobs]);
```

Implement `summarizeJobs(jobs)` below existing helpers:

```tsx
function summarizeJobs(jobs: JobOut[]) {
  return {
    total: jobs.length,
    running: jobs.filter((job) => job.status === "running" || job.status === "ready").length,
    succeeded: jobs.filter((job) => job.status === "succeeded").length,
    failed: jobs.filter((job) => job.status === "failed").length,
    warnings: jobs.filter(hasInspectableQualityWarnings).length,
  };
}
```

- [x] **Step 2: Add `JobsMetricStrip`**

Create a local component rendering five compact metric cells: Total Jobs, Running, Succeeded, Failed, Warning Jobs.

- [x] **Step 3: Replace the generic jobs toolbar**

In the Jobs panel, render `JobsMetricStrip` and a new toolbar with:
- Search jobs input.
- Status select.
- Warning only toggle.
- Clear Filters button.
- Auto refresh toggle.
- Interval select: 5s, 10s, 30s.

### Task 4: Redesign the Jobs Table

**Files:**
- Modify: `frontend/src/features/documents/documents-page.tsx`

- [x] **Step 1: Replace job columns**

Change columns to match the approved design:
- Job
- Document
- Status
- Progress
- Stage (MinerU)
- Latest Log Preview
- Warnings
- Actions

- [x] **Step 2: Add selected row affordance**

Pass selected job state into the actions cell and row controls by using row button actions. Keep selection driven by `setSelectedWarningJobId(job.id)`.

- [x] **Step 3: Warning count cell**

Use a helper:

```tsx
function jobWarningCount(job: JobOut, liveEvent?: LiveJobEventSnapshot): number {
  return jobWarnings(job, liveEvent).length + jobParserQualityGroups(job).reduce((total, group) => total + group.warningCount, 0);
}
```

Show an amber warning icon and count for warning jobs, neutral `0` when none.

### Task 5: Redesign Selected Warning Inspector

**Files:**
- Modify: `frontend/src/features/documents/documents-page.tsx`

- [x] **Step 1: Update `QualityWarningsPanel` header**

Render selected job name, job id, and action buttons in a dense header.

- [x] **Step 2: Add job summary sidebar**

Show document name, status, progress, current stage, latest log, and warning count.

- [x] **Step 3: Add warning overview chips**

Render warning count chips from `details.warning_counts`, or fall back to parser quality groups.

- [x] **Step 4: Keep existing warning detail table**

Reuse current warning details table, search, filter, repair action, and repair plan behavior while restyling the container to match the approved screenshot.

### Task 6: Verification

**Files:**
- Modify: `.planning/quick/260522-qdf-implement-jobs-and-warnings-tab-redesign/260522-qdf-SUMMARY.md`
- Modify: `.planning/STATE.md`

- [x] **Step 1: Run tests**

Run: `npx.cmd vitest run tests/documents-page.test.tsx tests/data-table.test.tsx`

Expected: PASS.

- [x] **Step 2: Run lint**

Run: `npx.cmd eslint src/features/documents/documents-page.tsx tests/documents-page.test.tsx`

Expected: PASS.

- [x] **Step 3: Browser verify**

Open `http://localhost:5173/documents`, switch to Jobs & Warnings, confirm:
- Metrics strip is visible.
- Warning-only and auto-refresh controls are visible.
- Jobs table has the approved columns.
- Inspect warnings opens the redesigned selected-job panel.

- [x] **Step 4: Write GSD summary**

Create `.planning/quick/260522-qdf-implement-jobs-and-warnings-tab-redesign/260522-qdf-SUMMARY.md` with changed files and verification results.

---

## Self-Review

Spec coverage: The plan covers the screenshot's metrics row, filter toolbar, auto-refresh controls, jobs table anatomy, selected-job inspector, warning chips, repair action, and detail table.

Placeholder scan: No placeholders remain.

Type consistency: All referenced helpers use existing `JobOut`, `DocumentOut`, `LiveJobEventSnapshot`, and `JobQualityWarningsOut` shapes already present in `DocumentsPage`.
