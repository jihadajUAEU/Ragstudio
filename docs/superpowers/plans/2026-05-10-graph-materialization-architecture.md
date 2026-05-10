# Graph Materialization Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Ragstudio-owned Neo4j graph projection from `relationship_metadata.graph_relationships` during indexing so graph retrieval can return real document-scoped neighbors.

**Architecture:** Postgres remains the source of truth for chunks, references, and relationship metadata. Neo4j becomes a rebuildable query projection owned by Ragstudio, written during indexing and read by `GraphExpansionService`. RAG-Anything still handles parsing/native indexing, but Quran/Hadith/domain graph edges are materialized from Ragstudio metadata so retrieval is scoped, explainable, and repairable.

**Tech Stack:** Python 3.12, FastAPI service layer, SQLAlchemy async sessions, Neo4j Python driver, pytest, existing Ragstudio `AdapterChunk`, `Chunk`, `RuntimeProfile`, `IndexLifecycleService`, `GraphExpansionService`.

---

## Current Problem

The current indexing path creates relationship metadata, but does not write those relationships into Neo4j:

- `MinerURelationshipBuilder.annotate()` adds `relationship_metadata.graph_relationships` to adapter chunk metadata.
- `IndexLifecycleService.reindex_document()` persists annotated chunks into Postgres.
- `GraphExpansionService.expand()` queries Neo4j directly.
- Neo4j currently has zero `ragstudio_default` nodes after successful indexing, so graph expansion returns `expanded_candidates = 0`.

This plan adds an explicit graph projection stage to indexing.

## File Structure

- Create: `backend/src/ragstudio/services/graph_workspace.py`
  - Shared workspace label and graph ID helpers.
  - Prevents materialization, expansion, and native graph reads from drifting.

- Create: `backend/src/ragstudio/services/graph_materialization_service.py`
  - Owns all Neo4j writes for Ragstudio relationship metadata.
  - Deletes and rebuilds graph projection for one document.
  - Returns node/edge counts for job/graph diagnostics.

- Create: `backend/src/ragstudio/services/graph_projection_runner.py`
  - Processes pending `GraphProjectionRecord` rows after Postgres chunk/index commits.
  - Loads authoritative chunks from Postgres, writes Neo4j, and updates durable projection status.

- Modify: `backend/src/ragstudio/db/models.py`
  - Add durable `GraphProjectionRecord` status rows so graph projection state is observable, retryable, and independent from `IndexRecord.index_shape`.

- Modify: `backend/src/ragstudio/services/graph_expansion_service.py`
  - Reuse shared workspace helper.
  - Add reference-hop expansion so chunk -> ref -> neighboring ref -> chunk works.
  - Keep direct neighbor expansion intact.

- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
  - Hydrate graph-expanded chunk IDs from Postgres before final fusion/rerank/answer generation.

- Optional follow-up: `backend/src/ragstudio/services/native_raganything_adapter.py`
  - Reuse shared workspace helper for graph reads and LightRAG workspace naming only if the adapter currently duplicates workspace label logic.

- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
  - Create pending graph projection records during runtime indexing after chunks are persisted.
  - Keep `IndexRecord.index_shape` equal to `profile.index_shape`; do not store graph status or counts there.
  - Expose graph materialization status through `GraphProjectionRecord` and copy the latest status into `job.result`.

- Modify: `backend/src/ragstudio/services/document_service.py`
  - Preserve graph materialization counts in `job.result` after indexing.

- Test: `backend/tests/test_graph_workspace.py`
  - Unit tests for workspace label and ID helpers.

- Test: `backend/tests/test_graph_materialization_service.py`
  - Unit tests for generated Cypher parameters and relationship conversion using a fake Neo4j driver.

- Test: `backend/tests/test_graph_expansion_service.py`
  - Add tests for reference-hop expansion and shared workspace behavior.

- Test: `backend/tests/test_mineru_reindex_jobs.py`
  - Add integration-style service tests proving indexing creates pending graph projection records and post-commit materialization stores counts.

## Review Amendments

These corrections are part of the implementation contract:

- `IndexRecord.index_shape` is a runtime-readiness contract. Keep it stable and equal to `RuntimeProfile.index_shape`; dynamic graph materialization metadata must not be written into it.
- Neo4j is a projection, not a source of truth. Store compact graph properties in Neo4j, then hydrate full chunk text and authoritative metadata from Postgres during retrieval.
- Graph materialization is quality-enhancing but should be operationally soft-fail by default. If Neo4j write fails, indexing should still persist chunks and record `graph_materialization.status = "failed"` for diagnostics/retry unless a future runtime profile explicitly marks graph as required.
- Neo4j node properties must be primitive/list-safe. Flatten selected source-location fields and JSON-encode complex metadata instead of writing nested dicts.
- Document deletion and repair/backfill are part of the architecture: deleting a document must delete its graph projection, and existing successful documents need a rematerialization path without full parsing/reindexing.
- Reference projection nodes must be document-scoped. Do not merge `ref:book:53:hadith:17` globally across documents; use document-scoped projection IDs such as `ref:{document_id}:book:53:hadith:17`. If cross-document canonical references become useful later, add a separate `CanonicalReference` node type and connect document-scoped references to it.
- Neo4j materialization must be transactionally safe. Avoid delete-first partial failure by writing inside one `execute_write()` transaction, or by writing a new `projection_run_id` and making it active only after all nodes/edges are written.
- Materialization should run from committed Postgres state. The preferred path is an outbox/projection record created during indexing and processed after the chunk/index transaction commits.
- Graph expansion must hydrate authoritative chunk text from Postgres before answer generation. `text_preview` is only a graph inspection/debug fallback, not final answer evidence.

---

### Task 1: Add Shared Graph Workspace Helpers

**Files:**
- Create: `backend/src/ragstudio/services/graph_workspace.py`
- Test: `backend/tests/test_graph_workspace.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_graph_workspace.py`:

```python
from types import SimpleNamespace

from ragstudio.services.graph_workspace import (
    chunk_graph_id,
    graph_relationship_type,
    reference_graph_id,
    workspace_label,
)


def test_workspace_label_sanitizes_profile_id():
    profile = SimpleNamespace(id="tenant` one")

    assert workspace_label(profile) == "ragstudio_tenant__one"


def test_workspace_label_defaults_when_profile_id_is_missing():
    profile = SimpleNamespace()

    assert workspace_label(profile) == "ragstudio_default"


def test_chunk_graph_id_is_stable_for_persisted_chunk():
    assert (
        chunk_graph_id(document_id="doc-1", chunk_id="chunk-9")
        == "chunk:doc-1:chunk-9"
    )


