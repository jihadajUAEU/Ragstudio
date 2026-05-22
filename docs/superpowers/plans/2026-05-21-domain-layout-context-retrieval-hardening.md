# Domain Layout Context Retrieval Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Ragstudio's domain-aware, layout-aware, context-aware chunking strategy explicit from upload through persistence, quality gates, vector/runtime materialization, and retrieval.

**Architecture:** Store the compiled indexing contract at the document level, keep chunk-level canonical evidence as the source of truth, and route retrieval lanes from the persisted contract plus per-chunk quality policy. Wire the currently scaffolded vector lane to a real bounded canonical candidate source and add layout/context ranking signals without making live vision calls during queries.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async ORM, Pydantic, PostgreSQL JSONB/pgvector-ready metadata, pytest.

---

## File Structure

- Modify `backend/src/ragstudio/db/models.py`: add `Document.index_contract` JSON field for compiled upload/reindex metadata.
- Modify `backend/src/ragstudio/db/engine.py`: add compatibility column creation in `init_db()` if the repo uses existing `_ensure_*_columns()` helpers.
- Modify `backend/src/ragstudio/schemas/documents.py`: expose the document contract and readiness state.
- Modify `backend/src/ragstudio/services/document_contract.py`: create a small service/helper for compiling a document contract summary from `IndexDocumentIn`.
- Modify `backend/src/ragstudio/api/routes/documents.py`: save compiled contract on upload/reindex job creation and return contract status.
- Modify `backend/src/ragstudio/services/document_service.py`: persist contract snapshots when uploading or queueing reindex jobs.
- Modify `backend/src/ragstudio/services/chunk_service.py`: read document-level contract before sampling chunks; keep chunk fallback for old rows.
- Create `backend/src/ragstudio/services/vector_candidate_repository.py`: bounded canonical vector candidate source, with quality-policy filtering.
- Modify `backend/src/ragstudio/services/retrieval_orchestrator.py`: execute vector lane through the repository and hydrate candidates.
- Modify `backend/src/ragstudio/services/chunk_splitter.py`: reconstruct multi-column visual reading order with script-direction-aware column sorting.
- Modify `backend/src/ragstudio/services/chunk_persistence_service.py`: remove redundant per-chunk `index_shape` metadata while keeping `IndexRecord.index_shape` authoritative.
- Modify `backend/src/ragstudio/services/hybrid_chunk_search.py`: add layout/context scoring signals from provenance/source metadata.
- Modify `backend/src/ragstudio/services/metadata_retrieval_service.py`: preserve layout/context match features on candidates.
- Tests:
  - `backend/tests/test_document_contract.py`
  - `backend/tests/test_documents.py`
  - `backend/tests/test_chunks.py`
  - `backend/tests/test_vector_candidate_repository.py`
  - `backend/tests/test_reading_order.py`
  - `backend/tests/test_chunk_persistence_service.py`
  - `backend/tests/test_retrieval_orchestrator.py`
  - `backend/tests/test_metadata_retrieval_service.py`

---

### Task 1: Persist A Document-Level Compiled Metadata Contract

**Files:**
- Create: `backend/src/ragstudio/services/document_contract.py`
- Modify: `backend/src/ragstudio/db/models.py`
- Modify: `backend/src/ragstudio/db/engine.py`
- Modify: `backend/src/ragstudio/schemas/documents.py`
- Test: `backend/tests/test_document_contract.py`

- [ ] **Step 1: Write the failing contract helper tests**

Add `backend/tests/test_document_contract.py`:

```python
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn
from ragstudio.services.document_contract import build_document_index_contract


def test_build_document_index_contract_marks_reference_contract_ready():
    options = IndexDocumentIn(
        domain_metadata=DomainMetadata(
            domain="quran_tafseer",
            language="arabic",
            custom_json={
                "reference_schema": {"type": "chapter_verse"},
                "chunking": {"unit": "verse"},
                "domain_structure": {
                    "primary_anchor": {
                        "regex": r"(?P<chapter>\d{1,4}):(?P<verse>\d{1,4})"
                    }
                },
                "reference_resolution": {
                    "enabled": True,
                    "build_canonical_units": True,
                },
                "vision_recovery_policy": {"enabled": True},
            },
        )
    )

    contract = build_document_index_contract(options)

    assert contract["contract_status"] == "compiled_reference_contract"
    assert contract["domain_metadata"]["domain"] == "quran_tafseer"
    assert contract["reference_contract"]["schema_type"] == "chapter_verse"
    assert contract["reference_contract"]["canonical_units"] is True
    assert contract["layout_context"]["vision_recovery_enabled"] is True
    assert contract["retrieval_contract"]["source_of_truth"] == "postgres_canonical_evidence"


def test_build_document_index_contract_marks_generic_metadata():
    contract = build_document_index_contract(IndexDocumentIn())

    assert contract["contract_status"] == "generic"
    assert contract["reference_contract"]["schema_type"] is None
    assert contract["reference_contract"]["canonical_units"] is False
    assert contract["layout_context"]["vision_recovery_enabled"] is False
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_document_contract.py -q
```

