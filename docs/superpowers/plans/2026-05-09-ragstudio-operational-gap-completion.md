# Ragstudio Operational Gap Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the remaining Ragstudio UI/runtime gaps into working, testable product behavior for pipeline actions, scoped runtime queries, graph exploration, reranker diagnostics, and metadata review.

**Architecture:** Keep the existing FastAPI + React architecture and add narrow service/UI units at the current boundaries. Backend tasks expose missing product state through existing routes or small route additions; frontend tasks make each stage actionable without turning Pipeline into a separate workflow engine.

**Tech Stack:** FastAPI, SQLAlchemy async sessions, Pydantic schemas, React, TanStack Query, ReactFlow, Vitest, Pytest, Playwright.

---

## File Structure

- Modify `backend/src/ragstudio/services/query_service.py`: allow native runtime scoped query when supported and return a product-visible failure when the active adapter refuses scoping.
- Modify `backend/src/ragstudio/services/native_raganything_adapter.py`: add a capability method for scoped queries and include the unsupported reason in runtime query results.
- Modify `backend/tests/test_runtime_query_service.py`: cover scoped native-query success/failure behavior.
- Modify `frontend/src/features/query/query-page.tsx`: show runtime capability failures before the user misreads an empty answer as a bad answer.
- Modify `backend/src/ragstudio/services/graph_service.py`: add a fallback graph built from chunk relationship metadata when runtime graph is unavailable or empty.
- Modify `backend/tests/test_optimizer_graph_diagnostics.py`: add graph fallback coverage using chunk metadata fixtures.
- Modify `frontend/src/features/graph/graph-page.tsx`: add filters for node type, edge type, document, and page/reference.
- Modify `frontend/tests/graph-page.test.tsx`: cover real Neo4j-shaped nodes and filtered rendering.
- Modify `frontend/src/features/pipeline/pipeline-builder.tsx`: add stage action buttons that navigate to existing workflow pages and show blocking diagnostics beside affected stages.
- Modify `frontend/tests/pipeline-builder.test.tsx`: cover stage actions and warning placement.
- Modify `backend/src/ragstudio/services/reranker_service.py`: expand traces for skipped, blocked, failed, and applied reranker states.
- Modify `backend/tests/test_query_runs.py`: add malformed payload, HTTP 500, timeout, and reranker-disabled tests.
- Modify `frontend/src/features/query/query-page.tsx`: render reranker trace summaries outside raw JSON.
- Modify `frontend/tests/query-page.test.tsx`: cover reranker trace summaries.
- Modify `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`: add accept/reject per autosuggest-changed field.
- Modify `frontend/tests/domain-metadata-panel.test.tsx`: cover accept/reject behavior and upload metadata after rejection.
- Modify `docs/workflows.md`: document the new pipeline, graph, reranker, and autosuggest workflows.

---

### Task 1: Runtime Scoped Query Capability

**Files:**
- Modify: `backend/src/ragstudio/services/native_raganything_adapter.py`
- Modify: `backend/src/ragstudio/services/query_service.py`
- Test: `backend/tests/test_runtime_query_service.py`

- [ ] **Step 1: Write the failing scoped-query capability tests**

Add these tests to `backend/tests/test_runtime_query_service.py` after `test_query_service_uses_runtime_without_chunk_search`:

```python
@pytest.mark.asyncio
async def test_query_service_records_native_scope_limitation_as_failed_run(client):
    app = client._transport.app
    runtime = FakeRuntime(
        RuntimeQueryResult(
            answer="",
            sources=[],
            error=(
                "Native RAG-Anything query cannot yet enforce selected document_ids; "
                "refusing to run an unscoped runtime query."
            ),
            error_type="native_document_scope_unsupported",
        )
    )
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(session, app)

        result = await QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
        ).run_query(QueryIn(query="scoped?", document_ids=[document.id], variant_ids=[variant.id]))

    run = result.runs[0]
    assert run.status == StageStatus.FAILED
    assert run.error_type == "native_document_scope_unsupported"
    assert "cannot yet enforce selected document_ids" in (run.error or "")


@pytest.mark.asyncio
async def test_query_service_allows_unscoped_runtime_query_when_no_documents_requested(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        _, variant = await _create_runtime_records(session, app, indexed=False)

        result = await QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(),
            health_service=FakeHealthService(),
        ).run_query(QueryIn(query="unscoped?", document_ids=[], variant_ids=[variant.id]))

    run = result.runs[0]
    assert run.status == StageStatus.SUCCEEDED
    assert run.answer == "runtime answer: unscoped?"
```

- [ ] **Step 2: Run the focused tests to verify failure**

Run:

```bash
.venv/bin/pytest backend/tests/test_runtime_query_service.py -v
```

Expected: the new unscoped test fails because `_validate_index_readiness` or test fixture assumptions still force document indexing.

- [ ] **Step 3: Implement query readiness so empty `document_ids` skips index checks**

In `backend/src/ragstudio/services/query_service.py`, keep this existing guard in `_validate_index_readiness`:

```python
if not document_ids:
    return
```

If it was removed or changed during implementation, restore it exactly before any database query in `_validate_index_readiness`.

- [ ] **Step 4: Add native adapter capability reporting**

In `backend/src/ragstudio/services/native_raganything_adapter.py`, update `capability_report()`:

```python
def capability_report(self) -> dict[str, Any]:
    return {
        "raganything_available": True,
        "active_backend": "runtime",
        "indexing": "raganything",
        "query": "raganything",
        "graph": "neo4j",
        "scoped_query": False,
        "scoped_query_detail": (
            "Native RAG-Anything query cannot yet enforce selected document_ids."
        ),
    }
```

- [ ] **Step 5: Run focused backend tests**

Run:

```bash
.venv/bin/pytest backend/tests/test_runtime_query_service.py -v
```