def test_reference_graph_id_scopes_reference_to_document():
    assert (
        reference_graph_id(document_id="doc-1", reference="book:53:hadith:17")
        == "ref:doc-1:book:53:hadith:17"
    )
    assert (
        reference_graph_id(document_id="doc-1", reference="ref:book:53:hadith:17")
        == "ref:doc-1:book:53:hadith:17"
    )


def test_graph_relationship_type_is_neo4j_safe():
    assert graph_relationship_type("next_hadith") == "NEXT_HADITH"
    assert graph_relationship_type("same-book") == "SAME_BOOK"
    assert graph_relationship_type(" references ") == "REFERENCES"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
./.venv/bin/pytest backend/tests/test_graph_workspace.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.graph_workspace'`.

- [ ] **Step 3: Implement shared helpers**

Create `backend/src/ragstudio/services/graph_workspace.py`:

```python
from __future__ import annotations

from typing import Any


def workspace_label(profile: Any) -> str:
    raw = f"ragstudio_{getattr(profile, 'id', 'default')}"
    safe = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in raw
    ).strip("_")
    return (safe or "ragstudio_default").replace("`", "``")


def chunk_graph_id(*, document_id: str, chunk_id: str) -> str:
    return f"chunk:{document_id}:{chunk_id}"


def reference_graph_id(*, document_id: str, reference: str) -> str:
    normalized = reference.strip()
    if normalized.startswith("ref:"):
        normalized = normalized.removeprefix("ref:")
    return f"ref:{document_id}:{normalized}"


def graph_relationship_type(value: str) -> str:
    normalized = value.strip().replace("-", "_").replace(" ", "_")
    safe = "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in normalized
    )
    collapsed = "_".join(part for part in safe.split("_") if part)
    return (collapsed or "RELATED").upper()
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
./.venv/bin/pytest backend/tests/test_graph_workspace.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/graph_workspace.py backend/tests/test_graph_workspace.py
git commit -m "Add graph workspace helpers"
```

---

### Task 2: Add Graph Materialization Service

**Files:**
- Create: `backend/src/ragstudio/services/graph_materialization_service.py`
- Test: `backend/tests/test_graph_materialization_service.py`

- [ ] **Step 1: Write fake driver and materialization tests**

Create `backend/tests/test_graph_materialization_service.py`:

```python
from types import SimpleNamespace

import pytest
from ragstudio.db.models import Chunk
from ragstudio.services.graph_materialization_service import GraphMaterializationService


class FakeSession:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def run(self, query, **params):
        self.calls.append((query, params))
        return []

    def execute_write(self, callback):
        return callback(self)


class FakeDriver:
    def __init__(self):
        self.session_instance = FakeSession()
        self.closed = False

    def session(self):
        return self.session_instance

    def close(self):
        self.closed = True


def profile():
    return SimpleNamespace(
        id="default",
        neo4j_uri="bolt://neo4j:7687",
        neo4j_username="neo4j",
        neo4j_password="secret",
    )


def chunk_with_relationships():
    return Chunk(
        id="chunk-1",
        document_id="doc-1",
        text="Book 53, Hadith 17 says justice among people is charity.",
        source_location={"page": 10},
        metadata_json={
            "runtime_source_id": "runtime-1",
            "reference_metadata": {
                "references": ["book:53:hadith:17"],
                "next_ref": "book:53:hadith:18",
            },
            "relationship_metadata": {
                "references": ["book:53:hadith:17"],
                "graph_relationships": [
                    {
                        "type": "references",
                        "source": "chunk:0",
                        "target": "ref:book:53:hadith:17",
                        "evidence": "reference_metadata",
                    },
                    {
                        "type": "next_hadith",
                        "source": "ref:book:53:hadith:17",
                        "target": "ref:book:53:hadith:18",
                        "evidence": "reference_metadata",
                    },
                ],
            },
        },
        runtime_profile_id="default",
        runtime_source_id="runtime-1",
        content_type="text",
    )


@pytest.mark.asyncio
async def test_replace_document_graph_deletes_and_rebuilds_projection():
    driver = FakeDriver()
    service = GraphMaterializationService(driver_factory=lambda *args, **kwargs: driver)

    result = await service.replace_document_graph(
        document_id="doc-1",
        profile=profile(),
        chunks=[chunk_with_relationships()],
    )

    calls = driver.session_instance.calls
    assert "DETACH DELETE" in calls[0][0]
    assert calls[0][1]["document_id"] == "doc-1"
    assert calls[1][1]["chunk_nodes"][0]["chunk_id"] == "chunk-1"
    assert calls[1][1]["chunk_nodes"][0]["id"] == "chunk:doc-1:chunk-1"
    assert calls[1][1]["reference_nodes"][0]["id"] == "ref:doc-1:book:53:hadith:17"
    relationship_types = {
        relationship["type"]
        for _, params in calls[2:]
        for relationship in params["relationships"]
    }
    assert relationship_types == {"REFERENCES", "NEXT_HADITH"}
    assert result.node_count == 3
    assert result.edge_count == 2
    assert driver.closed is True


@pytest.mark.asyncio
async def test_replace_document_graph_skips_when_neo4j_uri_missing():
    service = GraphMaterializationService(driver_factory=lambda *args, **kwargs: None)
    result = await service.replace_document_graph(
        document_id="doc-1",
        profile=SimpleNamespace(id="default", neo4j_uri=None),
        chunks=[chunk_with_relationships()],
    )

    assert result.status == "skipped"
    assert result.reason == "neo4j_uri_missing"
    assert result.node_count == 0
    assert result.edge_count == 0
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
./.venv/bin/pytest backend/tests/test_graph_materialization_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.graph_materialization_service'`.

- [ ] **Step 3: Implement materialization service**

Create `backend/src/ragstudio/services/graph_materialization_service.py`:

