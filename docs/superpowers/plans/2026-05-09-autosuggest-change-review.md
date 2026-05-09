# Autosuggest Change Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a compact review of every metadata field changed by Auto-suggest and highlight the changed fields in the Documents metadata form.

**Architecture:** Keep the feature local to `DomainMetadataPanel` because the parent page already supplies all required state and callbacks. Add small pure helpers in the same file to build and format a metadata change set, then render a review panel and field highlights from that state. Tests drive the behavior through the existing mocked `apiClient.suggestDomainMetadata` API.

**Tech Stack:** React, TypeScript, TanStack Query parent data flow, Vitest, Testing Library, Docker Compose frontend test runner.

---

## File Structure

- Modify: `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`
  - Add `MetadataChangeField` and `MetadataChange` types.
  - Add pure diff/format helpers at the bottom of the file.
  - Track `autosuggestChanges` state after successful suggestions.
  - Render the hybrid review panel above the metadata field grid.
  - Apply highlight attributes/classes to changed fields.
  - Clear each field's highlight when the user manually edits that field.
- Modify: `frontend/tests/domain-metadata-panel.test.tsx`
  - Extend existing autosuggest tests.
  - Add coverage for scalar, array, and Custom JSON changes.
  - Add coverage for manual clearing and failed autosuggest preservation.

No backend files are needed.

---

### Task 1: Add Autosuggest Review Tests

**Files:**
- Modify: `frontend/tests/domain-metadata-panel.test.tsx`

- [ ] **Step 1: Add failing test for scalar, array, and Custom JSON review output**

Append this test inside `describe("DomainMetadataPanel", () => { ... })`, before the final sample JSON test:

```tsx
  it("shows all autosuggested metadata changes and marks changed fields", async () => {
    mocks.suggestDomainMetadata.mockResolvedValueOnce({
      domain_metadata: {
        domain: "tafseer",
        document_type: "book",
        language: "mixed",
        collection: "Tafseer Ibn Kathir",
        tags: ["quran", "tafseer"],
        reference_pattern: "Surah N, Ayah N",
        metadata_sources: ["heuristic", "profile"],
        custom_json: {
          audience: "research",
          citation_style: "surah_ayah",
        },
      },
    });

    render(
      <DomainMetadataPanel
        profiles={[]}
        value={{
          parser_mode: "mineru_strict",
          domain_metadata: {
            domain: "generic",
            document_type: "document",
            language: "",
            collection: "",
            tags: ["quran"],
            metadata_sources: ["user"],
            custom_json: { audience: "general" },
          },
        }}
        onChange={vi.fn()}
        suggestContext={{ filename: "tafseer_ibn_kathir.pdf", content_type: "application/pdf" }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /auto-suggest/i }));

    expect(await screen.findByText("Auto-suggest updated metadata")).toBeVisible();
    expect(screen.getByText("8 fields changed")).toBeVisible();
    expect(screen.getByText("Domain")).toBeVisible();
    expect(screen.getByText("generic -> tafseer")).toBeVisible();
    expect(screen.getByText("Document type")).toBeVisible();
    expect(screen.getByText("document -> book")).toBeVisible();
    expect(screen.getByText("Language")).toBeVisible();
    expect(screen.getByText("empty -> mixed")).toBeVisible();
    expect(screen.getByText("Collection")).toBeVisible();
    expect(screen.getByText("empty -> Tafseer Ibn Kathir")).toBeVisible();
    expect(screen.getByText("Tags")).toBeVisible();
    expect(screen.getByText("added tafseer")).toBeVisible();
    expect(screen.getByText("Reference pattern")).toBeVisible();
    expect(screen.getByText("empty -> Surah N, Ayah N")).toBeVisible();
    expect(screen.getByText("Metadata sources")).toBeVisible();
    expect(screen.getByText("added heuristic, profile; removed user")).toBeVisible();
    expect(screen.getByText("Custom JSON")).toBeVisible();
    expect(screen.getByText("added citation_style; changed audience")).toBeVisible();

    expect(screen.getByLabelText("Domain").closest("[data-autosuggest-changed]")).toHaveAttribute(
      "data-autosuggest-changed",
      "true",
    );
    expect(
      screen.getByLabelText("Document type").closest("[data-autosuggest-changed]"),
    ).toHaveAttribute("data-autosuggest-changed", "true");
    expect(
      screen.getByLabelText("Custom JSON").closest("[data-autosuggest-changed]"),
    ).toHaveAttribute("data-autosuggest-changed", "true");
  });
```