Expected: all tests in `test_runtime_query_service.py` pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/native_raganything_adapter.py backend/src/ragstudio/services/query_service.py backend/tests/test_runtime_query_service.py
git commit -m "fix: surface scoped runtime query limitations"
```

---

### Task 2: Fallback Graph From Chunk Relationships

**Files:**
- Modify: `backend/src/ragstudio/services/graph_service.py`
- Test: `backend/tests/test_optimizer_graph_diagnostics.py`

- [ ] **Step 1: Write the failing fallback graph test**

Add this test to `backend/tests/test_optimizer_graph_diagnostics.py`:

```python
@pytest.mark.asyncio
async def test_graph_service_builds_fallback_graph_from_chunk_relationship_metadata(client):
    from ragstudio.db.models import Chunk, Document
    from ragstudio.schemas.common import StageStatus
    from ragstudio.services.graph_service import GraphService

    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="relationships.txt",
            content_type="text/plain",
            sha256="relationships-graph",
            artifact_path=str(app.state.settings.data_dir / "relationships.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="Surah 2 ayah 255 mentions the Throne Verse.",
                source_location={"page": 12},
                metadata_json={
                    "relationship_metadata": {
                        "graph_relationships": [
                            {
                                "source": "reference:2:255",
                                "target": "topic:throne_verse",
                                "type": "mentions",
                                "source_label": "2:255",
                                "target_label": "Throne Verse",
                            }
                        ]
                    }
                },
            )
        )
        await session.commit()

        graph = await GraphService(session, app.state.settings).get_graph()

    assert {node["id"] for node in graph.nodes} == {"reference:2:255", "topic:throne_verse"}
    assert graph.edges == [
        {
            "id": "reference:2:255-topic:throne_verse-mentions",
            "source": "reference:2:255",
            "target": "topic:throne_verse",
            "type": "mentions",
            "properties": {"document_id": document.id, "page": 12},
        }
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
.venv/bin/pytest backend/tests/test_optimizer_graph_diagnostics.py::test_graph_service_builds_fallback_graph_from_chunk_relationship_metadata -v
```

Expected: FAIL because `GraphService` returns the placeholder fallback graph with no nodes or edges.

- [ ] **Step 3: Implement fallback graph extraction**

Add imports and helper methods to `backend/src/ragstudio/services/graph_service.py`:

```python
from typing import Any

from ragstudio.db.models import Chunk
from sqlalchemy import select
```

Add this logic to `_graph()` before `return await self.adapter.graph()` in the `profile.runtime_mode == "fallback"` branch:

```python
fallback_graph = await self._relationship_metadata_graph()
if fallback_graph["nodes"] or fallback_graph["edges"]:
    return fallback_graph
return await self.adapter.graph()
```

Add this method to `GraphService`:

```python
async def _relationship_metadata_graph(self) -> dict[str, list[dict[str, Any]]]:
    if self.session is None:
        return {"nodes": [], "edges": []}
    result = await self.session.execute(select(Chunk))
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    for chunk in result.scalars().all():
        relationships = (
            chunk.metadata_json.get("relationship_metadata", {})
            .get("graph_relationships", [])
        )
        if not isinstance(relationships, list):
            continue
        for relationship in relationships:
            if not isinstance(relationship, dict):
                continue
            source = relationship.get("source")
            target = relationship.get("target")
            rel_type = relationship.get("type")
            if not all(isinstance(value, str) and value for value in [source, target, rel_type]):
                continue
            nodes.setdefault(
                source,
                {
                    "id": source,
                    "labels": ["FallbackRelationship"],
                    "properties": {
                        "label": relationship.get("source_label", source),
                        "document_id": chunk.document_id,
                        **chunk.source_location,
                    },
                },
            )
            nodes.setdefault(
                target,
                {
                    "id": target,
                    "labels": ["FallbackRelationship"],
                    "properties": {
                        "label": relationship.get("target_label", target),
                        "document_id": chunk.document_id,
                        **chunk.source_location,
                    },
                },
            )
            edge_id = f"{source}-{target}-{rel_type}"
            edges.setdefault(
                edge_id,
                {
                    "id": edge_id,
                    "source": source,
                    "target": target,
                    "type": rel_type,
                    "properties": {
                        "document_id": chunk.document_id,
                        **chunk.source_location,
                    },
                },
            )
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}
```

- [ ] **Step 4: Run the fallback graph test**

Run:

```bash
.venv/bin/pytest backend/tests/test_optimizer_graph_diagnostics.py::test_graph_service_builds_fallback_graph_from_chunk_relationship_metadata -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/graph_service.py backend/tests/test_optimizer_graph_diagnostics.py
git commit -m "feat: expose fallback relationship graph"
```

---

### Task 3: Graph Filters For Domain Exploration

**Files:**
- Modify: `frontend/src/features/graph/graph-page.tsx`
- Test: `frontend/tests/graph-page.test.tsx`

- [ ] **Step 1: Write the failing filter test**

Add this test to `frontend/tests/graph-page.test.tsx`:

```tsx
it("filters the graph map by node type", async () => {
  vi.mocked(apiClient.diagnostics).mockResolvedValue({
    capabilities: { graph: true },
    dependency_status: {},
    warnings: [],
    runtime_mode: "runtime",
    overall_status: "ready",
    checks: [],
  });
  vi.mocked(apiClient.graph).mockResolvedValue({
    nodes: [
      { id: "verse-1", labels: ["Reference"], properties: { label: "2:255" } },
      { id: "topic-1", labels: ["Topic"], properties: { label: "Throne Verse" } },
    ],
    edges: [{ source: "verse-1", target: "topic-1", type: "mentions" }],
  });

  renderGraphPage();

  fireEvent.change(await screen.findByLabelText("Node type"), {
    target: { value: "Reference" },
  });

  const map = await screen.findByLabelText("Graph relationship map");
  expect(map).toHaveTextContent("2:255");
  expect(map).not.toHaveTextContent("Throne Verse");
});
```

Also add this import at the top:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd frontend
npm test -- --run tests/graph-page.test.tsx
```