```python
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from ragstudio.db.models import Chunk
from ragstudio.services.graph_workspace import (
    chunk_graph_id,
    graph_relationship_type,
    reference_graph_id,
    workspace_label,
)


@dataclass(frozen=True)
class GraphMaterializationResult:
    status: str
    node_count: int
    edge_count: int
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "reason": self.reason,
        }


class GraphMaterializationService:
    def __init__(self, *, driver_factory: Any | None = None):
        self.driver_factory = driver_factory

    async def replace_document_graph(
        self,
        *,
        document_id: str,
        profile: Any,
        chunks: list[Chunk],
    ) -> GraphMaterializationResult:
        if not getattr(profile, "neo4j_uri", None):
            return GraphMaterializationResult(
                status="skipped",
                node_count=0,
                edge_count=0,
                reason="neo4j_uri_missing",
            )

        driver = self._driver(profile)
        if driver is None:
            return GraphMaterializationResult(
                status="skipped",
                node_count=0,
                edge_count=0,
                reason="driver_unavailable",
            )

        label = workspace_label(profile)
        chunk_nodes, reference_nodes, relationships = self._projection(document_id, chunks)
        try:
            await asyncio.to_thread(
                self._replace_graph,
                driver,
                workspace_label=label,
                document_id=document_id,
                chunk_nodes=chunk_nodes,
                reference_nodes=reference_nodes,
                relationships=relationships,
            )
        except Exception as exc:
            return GraphMaterializationResult(
                status="failed",
                node_count=0,
                edge_count=0,
                reason=str(exc),
            )
        finally:
            close = getattr(driver, "close", None)
            if close is not None:
                await asyncio.to_thread(close)

        return GraphMaterializationResult(
            status="succeeded",
            node_count=len(chunk_nodes) + len(reference_nodes),
            edge_count=len(relationships),
        )

    def _driver(self, profile: Any) -> Any:
        try:
            if self.driver_factory is not None:
                return self.driver_factory(getattr(profile, "neo4j_uri"), auth=_auth(profile))
            graph_database = import_module("neo4j").GraphDatabase
            return graph_database.driver(getattr(profile, "neo4j_uri"), auth=_auth(profile))
        except (ImportError, ModuleNotFoundError, RuntimeError, OSError):
            return None

    def _projection(
        self,
        document_id: str,
        chunks: list[Chunk],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        chunk_nodes: list[dict[str, Any]] = []
        reference_nodes_by_id: dict[str, dict[str, Any]] = {}
        relationships: list[dict[str, Any]] = []
        legacy_to_chunk_id: dict[str, str] = {}

        for index, chunk in enumerate(chunks):
            node_id = chunk_graph_id(document_id=document_id, chunk_id=chunk.id)
            legacy_to_chunk_id[f"chunk:{index}"] = node_id
            metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
            references = _references(metadata)
            for reference in references:
                ref_id = reference_graph_id(document_id=document_id, reference=reference)
                reference_nodes_by_id.setdefault(
                    ref_id,
                    {
                        "id": ref_id,
                        "reference": reference,
                        "document_id": document_id,
                    },
                )
            chunk_nodes.append(
                {
                    "id": node_id,
                    "chunk_id": chunk.id,
                    "document_id": document_id,
                    "runtime_source_id": chunk.runtime_source_id,
                    "source_id": metadata.get("source_id"),
                    "text_preview": chunk.text[:500],
                    "content_type": chunk.content_type,
                    **_source_location_properties(chunk.source_location),
                    "references": references,
                }
            )

        for chunk in chunks:
            metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
            relationship_metadata = metadata.get("relationship_metadata")
            if not isinstance(relationship_metadata, dict):
                continue
            for relationship in relationship_metadata.get("graph_relationships", []):
                if not isinstance(relationship, dict):
                    continue
                source = _graph_node_id(
                    str(relationship.get("source") or ""),
                    legacy_to_chunk_id,
                    document_id=document_id,
                )
                target = _graph_node_id(
                    str(relationship.get("target") or ""),
                    legacy_to_chunk_id,
                    document_id=document_id,
                )
                rel_type = graph_relationship_type(str(relationship.get("type") or "RELATED"))
                if not source or not target:
                    continue
                if source.startswith("ref:"):
                    reference_nodes_by_id.setdefault(
                        source,
                        {
                            "id": source,
                            "reference": _reference_value_from_node_id(source, document_id),
                            "document_id": document_id,
                        },
                    )
                if target.startswith("ref:"):
                    reference_nodes_by_id.setdefault(
                        target,
                        {
                            "id": target,
                            "reference": _reference_value_from_node_id(target, document_id),
                            "document_id": document_id,
                        },
                    )
                relationships.append(
                    {
                        "source": source,
                        "target": target,
                        "type": rel_type,
                        "document_id": document_id,
                        "evidence": relationship.get("evidence"),
                    }
                )

        return chunk_nodes, list(reference_nodes_by_id.values()), relationships

    def _replace_graph(
        self,
        driver: Any,
        *,
        workspace_label: str,
        document_id: str,
        chunk_nodes: list[dict[str, Any]],
        reference_nodes: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
    ) -> None:
        def write_transaction(tx: Any) -> None:
            tx.run(delete_query, document_id=document_id)
            tx.run(
                upsert_nodes_query,
                chunk_nodes=chunk_nodes,
                reference_nodes=reference_nodes,
            )
            for rel_type in sorted({relationship["type"] for relationship in relationships}):
                typed_relationships = [
                    relationship
                    for relationship in relationships
                    if relationship["type"] == rel_type
                ]
                tx.run(
                    f"""
                    UNWIND $relationships AS rel
                    MATCH (source:`{workspace_label}` {{id: rel.source, document_id: rel.document_id}})
                    MATCH (target:`{workspace_label}` {{id: rel.target, document_id: rel.document_id}})
                    MERGE (source)-[relationship:`{rel_type}` {{document_id: rel.document_id}}]->(target)
                    SET relationship.evidence = rel.evidence
                    """,
                    relationships=typed_relationships,
                )

        delete_query = f"""
        MATCH (n:`{workspace_label}`)
        WHERE n.document_id = $document_id
        DETACH DELETE n
        """
        upsert_nodes_query = f"""
        UNWIND $chunk_nodes AS node
        MERGE (chunk:`{workspace_label}` {{id: node.id}})
        SET chunk:Chunk:RagstudioChunk,
            chunk.chunk_id = node.chunk_id,
            chunk.document_id = node.document_id,
            chunk.runtime_source_id = node.runtime_source_id,
            chunk.source_id = node.source_id,
            chunk.text_preview = node.text_preview,
            chunk.content_type = node.content_type,
            chunk.page = node.page,
            chunk.section = node.section,
            chunk.start_index = node.start_index,
            chunk.end_index = node.end_index,
            chunk.source_location_json = node.source_location_json,
            chunk.references = node.references
        WITH 1 AS ignored
        UNWIND $reference_nodes AS node
        MERGE (ref:`{workspace_label}` {{id: node.id}})
        SET ref:Reference:RagstudioReference,
            ref.reference = node.reference,
            ref.document_id = node.document_id
        """
        with driver.session() as session:
            session.execute_write(write_transaction)


def _auth(profile: Any) -> tuple[str, str] | None:
    username = getattr(profile, "neo4j_username", None)
    password = getattr(profile, "neo4j_password", None)
    if username or password:
        return (username or "", password or "")
    return None


def _references(metadata: dict[str, Any]) -> list[str]:
    reference_metadata = metadata.get("reference_metadata")
    if not isinstance(reference_metadata, dict):
        return []
    references = reference_metadata.get("references")
    if not isinstance(references, list):
        return []
    return [str(reference) for reference in references if reference is not None]


def _source_location_properties(value: Any) -> dict[str, Any]:
    source_location = value if isinstance(value, dict) else {}
    return {
        "page": source_location.get("page"),
        "section": source_location.get("section"),
        "start_index": source_location.get("start_index"),
        "end_index": source_location.get("end_index"),
        "source_location_json": json.dumps(source_location, ensure_ascii=False)
        if source_location
        else None,
    }


def _graph_node_id(
    value: str,
    legacy_to_chunk_id: dict[str, str],
    *,
    document_id: str,
) -> str:
    if not value:
        return ""
    if value in legacy_to_chunk_id:
        return legacy_to_chunk_id[value]
    if value.startswith("ref:"):
        return reference_graph_id(document_id=document_id, reference=value)
    if value.startswith("chunk:"):
        return value
    return reference_graph_id(document_id=document_id, reference=value)


def _reference_value_from_node_id(node_id: str, document_id: str) -> str:
    prefix = f"ref:{document_id}:"
    if node_id.startswith(prefix):
        return node_id.removeprefix(prefix)
    return node_id.removeprefix("ref:")
```