- [ ] **Step 2: Add failing test for clearing a changed scalar field after manual edit**

Append this test after the test from Step 1:

```tsx
  it("clears a changed field from the autosuggest review after manual edit", async () => {
    mocks.suggestDomainMetadata.mockResolvedValueOnce({
      domain_metadata: {
        domain: "policy",
        document_type: "admin_document",
        tags: [],
      },
    });

    render(
      <DomainMetadataPanel
        profiles={[]}
        value={{
          parser_mode: "local_fallback",
          domain_metadata: { domain: "generic", document_type: "document", tags: [] },
        }}
        onChange={vi.fn()}
        suggestContext={{ filename: "policy.pdf", content_type: "application/pdf" }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /auto-suggest/i }));

    expect(await screen.findByText("2 fields changed")).toBeVisible();
    expect(screen.getByText("generic -> policy")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Domain"), {
      target: { value: "policy-final" },
    });

    expect(screen.queryByText("generic -> policy")).not.toBeInTheDocument();
    expect(screen.getByText("1 field changed")).toBeVisible();
    expect(screen.getByLabelText("Domain").closest("[data-autosuggest-changed]")).toBeNull();
    expect(
      screen.getByLabelText("Document type").closest("[data-autosuggest-changed]"),
    ).toHaveAttribute("data-autosuggest-changed", "true");
  });
```

- [ ] **Step 3: Add failing test for failed autosuggest preserving current state and previous summary**

Append this test after the test from Step 2:

```tsx
  it("keeps previous metadata and review when autosuggest fails", async () => {
    mocks.suggestDomainMetadata
      .mockResolvedValueOnce({
        domain_metadata: {
          domain: "policy",
          document_type: "admin_document",
          custom_json: { department: "research" },
        },
      })
      .mockRejectedValueOnce(new Error("suggestion failed"));

    const onChange = vi.fn();
    render(
      <DomainMetadataPanel
        profiles={[]}
        value={{
          parser_mode: "local_fallback",
          domain_metadata: {
            domain: "generic",
            document_type: "document",
            custom_json: { department: "general" },
          },
        }}
        onChange={onChange}
        suggestContext={{ filename: "policy.pdf", content_type: "application/pdf" }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /auto-suggest/i }));

    expect(await screen.findByText("Auto-suggest updated metadata")).toBeVisible();
    expect(screen.getByText("generic -> policy")).toBeVisible();
    expect(screen.getByDisplayValue(/research/)).toBeVisible();

    onChange.mockClear();
    fireEvent.click(screen.getByRole("button", { name: /auto-suggest/i }));

    expect(await screen.findByText("Metadata suggestion failed.")).toBeVisible();
    expect(screen.getByText("generic -> policy")).toBeVisible();
    expect(screen.getByDisplayValue(/research/)).toBeVisible();
    expect(onChange).not.toHaveBeenCalled();
  });
```

- [ ] **Step 4: Run tests to verify they fail**

Run:

```bash
docker compose run --rm --no-deps -v "$PWD/frontend/src:/app/frontend/src" -v "$PWD/frontend/tests:/app/frontend/tests:ro" frontend npm run test -- --run tests/domain-metadata-panel.test.tsx
```

Expected: FAIL. The failure should mention missing `Auto-suggest updated metadata`, missing change count text, or missing `data-autosuggest-changed`.

- [ ] **Step 5: Leave failing tests uncommitted until implementation passes**

Run:

```bash
git status --short frontend/tests/domain-metadata-panel.test.tsx
```

Expected: `frontend/tests/domain-metadata-panel.test.tsx` is modified and unstaged. Continue to Task 2 without committing.

---

### Task 2: Add Change Detection Helpers

**Files:**
- Modify: `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`

- [ ] **Step 1: Add metadata change types near `sampleCustomJson`**

Insert this block after the `sampleCustomJson` constant:

```tsx
type MetadataChangeField =
  | "domain"
  | "document_type"
  | "language"
  | "collection"
  | "tags"
  | "reference_pattern"
  | "metadata_sources"
  | "custom_json";

type MetadataChange = {
  field: MetadataChangeField;
  label: string;
  summary: string;
};
```

- [ ] **Step 2: Add helper functions at the bottom of the file**

Append these helpers after `TextField`:

```tsx
const metadataFieldLabels: Record<MetadataChangeField, string> = {
  domain: "Domain",
  document_type: "Document type",
  language: "Language",
  collection: "Collection",
  tags: "Tags",
  reference_pattern: "Reference pattern",
  metadata_sources: "Metadata sources",
  custom_json: "Custom JSON",
};

function buildMetadataChangeSet(
  before: DomainMetadata,
  after: DomainMetadata,
): MetadataChange[] {
  const changes: MetadataChange[] = [];
  const scalarFields: MetadataChangeField[] = [
    "domain",
    "document_type",
    "language",
    "collection",
    "reference_pattern",
  ];

  for (const field of scalarFields) {
    const beforeValue = getStringField(before, field);
    const afterValue = getStringField(after, field);
    if (beforeValue !== afterValue) {
      changes.push({
        field,
        label: metadataFieldLabels[field],
        summary: `${formatMetadataValue(beforeValue)} -> ${formatMetadataValue(afterValue)}`,
      });
    }
  }

  addArrayChange(changes, "tags", before.tags ?? [], after.tags ?? []);
  addArrayChange(
    changes,
    "metadata_sources",
    before.metadata_sources ?? [],
    after.metadata_sources ?? [],
  );

  const customJsonSummary = formatCustomJsonChange(
    before.custom_json ?? {},
    after.custom_json ?? {},
  );
  if (customJsonSummary) {
    changes.push({
      field: "custom_json",
      label: metadataFieldLabels.custom_json,
      summary: customJsonSummary,
    });
  }

  return changes;
}

function getStringField(metadata: DomainMetadata, field: MetadataChangeField): string {
  const value = metadata[field as keyof DomainMetadata];
  return typeof value === "string" ? value : "";
}

function addArrayChange(
  changes: MetadataChange[],
  field: "tags" | "metadata_sources",
  beforeValues: string[],
  afterValues: string[],
) {
  const added = afterValues.filter((value) => !beforeValues.includes(value));
  const removed = beforeValues.filter((value) => !afterValues.includes(value));
  if (added.length === 0 && removed.length === 0) {
    return;
  }

  const summary = [
    added.length > 0 ? `added ${added.join(", ")}` : null,
    removed.length > 0 ? `removed ${removed.join(", ")}` : null,
  ]
    .filter(Boolean)
    .join("; ");

  changes.push({
    field,
    label: metadataFieldLabels[field],
    summary,
  });
}

function formatCustomJsonChange(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
): string | null {
  const beforeKeys = Object.keys(before).sort();
  const afterKeys = Object.keys(after).sort();
  const added = afterKeys.filter((key) => !beforeKeys.includes(key));
  const removed = beforeKeys.filter((key) => !afterKeys.includes(key));
  const changed = afterKeys.filter(
    (key) =>
      beforeKeys.includes(key) &&
      JSON.stringify(before[key]) !== JSON.stringify(after[key]),
  );

  if (added.length === 0 && removed.length === 0 && changed.length === 0) {
    return null;
  }

  return [
    added.length > 0 ? `added ${added.join(", ")}` : null,
    removed.length > 0 ? `removed ${removed.join(", ")}` : null,
    changed.length > 0 ? `changed ${changed.join(", ")}` : null,
  ]
    .filter(Boolean)
    .join("; ");
}

function formatMetadataValue(value: string): string {
  return value.length > 0 ? value : "empty";
}
```

- [ ] **Step 3: Run TypeScript/test command and verify helper-only failure shape**

Run:

```bash
docker compose run --rm --no-deps -v "$PWD/frontend/src:/app/frontend/src" -v "$PWD/frontend/tests:/app/frontend/tests:ro" frontend npm run test -- --run tests/domain-metadata-panel.test.tsx
```

Expected: FAIL. TypeScript should pass. Runtime assertions should still fail because the UI state/rendering has not been added.

---

### Task 3: Render Review Panel and Highlight Changed Fields

**Files:**
- Modify: `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`

- [ ] **Step 1: Add autosuggest change state**

Inside `DomainMetadataPanel`, after `suggestState`, add:

```tsx
  const [autosuggestChanges, setAutosuggestChanges] = useState<MetadataChange[]>([]);
```

- [ ] **Step 2: Add local helper callbacks inside `DomainMetadataPanel`**

Inside `DomainMetadataPanel`, after `setMetadata`, add:

```tsx
  const hasAutosuggestChange = (field: MetadataChangeField) =>
    autosuggestChanges.some((change) => change.field === field);

  const clearChangedField = (field: MetadataChangeField) => {
    setAutosuggestChanges((changes) => changes.filter((change) => change.field !== field));
  };

  const changedFieldProps = (field: MetadataChangeField) =>
    hasAutosuggestChange(field) ? { "data-autosuggest-changed": "true" } : {};
```