Expected: FAIL because there is no `Node type` select.

- [ ] **Step 3: Add graph filter state and filtered datasets**

In `frontend/src/features/graph/graph-page.tsx`, change the import:

```tsx
import { useMemo, useState } from "react";
```

Inside `GraphPage()`, add state and filtered values after `previewEdges`:

```tsx
const [nodeTypeFilter, setNodeTypeFilter] = useState("all");
const nodeTypeOptions = useMemo(
  () => Array.from(new Set(previewNodes.map((item) => graphType(item, "entity")))).sort(),
  [previewNodes],
);
const filteredNodes = useMemo(
  () =>
    nodeTypeFilter === "all"
      ? previewNodes
      : previewNodes.filter((item) => graphType(item, "entity") === nodeTypeFilter),
  [nodeTypeFilter, previewNodes],
);
const filteredNodeIds = useMemo(
  () => new Set(filteredNodes.map((item, index) => graphId(item, index))),
  [filteredNodes],
);
const filteredEdges = useMemo(
  () =>
    previewEdges.filter((item) => {
      const source = graphEndpoint(item, ["source", "source_id", "from", "start"]);
      const target = graphEndpoint(item, ["target", "target_id", "to", "end"]);
      return Boolean(source && target && filteredNodeIds.has(source) && filteredNodeIds.has(target));
    }),
  [filteredNodeIds, previewEdges],
);
const visualGraph = useMemo(
  () => buildVisualGraph(filteredNodes, filteredEdges),
  [filteredNodes, filteredEdges],
);
```

Remove the older `visualGraph` assignment that used `previewNodes` and `previewEdges`.

- [ ] **Step 4: Add filter controls above the graph canvas**

Replace the populated graph branch opening with:

```tsx
<section className="grid gap-4">
  <div className="flex flex-wrap items-end gap-3 rounded-md border border-[#d6dde1] bg-white p-3">
    <label className="min-w-48 text-sm font-medium text-[#3a4a53]">
      <span className="mb-1.5 block">Node type</span>
      <select
        aria-label="Node type"
        className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm"
        value={nodeTypeFilter}
        onChange={(event) => setNodeTypeFilter(event.target.value)}
      >
        <option value="all">All node types</option>
        {nodeTypeOptions.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
    <p className="min-h-10 text-sm leading-10 text-[#62717a]">
      Showing {formatCount(filteredNodes.length)} nodes and {formatCount(filteredEdges.length)} edges.
    </p>
  </div>
  <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
```

Close the extra wrapper after the side panel:

```tsx
  </div>
</section>
```

- [ ] **Step 5: Run graph component tests**

Run:

```bash
cd frontend
npm test -- --run tests/graph-page.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/graph/graph-page.tsx frontend/tests/graph-page.test.tsx
git commit -m "feat: add graph exploration filters"
```

---

### Task 4: Actionable Pipeline Status

**Files:**
- Modify: `frontend/src/features/pipeline/pipeline-builder.tsx`
- Test: `frontend/tests/pipeline-builder.test.tsx`

- [ ] **Step 1: Write the failing navigation test**

Add this test to `frontend/tests/pipeline-builder.test.tsx`:

```tsx
it("shows workflow actions for pipeline stages", async () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <PipelineBuilder />
    </QueryClientProvider>,
  );

  expect(await screen.findByRole("link", { name: "Open Documents" })).toHaveAttribute(
    "href",
    "/documents",
  );
  expect(screen.getByRole("link", { name: "Open Settings" })).toHaveAttribute(
    "href",
    "/settings",
  );
  expect(screen.getByRole("link", { name: "Open Query" })).toHaveAttribute("href", "/query");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd frontend
npm test -- --run tests/pipeline-builder.test.tsx
```