Implementation note: prefer actual write counts from Cypher `RETURN count(...)` or Neo4j result summaries over intended counts from `len(...)`, especially for relationships where a missing source/target `MATCH` can otherwise make diagnostics lie.

- [ ] **Step 4: Run tests**

Run:

```bash
./.venv/bin/pytest backend/tests/test_graph_materialization_service.py backend/tests/test_graph_workspace.py -q
```

Expected: PASS.

- [ ] **Step 5: Verify there is no APOC dependency**

Run against local Neo4j:

```bash
rg -n "apoc\\." backend/src/ragstudio/services/graph_materialization_service.py
```

Expected: no matches. The materializer groups relationships by sanitized type and uses native `MERGE`.

- [ ] **Step 6: Add Neo4j indexes for projection reads**

Add a small setup step in `GraphMaterializationService` before writes, using stable labels so Neo4j can optimize document-scoped lookups even though workspace labels are dynamic:

```cypher
CREATE INDEX ragstudio_chunk_projection IF NOT EXISTS
FOR (n:RagstudioChunk)
ON (n.document_id, n.id);

CREATE INDEX ragstudio_reference_projection IF NOT EXISTS
FOR (n:RagstudioReference)
ON (n.document_id, n.id);
```

Relationship type names must come from sanitized values that are also allowed by `relationship_metadata.graph_profile.edge_types`. Unknown edge types should become `RELATED` or be skipped with a traceable reason instead of creating unbounded schema sprawl.

Run:

```bash
./.venv/bin/pytest backend/tests/test_graph_materialization_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/graph_materialization_service.py backend/tests/test_graph_materialization_service.py
git commit -m "Add graph materialization service"
```

---

### Task 3: Add Durable Graph Projection Status

**Files:**
- Modify: `backend/src/ragstudio/db/models.py`
- Modify: `backend/src/ragstudio/db/engine.py` if table initialization has explicit model imports
- Test: `backend/tests/test_graph_materialization_service.py`
- Test: `backend/tests/test_mineru_reindex_jobs.py`

- [ ] **Step 1: Add `GraphProjectionRecord` model**

Add a durable projection-status row keyed by document/profile. This keeps graph state out of `IndexRecord.index_shape` while making diagnostics, retry, and backfill possible.

```python
class GraphProjectionRecord(Base, TimestampMixin):
    __tablename__ = "graph_projection_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    runtime_profile_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")
    projection_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    node_count: Mapped[int] = mapped_column(Integer, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Add an index/constraint appropriate for the current database setup:

```python
Index(
    "ix_graph_projection_document_profile",
    "document_id",
    "runtime_profile_id",
)
```

- [ ] **Step 2: Use records as the materialization outbox**

During indexing, create or update a `GraphProjectionRecord(status="pending")` in the same Postgres transaction that persists chunks and `IndexRecord`. After that transaction commits, materialize Neo4j from committed chunks and update the record to `succeeded`, `failed`, or `skipped`.

Implementation contract:

- `IndexRecord.index_shape` remains exactly `profile.index_shape`.
- `GraphProjectionRecord` is the durable graph status.
- `job.result.graph_materialization` is the user-visible copy of the latest graph projection status.
- A failed graph projection does not invalidate the document's chunk/index success.

- [ ] **Step 3: Add tests**

Tests should prove:

- indexing creates a pending projection record;
- successful materialization updates it to `succeeded` with counts;
- failed materialization updates it to `failed` with `error`;
- query readiness still accepts the document because `IndexRecord.index_shape` was not changed.

Run:

```bash
./.venv/bin/pytest backend/tests/test_graph_materialization_service.py backend/tests/test_mineru_reindex_jobs.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/src/ragstudio/db/models.py backend/src/ragstudio/db/engine.py backend/tests/test_graph_materialization_service.py backend/tests/test_mineru_reindex_jobs.py
git commit -m "Add graph projection status records"
```

---

### Task 4: Integrate Materialization Into Runtime Indexing

**Files:**
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py:1-160`
- Modify: `backend/src/ragstudio/services/document_service.py:326-360`
- Create: `backend/src/ragstudio/services/graph_projection_runner.py`
- Test: `backend/tests/test_mineru_reindex_jobs.py`

- [ ] **Step 1: Write failing integration test**

Append to `backend/tests/test_mineru_reindex_jobs.py`:

```python
from ragstudio.db.models import GraphProjectionRecord
from ragstudio.services.index_lifecycle_service import IndexLifecycleService


@pytest.mark.asyncio
async def test_runtime_reindex_materializes_graph_projection(
    tmp_path,
    database_url,
    monkeypatch,
):
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine)

    async with session_factory() as session:
        artifact = tmp_path / "doc.pdf"
        artifact.write_bytes(b"%PDF-1.4")
        settings = SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="gpt-4o",
            llm_base_url="http://127.0.0.1:8004/v1",
            embedding_model="text-embedding-3-large",
            embedding_base_url="http://127.0.0.1:8001/v1",
            storage_backend="postgres_pgvector_neo4j",
            runtime_mode="runtime",
            neo4j_uri="bolt://neo4j:7687",
            neo4j_username="neo4j",
            neo4j_password="secret",
        )
        document = Document(
            filename="doc.pdf",
            content_type="application/pdf",
            sha256="graph-materialization-sha",
            artifact_path=str(artifact),
            status="ready",
        )
        session.add_all([settings, document])
        await session.flush()

        class FakeRuntime:
            async def delete_document_index(self, document_id):
                return None

            async def index_preparsed_chunks(self, artifact_path, chunks, *, document_id):
                return [
                    type(
                        "RuntimeChunk",
                        (),
                        {
                            "text": "Book 53, Hadith 17",
                            "source_location": {"page": 1},
                            "metadata": {
                                "reference_metadata": {
                                    "references": ["book:53:hadith:17"],
                                },
                                "relationship_metadata": {
                                    "graph_relationships": [
                                        {
                                            "type": "references",
                                            "source": "chunk:0",
                                            "target": "ref:book:53:hadith:17",
                                            "evidence": "reference_metadata",
                                        }
                                    ]
                                },
                            },
                        },
                    )()
                ]

        class FakeRuntimeFactory:
            def build(self, profile):
                return FakeRuntime()

        async def fake_preparse(self, runtime, document, options, *, on_mineru_status=None):
            return [
                type(
                    "AdapterChunkLike",
                    (),
                    {
                        "text": "Book 53, Hadith 17",
                        "source_location": {"page": 1},
                        "metadata": {
                            "reference_metadata": {
                                "references": ["book:53:hadith:17"],
                            },
                            "relationship_metadata": {
                                "graph_relationships": [
                                    {
                                        "type": "references",
                                        "source": "chunk:0",
                                        "target": "ref:book:53:hadith:17",
                                        "evidence": "reference_metadata",
                                    }
                                ]
                            },
                        },
                        "runtime_source_id": None,
                        "content_type": "text",
                        "preview_ref": None,
                    },
                )()
            ]

        monkeypatch.setattr(
            IndexLifecycleService,
            "_preparse_runtime_document",
            fake_preparse,
        )

        service = IndexLifecycleService(
            session,
            type(
                "Settings",
                (),
                {
                    "data_dir": tmp_path,
                    "resolved_runtime_working_dir": tmp_path / "runtime",
                    "neo4j_uri": "bolt://neo4j:7687",
                    "neo4j_username": "neo4j",
                    "neo4j_password": "secret",
                },
            )(),
            runtime_factory=FakeRuntimeFactory(),
        )
        result = await service.reindex_document(document.id, options=IndexDocumentIn())

        assert result is not None
        assert result.graph_materialization["status"] == "pending"
        projection_record = await session.scalar(
            select(GraphProjectionRecord).where(
                GraphProjectionRecord.document_id == document.id
            )
        )
        assert projection_record is not None
        assert projection_record.status == "pending"
        assert projection_record.runtime_profile_id == "default"

    await engine.dispose()
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
./.venv/bin/pytest backend/tests/test_mineru_reindex_jobs.py::test_runtime_reindex_materializes_graph_projection -q
```

Expected: FAIL because `IndexLifecycleService.reindex_document()` still returns a raw chunk list and does not create a `GraphProjectionRecord`.

- [ ] **Step 3: Add projection result to index lifecycle**

Modify `backend/src/ragstudio/services/index_lifecycle_service.py`.

Add import:

```python
from dataclasses import dataclass

from ragstudio.db.models import GraphProjectionRecord
```

Add an explicit lifecycle return type instead of storing graph state on the service instance:

```python
@dataclass(frozen=True)
class IndexLifecycleResult:
    chunks: list[ChunkOut]
    graph_projection_record_id: str | None
    graph_materialization: dict[str, Any]
```

Change constructor:

```python
def __init__(
    self,
    session: AsyncSession,
    settings: AppSettings,
    *,
    runtime_factory: Any | None = None,
    health_service: RuntimeHealthService | None = None,
    normalizer: TraceNormalizer | None = None,
):
    self.session = session
    self.settings = settings
    self.runtime_factory = runtime_factory or self._runtime_factory(settings)
    self.health_service = health_service or self._health_service(session)
    self.normalizer = normalizer or TraceNormalizer()
```

After chunk rows are added and flushed, create a pending graph projection record. Keep the runtime index shape unchanged and do not write to Neo4j inside this uncommitted Postgres transaction:

```python
self.session.add_all(chunks)
await self.session.flush()
projection_record = GraphProjectionRecord(
    document_id=document.id,
    runtime_profile_id=profile.id,
    status="pending",
    node_count=0,
    edge_count=0,
)
self.session.add(projection_record)
self.session.add(
    IndexRecord(
        document_id=document.id,
        runtime_profile_id=profile.id,
        status=StageStatus.SUCCEEDED.value,
        index_shape=profile.index_shape,
        chunk_count=len(chunks),
    )
)
document.status = StageStatus.SUCCEEDED.value
for chunk in chunks:
    await self.session.refresh(chunk)
return IndexLifecycleResult(
    chunks=[ChunkOut.model_validate(chunk) for chunk in chunks],
    graph_projection_record_id=projection_record.id,
    graph_materialization={
        "status": "pending",
        "node_count": 0,
        "edge_count": 0,
        "reason": None,
    },
)
```

Remove the earlier `self.session.add(IndexRecord(...))` block so only one `IndexRecord` is created.

- [ ] **Step 4: Run focused tests**

Run:

```bash
./.venv/bin/pytest backend/tests/test_mineru_reindex_jobs.py::test_runtime_reindex_materializes_graph_projection -q
```

Expected: PASS.

- [ ] **Step 5: Preserve graph counts in job result**

Modify `DocumentService._index_document_for_job()` in `backend/src/ragstudio/services/document_service.py`.

Hold the `IndexLifecycleResult` in a local variable. After the indexing transaction commits, materialize Neo4j from committed Postgres chunks and update `GraphProjectionRecord`; then copy the durable projection status into `job.result`:

```python
index_service = IndexLifecycleService(self.session, self.settings)
lifecycle_result = await index_service.reindex_document(
    document.id,
    options=options,
    on_mineru_status=on_mineru_status,
)
chunks = lifecycle_result.chunks if lifecycle_result is not None else []
graph_materialization = dict(
    lifecycle_result.graph_materialization if lifecycle_result is not None else {}
)
```

Then, in the outer indexing flow after the chunk/index transaction commits, run graph materialization from the committed chunks:

```python
graph_materialization = await GraphProjectionRunner(
    self.session,
    self.settings,
).materialize_pending(document.id)
job.result = {
    **job.result,
    "graph_materialization": graph_materialization,
}
await self.session.commit()
```

The runner should load the latest pending `GraphProjectionRecord`, load `Chunk` rows from Postgres, call `GraphMaterializationService.replace_document_graph()`, update the projection record, and return `GraphMaterializationResult.to_dict()`.

Create `backend/src/ragstudio/services/graph_projection_runner.py` for this orchestration instead of putting Neo4j retry/status logic directly in `DocumentService`.

Set job result:

```python
job.result = {
    **job.result,
    "document_id": document.id,
    "chunk_count": chunk_count,
    "graph_materialization": graph_materialization,
}
```

Add import if missing:

```python
from ragstudio.db.models import Document, GraphProjectionRecord, Job
```

- [ ] **Step 6: Add projection and job-result assertions**

Extend `test_runtime_reindex_materializes_graph_projection` to prove runtime readiness metadata remains stable and projection status is stored separately:

```python
latest_index = await session.scalar(
    select(IndexRecord)
    .where(IndexRecord.document_id == document.id)
    .order_by(IndexRecord.created_at.desc())
    .limit(1)
)
assert latest_index is not None
assert "graph_materialization" not in latest_index.index_shape
assert latest_index.index_shape["graph_storage"] == "neo4j"

projection_record = await session.scalar(
    select(GraphProjectionRecord)
    .where(GraphProjectionRecord.document_id == document.id)
    .order_by(GraphProjectionRecord.created_at.desc())
    .limit(1)
)
assert projection_record is not None
assert projection_record.status == "pending"
assert projection_record.node_count == 0
assert projection_record.edge_count == 0
```

Add a separate `DocumentService` or `GraphProjectionRunner` test proving the post-commit runner updates `GraphProjectionRecord` to `succeeded` and copies that status into `job.result["graph_materialization"]`.

Run:

```bash
./.venv/bin/pytest backend/tests/test_mineru_reindex_jobs.py::test_runtime_reindex_materializes_graph_projection -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/index_lifecycle_service.py backend/src/ragstudio/services/document_service.py backend/src/ragstudio/services/graph_projection_runner.py backend/tests/test_mineru_reindex_jobs.py
git commit -m "Materialize graph during indexing"
```

---

### Task 5: Make Graph Expansion Follow Reference Paths

**Files:**
- Modify: `backend/src/ragstudio/services/graph_expansion_service.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Test: `backend/tests/test_graph_expansion_service.py`

- [ ] **Step 1: Add failing test for chunk -> reference -> neighbor reference -> chunk**

Append to `backend/tests/test_graph_expansion_service.py`:

```python
@pytest.mark.asyncio
async def test_graph_expansion_can_follow_reference_path_to_neighbor_chunk():
    driver = FakeDriver(
        [
            FakeRecord(
                relationship_id="rel-path-1",
                relationship_type="NEXT_HADITH",
                relationship_properties={"evidence": "reference_metadata"},
                seed_properties={"chunk_id": "seed-1"},
                neighbor_id="chunk-node-2",
                neighbor_labels=["Chunk"],
                neighbor_properties={
                    "id": "chunk:doc-1:neighbor-1",
                    "chunk_id": "neighbor-1",
                    "document_id": "doc-1",
                    "text_preview": "Book 1 Hadith 2",
                    "page": 2,
                },
            )
        ]
    )
    service = GraphExpansionService(driver_factory=lambda *args, **kwargs: driver)

    candidates, traces = await service.expand(
        "show next hadith",
        seeds=[seed_candidate()],
        profile=profile(),
        document_ids=["doc-1"],
        limit=4,
    )

    query, params = driver.session_instance.calls[0]
    assert "referenced_seed" in query
    assert "neighbor_ref" in query
    assert params["seed_ids"] == ["seed-1", "seed-runtime"]
    assert candidates[0].chunk_id == "neighbor-1"
    assert candidates[0].metadata["graph_relationship"]["type"] == "NEXT_HADITH"
    assert traces[0]["expanded_candidates"] == 1
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
./.venv/bin/pytest backend/tests/test_graph_expansion_service.py::test_graph_expansion_can_follow_reference_path_to_neighbor_chunk -q
```

Expected: FAIL because the query does not contain `referenced_seed` or `neighbor_ref`.

- [ ] **Step 3: Update graph expansion Cypher**

Modify `_run_query()` in `backend/src/ragstudio/services/graph_expansion_service.py`.

Keep graph expansion ID-first. Neo4j should return candidate chunk IDs, relationship metadata, and path evidence. The final answer path must hydrate full text and authoritative metadata from Postgres before scoring/reranking. `text_preview` may remain in Neo4j for graph inspection, but it is not final answer evidence.

Replace the current Cypher with:

```python
cypher = f"""
MATCH (seed:`{workspace_label}`)
WHERE coalesce(
    seed.chunk_id,
    seed.runtime_source_id,
    seed.id,
    seed.source_id
) IN $seed_ids
CALL {{
    WITH seed
    MATCH (seed)-[relationship]-(neighbor:`{workspace_label}`)
    RETURN relationship,
           neighbor,
           properties(seed) AS seed_properties
    UNION
    WITH seed
    MATCH (seed)-[:REFERENCES]->(referenced_seed:`{workspace_label}`)
    MATCH (referenced_seed)-[relationship]-(neighbor_ref:`{workspace_label}`)
    MATCH (neighbor_chunk:`{workspace_label}`)-[:REFERENCES]->(neighbor_ref)
    WHERE neighbor_chunk.id <> seed.id
    RETURN relationship,
           neighbor_chunk AS neighbor,
           properties(seed) AS seed_properties
	}}
	WHERE "Chunk" IN labels(neighbor)
	AND coalesce(neighbor.chunk_id, neighbor.id) <> coalesce(seed.chunk_id, seed.id)
	AND (
	    size($document_ids) = 0
	    OR coalesce(
	        neighbor.document_id,
	        neighbor.full_doc_id,
	        neighbor.doc_id
	    ) IN $document_ids
	)
	WITH relationship, neighbor, seed_properties, coalesce(relationship.weight, 1.0) AS path_weight
	RETURN elementId(relationship) AS relationship_id,
	       type(relationship) AS relationship_type,
	       properties(relationship) AS relationship_properties,
	       seed_properties,
	       elementId(neighbor) AS neighbor_id,
	       labels(neighbor) AS neighbor_labels,
	       properties(neighbor) AS neighbor_properties
	ORDER BY path_weight DESC
	LIMIT $limit
	"""
