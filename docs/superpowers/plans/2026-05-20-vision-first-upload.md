# Vision-First Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the profile/manual upload metadata flow with a vision-first flow that blocks indexing until AI metadata is generated from the selected file.

**Architecture:** Keep the existing backend suggestion and upload APIs. Move orchestration into `DocumentsPage`: selected file drives a vision metadata mutation, the returned `domain_metadata` becomes the only upload metadata source, and reindexing uses each document's persisted `latest_index_options` instead of the current upload form state.

**Tech Stack:** React, TanStack Query, TypeScript, Vitest, Testing Library, FastAPI API client contracts.

---

## File Structure

- Modify `frontend/src/features/documents/documents-page.tsx`: remove upload-path profile/manual controls, add vision analysis state, submit only generated metadata, and decouple reindexing from upload state.
- Modify `frontend/tests/documents-page.test.tsx`: replace manual metadata/profile tests with vision-first upload tests and update reindex tests.
- No backend code change is expected: `frontend/src/api/client.ts` already supports `suggestDomainMetadata({ file })` without `profile_id`, and `/api/domain-profiles/suggest` already has backend coverage for no-profile vision suggestions.

## Task 1: Add Vision-First Upload Tests

**Files:**
- Modify: `frontend/tests/documents-page.test.tsx`

- [ ] **Step 1: Replace default upload test with a vision-gated test**

Replace the current `"uploads with strict MinerU as the default parser"` test with:

```ts
it("uploads only after vision metadata is generated for the selected file", async () => {
  renderDocumentsPage();

  const file = new File(["pdf"], "quran-arabic-english.pdf", { type: "application/pdf" });
  fireEvent.change(screen.getByLabelText(/upload file/i), { target: { files: [file] } });

  const uploadButton = screen.getByRole("button", { name: /upload and index/i });
  expect(uploadButton).toBeDisabled();

  fireEvent.click(screen.getByRole("button", { name: /analyze with vision/i }));

  await waitFor(() => {
    expect(apiClient.suggestDomainMetadata).toHaveBeenCalledWith({ file });
  });
  expect(await screen.findByText("quran_tafseer")).toBeVisible();
  expect(uploadButton).toBeEnabled();

  fireEvent.click(uploadButton);

  await waitFor(() => {
    expect(apiClient.uploadDocument).toHaveBeenCalledWith({
      file,
      options: {
        parser_mode: "mineru_strict",
        domain_metadata: expect.objectContaining({
          domain: "policy",
          document_type: "admin_document",
        }),
      },
    });
  });
});
```

If the shared mock suggestion still returns `domain: "policy"`, either update the expectation text from `"quran_tafseer"` to `"policy"` or update the `beforeEach` mock to return Quran-like metadata:

```ts
vi.mocked(apiClient.suggestDomainMetadata).mockResolvedValue({
  domain_metadata: {
    domain: "quran_tafseer",
    document_type: "translation",
    metadata_sources: ["ai_vision"],
    custom_json: {
      quality_policy: {
        required_scripts: ["arabic", "latin"],
      },
    },
  },
  confidence: 0.95,
  evidence_pages: [1, 2, 3],
  warnings: [],
});
```

- [ ] **Step 2: Add a test that manual controls are absent from upload**

Add this test near the upload tests:

```ts
it("does not show manual profile or metadata controls in the upload flow", () => {
  renderDocumentsPage();

  expect(screen.queryByLabelText("Domain profile")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Parser")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Domain")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Document type")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Language")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Collection")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Tags")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Custom JSON")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Override MinerU parser options")).not.toBeInTheDocument();
});
```

- [ ] **Step 3: Add a test that file changes clear generated metadata**

Add:

```ts
it("clears generated vision metadata when the selected file changes", async () => {
  renderDocumentsPage();

  const firstFile = new File(["first"], "first.pdf", { type: "application/pdf" });
  const secondFile = new File(["second"], "second.pdf", { type: "application/pdf" });
  const fileInput = screen.getByLabelText(/upload file/i);

  fireEvent.change(fileInput, { target: { files: [firstFile] } });
  fireEvent.click(screen.getByRole("button", { name: /analyze with vision/i }));
  expect(await screen.findByText("Vision metadata generated")).toBeVisible();

  fireEvent.change(fileInput, { target: { files: [secondFile] } });

  expect(screen.queryByText("Vision metadata generated")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /upload and index/i })).toBeDisabled();
});
```