Expected: FAIL because `ragstudio.services.document_contract` does not exist.

- [ ] **Step 3: Implement the contract helper**

Create `backend/src/ragstudio/services/document_contract.py`:

```python
from __future__ import annotations

from typing import Any

from ragstudio.schemas.parsing import IndexDocumentIn


def build_document_index_contract(options: IndexDocumentIn) -> dict[str, Any]:
    domain_metadata = options.domain_metadata.model_dump(mode="json", exclude_none=True)
    custom_json = domain_metadata.get("custom_json")
    custom_json = custom_json if isinstance(custom_json, dict) else {}
    reference_schema = _dict_value(custom_json.get("reference_schema"))
    reference_resolution = _dict_value(custom_json.get("reference_resolution"))
    domain_structure = _dict_value(custom_json.get("domain_structure"))
    primary_anchor = _dict_value(domain_structure.get("primary_anchor"))
    vision_policy = _dict_value(custom_json.get("vision_recovery_policy"))
    chunking = _dict_value(custom_json.get("chunking"))

    has_reference_contract = bool(
        reference_schema.get("type")
        and primary_anchor.get("regex")
        and reference_resolution.get("build_canonical_units") is True
    )
    is_generic = (
        domain_metadata.get("domain", "generic") == "generic"
        and not has_reference_contract
    )

    return {
        "contract_version": 1,
        "contract_status": (
            "compiled_reference_contract"
            if has_reference_contract
            else "generic" if is_generic else "metadata_only"
        ),
        "parser_mode": options.parser_mode,
        "domain_metadata": domain_metadata,
        "reference_contract": {
            "schema_type": reference_schema.get("type"),
            "chunk_unit": chunking.get("unit"),
            "primary_anchor_regex": primary_anchor.get("regex"),
            "canonical_units": reference_resolution.get("build_canonical_units") is True,
        },
        "layout_context": {
            "vision_recovery_enabled": vision_policy.get("enabled") is True,
            "preserve_original_blocks": bool(
                _dict_value(custom_json.get("provenance")).get("preserve_original_blocks")
            ),
        },
        "retrieval_contract": {
            "source_of_truth": "postgres_canonical_evidence",
            "allow_raganything_runtime_lane": True,
        },
    }


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
```

- [ ] **Step 4: Add the document column and schema field**

In `backend/src/ragstudio/db/models.py`, add to `Document`:

```python
    index_contract: Mapped[dict[str, Any]] = mapped_column(JsonDictType, default=dict)
```

In `backend/src/ragstudio/schemas/documents.py`, update `DocumentOut`:

```python
from typing import Any

from ragstudio.schemas.common import StageStatus, StudioModel
from ragstudio.schemas.parsing import IndexDocumentIn


class DocumentOut(StudioModel):
    id: str
    filename: str
    content_type: str
    sha256: str
    status: StageStatus
    latest_index_options: IndexDocumentIn | None = None
    index_contract: dict[str, Any] = {}
```

In `backend/src/ragstudio/db/engine.py`, find the existing compatibility column helper pattern. Add equivalent logic for:

```python
ALTER TABLE documents ADD COLUMN IF NOT EXISTS index_contract JSONB DEFAULT '{}'::jsonb
```

If the helper must support SQLite tests, use the repo's existing dialect branching and add the JSON column with the local equivalent used by other JSON fields.