```

Before finishing this task, add a dedupe step in Python so the same `chunk_id` is returned once even if it is reachable through both a direct edge and a reference path.

Add real Postgres hydration before final fusion. `GraphExpansionService` may still produce lightweight graph candidates, but `RetrievalOrchestrator` must replace graph candidate text/source metadata with authoritative `Chunk` rows before rerank/answer generation.

Add a chunk lookup helper:

```python
async def chunks_by_id(self, chunk_ids: list[str]) -> dict[str, ChunkOut]:
    result = await self.session.execute(select(Chunk).where(Chunk.id.in_(chunk_ids)))
    return {
        chunk.id: ChunkOut.model_validate(chunk)
        for chunk in result.scalars().all()
    }
```

Then hydrate graph candidates in the orchestrator:

```python
async def _hydrate_graph_candidates(
    self,
    candidates: list[EvidenceCandidate],
) -> list[EvidenceCandidate]:
    by_id = await self.chunk_service.chunks_by_id(
        [candidate.chunk_id for candidate in candidates if candidate.chunk_id]
    )
    hydrated: list[EvidenceCandidate] = []
    for candidate in candidates:
        chunk = by_id.get(candidate.chunk_id or "")
        if chunk is None:
            continue
        hydrated.append(
            EvidenceCandidate(
                candidate_id=candidate.candidate_id,
                text=chunk.text,
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                source_location=chunk.source_location,
                metadata={**chunk.metadata, "graph_relationship": candidate.metadata.get("graph_relationship")},
                tool=candidate.tool,
                tool_rank=candidate.tool_rank,
                base_score=candidate.base_score,
                boost_score=candidate.boost_score,
                final_score=candidate.final_score,
                reasons=candidate.reasons,
            )
        )
    return hydrated
```

If a temporary fallback is needed, `_candidate_from_row()` may read `text_preview`, but add a test proving final answer evidence uses hydrated Postgres `Chunk.text`, not the Neo4j preview.

- [ ] **Step 4: Run graph expansion tests**

Run:

```bash
./.venv/bin/pytest backend/tests/test_graph_expansion_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/graph_expansion_service.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/src/ragstudio/services/chunk_service.py backend/tests/test_graph_expansion_service.py
git commit -m "Expand graph retrieval through references"
```

---

### Task 6: Add Graph Health Diagnostics for Empty Projection

**Files:**
- Modify: `backend/src/ragstudio/services/diagnostics_service.py`
- Modify: `backend/src/ragstudio/services/graph_service.py`
- Test: `backend/tests/test_graph_service.py`

- [ ] **Step 1: Write failing test for metadata relationships without Neo4j projection**

Create `backend/tests/test_graph_service.py` if it does not exist:

```python
import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.services.graph_service import GraphService


@pytest.mark.asyncio
async def test_graph_service_reports_metadata_fallback_when_runtime_graph_empty(
    tmp_path,
    database_url,
):
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine)

    async with session_factory() as session:
        document = Document(
            filename="doc.pdf",
            content_type="application/pdf",
            sha256="graph-service-sha",
            artifact_path=str(tmp_path / "doc.pdf"),
            status="succeeded",
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="Book 53 Hadith 17",
                source_location={"page": 1},
                metadata_json={
                    "relationship_metadata": {
                        "graph_relationships": [
                            {
                                "type": "references",
                                "source": "chunk:0",
                                "target": "ref:book:53:hadith:17",
                            }
                        ]
                    }
                },
            )
        )
        await session.commit()

        graph = await GraphService(
            session=session,
            settings=type("Settings", (), {})(),
        ).get_graph()

    await engine.dispose()

    assert graph.detail == "Relationship metadata fallback graph."
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
```

- [ ] **Step 2: Run test**

Run:

```bash
./.venv/bin/pytest backend/tests/test_graph_service.py -q
```

Expected: PASS if current fallback is already wired. If it fails because `detail` is different, update `GraphService._relationship_metadata_graph()` to return `detail="Relationship metadata fallback graph."` when fallback nodes or edges exist.

- [ ] **Step 3: Add diagnostic copy for the exact operational gap**

Modify `backend/src/ragstudio/services/diagnostics_service.py` to read `GraphProjectionRecord` and include a diagnostic finding when relationship metadata exists but the Neo4j projection is missing, pending, skipped, or failed:

```python
	{
	    "name": "graph_materialization",
	    "status": "warning",
	    "detail": (
	        "Chunks contain relationship metadata but Neo4j projection is not ready. "
	        "Run graph rematerialization or reindex the document."
	    ),
	}
```

Place it in the graph-related diagnostics section where runtime graph availability is summarized. Include the latest projection status, node count, edge count, and error when available.

- [ ] **Step 4: Run diagnostics tests**

Run:

```bash
./.venv/bin/pytest backend/tests/test_graph_service.py backend/tests/test_runtime_health_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/diagnostics_service.py backend/src/ragstudio/services/graph_service.py backend/tests/test_graph_service.py
git commit -m "Report graph materialization health"
```

---

### Task 7: Add Delete and Rematerialization Paths

**Files:**
- Modify: `backend/src/ragstudio/services/graph_materialization_service.py`
- Modify: `backend/src/ragstudio/services/document_service.py`
- Test: `backend/tests/test_graph_materialization_service.py`
- Test: `backend/tests/test_documents.py`

- [ ] **Step 1: Add document graph delete support**

Add `delete_document_graph(document_id, profile)` to `GraphMaterializationService`.

Implementation contract:

```python
async def delete_document_graph(self, *, document_id: str, profile: Any) -> GraphMaterializationResult:
    # Resolve driver and workspace label the same way as replace_document_graph().
    # Run:
    # MATCH (n:`{workspace_label}`)
    # WHERE n.document_id = $document_id
    # DETACH DELETE n
    # Return status/count diagnostics; soft-fail with status="failed" on Neo4j errors.
```

- [ ] **Step 2: Wire document deletion to graph cleanup**

In `DocumentService.delete_document()`, call graph cleanup before committing the document delete. If graph cleanup fails, do not block the user-visible delete; record the failure in logs/diagnostics and continue deleting the Postgres source of truth.

Important: deleting the Postgres document must remain authoritative. Neo4j cleanup is a projection cleanup task and can be retried.

Also delete or mark terminal any `GraphProjectionRecord` rows for the document so diagnostics do not report stale pending work after the source document is gone.

- [ ] **Step 3: Add rematerialization from existing chunks**

Add a service method such as:

```python
async def rematerialize_document_graph(document_id: str, profile: Any) -> GraphMaterializationResult:
    # Load persisted Chunk rows for the document from Postgres.
    # Call replace_document_graph(document_id=document_id, profile=profile, chunks=chunks).
