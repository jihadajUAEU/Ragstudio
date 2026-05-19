# Positive Recovery Warnings And Evidence Highlights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show `recovered_text_from_disallowed_block` as a positive parser recovery/audit signal and highlight the recovered text in document parse evidence.

**Architecture:** Keep warning severity semantics intact in the backend: suppressed `info` warnings remain audit rows and counted warnings remain quality issues. Add a small frontend classification helper so warning details and parse evidence render accepted recovery rows with success styling, clearer copy, and source-block highlighting without changing indexing policy.

**Tech Stack:** React, TypeScript, TanStack Query data already loaded through `apiClient.jobQualityWarnings`, existing `EvidenceInspector`, Vitest, Testing Library, Tailwind design tokens in `frontend/src/lib/design-tokens.ts`.

---

## File Structure

- Modify `frontend/src/features/documents/documents-page.tsx`
  - Add a local warning presentation helper for `accepted_recovery` / `suppressed_from_counts`.
  - Render these rows as positive "Recovered text" audit signals in warning details.
  - Keep counted warning chips unchanged for real parser quality warnings.
- Modify `frontend/src/features/document-evidence/evidence-inspector.tsx`
  - Add warning classification helpers.
  - Render accepted recovery warnings with success styling in the decision summary.
  - Highlight source blocks whose `warning_ids` include accepted recovery warnings.
  - Add a compact "Recovered text" badge and recovery note on highlighted parser blocks.
- Modify `frontend/src/features/document-evidence/types.ts`
  - Add optional warning metadata fields needed by the UI: `quality_gate_action`, `suppressed_from_counts`, and `block_type`.
- Modify `backend/src/ragstudio/schemas/document_parse_evidence.py`
  - Add matching optional fields to `WarningEvidence`.
- Modify `backend/src/ragstudio/services/document_parse_evidence_service.py`
  - Populate those fields from the persisted parser warning payload.
- Modify `frontend/tests/documents-page.test.tsx`
  - Update the audit-row test to assert positive recovery language/styling.
- Modify `frontend/tests/document-evidence-inspector.test.tsx`
  - Add coverage that accepted recovery warning rows highlight the recovered parser block.

## Task 1: Label Accepted Recovery Rows As Positive In Warning Details

**Files:**
- Modify: `frontend/src/features/documents/documents-page.tsx`
- Test: `frontend/tests/documents-page.test.tsx`

- [ ] **Step 1: Write the failing warning-details test**

Add assertions to the existing audit-only warning details test near `quality_gate_action: "accepted_recovery"`:

```tsx
expect(await screen.findByText("No counted parser warnings.")).toBeVisible();
expect(screen.getByText("Recovered text")).toBeVisible();
expect(screen.getByText("Accepted recovery")).toBeVisible();
expect(screen.getByText("This row is audit evidence, not a counted parser warning.")).toBeVisible();
expect(screen.getByText("Audit-only recovered parser text.")).toBeVisible();
```

- [ ] **Step 2: Run the focused failing test**

Run from `frontend/`:

```powershell
npm test -- --run tests/documents-page.test.tsx -t "shows suppressed parser recovery rows without counting them"
```

Expected: FAIL because the UI currently renders the row as a normal warning row and does not show `Recovered text`, `Accepted recovery`, or the audit explanation.

- [ ] **Step 3: Add a local warning presentation helper**

In `frontend/src/features/documents/documents-page.tsx`, add this helper near `WarningMetadataCell` helpers:

```tsx
function isAcceptedRecoveryWarning(item: ParserQualityWarningOut) {
  return (
    item.code === "recovered_text_from_disallowed_block" ||
    item.warning?.quality_gate_action === "accepted_recovery" ||
    item.warning?.suppressed_from_counts === true
  );
}

function warningDisplayLabel(item: ParserQualityWarningOut) {
  return isAcceptedRecoveryWarning(item) ? "Recovered text" : item.code;
}

function warningDisplayTone(item: ParserQualityWarningOut) {
  return isAcceptedRecoveryWarning(item)
    ? {
        label: "Accepted recovery",
        className: "border-[#5ca66b] bg-[#ecf8ee] text-[#235c2f]",
        note: "This row is audit evidence, not a counted parser warning.",
      }
    : {
        label: "Parser warning",
        className: "border-[#e2c46b] bg-[#fff8df] text-[#705000]",
        note: "",
      };
}
```