- [ ] **Step 3: Update `suggest` to build and store the change set**

Replace the successful portion of `suggest`:

```tsx
      onChange({ ...value, domain_metadata: response.domain_metadata });
      setCustomJsonDraft(JSON.stringify(response.domain_metadata.custom_json ?? {}, null, 2));
      setCustomJsonError("");
      onValidityChange?.(true);
      setSuggestState("idle");
```

with:

```tsx
      const nextMetadata = response.domain_metadata;
      setAutosuggestChanges(buildMetadataChangeSet(metadata, nextMetadata));
      onChange({ ...value, domain_metadata: nextMetadata });
      setCustomJsonDraft(JSON.stringify(nextMetadata.custom_json ?? {}, null, 2));
      setCustomJsonError("");
      onValidityChange?.(true);
      setSuggestState("idle");
```

- [ ] **Step 4: Clear autosuggest review on profile selection**

Inside the profile select `if (profile) { ... }` block, add this line before `setCustomJsonError("")`:

```tsx
                setAutosuggestChanges([]);
```

- [ ] **Step 5: Render the review panel**

Immediately before `<div className="grid gap-3 sm:grid-cols-2">`, insert:

```tsx
      {autosuggestChanges.length > 0 ? (
        <div className="mb-3 rounded-md border border-[#9ccbd8] bg-[#edf7fa] p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-[#1f2933]">
              Auto-suggest updated metadata
            </p>
            <p className="text-xs font-medium text-[#176b87]">
              {autosuggestChanges.length}{" "}
              {autosuggestChanges.length === 1 ? "field changed" : "fields changed"}
            </p>
          </div>
          <dl className="mt-2 grid gap-1.5 text-xs text-[#3a4a53]">
            {autosuggestChanges.map((change) => (
              <div key={change.field} className="grid gap-1 sm:grid-cols-[150px_minmax(0,1fr)]">
                <dt className="font-semibold">{change.label}</dt>
                <dd className="min-w-0 break-words">{change.summary}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
```

- [ ] **Step 6: Add a changed-field wrapper helper component**

Replace the existing `TextField` function with this implementation:

```tsx
function TextField({
  label,
  value,
  disabled,
  changed,
  onChange,
}: {
  label: string;
  value: string;
  disabled: boolean;
  changed?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label
      className={
        changed
          ? "rounded-md border border-[#9ccbd8] bg-[#f3fafc] p-2 text-sm font-medium text-[#3a4a53]"
          : "text-sm font-medium text-[#3a4a53]"
      }
      {...(changed ? { "data-autosuggest-changed": "true" } : {})}
    >
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

- [ ] **Step 7: Pass changed state and clear highlights for scalar fields**

Replace the five `TextField` calls for `Domain`, `Document type`, `Language`, `Collection`, and `Tags` with:

```tsx
        <TextField
          label="Domain"
          value={metadata.domain ?? ""}
          disabled={disabled}
          changed={hasAutosuggestChange("domain")}
          onChange={(domain) => {
            clearChangedField("domain");
            setMetadata({ domain });
          }}
        />
        <TextField
          label="Document type"
          value={metadata.document_type ?? ""}
          disabled={disabled}
          changed={hasAutosuggestChange("document_type")}
          onChange={(document_type) => {
            clearChangedField("document_type");
            setMetadata({ document_type });
          }}
        />
        <TextField
          label="Language"
          value={metadata.language ?? ""}
          disabled={disabled}
          changed={hasAutosuggestChange("language")}
          onChange={(language) => {
            clearChangedField("language");
            setMetadata({ language });
          }}
        />
        <TextField
          label="Collection"
          value={metadata.collection ?? ""}
          disabled={disabled}
          changed={hasAutosuggestChange("collection")}
          onChange={(collection) => {
            clearChangedField("collection");
            setMetadata({ collection });
          }}
        />
        <TextField
          label="Tags"
          value={(metadata.tags ?? []).join(", ")}
          disabled={disabled}
          changed={hasAutosuggestChange("tags")}
          onChange={(tags) => {
            clearChangedField("tags");
            setMetadata({ tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean) });
          }}
        />
```

- [ ] **Step 8: Highlight and clear Custom JSON**

Replace:

```tsx
        <div className="text-sm font-medium text-[#3a4a53] sm:col-span-2">