- [ ] **Step 4: Add a test that vision failure blocks upload**

Add:

```ts
it("blocks upload when vision metadata generation fails", async () => {
  vi.mocked(apiClient.suggestDomainMetadata).mockRejectedValueOnce(
    new Error("Vision service unavailable"),
  );
  renderDocumentsPage();

  const file = new File(["pdf"], "sample.pdf", { type: "application/pdf" });
  fireEvent.change(screen.getByLabelText(/upload file/i), { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: /analyze with vision/i }));

  expect(await screen.findByText("Vision service unavailable")).toBeVisible();
  expect(screen.getByRole("button", { name: /upload and index/i })).toBeDisabled();
  expect(apiClient.uploadDocument).not.toHaveBeenCalled();
});
```

- [ ] **Step 5: Delete obsolete upload-form tests**

Remove tests that require controls no longer present in the upload path:

```ts
it("uploads with document-specific MinerU parser options", ...);
it("uses MinerU strict as the only parser mode", ...);
it("passes the selected upload file to metadata autosuggest", ...);
it("places auto-suggest after the domain profile selector", ...);
it("places the upload action after the custom JSON editor", ...);
it("reindexes an uploaded document with the current parser and metadata", ...);
it("reindexes with document-specific MinerU parser options", ...);
it("allows stored-option reindex while the upload metadata form is invalid", ...);
```

- [ ] **Step 6: Run the focused test file and verify it fails**

Run:

```bash
cd frontend
npm test -- --run tests/documents-page.test.tsx
```

Expected: the new tests fail because the UI still renders manual controls and upload does not require vision metadata.

## Task 2: Implement Vision Metadata State in DocumentsPage

**Files:**
- Modify: `frontend/src/features/documents/documents-page.tsx`

- [ ] **Step 1: Remove upload metadata imports**

Remove the `DomainMetadataPanel` import. Keep `MinerUParseOptionsControls` only if another part of the same file still renders it; otherwise remove that helper in Task 4.

```ts
import { DomainMetadataPanel } from "../domain-metadata/domain-metadata-panel";
```

- [ ] **Step 2: Replace manual metadata state with generated metadata state**

Replace:

```ts
const [indexOptions, setIndexOptions] = useState<IndexDocumentIn>({
  parser_mode: DEFAULT_PARSER_MODE,
  domain_metadata: { domain: "generic", document_type: "document", tags: [] },
});
const [metadataValid, setMetadataValid] = useState(true);
const setMineruParseOptions = useCallback(
  (mineru_parse_options: MinerUParseOptionsIn | null) => {
    setIndexOptions((current) => ({ ...current, mineru_parse_options }));
  },
  [],
);
```

with:

```ts
const [visionSuggestion, setVisionSuggestion] =
  useState<Awaited<ReturnType<typeof apiClient.suggestDomainMetadata>> | null>(null);
```

If TypeScript complains about the async return type, use the generated API type already exported for the response, for example:

```ts
type DomainMetadataSuggestion = Awaited<ReturnType<typeof apiClient.suggestDomainMetadata>>;
const [visionSuggestion, setVisionSuggestion] = useState<DomainMetadataSuggestion | null>(null);
```

- [ ] **Step 3: Remove profile query from upload path**

Delete:

```ts
const profilesQuery = useQuery({
  queryKey: ["domain-profiles"],
  queryFn: apiClient.domainProfiles,
});
```

Do not replace it in `DocumentsPage`; upload must not fetch or offer profiles.

- [ ] **Step 4: Add the vision analysis mutation**

Add after `uploadDocument` or before it:

```ts
const analyzeWithVision = useMutation({
  mutationFn: apiClient.suggestDomainMetadata,
  onSuccess: (suggestion) => {
    setVisionSuggestion(suggestion);
  },
});
```

- [ ] **Step 5: Clear generated metadata when file changes**

Replace the file input `onChange` body:

```ts
onChange={(event) => setFile(event.target.files?.[0] ?? null)}
```

with:

```ts
onChange={(event) => {
  setFile(event.target.files?.[0] ?? null);
  setVisionSuggestion(null);
  analyzeWithVision.reset();
  uploadDocument.reset();
}}
```

- [ ] **Step 6: Submit only generated metadata**

Replace the form submit block:

```ts
if (file) {
  uploadDocument.mutate({ file, options: indexOptions });
}
```

with:

```ts
if (file && visionSuggestion) {
  uploadDocument.mutate({
    file,
    options: {
      parser_mode: DEFAULT_PARSER_MODE,
      domain_metadata: visionSuggestion.domain_metadata,
    },
  });
}
```

- [ ] **Step 7: Reset generated metadata after successful upload**

In `uploadDocument.onSuccess`, add:

```ts
setVisionSuggestion(null);
analyzeWithVision.reset();
```

Keep the existing file input reset and query invalidation.

## Task 3: Replace Upload UI With File + Vision + Upload

**Files:**
- Modify: `frontend/src/features/documents/documents-page.tsx`

- [ ] **Step 1: Remove the index options `<details>` block**

Delete the full block that renders:

```tsx
<details className="rounded-lg border border-[#d8e1e6] bg-[#f7fafb] p-3">
  <summary ...>Index options</summary>
  <div className="mt-3 min-w-0">
    <DomainMetadataPanel ... />
    <MinerUParseOptionsControls ... />
  </div>
</details>
```

- [ ] **Step 2: Add the vision action and summary**

Insert this after the file chooser:

```tsx
<div className="flex flex-wrap items-center gap-3">
  <Button
    type="button"
    variant="secondary"
    disabled={!file || analyzeWithVision.isPending || uploadDocument.isPending}
    onClick={() => {
      if (file) {
        analyzeWithVision.mutate({ file });
      }
    }}
  >
    {analyzeWithVision.isPending ? (
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
    ) : (
      <Sparkles className="h-4 w-4" aria-hidden="true" />
    )}
    Analyze with vision
  </Button>
  {visionSuggestion ? (
    <span className="text-sm font-medium text-[#1f6f43]">Vision metadata generated</span>
  ) : (
    <span className="text-sm text-[#62717a]">Vision analysis required before upload.</span>
  )}
</div>
{visionSuggestion ? (
  <div className="rounded-md border border-[#cfe3d5] bg-[#f6fbf7] p-3 text-sm text-[#24313a]">
    <div className="font-medium">{visionSuggestion.domain_metadata.domain}</div>
    <div className="mt-1 text-[#62717a]">
      {visionSuggestion.domain_metadata.document_type ?? "document"} · Confidence{" "}
      {Math.round((visionSuggestion.confidence ?? 0) * 100)}%
    </div>
    {visionSuggestion.evidence_pages.length > 0 ? (
      <div className="mt-1 text-[#62717a]">
        Evidence pages: {visionSuggestion.evidence_pages.join(", ")}
      </div>
    ) : null}
  </div>
) : null}
{analyzeWithVision.error ? (
  <p className="text-sm text-[#a63d2a]" role="alert">
    {analyzeWithVision.error.message}
  </p>
) : null}
```

If `Sparkles` is not already imported from `lucide-react`, add it to the existing icon import list.

- [ ] **Step 3: Change the upload button gate and label**

Replace:

```tsx
<Button type="submit" disabled={!file || !metadataValid || uploadDocument.isPending}>
```

with:

```tsx
<Button
  type="submit"
  disabled={!file || !visionSuggestion || analyzeWithVision.isPending || uploadDocument.isPending}
>
```

Change the visible button text from `Upload` to:

```tsx
Upload and index
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
cd frontend
npm test -- --run tests/documents-page.test.tsx
```

Expected: upload tests pass or reveal only reindex-related failures addressed in Task 4.

## Task 4: Decouple Reindex From Upload State

**Files:**
- Modify: `frontend/src/features/documents/documents-page.tsx`
- Modify: `frontend/tests/documents-page.test.tsx`

- [ ] **Step 1: Use only stored index options for reindex**

Replace:

```ts
const baseOptions = document.latest_index_options ?? indexOptions;
reindexDocument.mutate({
  documentId: document.id,
  options: indexOptions.mineru_parse_options
    ? { ...baseOptions, mineru_parse_options: indexOptions.mineru_parse_options }
    : baseOptions,
});
```