Expected: FAIL because no links exist.

- [ ] **Step 3: Add stage action links**

In `frontend/src/features/pipeline/pipeline-builder.tsx`, add this block after the stage checklist:

```tsx
<div className="mt-4 grid gap-2">
  <StageAction href="/documents" label="Open Documents" />
  <StageAction href="/settings" label="Open Settings" />
  <StageAction href="/variants" label="Open Variants" />
  <StageAction href="/query" label="Open Query" />
</div>
```

Add this helper below `StageCheck`:

```tsx
function StageAction({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      className="inline-flex h-9 items-center justify-center rounded-md border border-[#d6dde1] bg-white px-3 text-sm font-medium text-[#24313a] hover:bg-[#edf3f5]"
    >
      {label}
    </a>
  );
}
```

- [ ] **Step 4: Verify route behavior manually**

Run the Vite app and open the Pipeline page:

```bash
cd frontend
npm run dev
```

In a browser, open `http://127.0.0.1:5173/pipeline`, click `Open Documents`, and confirm the Documents page renders. Vite serves client routes directly, so a normal anchor navigation is acceptable for this app.

- [ ] **Step 5: Run pipeline tests**

Run:

```bash
cd frontend
npm test -- --run tests/pipeline-builder.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/pipeline/pipeline-builder.tsx frontend/tests/pipeline-builder.test.tsx
git commit -m "feat: add pipeline stage actions"
```

---

### Task 5: Reranker Trace Summaries In Query UI

**Files:**
- Modify: `frontend/src/features/query/query-page.tsx`
- Test: `frontend/tests/query-page.test.tsx`

- [ ] **Step 1: Write the failing reranker summary test**

Create `frontend/tests/query-page.test.tsx` if it does not exist. Add:

```tsx
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../src/api/client";
import { QueryPage } from "../src/features/query/query-page";

vi.mock("../src/api/client", () => ({
  apiClient: {
    documents: vi.fn(),
    variants: vi.fn(),
    query: vi.fn(),
  },
}));

function renderQueryPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <QueryPage />
    </QueryClientProvider>,
  );
}

describe("QueryPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-1",
          filename: "source.txt",
          content_type: "text/plain",
          status: "succeeded",
          sha256: "sha",
        },
      ],
      total: 1,
    });
    vi.mocked(apiClient.variants).mockResolvedValue({
      items: [{ id: "variant-1", name: "Balanced", preset: "balanced", parameters: {} }],
      total: 1,
    });
    vi.mocked(apiClient.query).mockResolvedValue({
      runs: [
        {
          id: "run-1",
          variant_id: "variant-1",
          experiment_id: null,
          query: "alpha",
          status: "succeeded",
          answer: "answer",
          sources: [],
          chunk_traces: [],
          timings: {},
          error: null,
          runtime_profile_id: null,
          document_ids: ["doc-1"],
          query_config: {},
          reranker_traces: [
            { status: "failed", provider: "generic_http", error_type: "ConnectError" },
          ],
          token_metadata: {},
        },
      ],
    });
  });

  it("summarizes reranker status outside raw JSON", async () => {
    renderQueryPage();

    fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
      target: { value: "alpha" },
    });
    fireEvent.click(await screen.findByText("source.txt"));
    fireEvent.click(await screen.findByText("Balanced"));
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(apiClient.query).toHaveBeenCalled());
    expect(await screen.findByText("Reranker failed")).toBeVisible();
    expect(screen.getByText("generic_http · ConnectError")).toBeVisible();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd frontend
npm test -- --run tests/query-page.test.tsx
```

Expected: FAIL because `Reranker failed` is not rendered.

- [ ] **Step 3: Add reranker summary rendering**