If TypeScript reports that `warning.quality_gate_action` or `warning.suppressed_from_counts` is not typed, use the existing generated API type shape through a narrow local read:

```tsx
const warningRecord = item.warning as Record<string, unknown> | null | undefined;
```

Then read `warningRecord?.quality_gate_action` and `warningRecord?.suppressed_from_counts`.

- [ ] **Step 4: Render positive recovery labels in the warning table**

Find the warning detail table column that renders `code` / message. Replace the visible code label with `warningDisplayLabel(item)` and add the tone badge:

```tsx
const tone = warningDisplayTone(item);

return (
  <div className="min-w-0 space-y-1">
    <div className="flex flex-wrap items-center gap-2">
      <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${tone.className}`}>
        {warningDisplayLabel(item)}
      </span>
      <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${tone.className}`}>
        {tone.label}
      </span>
    </div>
    <p className="break-words text-sm text-[#1f2933]">{item.message}</p>
    {tone.note ? <p className="text-xs text-[#235c2f]">{tone.note}</p> : null}
  </div>
);
```

Keep the filter values based on raw `item.code`, so searching/filtering still works for `recovered_text_from_disallowed_block`.

- [ ] **Step 5: Run the focused test and commit**

Run:

```powershell
npm test -- --run tests/documents-page.test.tsx -t "shows suppressed parser recovery rows without counting them"
```

Expected: PASS.

Commit:

```powershell
git add frontend/src/features/documents/documents-page.tsx frontend/tests/documents-page.test.tsx
git commit -m "feat: show parser recoveries as positive audit rows"
```

## Task 2: Carry Recovery Metadata Into Document Parse Evidence

**Files:**
- Modify: `backend/src/ragstudio/schemas/document_parse_evidence.py`
- Modify: `backend/src/ragstudio/services/document_parse_evidence_service.py`
- Modify: `frontend/src/features/document-evidence/types.ts`

- [ ] **Step 1: Write the backend schema fields**

In `backend/src/ragstudio/schemas/document_parse_evidence.py`, extend `WarningEvidence`:

```python
class WarningEvidence(StudioModel):
    id: str
    code: str
    message: str
    severity: str = "warning"
    page: int | None = None
    block_id: str | None = None
    block_type: str | None = None
    quality_gate_action: str | None = None
    suppressed_from_counts: bool = False
    decision_id: str | None = None
    affected_chunk_ids: list[str] = Field(default_factory=list)
```

- [ ] **Step 2: Populate the fields from parser warning payloads**

In `backend/src/ragstudio/services/document_parse_evidence_service.py`, inside the warning-building loop where `WarningEvidence(...)` is created, add:

```python
warning_payload = self._dict_value(item.get("warning"))
quality_gate_action = self._coerce_string(
    warning_payload.get("quality_gate_action") or item.get("quality_gate_action")
)
suppressed_from_counts = bool(
    warning_payload.get("suppressed_from_counts") or item.get("suppressed_from_counts")
)
block_type = self._coerce_string(
    item.get("block_type") or warning_payload.get("block_type")
)
```

Then pass these into `WarningEvidence`:

```python
block_type=block_type,
quality_gate_action=quality_gate_action,
suppressed_from_counts=suppressed_from_counts,
```

- [ ] **Step 3: Update frontend evidence types**

In `frontend/src/features/document-evidence/types.ts`, extend `WarningEvidence`:

```ts
export interface WarningEvidence {
  id: string;
  code: string;
  message: string;
  severity: string;
  page?: number | null;
  block_id?: string | null;
  block_type?: string | null;
  quality_gate_action?: string | null;
  suppressed_from_counts?: boolean;
  decision_id?: string | null;
  affected_chunk_ids: string[];
}
```

- [ ] **Step 4: Run backend compile and frontend type check**

Run:

```powershell
python -m py_compile backend/src/ragstudio/schemas/document_parse_evidence.py backend/src/ragstudio/services/document_parse_evidence_service.py
```

Expected: no output.

Run from `frontend/`:

```powershell
npm run typecheck
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/ragstudio/schemas/document_parse_evidence.py backend/src/ragstudio/services/document_parse_evidence_service.py frontend/src/features/document-evidence/types.ts
git commit -m "feat: expose parser recovery metadata in evidence"
```

## Task 3: Highlight Recovered Text In Document Parse Evidence

**Files:**
- Modify: `frontend/src/features/document-evidence/evidence-inspector.tsx`
- Test: `frontend/tests/document-evidence-inspector.test.tsx`

- [ ] **Step 1: Write the failing parse-evidence test**

Add a test to `frontend/tests/document-evidence-inspector.test.tsx`:

```tsx
it("highlights accepted recovered text in source blocks", () => {
  render(
    <EvidenceInspector
      evidence={{
        ...evidence,
        parser_blocks: [
          {
            id: "block-recovered",
            page: 7,
            block_index: 3,
            block_type: "header",
            text_preview: "Recovered Arabic header text kept with provenance.",
            warning_ids: ["warning-recovered"],
          },
        ],
        normalization_decisions: [
          {
            id: "decision-recovered",
            decision_type: "quality_warning",
            title: "Recovered parser text",
            summary: "Recovered text was accepted as audit evidence.",
            input_block_ids: ["block-recovered"],
            output_chunk_ids: [],
            warning_ids: ["warning-recovered"],
            status: "recorded",
          },
        ],
        chunks: [],
        warnings: [
          {
            id: "warning-recovered",
            code: "recovered_text_from_disallowed_block",
            message: "Used parser-provided recovered text for a disallowed block type.",
            severity: "info",
            page: 7,
            block_id: "block-recovered",
            block_type: "header",
            quality_gate_action: "accepted_recovery",
            suppressed_from_counts: true,
            affected_chunk_ids: [],
          },
        ],
      }}
    />,
  );

  const sourceBlocks = screen.getByRole("region", { name: "Source blocks" });
  expect(within(sourceBlocks).getByText("Recovered text")).toBeVisible();
  expect(within(sourceBlocks).getByText("Accepted recovery from header")).toBeVisible();
  expect(within(sourceBlocks).getByText("Recovered Arabic header text kept with provenance.")).toBeVisible();
});
```

- [ ] **Step 2: Run the focused failing test**

Run from `frontend/`:

```powershell
npm test -- --run tests/document-evidence-inspector.test.tsx -t "highlights accepted recovered text"
```

Expected: FAIL because `EvidenceInspector` does not classify or highlight accepted recovery warnings yet.

- [ ] **Step 3: Add evidence warning helpers**

In `frontend/src/features/document-evidence/evidence-inspector.tsx`, add helpers near `orderByIds`:

```tsx
function isAcceptedRecoveryWarning(warning?: WarningEvidence | null) {
  return Boolean(
    warning &&
      (warning.code === "recovered_text_from_disallowed_block" ||
        warning.quality_gate_action === "accepted_recovery" ||
        warning.suppressed_from_counts),
  );
}

function recoveryLabel(warning?: WarningEvidence | null) {
  const blockType = warning?.block_type ? ` from ${titleCase(warning.block_type)}` : "";
  return `Accepted recovery${blockType}`;
}
```

- [ ] **Step 4: Pass warnings into source block cards**

In `EvidenceInspector`, create a map:

```tsx
const warningsById = new Map(evidence.warnings.map((warning) => [warning.id, warning]));
```

Change the `BlockCard` render:

```tsx
<BlockCard key={block.id} block={block} warningsById={warningsById} />
```

Change the component signature:

```tsx
function BlockCard({
  block,
  warningsById,
}: {
  block: ParserBlockEvidence;
  warningsById: Map<string, WarningEvidence>;
}) {
  const recoveryWarning = block.warning_ids.map((id) => warningsById.get(id)).find(isAcceptedRecoveryWarning);
  const isRecovered = Boolean(recoveryWarning);

  return (
    <article
      className={cn(
        "rounded-md border p-3",
        isRecovered ? cn(rs.border.success, rs.bg.successSoft) : cn(rs.border.line, rs.bg.field),
      )}
    >
      <div className="flex flex-wrap gap-2 text-xs font-semibold">
        <span className={rs.text.muted}>{titleCase(block.block_type)}</span>
        <span className={rs.text.muted}>page {block.page ?? "?"}</span>
        <span className={rs.text.muted}>block {block.block_index ?? "?"}</span>
        {block.modality ? <span className={rs.text.accent}>mode {block.modality}</span> : null}
        {isRecovered ? (
          <>
            <span className={cn("rounded-md border px-2 py-0.5", rs.border.success, rs.bg.paper, rs.text.success)}>
              Recovered text
            </span>
            <span className={rs.text.success}>{recoveryLabel(recoveryWarning)}</span>
          </>
        ) : null}
      </div>
      <p className={cn("mt-2 whitespace-pre-wrap text-sm leading-6", rs.text.body)}>{block.text_preview}</p>
    </article>
  );
}
```