```

This lets existing successful documents gain graph projection without re-running parsing/native indexing.

Rematerialization must create/update a `GraphProjectionRecord` and should be callable by an internal repair script or future admin action.

- [ ] **Step 4: Add tests**

Tests should prove:

- deleting a document calls `delete_document_graph()`;
- graph delete failure does not roll back document deletion;
- rematerialization uses existing chunks and writes the expected relationship projection.

Run:

```bash
./.venv/bin/pytest backend/tests/test_graph_materialization_service.py backend/tests/test_documents.py -q
```

Expected: PASS.

---

### Task 8: End-to-End Local Verification

**Files:**
- No source file changes required unless verification exposes a defect.

- [ ] **Step 1: Restart backend and frontend only**

Run:

```bash
docker compose restart backend frontend
```

Expected: backend and frontend restart while Postgres and Neo4j retain data.

- [ ] **Step 2: Reindex a document**

Use the UI at:

```text
http://localhost:5173/documents
```

Upload or reindex a Quran/Hadith document with domain metadata that includes:

```json
{
  "graph": {
    "node_types": ["book", "chapter", "hadith", "chunk"],
    "edge_types": ["references", "next_hadith", "same_book", "same_chapter"],
    "materialize_from": ["mineru_structure", "reference_metadata"],
    "confidence_policy": "evidence_required"
  }
}
```

Expected: job succeeds and job result includes:

```json
{
  "graph_materialization": {
    "status": "succeeded",
    "node_count": 1,
    "edge_count": 1
  }
}
```

The exact counts depend on document size; both should be greater than zero for a document with references.

- [ ] **Step 3: Verify Neo4j workspace has data**

Run:

```bash
docker exec ragstudio-neo4j cypher-shell -u neo4j -p ragstudio-password 'MATCH (n:`ragstudio_default`) RETURN count(n) AS node_count;'
```

Expected: `node_count` is greater than `0`.

Run:

```bash
docker exec ragstudio-neo4j cypher-shell -u neo4j -p ragstudio-password 'MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS count ORDER BY count DESC LIMIT 10;'
```

Expected: relationship types include at least one of `REFERENCES`, `NEXT_HADITH`, `NEXT_AYAH`, or `NEXT_CHUNK`.

- [ ] **Step 4: Verify graph retrieval returns candidates**

Run a query that should follow a graph edge:

```bash
python3 - <<'PY'
import json, urllib.request

def get(path):
    with urllib.request.urlopen("http://localhost:8000" + path, timeout=30) as response:
        return json.loads(response.read().decode())

variants = get("/api/variants")["items"]
variant = variants[0]
document_id = "REPLACE_WITH_THE_DOCUMENT_ID_REINDEXED_IN_STEP_2"
payload = {
    "query": "what comes after Book 53 Hadith 17",
    "document_ids": [document_id],
    "variant_ids": [variant["id"]],
    "limit": 8,
}
req = urllib.request.Request(
    "http://localhost:8000/api/query",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=300) as response:
    data = json.loads(response.read().decode())
run = data["runs"][0]
print(json.dumps(run["chunk_traces"], indent=2, ensure_ascii=False))
PY
```

Expected: trace contains:

```json
{
  "stage": "graph_expansion",
  "status": "ok",
  "expanded_candidates": 1
}
```

Use the exact document ID from the Step 2 upload/reindex job. Do not use the first succeeded document in the library; that can accidentally verify an older projection.

Use actual IDs from:

```bash
python3 - <<'PY'
import json, urllib.request
for path in ["/api/documents", "/api/variants"]:
    with urllib.request.urlopen("http://localhost:8000" + path, timeout=30) as response:
        print(path, response.read().decode())
PY
```

- [ ] **Step 5: Run focused regression suite**

Run:

```bash
./.venv/bin/ruff check backend/src/ragstudio/db/models.py backend/src/ragstudio/services/graph_workspace.py backend/src/ragstudio/services/graph_materialization_service.py backend/src/ragstudio/services/graph_projection_runner.py backend/src/ragstudio/services/graph_expansion_service.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/src/ragstudio/services/chunk_service.py backend/src/ragstudio/services/index_lifecycle_service.py backend/src/ragstudio/services/document_service.py backend/tests/test_graph_workspace.py backend/tests/test_graph_materialization_service.py backend/tests/test_graph_expansion_service.py backend/tests/test_mineru_reindex_jobs.py
./.venv/bin/pytest backend/tests/test_graph_workspace.py backend/tests/test_graph_materialization_service.py backend/tests/test_graph_expansion_service.py backend/tests/test_mineru_reindex_jobs.py backend/tests/test_documents.py -q
```

Expected: ruff passes and pytest passes.

- [ ] **Step 6: Commit verification fixes if needed**

If verification required code fixes, commit them:

```bash
git add backend/src/ragstudio backend/tests
git commit -m "Verify graph materialization retrieval"
```

If no fixes were required, do not create an empty commit.

---

## Self-Review

**Spec coverage:** This plan covers the requested long-term architecture: Ragstudio-owned graph projection records during indexing, post-commit Neo4j materialization from `relationship_metadata.graph_relationships`, retrieval expansion over that projection, graph health diagnostics, delete/rematerialization paths, and local verification.

**Placeholder scan:** The plan contains concrete file paths, function names, tests, commands, and expected results. It intentionally avoids open-ended implementation instructions.

**Type consistency:** `GraphMaterializationResult`, `GraphProjectionRecord`, `IndexLifecycleResult`, `GraphMaterializationService.replace_document_graph`, `workspace_label`, `chunk_graph_id`, `reference_graph_id`, and `graph_relationship_type` are introduced before later tasks consume them. `IndexLifecycleService` creates durable pending projection records while preserving `IndexRecord.index_shape` as the runtime readiness contract; `GraphProjectionRunner` performs post-commit Neo4j materialization from persisted `Chunk` rows.

**Architecture decision:** Postgres is the source of truth. Neo4j is a rebuildable retrieval projection with document-scoped reference nodes. RAG-Anything remains useful for parsing/native indexing, while Ragstudio owns domain graph semantics and document-scoped graph retrieval. Graph failures degrade retrieval quality but should not destroy a successful chunk/index write unless a future profile explicitly requires graph.