- [ ] **Step 5: Run the contract tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_document_contract.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/document_contract.py backend/src/ragstudio/db/models.py backend/src/ragstudio/db/engine.py backend/src/ragstudio/schemas/documents.py backend/tests/test_document_contract.py
git commit -m "feat: persist document index contract shape"
```

---

### Task 2: Save Contract Snapshots During Upload And Reindex

**Files:**
- Modify: `backend/src/ragstudio/services/document_service.py`
- Modify: `backend/src/ragstudio/api/routes/documents.py`
- Test: `backend/tests/test_documents.py`

- [ ] **Step 1: Add failing upload/reindex contract tests**

Append focused tests in `backend/tests/test_documents.py`:

```python
async def test_upload_stores_compiled_document_index_contract(client, monkeypatch):
    async def fake_runtime_ready(*args, **kwargs):
        return None

    async def fake_validate_sidecar(self, options):
        return None

    monkeypatch.setattr(
        "ragstudio.api.routes.documents._ensure_runtime_ready",
        fake_runtime_ready,
    )
    monkeypatch.setattr(
        "ragstudio.services.chunk_service.ChunkService.validate_strict_mineru_sidecar",
        fake_validate_sidecar,
    )

    response = await client.post(
        "/api/documents",
        files={"file": ("sample.txt", b"Verse 1:1\nIn the name", "text/plain")},
        data={
            "parser_mode": "mineru_strict",
            "domain_metadata": (
                '{"domain":"quran_tafseer","language":"arabic",'
                '"custom_json":{"reference_schema":{"type":"chapter_verse"},'
                '"chunking":{"unit":"verse"},'
                '"domain_structure":{"primary_anchor":{"regex":"(?P<chapter>\\\\d{1,4}):(?P<verse>\\\\d{1,4})"}},'
                '"reference_resolution":{"enabled":true,"build_canonical_units":true}}}'
            ),
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["index_contract"]["contract_status"] == "compiled_reference_contract"
    assert body["index_contract"]["reference_contract"]["schema_type"] == "chapter_verse"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_documents.py::test_upload_stores_compiled_document_index_contract -q
```

Expected: FAIL because upload does not save `Document.index_contract`.

- [ ] **Step 3: Save the contract in document service**

In `backend/src/ragstudio/services/document_service.py`, import:

```python
from ragstudio.services.document_contract import build_document_index_contract
```

When creating a new `Document`, set:

```python
            index_contract=build_document_index_contract(options or IndexDocumentIn()),
```

In `_enqueue_index_job()`, before commit, update the existing document when options are supplied:

```python
        if options is not None:
            document.index_contract = build_document_index_contract(options)
```

In `_ensure_queued_index_job()` and `_ensure_indexed()`, preserve existing contracts when `options is None`; do not overwrite a compiled contract with generic metadata during duplicate upload.

- [ ] **Step 4: Run the focused test**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_documents.py::test_upload_stores_compiled_document_index_contract -q
```

Expected: PASS.

- [ ] **Step 5: Run adjacent document tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_documents.py backend/tests/test_mineru_reindex_jobs.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/document_service.py backend/src/ragstudio/api/routes/documents.py backend/tests/test_documents.py
git commit -m "feat: store compiled index contract on documents"
```

---

### Task 3: Use Document Contracts For Retrieval Route Input

**Files:**
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Test: `backend/tests/test_chunks.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Add failing contract lookup test**

Append to `backend/tests/test_chunks.py`:

```python
async def test_domain_metadata_for_documents_prefers_document_index_contract(session, tmp_path):
    from ragstudio.db.models import Chunk, Document
    from ragstudio.services.chunk_service import ChunkService

    doc = Document(
        id="doc-contract-route",
        filename="contract.txt",
        content_type="text/plain",
        sha256="contract-route-sha",
        artifact_path=str(tmp_path / "contract.txt"),
        index_contract={
            "contract_status": "compiled_reference_contract",
            "domain_metadata": {
                "domain": "quran_tafseer",
                "language": "arabic",
                "custom_json": {
                    "reference_schema": {"type": "chapter_verse"},
                    "reference_resolution": {"build_canonical_units": True},
                },
            },
        },
    )
    session.add(doc)
    session.add(
        Chunk(
            id="chunk-generic-old",
            document_id=doc.id,
            text="old generic chunk",
            metadata_json={"domain_metadata": {"domain": "generic"}},
        )
    )
    await session.commit()

    metadata = await ChunkService(session, tmp_path).domain_metadata_for_documents([doc.id])

    assert metadata == [
        {
            "domain": "quran_tafseer",
            "language": "arabic",
            "custom_json": {
                "reference_schema": {"type": "chapter_verse"},
                "reference_resolution": {"build_canonical_units": True},
            },
            "document_id": doc.id,
            "contract_status": "compiled_reference_contract",
        }
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_chunks.py::test_domain_metadata_for_documents_prefers_document_index_contract -q
```

Expected: FAIL because `domain_metadata_for_documents()` samples chunk metadata first.

- [ ] **Step 3: Implement document-contract-first lookup**

In `backend/src/ragstudio/services/chunk_service.py`, import `Document` if not already imported. At the start of `domain_metadata_for_documents()`, load matching documents:

```python
        document_rows = (
            await self.session.execute(
                select(Document.id, Document.index_contract).where(Document.id.in_(requested))
            )
        ).all()
        for document_id, index_contract in document_rows:
            if not isinstance(index_contract, dict):
                continue
            domain_metadata = index_contract.get("domain_metadata")
            if not isinstance(domain_metadata, dict):
                continue
            metadata_copy = sanitize_db_value(domain_metadata)
            scrubbed_metadata = self._scrub_domain_metadata_lookup_value(metadata_copy)
            if not isinstance(scrubbed_metadata, dict):
                continue
            scrubbed_metadata["document_id"] = document_id
            contract_status = index_contract.get("contract_status")
            if isinstance(contract_status, str):
                scrubbed_metadata["contract_status"] = contract_status
            metadata_by_document[document_id].append(scrubbed_metadata)
            seen_by_document[document_id].add(
                json.dumps(scrubbed_metadata, sort_keys=True, separators=(",", ":"), default=str)
            )
```

Keep the existing chunk-sampling loop after this block so old documents without contracts still work.

- [ ] **Step 4: Run lookup and route tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_chunks.py::test_domain_metadata_for_documents_prefers_document_index_contract backend/tests/test_retrieval_orchestrator.py::test_orchestrator_emits_retrieval_route_plan_trace -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/chunk_service.py backend/tests/test_chunks.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: route retrieval from document index contracts"
```

---

### Task 4: Wire The Vector Lane To Canonical Chunks

**Files:**
- Create: `backend/src/ragstudio/services/vector_candidate_repository.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Test: `backend/tests/test_vector_candidate_repository.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Add repository tests**

Create `backend/tests/test_vector_candidate_repository.py`:

```python
from ragstudio.db.models import Chunk, Document
from ragstudio.services.vector_candidate_repository import VectorCandidateRepository


async def test_vector_candidate_repository_filters_quality_blocked_chunks(session, tmp_path):
    doc = Document(
        id="doc-vector",
        filename="vector.txt",
        content_type="text/plain",
        sha256="vector-sha",
        artifact_path=str(tmp_path / "vector.txt"),
    )
    session.add(doc)
    session.add_all(
        [
            Chunk(
                id="chunk-allowed",
                document_id=doc.id,
                text="alpha allowed answer",
                metadata_json={"quality_action_policy": {"index_vector": True}},
            ),
            Chunk(
                id="chunk-blocked",
                document_id=doc.id,
                text="alpha blocked answer",
                metadata_json={"quality_action_policy": {"index_vector": False}},
            ),
        ]
    )
    await session.commit()

    rows = await VectorCandidateRepository(session).candidate_rows(
        query="alpha",
        document_ids=[doc.id],
        limit=10,
    )

    assert [row["chunk_id"] for row in rows] == ["chunk-allowed"]
    assert rows[0]["metadata"]["quality_action_policy"]["index_vector"] is True
```

- [ ] **Step 2: Run repository test to verify it fails**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_vector_candidate_repository.py -q
```

Expected: FAIL because the repository does not exist.

- [ ] **Step 3: Implement a bounded canonical candidate source**

Create `backend/src/ragstudio/services/vector_candidate_repository.py`:

```python
from __future__ import annotations

from typing import Any

from ragstudio.db.models import Chunk
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession


class VectorCandidateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def candidate_rows(
        self,
        *,
        query: str,
        document_ids: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        terms = _terms(query)
        statement = select(Chunk)
        if document_ids:
            statement = statement.where(Chunk.document_id.in_(document_ids))
        if terms:
            statement = statement.where(
                or_(*(Chunk.text.ilike(f"%{_escape_like(term)}%", escape="\\") for term in terms))
            )
        result = await self.session.execute(
            statement.order_by(Chunk.created_at.asc(), Chunk.id.asc()).limit(max(limit, 1))
        )
        rows = []
        for rank, chunk in enumerate(result.scalars().all(), start=1):
            metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
            policy = metadata.get("quality_action_policy")
            if isinstance(policy, dict) and policy.get("index_vector") is False:
                continue
            rows.append(
                {
                    "candidate_id": f"vector-row:{chunk.id}",
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "text": chunk.text,
                    "source_location": chunk.source_location,
                    "metadata": metadata,
                    "score": max(0.01, 1.0 / rank),
                    "rank": rank,
                }
            )
        return rows


def _terms(query: str) -> list[str]:
    return [term for term in query.casefold().split() if len(term) >= 3][:5]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
```

This is intentionally a canonical bounded executor, not final pgvector SQL. It gives the orchestrator a real quality-gated vector lane now and can later be swapped for distance-ordered pgvector rows behind the same method.

- [ ] **Step 4: Wire orchestrator vector execution**

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, import:

```python
from ragstudio.services.vector_candidate_repository import VectorCandidateRepository
from ragstudio.services.vector_retrieval_service import prepare_vector_candidates
```

Add an optional constructor argument:

```python
        vector_candidate_repository: Any | None = None,
```

Store it:

```python
        self.vector_candidate_repository = vector_candidate_repository
```

After metadata/native retrieval and before final fusion, when `_lane_is_executable(route_plan, "vector")`, run:

```python
            vector_repo = self.vector_candidate_repository
            if vector_repo is None and hasattr(self.chunk_service, "session"):
                vector_repo = VectorCandidateRepository(self.chunk_service.session)
            vector_candidates: list[EvidenceCandidate] = []
            if vector_repo is not None:
                raw_vector_rows = await vector_repo.candidate_rows(
                    query=query,
                    document_ids=document_ids,
                    limit=route_plan.candidate_limit,
                )
                vector_result = prepare_vector_candidates(
                    raw_vector_rows,
                    baseline_gate=_vector_baseline_gate(query_config),
                    canonical_chunks={row["chunk_id"]: row for row in raw_vector_rows},
                )
                vector_candidates = list(vector_result.candidates)
                traces.append(vector_result.diagnostics.as_dict())
```

Include `vector_candidates` in the ranked lists passed to `RetrievalFusion.fuse()`. Replace the old `vector_lane_executor_unavailable` trace for the executable path.

- [ ] **Step 5: Add orchestrator vector lane test**

Append to `backend/tests/test_retrieval_orchestrator.py`:

```python
async def test_orchestrator_runs_quality_gated_vector_lane_when_baseline_passes():
    class VectorRepo:
        async def candidate_rows(self, *, query, document_ids, limit):
            return [
                {
                    "candidate_id": "vector-row:chunk-v1",
                    "chunk_id": "chunk-v1",
                    "document_id": document_ids[0],
                    "text": "vector alpha evidence",
                    "source_location": {"page": 1},
                    "metadata": {"quality_action_policy": {"index_vector": True}},
                    "score": 0.8,
                    "rank": 1,
                }
            ]

    orchestrator = RetrievalOrchestrator(
        chunk_service=EmptyMetadataChunkSearchService(),
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
        vector_candidate_repository=VectorRepo(),
    )

    result = await orchestrator.query(
        "alpha",
        runtime=NativeSearchShouldNotRun(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-vector"],
        variant_id="variant-1",
        query_config={"limit": 3, "vector_baseline_gate": {"passed": True}},
    )

    assert result.error is None
    assert any(source["chunk_id"] == "chunk-v1" for source in result.sources)
    assert any(
        trace.get("stage") == "vector_retrieval" and trace.get("status") == "ran"
        for trace in result.chunk_traces
    )
```

If `EmptyMetadataChunkSearchService` does not exist, define it near the other fake services with `search()` returning no items and `domain_metadata_for_documents()` returning `[]`.

- [ ] **Step 6: Run vector tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_vector_candidate_repository.py backend/tests/test_vector_retrieval_service.py backend/tests/test_retrieval_orchestrator.py::test_orchestrator_runs_quality_gated_vector_lane_when_baseline_passes -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/vector_candidate_repository.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_vector_candidate_repository.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: execute quality-gated vector retrieval lane"
```

---

### Task 5: Add Script-Aware Multi-Column Reading Order And Remove Chunk Metadata Bloat

**Files:**
- Modify: `backend/src/ragstudio/services/chunk_splitter.py`
- Modify: `backend/src/ragstudio/services/chunk_persistence_service.py`
- Create: `backend/tests/test_reading_order.py`
- Modify: `backend/tests/test_chunk_persistence_service.py`

- [ ] **Step 1: Add failing reading-order tests**

Create `backend/tests/test_reading_order.py`:

```python
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_splitter import ChunkSplitter
from ragstudio.services.parser_normalization import NormalizedBlock


def block(text: str, bbox: list[float], *, page: int = 1) -> NormalizedBlock:
    return NormalizedBlock(
        text=text,
        page=page,
        block_type="text",
        source_item={"bbox": bbox},
    )


def test_canonical_block_order_uses_ltr_columns_inside_vertical_bands():
    blocks = [
        block("Title", [0, 0, 1000, 80]),
        block("Left 1", [40, 120, 430, 180]),
        block("Right 1", [560, 120, 950, 180]),
        block("Left 2", [40, 210, 430, 270]),
        block("Right 2", [560, 210, 950, 270]),
        block("Footer", [0, 900, 1000, 960]),
    ]

    ordered = ChunkSplitter()._canonical_block_order(
        blocks,
        domain_metadata=DomainMetadata(language="english", script="latin"),
    )

    assert [item.text for _, item in ordered] == [
        "Title",
        "Left 1",
        "Left 2",
        "Right 1",
        "Right 2",
        "Footer",
    ]


def test_canonical_block_order_uses_rtl_columns_for_arabic_documents():
    blocks = [
        block("العنوان", [0, 0, 1000, 80]),
        block("Left translation 1", [40, 120, 430, 180]),
        block("Arabic right 1", [560, 120, 950, 180]),
        block("Left translation 2", [40, 210, 430, 270]),
        block("Arabic right 2", [560, 210, 950, 270]),
    ]

    ordered = ChunkSplitter()._canonical_block_order(
        blocks,
        domain_metadata=DomainMetadata(language="arabic", script="arabic"),
    )

    assert [item.text for _, item in ordered] == [
        "العنوان",
        "Arabic right 1",
        "Arabic right 2",
        "Left translation 1",
        "Left translation 2",
    ]
```

- [ ] **Step 2: Add failing persistence bloat test**

Append to `backend/tests/test_chunk_persistence_service.py`:

```python
async def test_persist_chunks_does_not_duplicate_index_shape_in_chunk_metadata(
    tmp_path,
    database_url,
):
    from ragstudio.db.engine import make_engine, make_session_factory
    from ragstudio.db.models import Document
    from ragstudio.schemas.parsing import IndexDocumentIn
    from ragstudio.services.adapter import AdapterChunk
    from ragstudio.services.chunk_persistence_service import ChunkPersistenceService

    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    async with session_factory() as session:
        document = Document(
            id="doc-no-index-shape-bloat",
            filename="shape.txt",
            content_type="text/plain",
            sha256="shape-sha",
            artifact_path=str(tmp_path / "shape.txt"),
        )
        session.add(document)
        await session.commit()

        chunks = await ChunkPersistenceService(session).persist(
            document,
            [
                AdapterChunk(
                    text="Chunk with runtime shape",
                    source_location={"page": 1},
                    metadata={"parser_metadata": {"backend": "mineru"}},
                )
            ],
            IndexDocumentIn(),
            runtime_profile_id="default",
            index_shape={"embedding_model": "text-embedding-3-large"},
        )

        stored = chunks[0]
        assert "index_shape" not in stored.metadata
    await engine.dispose()
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_reading_order.py backend/tests/test_chunk_persistence_service.py::test_persist_chunks_does_not_duplicate_index_shape_in_chunk_metadata -q
```

Expected: FAIL because `_canonical_block_order()` does not accept `domain_metadata`, LTR/RTL column grouping is not implemented, and chunk metadata still includes `index_shape`.

- [ ] **Step 4: Pass domain metadata into canonical block ordering**

In `backend/src/ragstudio/services/chunk_splitter.py`, change the call in `_canonical_reference_pieces()`:

```python
        ordered_blocks = self._canonical_block_order(
            normalized_blocks,
            domain_metadata=domain_metadata,
        )
```

Change the method signature:

```python
    def _canonical_block_order(
        self,
        normalized_blocks: list[NormalizedBlock],
        *,
        domain_metadata: DomainMetadata | None = None,
    ) -> list[tuple[int, NormalizedBlock]]:
```

- [ ] **Step 5: Implement banded script-aware column ordering**

In `backend/src/ragstudio/services/chunk_splitter.py`, replace the all-bbox page sort inside `_canonical_block_order()` with helper-driven ordering:

```python
            if all(self._source_bbox(block) is not None for _, block in page_blocks):
                ordered.extend(
                    self._banded_visual_order(
                        page_blocks,
                        domain_metadata=domain_metadata,
                    )
                )
                continue
```

Add these helpers below `_canonical_block_order()`:

```python
    def _banded_visual_order(
        self,
        page_blocks: list[tuple[int, NormalizedBlock]],
        *,
        domain_metadata: DomainMetadata | None,
    ) -> list[tuple[int, NormalizedBlock]]:
        page_width = self._page_width(page_blocks)
        full_width_threshold = page_width * 0.70
        full_width: list[tuple[int, NormalizedBlock]] = []
        column_blocks: list[tuple[int, NormalizedBlock]] = []
        for item in page_blocks:
            bbox = self._source_bbox(item[1])
            if bbox is None:
                column_blocks.append(item)
                continue
            x0, _y0, x1, _y1 = bbox
            if x1 - x0 >= full_width_threshold:
                full_width.append(item)
            else:
                column_blocks.append(item)

        if len(column_blocks) < 2:
            return sorted(page_blocks, key=lambda item: self._visual_order_key(item[0], item[1]))

        full_width_sorted = sorted(full_width, key=lambda item: self._visual_order_key(item[0], item[1]))
        bands: dict[int, list[tuple[int, NormalizedBlock]]] = {}
        for item in column_blocks:
            band = self._band_index(item[1], full_width_sorted)
            bands.setdefault(band, []).append(item)

        ordered: list[tuple[int, NormalizedBlock]] = []
        emitted_full_width: set[int] = set()
        max_band = max(bands.keys(), default=-1)
        for band in range(max_band + 1):
            if band < len(full_width_sorted):
                ordered.append(full_width_sorted[band])
                emitted_full_width.add(full_width_sorted[band][0])
            ordered.extend(
                self._order_columns_in_band(
                    bands.get(band, []),
                    page_width=page_width,
                    rtl=self._is_rtl_domain(domain_metadata),
                )
            )
        for item in full_width_sorted:
            if item[0] not in emitted_full_width:
                ordered.append(item)
        return ordered

    def _page_width(self, page_blocks: list[tuple[int, NormalizedBlock]]) -> float:
        widths = []
        max_x1 = 0.0
        for _index, block in page_blocks:
            bbox = self._source_bbox(block)
            if bbox is None:
                continue
            x0, _y0, x1, _y1 = bbox
            widths.append(x1 - x0)
            max_x1 = max(max_x1, x1)
        return max(1000.0, max_x1, *(widths or [0.0]))

    def _band_index(
        self,
        block: NormalizedBlock,
        full_width_sorted: list[tuple[int, NormalizedBlock]],
    ) -> int:
        bbox = self._source_bbox(block)
        if bbox is None:
            return 0
        _x0, y0, _x1, y1 = bbox
        midpoint = (y0 + y1) / 2
        for index, (_original_index, separator) in enumerate(full_width_sorted):
            sep_bbox = self._source_bbox(separator)
            if sep_bbox is None:
                continue
            _sx0, _sy0, _sx1, sy1 = sep_bbox
            if midpoint < sy1:
                return index
        return len(full_width_sorted)

    def _order_columns_in_band(
        self,
        blocks: list[tuple[int, NormalizedBlock]],
        *,
        page_width: float,
        rtl: bool,
    ) -> list[tuple[int, NormalizedBlock]]:
        if not blocks:
            return []
        clusters = self._column_clusters(blocks, gap_tolerance=page_width * 0.05)
        clusters = sorted(
            clusters,
            key=lambda cluster: self._cluster_x0(cluster),
            reverse=rtl,
        )
        ordered: list[tuple[int, NormalizedBlock]] = []
        for cluster in clusters:
            ordered.extend(
                sorted(
                    cluster,
                    key=lambda item: self._visual_order_key(item[0], item[1]),
                )
            )
        return ordered

    def _column_clusters(
        self,
        blocks: list[tuple[int, NormalizedBlock]],
        *,
        gap_tolerance: float,
    ) -> list[list[tuple[int, NormalizedBlock]]]:
        sorted_blocks = sorted(
            blocks,
            key=lambda item: (self._source_bbox(item[1]) or (0.0, 0.0, 0.0, 0.0))[0],
        )
        clusters: list[list[tuple[int, NormalizedBlock]]] = []
        current: list[tuple[int, NormalizedBlock]] = []
        current_right: float | None = None
        for item in sorted_blocks:
            bbox = self._source_bbox(item[1])
            if bbox is None:
                continue
            x0, _y0, x1, _y1 = bbox
            if current and current_right is not None and x0 - current_right > gap_tolerance:
                clusters.append(current)
                current = []
                current_right = None
            current.append(item)
            current_right = max(current_right if current_right is not None else x1, x1)
        if current:
            clusters.append(current)
        return clusters

    def _cluster_x0(self, cluster: list[tuple[int, NormalizedBlock]]) -> float:
        values = [
            bbox[0]
            for _index, block in cluster
            if (bbox := self._source_bbox(block)) is not None
        ]
        return min(values) if values else 0.0

    def _is_rtl_domain(self, domain_metadata: DomainMetadata | None) -> bool:
        if domain_metadata is None:
            return False
        values = [
            domain_metadata.script,
            domain_metadata.language,
            domain_metadata.domain,
            *domain_metadata.tags,
        ]
        normalized = {str(value).casefold() for value in values if value}
        return bool({"arabic", "ar", "quran", "quran_tafseer"} & normalized)
```

- [ ] **Step 6: Remove chunk-level index shape duplication**

In `backend/src/ragstudio/services/chunk_persistence_service.py`, remove this line from `_merge_metadata()`:

```python
        merged["index_shape"] = index_shape
```

Keep the `index_shape` parameter in the method signature for now to minimize call-site churn; `IndexLifecycleService` still writes the authoritative shape and quality reports to `IndexRecord.index_shape`.

- [ ] **Step 7: Run reading-order and persistence tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_reading_order.py backend/tests/test_chunk_persistence_service.py -q
```

Expected: PASS.

- [ ] **Step 8: Run adjacent ingestion tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_chunk_splitter.py backend/tests/test_canonical_assembly.py backend/tests/test_index_lifecycle_service.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/src/ragstudio/services/chunk_splitter.py backend/src/ragstudio/services/chunk_persistence_service.py backend/tests/test_reading_order.py backend/tests/test_chunk_persistence_service.py
git commit -m "feat: add script-aware multi-column reading order"
```

---

### Task 6: Add Layout And Context Retrieval Signals

**Files:**
- Modify: `backend/src/ragstudio/services/hybrid_chunk_search.py`
- Modify: `backend/src/ragstudio/services/metadata_retrieval_service.py`
- Test: `backend/tests/test_metadata_retrieval_service.py`

- [ ] **Step 1: Add failing layout/context scoring test**

Append to `backend/tests/test_metadata_retrieval_service.py`:

```python
def test_hybrid_search_boosts_layout_context_matches():
    from ragstudio.db.models import Chunk
    from ragstudio.services.hybrid_chunk_search import HybridChunkSearch

    chunk = Chunk(
        id="chunk-table-context",
        document_id="doc-layout",
        text="Revenue grew by 12 percent.",
        metadata_json={
            "modality": "table",
            "provenance": {
                "blocks": [
                    {
                        "role": "table",
                        "block_type": "table",
                        "page_start": 4,
                        "text_preview": "Revenue table",
                    }
                ]
            },
            "layout_context": {
                "section_title": "Financial results",
                "visual_neighborhood": ["table", "caption"],
            },
        },
    )

    score = HybridChunkSearch().score("financial results table revenue", chunk)

    assert score.breakdown["layout_context"] > 0
    assert score.score >= score.breakdown["layout_context"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_metadata_retrieval_service.py::test_hybrid_search_boosts_layout_context_matches -q
```

Expected: FAIL because `layout_context` is not in the score breakdown.

- [ ] **Step 3: Implement layout/context boost**

In `backend/src/ragstudio/services/hybrid_chunk_search.py`, add this method:

```python
    def _layout_context_boost(self, query_text: str, metadata: dict[str, Any]) -> float:
        query_terms = self._terms(query_text)
        if not query_terms:
            return 0.0
        layout_terms: set[str] = set()
        for key in ("modality", "content_type"):
            value = metadata.get(key)
            if isinstance(value, str):
                layout_terms.update(self._terms(value))
        layout_context = metadata.get("layout_context")
        if isinstance(layout_context, dict):
            for value in layout_context.values():
                if isinstance(value, str):
                    layout_terms.update(self._terms(value))
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            layout_terms.update(self._terms(item))
        provenance = metadata.get("provenance")
        if isinstance(provenance, dict):
            blocks = provenance.get("blocks")
            if isinstance(blocks, list):
                for block in blocks[:8]:
                    if not isinstance(block, dict):
                        continue
                    for key in ("role", "block_type", "text_preview"):
                        value = block.get(key)
                        if isinstance(value, str):
                            layout_terms.update(self._terms(value))
        overlap = query_terms & layout_terms
        return min(16.0, len(overlap) * 4.0)
```

In `score()`, compute:

```python
        layout_context = self._layout_context_boost(query_text, metadata)
```

Add it to `breakdown`:

```python
            "layout_context": layout_context,
```

- [ ] **Step 4: Preserve match features on metadata candidates**

In `backend/src/ragstudio/services/metadata_retrieval_service.py`, inside `_match_features()`, add:

```python
        if effective_pass == "semantic_metadata":
            return {"semantic_metadata": True}
```

Inside `_candidate_from_chunk()`, after `metadata = _chunk_metadata(chunk)`, add:

```python
        score_breakdown = metadata.get("score_breakdown")
        layout_score = 0.0
        if isinstance(score_breakdown, dict) and isinstance(score_breakdown.get("layout_context"), (int, float)):
            layout_score = float(score_breakdown["layout_context"])
```

When constructing `EvidenceCandidate`, merge layout match features:

```python
            match_features={
                **self._match_features(retrieval_pass, effective_pass),
                **({"layout_context": True} if layout_score > 0 else {}),
            },
```

- [ ] **Step 5: Run metadata retrieval tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_metadata_retrieval_service.py backend/tests/test_chunks.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/hybrid_chunk_search.py backend/src/ragstudio/services/metadata_retrieval_service.py backend/tests/test_metadata_retrieval_service.py
git commit -m "feat: add layout context retrieval signals"
```

---

### Task 7: Add End-To-End Regression Coverage For Contract, Quality, Vision, And Retrieval

**Files:**
- Modify: `backend/tests/test_ingestion_retrieval_quality_gate.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Add an end-to-end service-level regression**

Add a test that builds:
- one document with `index_contract.contract_status = compiled_reference_contract`
- one repaired chunk with `reference_metadata`, `provenance.blocks`, `layout_context`, and `quality_action_policy.index_vector = True`
- one blocked chunk with `quality_action_policy.index_vector = False` and `project_graph = False`
- one query with `vector_baseline_gate = {"passed": True}`

Use this assertion shape:

```python
assert any(source["chunk_id"] == "chunk-repaired" for source in result.sources)
assert not any(source["chunk_id"] == "chunk-blocked" for source in result.sources)
assert any(
    trace.get("stage") == "retrieval_route_plan"
    and trace.get("domain_profile_id") == "reference_heavy"
    for trace in result.chunk_traces
)
assert any(
    trace.get("stage") == "vector_retrieval" and trace.get("status") in {"ran", "skipped"}
    for trace in result.chunk_traces
)
```

- [ ] **Step 2: Run the regression test**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_ingestion_retrieval_quality_gate.py backend/tests/test_retrieval_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the focused hardening suite**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_document_contract.py backend/tests/test_documents.py backend/tests/test_chunks.py backend/tests/test_chunk_persistence_service.py backend/tests/test_reading_order.py backend/tests/test_index_lifecycle_service.py backend/tests/test_metadata_retrieval_service.py backend/tests/test_vector_candidate_repository.py backend/tests/test_vector_retrieval_service.py backend/tests/test_retrieval_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_ingestion_retrieval_quality_gate.py backend/tests/test_retrieval_orchestrator.py
git commit -m "test: cover domain layout quality retrieval path"
```

---

## Self-Review

**Spec coverage:**
- Upload metadata readiness is covered by Tasks 1 and 2.
- Passing metadata through quality gates is covered by existing `IndexLifecycleService` plus Task 7 regression.
- Persistence is covered by Tasks 1, 2, and 3.
- Script-direction-aware multi-column ordering and chunk metadata bloat cleanup are covered by Task 5.
- Vision fallback is kept indexing-time and verified by Task 7 through recovered/provenance metadata.
- Retrieval use is covered by Tasks 3, 4, 6, and 7.

**No placeholders scan:**
- No task says TBD, TODO, similar to another task, or add tests without code. Task 7 intentionally describes fixture shape plus exact assertions because it depends on existing fake classes in the target test file.

**Type consistency:**
- `index_contract` is a `dict[str, Any]` on `Document` and `DocumentOut`.
- `build_document_index_contract()` accepts `IndexDocumentIn` and returns a JSON-safe dict.
- `VectorCandidateRepository.candidate_rows()` returns mappings accepted by `prepare_vector_candidates()`.