- [ ] **Step 5: Render accepted recovery warnings positively in the decision summary**

In `DecisionSummary`, replace the current warning card class selection with:

```tsx
const recovery = isAcceptedRecoveryWarning(warning);
```

Then render:

```tsx
<div
  key={warning.id}
  className={cn(
    "rounded-md border px-3 py-2 text-sm",
    recovery ? cn(rs.border.success, rs.bg.successSoft) : cn(rs.border.warning, rs.bg.warningSoft),
  )}
>
  <p className={cn("font-semibold", recovery ? rs.text.success : rs.text.warning)}>
    {recovery ? "Recovered text" : warning.code}
  </p>
  <p className={cn("mt-1", rs.text.body)}>{warning.message}</p>
  {recovery ? (
    <p className={cn("mt-1 text-xs font-semibold", rs.text.success)}>
      {recoveryLabel(warning)}. Audit evidence only; not a counted parser warning.
    </p>
  ) : null}
</div>
```

- [ ] **Step 6: Run the focused test and commit**

Run:

```powershell
npm test -- --run tests/document-evidence-inspector.test.tsx -t "highlights accepted recovered text"
```

Expected: PASS.

Commit:

```powershell
git add frontend/src/features/document-evidence/evidence-inspector.tsx frontend/tests/document-evidence-inspector.test.tsx
git commit -m "feat: highlight recovered parse evidence"
```

## Task 4: Regression Sweep And Manual Check

**Files:**
- Verify: `frontend/tests/documents-page.test.tsx`
- Verify: `frontend/tests/document-evidence-inspector.test.tsx`
- Verify: local UI at `http://127.0.0.1:5173`

- [ ] **Step 1: Run focused frontend tests**

Run from `frontend/`:

```powershell
npm test -- --run tests/documents-page.test.tsx tests/document-evidence-inspector.test.tsx
```

Expected: PASS.

- [ ] **Step 2: Run type check**

Run from `frontend/`:

```powershell
npm run typecheck
```

Expected: PASS.

- [ ] **Step 3: Manually verify Ibn Majah warning details**

Open the local app and inspect the completed Ibn Majah job.

Expected:
- Counted chip still shows `reference_unit_missing_expected_script=40`.
- `recovered_text_from_disallowed_block` rows display as `Recovered text` / `Accepted recovery`.
- The UI says those rows are audit evidence and not counted parser warnings.
- `display_rows` can still include the recovery rows.

- [ ] **Step 4: Manually verify document parse evidence**

Open parse evidence for the Ibn Majah document.

Expected:
- Parser blocks with accepted recovery warnings have a success-tinted highlight.
- The recovered text itself remains visible in the block preview.
- The block shows `Recovered text` and `Accepted recovery from Header` / `Footer` / `Page footnote` as applicable.
- Real missing-script warnings still use warning styling.

- [ ] **Step 5: Commit final verification notes if any test fixture changes were needed**

If no fixture updates were needed, skip this commit. If snapshots or fixtures were intentionally updated:

```powershell
git add frontend/tests
git commit -m "test: cover positive parser recovery display"
```

## Self-Review

Spec coverage:
- Positive warning display is covered by Task 1.
- Highlight recovered text in document parse evidence is covered by Tasks 2 and 3.
- Genuine counted warnings remain unchanged by design and are manually checked in Task 4.

Placeholder scan:
- No `TBD`, `TODO`, or deferred implementation steps remain.

Type consistency:
- `quality_gate_action`, `suppressed_from_counts`, and `block_type` are added consistently to backend schema, backend service population, frontend type, and UI helpers.

