# Query Evidence Visual Reinspection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let operators inspect retrieved evidence visually by rendering source page boxes from query results instead of showing `page` and `bbox` only as text.

**Architecture:** Keep canonical chunk evidence and source locations as the source of truth. Add a small frontend-only normalizer for page geometry, then render a reusable page-space overlay inside the existing query evidence drawer when `source_location` contains a page plus valid bbox; otherwise keep the existing raw source-location fallback visible.

**Tech Stack:** TypeScript, React, Tailwind CSS v4, Vitest, Testing Library, existing Query/Evidence components, existing FastAPI query payloads.

---

## Scope Check

This is a UI observability project. It does not change retrieval, ranking, chunk persistence, proof packet validation, or document parsing.

The current frontend already opens an evidence drawer from `frontend/src/features/query/query-page.tsx` and displays source locations in `frontend/src/features/evidence/evidence-viewer.tsx`. The missing operator value is page-space reinspection: a visual box when source metadata includes page and bbox, with the existing raw `Source location` section remaining visible when metadata cannot be normalized.

## File Structure

- Create `frontend/src/features/evidence/source-location.ts`
  - Normalize permissive `source_location` records into `{ page, bbox, pageWidth, pageHeight, label }`.
- Create `frontend/src/features/evidence/evidence-page-overlay.tsx`
  - Render a stable page frame and a single retrieved bounding box with keyboard-visible labels.
- Modify `frontend/src/features/evidence/evidence-viewer.tsx`
  - Add a "Visual source" section above raw source-location key/value rows when page and bbox metadata are present.
- Modify `frontend/src/features/query/query-page.tsx`
  - No behavioral change expected; verify `normalizeQuerySource()` already preserves `source_location` records.
- Add `frontend/tests/evidence-page-overlay.test.tsx`
  - Cover bbox normalization, scaled overlay placement, missing bbox fallback, and accessible labels.
- Modify `frontend/tests/query-page.test.tsx`
  - Prove query evidence with bbox opens an evidence drawer containing a visual overlay.
- Modify `frontend/tests/chunk-inspector.test.tsx`
  - Prove the shared `EvidenceViewer` change does not break chunk inspector evidence details.
- Modify `docs/user-guide.md`
  - Document that query evidence can be reinspected visually when page and bbox metadata are present.

---

### Task 1: Normalize Query Source Locations

**Files:**
- Create: `frontend/src/features/evidence/source-location.ts`
- Test: `frontend/tests/evidence-page-overlay.test.tsx`

- [ ] **Step 1: Write the failing normalization tests**

Create `frontend/tests/evidence-page-overlay.test.tsx` with these initial tests:

```tsx
import { describe, expect, it } from "vitest";
import "@testing-library/jest-dom/vitest";
import { normalizeSourceLocation } from "../src/features/evidence/source-location";

describe("normalizeSourceLocation", () => {
  it("extracts page and bbox from query source metadata", () => {
    expect(
      normalizeSourceLocation({
        page: 2,
        bbox: [10, 20, 200, 80],
        page_width: 600,
        page_height: 800,
        label: "source.pdf - page 2",
      }),
    ).toEqual({
      page: 2,
      bbox: [10, 20, 200, 80],
      pageWidth: 600,
      pageHeight: 800,
      label: "source.pdf - page 2",
    });
  });

  it("falls back to page_start and default page dimensions", () => {
    expect(
      normalizeSourceLocation({
        page_start: 4,
        bbox: [12, 30, 220, 120],
      }),
    ).toEqual({
      page: 4,
      bbox: [12, 30, 220, 120],
      pageWidth: 612,
      pageHeight: 792,
      label: "page 4",
    });
  });

  it("returns null when page or bbox is missing", () => {
    expect(normalizeSourceLocation({ page: 1 })).toBeNull();
    expect(normalizeSourceLocation({ bbox: [1, 2, 3, 4] })).toBeNull();
  });
});
```

- [ ] **Step 2: Run the test and verify it fails**

Run from `frontend/`:

```bash
npm test -- evidence-page-overlay.test.tsx
```

Expected: FAIL because `source-location.ts` does not exist.

- [ ] **Step 3: Implement the normalizer**

Create `frontend/src/features/evidence/source-location.ts`:

```ts
export interface VisualSourceLocation {
  page: number;
  bbox: [number, number, number, number];
  pageWidth: number;
  pageHeight: number;
  label: string;
}

const defaultPageWidth = 612;
const defaultPageHeight = 792;

export function normalizeSourceLocation(value: unknown): VisualSourceLocation | null {
  if (!isRecord(value)) {
    return null;
  }
  const page = numberValue(value.page) ?? numberValue(value.page_start) ?? numberValue(value.page_number);
  const bbox = bboxValue(value.bbox);
  if (page == null || bbox == null) {
    return null;
  }
  const pageWidth = numberValue(value.page_width) ?? numberValue(value.width) ?? defaultPageWidth;
  const pageHeight = numberValue(value.page_height) ?? numberValue(value.height) ?? defaultPageHeight;
  const label = stringValue(value.label) ?? `page ${page}`;
  return { page, bbox, pageWidth, pageHeight, label };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function bboxValue(value: unknown): [number, number, number, number] | null {
  if (!Array.isArray(value) || value.length !== 4) {
    return null;
  }
  const numbers = value.map(numberValue);
  if (numbers.some((item) => item == null)) {
    return null;
  }
  const [x1, y1, x2, y2] = numbers as [number, number, number, number];
  return x2 > x1 && y2 > y1 ? [x1, y1, x2, y2] : null;
}
```

- [ ] **Step 4: Run the normalization tests**

Run from `frontend/`:

```bash
npm test -- evidence-page-overlay.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit the normalizer**

```bash
git add frontend/src/features/evidence/source-location.ts frontend/tests/evidence-page-overlay.test.tsx
git commit -m "feat: normalize visual source locations"
```

---

### Task 2: Render Page-Space Evidence Boxes

**Files:**
- Create: `frontend/src/features/evidence/evidence-page-overlay.tsx`
- Modify: `frontend/tests/evidence-page-overlay.test.tsx`

- [ ] **Step 1: Add failing overlay render tests**

Add these imports at the top of `frontend/tests/evidence-page-overlay.test.tsx` next to the existing imports:

```tsx
import { render, screen } from "@testing-library/react";
import { EvidencePageOverlay } from "../src/features/evidence/evidence-page-overlay";
```

Then append this test:

```tsx

it("renders a scaled source box with an accessible label", () => {
  render(
    <EvidencePageOverlay
      source={{
        page: 2,
        bbox: [10, 20, 210, 120],
        pageWidth: 600,
        pageHeight: 800,
        label: "source.pdf - page 2",
      }}
    />,
  );

  expect(screen.getByRole("img", { name: "Visual source location for source.pdf - page 2" })).toBeVisible();
  expect(screen.getByText("page 2")).toBeVisible();
  expect(screen.getByLabelText("Retrieved evidence bounding box")).toHaveStyle({
    left: "1.6667%",
    top: "2.5%",
    width: "33.3333%",
    height: "12.5%",
  });
});
```

- [ ] **Step 2: Run the overlay test and verify it fails**

Run from `frontend/`:

```bash
npm test -- evidence-page-overlay.test.tsx
```

Expected: FAIL because `EvidencePageOverlay` does not exist.

- [ ] **Step 3: Implement the overlay component**

Create `frontend/src/features/evidence/evidence-page-overlay.tsx`:

```tsx
import type { VisualSourceLocation } from "./source-location";

interface EvidencePageOverlayProps {
  source: VisualSourceLocation;
}

export function EvidencePageOverlay({ source }: EvidencePageOverlayProps) {
  const [x1, y1, x2, y2] = source.bbox;
  const left = pct(x1, source.pageWidth);
  const top = pct(y1, source.pageHeight);
  const width = pct(x2 - x1, source.pageWidth);
  const height = pct(y2 - y1, source.pageHeight);

  return (
    <div
      role="img"
      aria-label={`Visual source location for ${source.label}`}
      className="rounded-md border border-[#d9e4e8] bg-[#f8fbfc] p-3"
    >
      <div className="mb-2 flex items-center justify-between text-xs text-[#62717a]">
        <span>{source.label}</span>
        <span>page {source.page}</span>
      </div>
      <div
        className="relative mx-auto aspect-[612/792] w-full max-w-[360px] overflow-hidden rounded-sm border border-[#bfd3dc] bg-white shadow-inner"
        style={{ aspectRatio: `${source.pageWidth} / ${source.pageHeight}` }}
      >
        <div className="absolute inset-0 bg-[linear-gradient(#eef4f6_1px,transparent_1px),linear-gradient(90deg,#eef4f6_1px,transparent_1px)] bg-[size:24px_24px]" />
        <div
          aria-label="Retrieved evidence bounding box"
          className="absolute border-2 border-[#176b87] bg-[#176b87]/20 shadow-[0_0_0_9999px_rgba(255,255,255,0.46)]"
          style={{ left, top, width, height }}
        />
      </div>
    </div>
  );
}