```

with:

```tsx
        <div
          className={
            hasAutosuggestChange("custom_json")
              ? "rounded-md border border-[#9ccbd8] bg-[#f3fafc] p-2 text-sm font-medium text-[#3a4a53] sm:col-span-2"
              : "text-sm font-medium text-[#3a4a53] sm:col-span-2"
          }
          {...changedFieldProps("custom_json")}
        >
```

Then inside `applyCustomJson`, after `onValidityChange?.(true);`, add:

```tsx
      clearChangedField("custom_json");
```

- [ ] **Step 9: Run tests and verify pass**

Run:

```bash
docker compose run --rm --no-deps -v "$PWD/frontend/src:/app/frontend/src" -v "$PWD/frontend/tests:/app/frontend/tests:ro" frontend npm run test -- --run tests/domain-metadata-panel.test.tsx
```

Expected: PASS.

---

### Task 4: Add Reference Pattern and Metadata Sources UI Coverage

**Files:**
- Modify: `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`
- Modify: `frontend/tests/domain-metadata-panel.test.tsx`

The spec requires `reference_pattern` and `metadata_sources` to be included in the review. The review can list them even if they are not editable fields. This task makes their review coverage explicit without adding new form controls.

- [ ] **Step 1: Ensure the first autosuggest review test asserts non-editable metadata fields**

Confirm the test from Task 1 includes these assertions:

```tsx
    expect(screen.getByText("Reference pattern")).toBeVisible();
    expect(screen.getByText("empty -> Surah N, Ayah N")).toBeVisible();
    expect(screen.getByText("Metadata sources")).toBeVisible();
    expect(screen.getByText("added heuristic, profile; removed user")).toBeVisible();
```

- [ ] **Step 2: Verify helper output covers non-editable metadata fields**

Confirm `buildMetadataChangeSet` includes:

```tsx
  const scalarFields: MetadataChangeField[] = [
    "domain",
    "document_type",
    "language",
    "collection",
    "reference_pattern",
  ];
```

and:

```tsx
  addArrayChange(
    changes,
    "metadata_sources",
    before.metadata_sources ?? [],
    after.metadata_sources ?? [],
  );
```

- [ ] **Step 3: Run focused tests**

Run:

```bash
docker compose run --rm --no-deps -v "$PWD/frontend/src:/app/frontend/src" -v "$PWD/frontend/tests:/app/frontend/tests:ro" frontend npm run test -- --run tests/domain-metadata-panel.test.tsx
```

Expected: PASS.

---

### Task 5: Browser Verification on Documents Page

**Files:**
- No source file changes expected.

- [ ] **Step 1: Make sure the app is running**

Run:

```bash
docker compose ps
```

Expected: `ragstudio-frontend` is listening on `127.0.0.1:5173` and `ragstudio-backend` is listening on `127.0.0.1:8000`. If either service is stopped, run:

```bash
docker compose up -d frontend backend
```

- [ ] **Step 2: Use browser automation to inspect the page**

Use Playwright or the available browser tool to open:

```text
http://127.0.0.1:5173/documents
```

Expected:

- The metadata panel renders normally.
- Selecting a file enables Auto-suggest.
- Clicking Auto-suggest shows `Auto-suggest updated metadata` when the mocked or live backend returns changed metadata.
- Changed fields have a visible light highlight.
- Custom JSON still edits normally.
- No visible text overlaps or table layout regressions on a 1440px desktop viewport.

- [ ] **Step 3: Commit implementation**

Run:

```bash
git add frontend/src/features/domain-metadata/domain-metadata-panel.tsx frontend/tests/domain-metadata-panel.test.tsx
git commit -m "feat: show autosuggest metadata changes"
```

Expected: commit succeeds.

---

## Final Verification

Run the targeted tests:

```bash
docker compose run --rm --no-deps -v "$PWD/frontend/src:/app/frontend/src" -v "$PWD/frontend/tests:/app/frontend/tests:ro" frontend npm run test -- --run tests/domain-metadata-panel.test.tsx
```

Expected: PASS.

Run the Documents page tests because the panel is embedded there:

```bash
docker compose run --rm --no-deps -v "$PWD/frontend/src:/app/frontend/src" -v "$PWD/frontend/tests:/app/frontend/tests:ro" frontend npm run test -- --run tests/documents-page.test.tsx
```

Expected: PASS.

Review changed files:

```bash
git status --short
git diff -- frontend/src/features/domain-metadata/domain-metadata-panel.tsx frontend/tests/domain-metadata-panel.test.tsx
```

Expected: only the intended component and test files are modified, unless prior uncommitted work exists in the shared workspace.