with:

```ts
if (!document.latest_index_options) {
  return;
}
reindexDocument.mutate({
  documentId: document.id,
  options: document.latest_index_options,
});
```

Update the dependency list from:

```ts
[indexOptions, reindexDocument]
```

to:

```ts
[reindexDocument]
```

- [ ] **Step 2: Disable reindex when stored options are missing**

Replace:

```ts
const canUseStoredIndexOptions = document.latest_index_options != null;
const canReindex = canUseStoredIndexOptions || metadataValid;
```

with:

```ts
const canReindex = document.latest_index_options != null;
```

Remove `metadataValid` from memo dependencies.

- [ ] **Step 3: Keep the stored-options reindex test**

Keep and update `"reindexes with the document's current index options when available"` so it still expects:

```ts
expect(apiClient.createDocumentReindexJob).toHaveBeenCalledWith("doc-1", {
  parser_mode: "mineru_strict",
  domain_metadata: expect.objectContaining({
    domain: "quran_tafseer",
    document_type: "commentary",
  }),
});
```

- [ ] **Step 4: Add a disabled reindex test for documents without stored options**

Add:

```ts
it("disables reindex when a document has no stored index options", async () => {
  vi.mocked(apiClient.documents).mockResolvedValue({
    items: [
      {
        id: "doc-1",
        filename: "legacy.pdf",
        content_type: "application/pdf",
        size_bytes: 1024,
        created_at: "2025-01-01T00:00:00Z",
        sha256: "sha-1",
        latest_index_options: null,
      },
    ],
    total: 1,
    limit: 500,
    offset: 0,
  });

  renderDocumentsPage();

  expect(await screen.findByRole("button", { name: /reindex legacy\.pdf/i })).toBeDisabled();
});
```

- [ ] **Step 5: Remove now-unused helper code**

If `MinerUParseOptionsControls` is no longer referenced, remove:

```ts
function MinerUParseOptionsControls(...)
```

and remove unused imported types such as:

```ts
MinerUParseOptionsIn
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
cd frontend
npm test -- --run tests/documents-page.test.tsx
```

Expected: `documents-page.test.tsx` passes.

## Task 5: Verification and Cleanup

**Files:**
- Modify only if failures point to a real issue:
  - `frontend/src/features/documents/documents-page.tsx`
  - `frontend/tests/documents-page.test.tsx`

- [ ] **Step 1: Run lint**

Run:

```bash
cd frontend
npm run lint
```

Expected: no unused imports, no hook dependency errors, no TypeScript-aware lint failures.

- [ ] **Step 2: Run frontend build**

Run:

```bash
cd frontend
npm run build
```

Expected: TypeScript and Vite build succeed.

- [ ] **Step 3: Manual browser verification**

Start the app if it is not already running:

```bash
docker compose up -d backend frontend worker postgres neo4j
```

Open the app and verify:

1. Upload area shows file chooser, `Analyze with vision`, and disabled `Upload and index`.
2. The old profile/domain/custom JSON controls are not visible.
3. Choosing a file keeps upload disabled.
4. Clicking `Analyze with vision` shows generated metadata.
5. Upload becomes enabled only after generated metadata appears.

- [ ] **Step 4: Commit only this feature's files**

Run:

```bash
git status --short
git add frontend/src/features/documents/documents-page.tsx frontend/tests/documents-page.test.tsx
git commit -m "feat: make document upload vision-first"
```

Expected: commit includes only the vision-first upload implementation and test updates. Do not stage unrelated backend changes from the existing dirty worktree.

## Self-Review

- Spec coverage: The plan removes manual upload metadata controls, calls vision autosuggest without `profile_id`, blocks upload until generated metadata exists, clears metadata on file change, preserves stored-option reindexing, and adds tests for failure handling.
- Placeholder scan: No task contains TBD, TODO, or vague "handle edge cases" instructions. Each behavior change has exact files, code, and commands.
- Type consistency: The plan uses the existing `apiClient.suggestDomainMetadata`, `apiClient.uploadDocument`, `DEFAULT_PARSER_MODE`, `latest_index_options`, and `IndexDocumentIn` contracts already present in the frontend code.