function pct(value: number, total: number) {
  return `${Number(((value / total) * 100).toFixed(4))}%`;
}
```

- [ ] **Step 4: Run the overlay test**

Run from `frontend/`:

```bash
npm test -- evidence-page-overlay.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit the overlay**

```bash
git add frontend/src/features/evidence/evidence-page-overlay.tsx frontend/tests/evidence-page-overlay.test.tsx
git commit -m "feat: render evidence bbox overlays"
```

---

### Task 3: Add Visual Source Section To Evidence Drawer

**Files:**
- Modify: `frontend/src/features/evidence/evidence-viewer.tsx`
- Modify: `frontend/tests/query-page.test.tsx`
- Modify: `frontend/tests/chunk-inspector.test.tsx`

- [ ] **Step 1: Add a failing query drawer test**

In `frontend/tests/query-page.test.tsx`, add a query source fixture to an existing "Evidence details" test with:

```ts
source_location: {
  label: "source.pdf - page 2",
  page: 2,
  bbox: [10, 20, 210, 120],
  page_width: 600,
  page_height: 800,
},
```

Then assert after opening "Evidence details":

```ts
expect(screen.getByRole("img", { name: "Visual source location for source.pdf - page 2" })).toBeVisible();
expect(screen.getByLabelText("Retrieved evidence bounding box")).toBeVisible();
```

Also add a second assertion in a source-location-only fixture without `bbox`:

```ts
expect(screen.queryByRole("img", { name: /Visual source location/ })).not.toBeInTheDocument();
expect(screen.getByText(/Source location/)).toBeVisible();
```

In `frontend/tests/chunk-inspector.test.tsx`, add or update a chunk details fixture with:

```ts
source_location: {
  label: "chunk-source.pdf - page 5",
  page: 5,
  bbox: [24, 40, 240, 160],
  page_width: 612,
  page_height: 792,
},
```

Then open the chunk evidence details and assert:

```ts
expect(screen.getByRole("img", { name: "Visual source location for chunk-source.pdf - page 5" })).toBeVisible();
expect(screen.getByText(/Source location/)).toBeVisible();
```

This keeps the shared `EvidenceViewer` behavior covered for both query results and chunk inspection.

- [ ] **Step 2: Run the focused query UI test and verify it fails**

Run from `frontend/`:

```bash
npm test -- query-page.test.tsx
```

Expected: FAIL because the evidence drawer does not render the visual overlay.

- [ ] **Step 3: Render the visual section**

Modify `frontend/src/features/evidence/evidence-viewer.tsx`:

```tsx
import { EvidencePageOverlay } from "./evidence-page-overlay";
import { normalizeSourceLocation } from "./source-location";
```

Inside `EvidenceViewer()`, after `const isOpen = open && evidence !== null;`:

```tsx
const visualSource = evidence ? normalizeSourceLocation(evidence.sourceLocation) : null;
```

Then render this before the existing "Source location" section:

```tsx
{visualSource ? (
  <EvidenceSection title="Visual source" defaultOpen>
    <EvidencePageOverlay source={visualSource} />
  </EvidenceSection>
) : null}
```

- [ ] **Step 4: Run query and overlay tests**

Run from `frontend/`:

```bash
npm test -- evidence-page-overlay.test.tsx query-page.test.tsx chunk-inspector.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Run frontend build**

Run from `frontend/`:

```bash
npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit the drawer integration**

```bash
git add frontend/src/features/evidence/evidence-viewer.tsx frontend/tests/query-page.test.tsx
git commit -m "feat: show visual query evidence overlays"
```

---

### Task 4: Document The Operator Workflow

**Files:**
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Add the user-guide note**

Add this paragraph to the query workflow section in `docs/user-guide.md`:

```markdown
When query evidence includes page and bounding-box metadata, open **Evidence details** and use **Visual source** to inspect the retrieved region in page coordinates. The visual overlay is an operator aid over canonical source metadata; when source metadata cannot be normalized into page plus bbox, Ragstudio still shows the raw source-location fields and trace details.
```

- [ ] **Step 2: Review the documentation diff**

Run:

```bash
git diff -- docs/user-guide.md
```

Expected: the new note is scoped to query evidence reinspection.

- [ ] **Step 3: Commit the docs**

```bash
git add docs/user-guide.md
git commit -m "docs: describe query evidence visual reinspection"
```