In `frontend/src/features/query/query-page.tsx`, add this inside `RunResult`, after the badges:

```tsx
<RerankerSummary traces={run.reranker_traces} />
```

Add this helper below `Badge`:

```tsx
function RerankerSummary({ traces }: { traces: Record<string, unknown>[] }) {
  if (!traces.length) {
    return null;
  }
  const first = traces[0];
  const status = typeof first.status === "string" ? first.status : "applied";
  const provider = typeof first.provider === "string" ? first.provider : "reranker";
  const errorType = typeof first.error_type === "string" ? first.error_type : "";
  const title =
    status === "failed"
      ? "Reranker failed"
      : status === "blocked_endpoint"
        ? "Reranker blocked"
        : status === "no_results"
          ? "Reranker returned no results"
          : "Reranker applied";
  const detail = [provider, errorType].filter(Boolean).join(" · ");
  return (
    <div className="mt-3 rounded-md border border-[#cfe3ea] bg-[#f5fafb] p-3 text-sm text-[#3a4a53]">
      <p className="font-semibold text-[#1f2933]">{title}</p>
      {detail ? <p className="mt-1 text-xs text-[#62717a]">{detail}</p> : null}
    </div>
  );
}
```

- [ ] **Step 4: Run query page tests**

Run:

```bash
cd frontend
npm test -- --run tests/query-page.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/query/query-page.tsx frontend/tests/query-page.test.tsx
git commit -m "feat: summarize reranker traces"
```

---

### Task 6: Autosuggest Per-Field Review Controls

**Files:**
- Modify: `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`
- Test: `frontend/tests/domain-metadata-panel.test.tsx`

- [ ] **Step 1: Write failing accept/reject tests**

Add this test to `frontend/tests/domain-metadata-panel.test.tsx`:

```tsx
it("rejects an autosuggested field and restores the prior value", async () => {
  const onChange = vi.fn();
  vi.mocked(apiClient.suggestDomainMetadata).mockResolvedValue({
    domain_metadata: { domain: "policy", document_type: "memo", tags: [] },
    confidence: 0.9,
    evidence_pages: [1],
    rationale: "Detected memo heading.",
    warnings: [],
  });

  render(
    <DomainMetadataPanel
      profiles={[]}
      value={{
        parser_mode: "local_fallback",
        domain_metadata: { domain: "generic", document_type: "document", tags: [] },
      }}
      onChange={onChange}
      suggestContext={{
        filename: "memo.txt",
        content_type: "text/plain",
        file: new File(["memo"], "memo.txt", { type: "text/plain" }),
      }}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Auto-suggest" }));
  await screen.findByText("Auto-suggest updated metadata");
  fireEvent.click(screen.getByRole("button", { name: "Reject Domain" }));

  expect(onChange).toHaveBeenLastCalledWith({
    parser_mode: "local_fallback",
    domain_metadata: { domain: "generic", document_type: "memo", tags: [] },
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd frontend
npm test -- --run tests/domain-metadata-panel.test.tsx
```

Expected: FAIL because no reject buttons exist.

- [ ] **Step 3: Store autosuggest baseline**

In `frontend/src/features/domain-metadata/domain-metadata-panel.tsx`, add state:

```tsx
const [autosuggestBaseline, setAutosuggestBaseline] = useState<DomainMetadata | null>(null);
```

Inside `suggest()`, before calling `onChange`, add:

```tsx
setAutosuggestBaseline(metadata);
```

- [ ] **Step 4: Add reject helper**

Add this helper inside `DomainMetadataPanel`:

```tsx
const rejectAutosuggestField = (field: MetadataChangeField) => {
  if (!autosuggestBaseline) {
    return;
  }
  const nextMetadata = { ...metadata };
  if (field === "tags") {
    nextMetadata.tags = autosuggestBaseline.tags ?? [];
  } else if (field === "metadata_sources") {
    nextMetadata.metadata_sources = autosuggestBaseline.metadata_sources ?? [];
  } else if (field === "custom_json") {
    nextMetadata.custom_json = autosuggestBaseline.custom_json ?? {};
    setCustomJsonDraft(JSON.stringify(nextMetadata.custom_json, null, 2));
  } else {
    const key = field as keyof DomainMetadata;
    nextMetadata[key] = autosuggestBaseline[key] as never;
  }
  clearChangedField(field);
  onChange({ ...value, domain_metadata: nextMetadata });
};
```

- [ ] **Step 5: Render reject buttons per changed field**

Inside the `autosuggestChanges.map()` block, below `<span>{change.summary}</span>`, add:

```tsx
<div className="mt-1 flex gap-2">
  <Button
    type="button"
    variant="secondary"
    size="sm"
    onClick={() => rejectAutosuggestField(change.field)}
  >
    Reject {change.label}
  </Button>
</div>
```

- [ ] **Step 6: Run domain metadata panel tests**

Run:

```bash
cd frontend
npm test -- --run tests/domain-metadata-panel.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/domain-metadata/domain-metadata-panel.tsx frontend/tests/domain-metadata-panel.test.tsx
git commit -m "feat: add autosuggest field review controls"
```

---

### Task 7: Documentation And Final Verification

**Files:**
- Modify: `docs/workflows.md`

- [ ] **Step 1: Update workflow documentation**

Add this section to `docs/workflows.md` near the existing Pipeline and Graph sections:

```markdown
### Operational Pipeline Status

The Pipeline page is a live status map, not a separate pipeline editor. Use it to identify which stage needs attention, then use the stage actions to open Documents, Settings, Variants, or Query.

### Graph Exploration

The Graph page renders runtime Neo4j graph data when runtime graph storage is available. In fallback mode it renders relationship metadata stored on indexed chunks when that metadata exists. Use node type filters to inspect references, topics, entities, and fallback relationship nodes.

### Reranker Diagnostics

When a reranker is configured, query runs include reranker traces. A successful trace shows applied ranks and scores. A failed, blocked, or empty reranker trace means the original retrieval order was preserved and the query still completed.

### Autosuggest Review

Document metadata autosuggest starts from the selected domain profile and proposes field-level changes. Review changed fields before upload and reject any field that should keep its previous value.
```

- [ ] **Step 2: Run backend tests**

Run:

```bash
.venv/bin/pytest backend/tests/test_query_runs.py backend/tests/test_runtime_query_service.py backend/tests/test_optimizer_graph_diagnostics.py -v
```

Expected: PASS.

- [ ] **Step 3: Run frontend tests**

Run:

```bash
cd frontend
npm test -- --run tests/documents-page.test.tsx tests/domain-metadata-panel.test.tsx tests/graph-page.test.tsx tests/pipeline-builder.test.tsx tests/query-page.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Run frontend build and lint**

Run:

```bash
cd frontend
npm run build
npm run lint
```

Expected: both commands exit 0. Vite may print the existing chunk-size warning; that warning is acceptable for this plan.

- [ ] **Step 5: Run diff sanity check**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` exits 0. `git status --short` lists only files changed by this plan.

- [ ] **Step 6: Commit**

```bash
git add docs/workflows.md
git commit -m "docs: document operational pipeline workflows"
```

---

## Self-Review

**Spec coverage:** The plan covers the remaining product gaps: scoped runtime query limitation, graph visualization backed by actual data, pipeline actionability, reranker diagnostics, autosuggest review, and workflow documentation.

**Placeholder scan:** The plan contains concrete commands, code snippets, and expected outcomes. Each code-changing step includes implementation-level detail.

**Type consistency:** Backend snippets use existing `GraphOut`, `RuntimeQueryResult`, `Chunk`, `Document`, and `SettingsProfile` shapes. Frontend snippets use current `RunOut` trace shape and existing React/TanStack patterns.
