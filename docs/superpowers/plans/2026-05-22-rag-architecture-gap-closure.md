# RAG Architecture Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the verified Ragstudio architecture gaps across domain-aware, layout-aware, and context-aware ingestion and retrieval without weakening canonical evidence, quality gates, or public proof safety.

**Architecture:** Keep Postgres canonical chunks as the source of truth, then make domain contracts, layout provenance, and parent context explicit bridge data for vector, graph, runtime, reranker, and answer assembly lanes. Every secondary lane must hydrate back to canonical evidence, preserve quality/materialization policy, and expose lane decisions in traces.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async ORM, Pydantic, PostgreSQL JSON/JSONB metadata, Neo4j graph projection, RAG-Anything/LightRAG runtime lane, pytest, Vitest where UI trace display changes are made.

---

## Scope Check

This plan covers six related gaps that must work together:

- Domain-aware retrieval is still partly hardcoded around Arabic religious expansion.
- Layout metadata is preserved in canonical chunks but is stripped or weakly bridged in native vector/runtime paths.
- Vector/runtime quality bypass is mostly fixed, but must be regression-locked and extended to native source hydration.
- Graph expansion exists, but vector hits do not yet seed graph/context neighborhood expansion.
- Context assembly is still mostly flat and lacks safe breadcrumbs/parent context.
- Reranking has before/after traces but no diversity-aware selection or redundancy control.

The work is split into independent tasks. Each task should pass on its own and be committed before moving on.

## File Structure

- Modify `backend/src/ragstudio/services/domain_query_expansion_service.py`: replace the hardcoded Arabic-only expansion decision with a registry-driven adapter lookup while preserving current Arabic behavior.
- Create `backend/src/ragstudio/services/domain_lexical_registry.py`: define a small registry and adapter protocol for domain-specific lexical expansion.
- Test `backend/tests/test_domain_query_expansion_service.py`: assert Arabic behavior still works and non-Arabic domain adapters can be registered without editing orchestration.
- Create `backend/src/ragstudio/services/evidence_context.py`: centralize breadcrumb, parent-context text, layout summary, and safe context-prefix construction from canonical chunk metadata.
- Modify `backend/src/ragstudio/services/metadata_retrieval_service.py`: attach context breadcrumbs and layout summaries to metadata candidates.
- Modify `backend/src/ragstudio/services/vector_candidate_repository.py`: return canonical metadata plus context breadcrumbs for vector candidates and keep quality filtering.
- Modify `backend/src/ragstudio/services/vector_retrieval_service.py`: keep hydrated canonical metadata and expose context/layout fields on vector candidates.
- Modify `backend/src/ragstudio/services/native_raganything_adapter.py`: preserve safe context prefixes and layout bridge metadata when inserting preparsed chunks into RAG-Anything.
- Test `backend/tests/test_evidence_context.py`, `backend/tests/test_vector_candidate_repository.py`, and `backend/tests/test_native_raganything_adapter.py`.
- Create `backend/src/ragstudio/services/layout_neighbor_service.py`: query bounded same-document layout/context neighbors from canonical chunks.
- Modify `backend/src/ragstudio/services/retrieval_orchestrator.py`: allow hydrated vector candidates to seed graph expansion and layout-neighbor expansion.
- Test `backend/tests/test_layout_neighbor_service.py` and `backend/tests/test_retrieval_orchestrator.py`.
- Modify `backend/src/ragstudio/services/context_assembly_service.py`: inject breadcrumbs, include neighbor/context labels, and report dropped/truncated evidence with clearer reasons.
- Modify `backend/src/ragstudio/services/runtime_answer_service.py`: include assembled breadcrumb/reference/page labels in the answer prompt.
- Test `backend/tests/test_context_assembly_service.py` and `backend/tests/test_runtime_answer_service.py`.
- Create `backend/src/ragstudio/services/candidate_diversity.py`: add deterministic MMR-style diversity selection for bounded candidate lists.
- Modify `backend/src/ragstudio/services/retrieval_evidence.py` or `backend/src/ragstudio/services/retrieval_orchestrator.py`: apply diversity after fusion/rerank and preserve trace reasons.
- Test `backend/tests/test_candidate_diversity.py` and focused retrieval orchestrator tests.
- Update `docs/superpowers/plans/2026-05-21-domain-layout-context-retrieval-hardening.md` only if it is referenced as current by project docs; otherwise leave it as historical context.

---

### Task 1: Registry-Driven Domain Lexical Expansion

**Files:**
- Create: `backend/src/ragstudio/services/domain_lexical_registry.py`
- Modify: `backend/src/ragstudio/services/domain_query_expansion_service.py`
- Test: `backend/tests/test_domain_query_expansion_service.py`

- [ ] **Step 1: Write failing tests for adapter registration and current Arabic behavior**

Create `backend/tests/test_domain_query_expansion_service.py` with these imports and tests:

```python
from ragstudio.services.domain_query_expansion_service import DomainQueryExpansionService
from ragstudio.services.domain_lexical_registry import DomainLexicalRegistry
from ragstudio.services.lexical_language_adapters import LexicalExpansion


class LegalLexicalAdapter:
    def supports_query(self, query: str) -> bool:
        return "force majeure" in query.casefold()

    def expand_query(self, query: str) -> LexicalExpansion:
        return LexicalExpansion(
            language="english",
            script="latin",
            match_type="domain_synonym",
            confidence=0.91,
            source="legal_test_adapter",
            terms=["force majeure", "act of god", "impossibility"],
        )


def test_domain_query_expansion_uses_registered_non_arabic_adapter():
    registry = DomainLexicalRegistry()
    registry.register("legal_reference", LegalLexicalAdapter())
    service = DomainQueryExpansionService(registry=registry)

    expansion = service.expand(
        "force majeure clause",
        domain_metadata=[
            {
                "domain": "legal",
                "document_type": "contract",
                "tags": ["contract", "reference"],
            }
        ],
    )

    assert expansion.domain_family == "legal_reference"
    assert [item.source for item in expansion.expansions] == ["legal_test_adapter"]
    assert expansion.trace["adapter_sources"] == ["legal_test_adapter"]
    assert "act of god" in expansion.trace["expanded_terms"]
    assert any(item.query == "impossibility" for item in expansion.retrieval_passes)


def test_domain_query_expansion_preserves_arabic_religious_family():
    service = DomainQueryExpansionService()

    expansion = service.expand(
        "quran 1:5",
        domain_metadata=[
            {
                "domain": "quran_tafseer",
                "document_type": "commentary",
                "tags": ["quran", "arabic"],
            }
        ],
    )

    assert expansion.domain_family == "arabic_religious"
    assert expansion.trace["domain_family"] == "arabic_religious"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_domain_query_expansion_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.domain_lexical_registry'` or constructor argument mismatch.

- [ ] **Step 3: Add the lexical registry**

Create `backend/src/ragstudio/services/domain_lexical_registry.py`:

```python
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from ragstudio.services.lexical_language_adapters import (
    ArabicLexicalAdapter,
    LexicalExpansion,
)


class DomainLexicalAdapter(Protocol):
    def supports_query(self, query: str) -> bool: ...

    def expand_query(self, query: str) -> LexicalExpansion: ...


class DomainLexicalRegistry:
    def __init__(self) -> None:
        arabic = ArabicLexicalAdapter()
        self._adapters: dict[str, list[DomainLexicalAdapter]] = {
            "arabic_religious": [arabic],
        }

    def register(self, domain_family: str, adapter: DomainLexicalAdapter) -> None:
        normalized = domain_family.strip().casefold()
        if not normalized:
            raise ValueError("domain_family must not be empty")
        self._adapters.setdefault(normalized, []).append(adapter)

    def adapters_for(self, domain_family: str) -> Iterable[DomainLexicalAdapter]:
        return tuple(self._adapters.get(domain_family.strip().casefold(), ()))
```

- [ ] **Step 4: Refactor `DomainQueryExpansionService` to use the registry**

In `backend/src/ragstudio/services/domain_query_expansion_service.py`, change the imports and constructor:

```python
from ragstudio.services.domain_lexical_registry import DomainLexicalRegistry
from ragstudio.services.lexical_language_adapters import LexicalExpansion
```

Replace the constructor with:

```python
class DomainQueryExpansionService:
    def __init__(self, registry: DomainLexicalRegistry | None = None):
        self.registry = registry or DomainLexicalRegistry()
```

Replace the two hardcoded `self.arabic_adapter` expansion blocks with:

```python
        adapter_sources: list[str] = []
        adapters = list(self.registry.adapters_for(domain_family))

        if query_hypothesis is not None and query_hypothesis.valid and query_hypothesis.target_terms:
            hypothesis_inputs = [
                term.surface
                for term in query_hypothesis.target_terms
                if term.surface.strip()
            ]
            for adapter in adapters:
                hypothesis_expansions = [
                    adapter.expand_query(term)
                    for term in hypothesis_inputs
                    if adapter.supports_query(term)
                ]
                for expansion in hypothesis_expansions:
                    if expansion.terms:
                        expansions.append(expansion)
                        adapter_sources.append(expansion.source)
            if expansions:
                expansion_source = "query_hypothesis"
                expansion_inputs = hypothesis_inputs

        if not expansions:
            for adapter in adapters:
                if not adapter.supports_query(query):
                    continue
                expansion = adapter.expand_query(query)
                if expansion.terms:
                    expansions.append(expansion)
                    adapter_sources.append(expansion.source)
                    break
```

In the trace payload, add:

```python
                "adapter_sources": list(dict.fromkeys(adapter_sources)),
```

Extend `_domain_family()` before the final `return "generic"`:

```python
    if religious_signals & {"legal", "law", "contract", "statute", "policy"}:
        return "legal_reference"
    if religious_signals & {"medical", "clinical", "healthcare"}:
        return "medical_reference"
    if religious_signals & {"finance", "financial", "invoice", "banking"}:
        return "financial_reference"
    if religious_signals & {"code", "source_code", "software"}:
        return "code_reference"
```

- [ ] **Step 5: Run the focused tests**

Run:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_domain_query_expansion_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add backend/src/ragstudio/services/domain_lexical_registry.py backend/src/ragstudio/services/domain_query_expansion_service.py backend/tests/test_domain_query_expansion_service.py
git commit -m "feat: make domain lexical expansion registry-driven"
```

---

### Task 2: Canonical Evidence Context And Layout Bridge

**Files:**
- Create: `backend/src/ragstudio/services/evidence_context.py`
- Modify: `backend/src/ragstudio/services/metadata_retrieval_service.py`
- Modify: `backend/src/ragstudio/services/vector_candidate_repository.py`
- Modify: `backend/src/ragstudio/services/vector_retrieval_service.py`
- Test: `backend/tests/test_evidence_context.py`
- Test: `backend/tests/test_metadata_retrieval_service.py`
- Test: `backend/tests/test_vector_retrieval_service.py`

- [ ] **Step 1: Write failing tests for breadcrumb and layout summary extraction**

Create `backend/tests/test_evidence_context.py`:

```python
from ragstudio.services.evidence_context import (
    evidence_context_from_metadata,
    prefixed_embedding_text,
)


def test_evidence_context_extracts_reference_section_and_layout():
    metadata = {
        "document_metadata": {"title": "Synthetic Tafseer"},
        "reference_metadata": {"references": ["1:5"]},
        "section_path": ["Surah Al-Fatihah", "Verse 5"],
        "content_type": "figure",
        "provenance": {
            "blocks": [
                {
                    "role": "caption",
                    "block_type": "image_caption",
                    "page_number": 3,
                    "bbox": [10, 20, 200, 60],
                }
            ]
        },
    }

    context = evidence_context_from_metadata(
        metadata,
        source_location={"page": 3},
        content_type="figure",
    )

    assert context["breadcrumb"] == "Synthetic Tafseer > Surah Al-Fatihah > Verse 5 > 1:5"
    assert context["layout_summary"] == "figure; page=3; block=image_caption; role=caption"
    assert context["page"] == 3
    assert context["reference"] == "1:5"


def test_prefixed_embedding_text_adds_context_once():
    text = "Guide us to the straight path."
    metadata = {
        "document_metadata": {"title": "Synthetic Tafseer"},
        "reference_metadata": {"references": ["1:5"]},
    }

    first = prefixed_embedding_text(text, metadata, source_location={"page": 1})
    second = prefixed_embedding_text(first, metadata, source_location={"page": 1})

    assert first.startswith("[Context: Synthetic Tafseer > 1:5]")
    assert second == first
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_evidence_context.py -q
```

Expected: FAIL because `evidence_context.py` does not exist.

- [ ] **Step 3: Implement `evidence_context.py`**

Create `backend/src/ragstudio/services/evidence_context.py`:

```python
from __future__ import annotations

from typing import Any


def evidence_context_from_metadata(
    metadata: dict[str, Any],
    *,
    source_location: dict[str, Any] | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    source = source_location or {}
    reference = _first_reference(metadata, source)
    page = _page(source)
    breadcrumb_parts = [
        _document_title(metadata),
        *_section_path(metadata),
        reference,
    ]
    breadcrumb = " > ".join(part for part in breadcrumb_parts if part)
    layout_summary = _layout_summary(metadata, source, content_type=content_type)
    return {
        key: value
        for key, value in {
            "breadcrumb": breadcrumb or None,
            "layout_summary": layout_summary or None,
            "page": page,
            "reference": reference,
        }.items()
        if value is not None
    }


def prefixed_embedding_text(
    text: str,
    metadata: dict[str, Any],
    *,
    source_location: dict[str, Any] | None = None,
    content_type: str | None = None,
) -> str:
    stripped = text.strip()
    if stripped.startswith("[Context:"):
        return stripped
    context = evidence_context_from_metadata(
        metadata,
        source_location=source_location,
        content_type=content_type,
    )
    breadcrumb = context.get("breadcrumb")
    layout = context.get("layout_summary")
    parts = [str(value) for value in (breadcrumb, layout) if isinstance(value, str) and value]
    if not parts:
        return stripped
    return f"[Context: {' | '.join(parts)}]\n{stripped}"


def _document_title(metadata: dict[str, Any]) -> str | None:
    value = metadata.get("document_metadata")
    if isinstance(value, dict) and isinstance(value.get("title"), str):
        title = value["title"].strip()
        return title or None
    return None


def _section_path(metadata: dict[str, Any]) -> list[str]:
    for key in ("section_path", "heading_path", "breadcrumbs"):
        value = metadata.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
    section = metadata.get("section")
    if isinstance(section, str) and section.strip():
        return [section.strip()]
    return []


def _first_reference(metadata: dict[str, Any], source_location: dict[str, Any]) -> str | None:
    source_reference = source_location.get("reference")
    if isinstance(source_reference, str) and source_reference.strip():
        return source_reference.strip()
    reference_metadata = metadata.get("reference_metadata")
    if isinstance(reference_metadata, dict):
        references = reference_metadata.get("references")
        if isinstance(references, list) and references:
            reference = str(references[0]).strip()
            return reference or None
    return None


def _page(source_location: dict[str, Any]) -> int | None:
    for key in ("page", "page_start", "page_number"):
        value = source_location.get(key)
        if isinstance(value, int):
            return value
    return None


def _layout_summary(
    metadata: dict[str, Any],
    source_location: dict[str, Any],
    *,
    content_type: str | None,
) -> str | None:
    pieces: list[str] = []
    resolved_content_type = content_type or _string(metadata.get("content_type"))
    if resolved_content_type:
        pieces.append(resolved_content_type)
    page = _page(source_location)
    if page is not None:
        pieces.append(f"page={page}")
    block = _first_provenance_block(metadata)
    if block:
        block_type = _string(block.get("block_type"))
        role = _string(block.get("role"))
        if block_type:
            pieces.append(f"block={block_type}")
        if role:
            pieces.append(f"role={role}")
    return "; ".join(dict.fromkeys(pieces)) or None


def _first_provenance_block(metadata: dict[str, Any]) -> dict[str, Any]:
    provenance = metadata.get("provenance")
    if not isinstance(provenance, dict):
        return {}
    blocks = provenance.get("blocks")
    if not isinstance(blocks, list):
        return {}
    for block in blocks:
        if isinstance(block, dict):
            return block
    return {}


def _string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
```

- [ ] **Step 4: Attach context to metadata candidates**

In `backend/src/ragstudio/services/metadata_retrieval_service.py`, add:

```python
from ragstudio.services.evidence_context import evidence_context_from_metadata
```

Inside `_candidate_from_chunk()`, after `metadata = _chunk_metadata(chunk)`, add:

```python
        context = evidence_context_from_metadata(
            metadata,
            source_location=_chunk_source_location(chunk),
            content_type=getattr(chunk, "content_type", None),
        )
        if context:
            metadata["evidence_context"] = context
```

- [ ] **Step 5: Attach context to vector repository rows**

In `backend/src/ragstudio/services/vector_candidate_repository.py`, add:

```python
from ragstudio.services.evidence_context import evidence_context_from_metadata
```

Before appending each row, compute:

```python
            context = evidence_context_from_metadata(
                metadata,
                source_location=chunk.source_location if isinstance(chunk.source_location, dict) else {},
                content_type=chunk.content_type,
            )
            if context:
                metadata = {**metadata, "evidence_context": context}
```

- [ ] **Step 6: Preserve context during vector hydration**

In `backend/src/ragstudio/services/vector_retrieval_service.py`, inside `_hydrate_candidate()` after `metadata.update(raw_metadata)`, add:

```python
    raw_context = raw_metadata.get("evidence_context")
    if isinstance(raw_context, dict):
        metadata["evidence_context"] = raw_context
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_evidence_context.py backend/tests/test_metadata_retrieval_service.py backend/tests/test_vector_retrieval_service.py backend/tests/test_vector_candidate_repository.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add backend/src/ragstudio/services/evidence_context.py backend/src/ragstudio/services/metadata_retrieval_service.py backend/src/ragstudio/services/vector_candidate_repository.py backend/src/ragstudio/services/vector_retrieval_service.py backend/tests/test_evidence_context.py backend/tests/test_metadata_retrieval_service.py backend/tests/test_vector_retrieval_service.py backend/tests/test_vector_candidate_repository.py
git commit -m "feat: preserve canonical evidence context in retrieval candidates"
```

---

### Task 3: Native Runtime Context Prefix And Layout Bridge Metadata

**Files:**
- Modify: `backend/src/ragstudio/services/native_raganything_adapter.py`
- Test: `backend/tests/test_native_raganything_adapter.py`

- [ ] **Step 1: Write failing tests for preparsed RAG-Anything content list enrichment**

Append to `backend/tests/test_native_raganything_adapter.py`:

```python
from pathlib import Path

from ragstudio.config import AppSettings
from ragstudio.schemas.runtime import RuntimeProfile
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.native_raganything_adapter import NativeRAGAnythingAdapter


def _profile(tmp_path: Path) -> RuntimeProfile:
    return RuntimeProfile(
        id="test",
        name="test",
        llm_provider="openai_compatible",
        llm_model="test-llm",
        llm_base_url="http://127.0.0.1:9999/v1",
        llm_api_key=None,
        llm_timeout_ms=10000,
        embedding_provider="openai_compatible",
        embedding_model="test-embed",
        embedding_base_url="http://127.0.0.1:9998/v1",
        embedding_api_key=None,
        embedding_dimensions=1024,
        parser="mineru",
        parse_method="auto",
        runtime_working_dir=tmp_path,
        context_window=1,
        context_mode="page",
        max_context_tokens=2000,
        top_k=5,
        chunk_top_k=5,
        max_total_tokens=6000,
        max_entity_tokens=2000,
        max_relation_tokens=2000,
        cosine_better_than_threshold=0.2,
        enable_image_processing=False,
        enable_table_processing=False,
        enable_equation_processing=False,
        enable_rerank=False,
        neo4j_uri=None,
        neo4j_username=None,
        neo4j_password=None,
        index_shape={},
    )


def test_preparsed_content_list_includes_context_prefix_and_bridge_metadata(tmp_path):
    adapter = NativeRAGAnythingAdapter(_profile(tmp_path), AppSettings())
    chunk = AdapterChunk(
        text="Guide us to the straight path.",
        source_location={"page": 1, "reference": "1:5"},
        metadata={
            "chunk_identity": "doc-1|1:5",
            "document_metadata": {"title": "Synthetic Tafseer"},
            "reference_metadata": {"references": ["1:5"]},
            "content_type": "text",
            "quality_action_policy": {"index_vector": True, "project_graph": True},
            "provenance": {"blocks": [{"block_type": "paragraph", "role": "body"}]},
        },
        runtime_source_id="runtime-1",
        content_type="text",
    )

    rows = adapter._content_list_from_preparsed_chunks([chunk], document_id="doc-1")

    assert rows[0]["text"].startswith("[Context: Synthetic Tafseer > 1:5")
    assert rows[0]["canonical_chunk_id"] == "runtime-1"
    assert rows[0]["full_doc_id"] == "doc-1"
    assert rows[0]["metadata"]["quality_action_policy"]["index_vector"] is True
    assert rows[0]["metadata"]["evidence_context"]["reference"] == "1:5"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_native_raganything_adapter.py::test_preparsed_content_list_includes_context_prefix_and_bridge_metadata -q
```

Expected: FAIL because `_content_list_from_preparsed_chunks()` only sends flat text/page data.

- [ ] **Step 3: Enrich native preparsed content list rows**

In `backend/src/ragstudio/services/native_raganything_adapter.py`, import:

```python
from ragstudio.services.evidence_context import (
    evidence_context_from_metadata,
    prefixed_embedding_text,
)
```

Inside `_content_list_from_preparsed_chunks()`, replace the `item` construction with:

```python
            metadata = dict(chunk.metadata)
            evidence_context = evidence_context_from_metadata(
                metadata,
                source_location=chunk.source_location,
                content_type=chunk.content_type,
            )
            if evidence_context:
                metadata["evidence_context"] = evidence_context
            item: dict[str, Any] = {
                "id": chunk_identity,
                "chunk_identity": chunk_identity,
                "canonical_chunk_id": chunk_identity,
                "full_doc_id": document_id,
                "type": chunk.content_type or "text",
                "text": prefixed_embedding_text(
                    chunk.text,
                    metadata,
                    source_location=chunk.source_location,
                    content_type=chunk.content_type,
                ),
                "metadata": {
                    key: metadata[key]
                    for key in (
                        "chunk_identity",
                        "reference_metadata",
                        "quality_action_policy",
                        "evidence_context",
                        "content_type",
                    )
                    if key in metadata
                },
            }
```

Keep the existing `page_idx` logic after this block.

- [ ] **Step 4: Run native adapter tests**

Run:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_native_raganything_adapter.py -q
```

Expected: PASS. If this file imports optional runtime libraries at module import time, use the targeted test first and report any missing optional dependency separately.

- [ ] **Step 5: Commit**

Run:

```bash
git add backend/src/ragstudio/services/native_raganything_adapter.py backend/tests/test_native_raganything_adapter.py
git commit -m "feat: bridge canonical context into native runtime chunks"
```

---

### Task 4: Layout And Context Neighbor Expansion

**Files:**
- Create: `backend/src/ragstudio/services/layout_neighbor_service.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Test: `backend/tests/test_layout_neighbor_service.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Write failing tests for bounded same-page/reference neighbors**

Create `backend/tests/test_layout_neighbor_service.py`:

```python
import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.services.layout_neighbor_service import LayoutNeighborService


@pytest.mark.asyncio
async def test_layout_neighbor_service_returns_same_reference_and_page_neighbors(database_url, tmp_path):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        session.add(
            Document(
                id="doc-layout-neighbor",
                filename="layout.pdf",
                content_type="application/pdf",
                sha256="layout-sha",
                artifact_path=str(tmp_path / "layout.pdf"),
            )
        )
        session.add_all(
            [
                Chunk(
                    id="seed",
                    document_id="doc-layout-neighbor",
                    text="Caption for figure.",
                    source_location={"page": 4, "reference": "1:5"},
                    metadata_json={"reference_metadata": {"references": ["1:5"]}},
                ),
                Chunk(
                    id="same-ref",
                    document_id="doc-layout-neighbor",
                    text="Body explains the figure.",
                    source_location={"page": 4, "reference": "1:5"},
                    metadata_json={"reference_metadata": {"references": ["1:5"]}},
                ),
                Chunk(
                    id="blocked",
                    document_id="doc-layout-neighbor",
                    text="Blocked neighbor.",
                    source_location={"page": 4, "reference": "1:5"},
                    metadata_json={"quality_action_policy": {"action": "block"}},
                ),
                Chunk(
                    id="other-page",
                    document_id="doc-layout-neighbor",
                    text="Far evidence.",
                    source_location={"page": 8, "reference": "9:9"},
                    metadata_json={},
                ),
            ]
        )
        await session.commit()

        neighbors = await LayoutNeighborService(session).neighbors_for(
            seed_chunk_ids=["seed"],
            document_ids=["doc-layout-neighbor"],
            limit=5,
        )

    await engine.dispose()

    assert [candidate.chunk_id for candidate in neighbors] == ["same-ref"]
    assert neighbors[0].retrieval_pass == "layout_neighbor"
    assert "layout_neighbor" in neighbors[0].reasons
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_layout_neighbor_service.py -q
```

Expected: FAIL because `LayoutNeighborService` does not exist.

- [ ] **Step 3: Implement the service**

Create `backend/src/ragstudio/services/layout_neighbor_service.py`:

```python
from __future__ import annotations

from typing import Any

from ragstudio.db.models import Chunk
from ragstudio.services.evidence_context import evidence_context_from_metadata
from ragstudio.services.retrieval_evidence import EvidenceCandidate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class LayoutNeighborService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def neighbors_for(
        self,
        *,
        seed_chunk_ids: list[str],
        document_ids: list[str],
        limit: int,
    ) -> list[EvidenceCandidate]:
        if not seed_chunk_ids:
            return []
        seed_rows = (
            await self.session.execute(select(Chunk).where(Chunk.id.in_(seed_chunk_ids)))
        ).scalars().all()
        if not seed_rows:
            return []

        pages = {_page(seed.source_location) for seed in seed_rows if _page(seed.source_location) is not None}
        references = {_reference(seed) for seed in seed_rows if _reference(seed)}
        statement = select(Chunk)
        if document_ids:
            statement = statement.where(Chunk.document_id.in_(document_ids))
        rows = (await self.session.execute(statement.order_by(Chunk.created_at.asc(), Chunk.id.asc()))).scalars().all()

        candidates: list[EvidenceCandidate] = []
        seed_ids = set(seed_chunk_ids)
        for row in rows:
            if row.id in seed_ids:
                continue
            metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
            policy = metadata.get("quality_action_policy")
            if isinstance(policy, dict) and policy.get("action") == "block":
                continue
            same_page = _page(row.source_location) in pages
            same_reference = _reference(row) in references
            if not same_page and not same_reference:
                continue
            context = evidence_context_from_metadata(
                metadata,
                source_location=row.source_location if isinstance(row.source_location, dict) else {},
                content_type=row.content_type,
            )
            if context:
                metadata = {**metadata, "evidence_context": context}
            candidates.append(
                EvidenceCandidate(
                    candidate_id=f"layout-neighbor:{row.id}",
                    text=row.text,
                    document_id=row.document_id,
                    chunk_id=row.id,
                    source_location=row.source_location if isinstance(row.source_location, dict) else {},
                    metadata=metadata,
                    tool="metadata",
                    tool_rank=len(candidates) + 1,
                    base_score=9.0,
                    boost_score=1.5,
                    final_score=10.5,
                    reasons=["layout_neighbor"],
                    retrieval_pass="layout_neighbor",
                    scope_status="in_scope",
                )
            )
            if len(candidates) >= max(limit, 1):
                break
        return candidates


def _page(source_location: Any) -> int | None:
    if not isinstance(source_location, dict):
        return None
    page = source_location.get("page") or source_location.get("page_start")
    return page if isinstance(page, int) else None


def _reference(chunk: Chunk) -> str | None:
    if isinstance(chunk.source_location, dict) and isinstance(chunk.source_location.get("reference"), str):
        return chunk.source_location["reference"]
    metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
    refs = metadata.get("reference_metadata", {}).get("references", [])
    return str(refs[0]) if isinstance(refs, list) and refs else None
```

- [ ] **Step 4: Wire neighbors into retrieval orchestrator after vector and metadata candidates**

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, import:

```python
from ragstudio.services.layout_neighbor_service import LayoutNeighborService
```

After `vector_candidates, vector_traces = await self._safe_vector_candidates(...)`, add:

```python
        layout_neighbors, layout_neighbor_traces = await self._safe_layout_neighbors(
            [*metadata_candidates, *vector_candidates],
            document_ids=document_ids,
            limit=max(limit, 1),
            timings=timings,
        )
```

When building the fused candidate list, include `layout_neighbors` with the existing native, metadata, vector, and graph candidates.

Add this method to `RetrievalOrchestrator`:

```python
    async def _safe_layout_neighbors(
        self,
        seeds: list[EvidenceCandidate],
        *,
        document_ids: list[str],
        limit: int,
        timings: dict[str, Any],
    ) -> tuple[list[EvidenceCandidate], list[dict[str, Any]]]:
        started = perf_counter()
        seed_chunk_ids = [
            candidate.chunk_id
            for candidate in seeds
            if candidate.chunk_id and candidate.tool in {"metadata", "pgvector", "graph"}
        ]
        if not seed_chunk_ids or not hasattr(self.chunk_service, "session"):
            timings["layout_neighbor_ms"] = _elapsed_ms(started)
            return [], [
                {
                    "stage": "layout_neighbor_expansion",
                    "status": "skipped",
                    "reason": "no_seed_chunks_or_session",
                    "candidate_count": 0,
                }
            ]
        try:
            candidates = await LayoutNeighborService(self.chunk_service.session).neighbors_for(
                seed_chunk_ids=list(dict.fromkeys(seed_chunk_ids)),
                document_ids=document_ids,
                limit=limit,
            )
        except Exception as exc:
            timings["layout_neighbor_ms"] = _elapsed_ms(started)
            return [], [
                {
                    "stage": "layout_neighbor_expansion",
                    "status": "failed",
                    "reason": exc.__class__.__name__,
                    "candidate_count": 0,
                }
            ]
        timings["layout_neighbor_ms"] = _elapsed_ms(started)
        return candidates, [
            {
                "stage": "layout_neighbor_expansion",
                "status": "ran",
                "reason": "same_page_or_reference_neighbors",
                "candidate_count": len(candidates),
                "candidate_ids": [candidate.candidate_id for candidate in candidates],
            }
        ]
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_layout_neighbor_service.py backend/tests/test_retrieval_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add backend/src/ragstudio/services/layout_neighbor_service.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_layout_neighbor_service.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: expand retrieval with canonical layout neighbors"
```

---

### Task 5: Vector Hits Seed Graph Expansion

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`
- Test: `backend/tests/test_graph_expansion_service.py`

- [ ] **Step 1: Add a failing unit test for vector graph seeds**

Append to `backend/tests/test_retrieval_orchestrator.py`:

```python
from ragstudio.services.retrieval_evidence import EvidenceCandidate
from ragstudio.services.retrieval_orchestrator import _graph_seed_candidates


def test_graph_seed_candidates_accept_hydrated_vector_hits():
    vector = EvidenceCandidate(
        candidate_id="vector:chunk-1",
        text="Hydrated canonical text",
        document_id="doc-1",
        chunk_id="chunk-1",
        source_location={"page": 1},
        metadata={
            "vector_retrieval": {"hydrated_to_canonical": True},
            "quality_action_policy": {"project_graph": True},
        },
        tool="pgvector",
        tool_rank=1,
        base_score=0.9,
        retrieval_pass="vector_db",
    )

    seeds = _graph_seed_candidates([vector], document_ids=["doc-1"], max_seeds=5)

    assert [seed.chunk_id for seed in seeds] == ["chunk-1"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_retrieval_orchestrator.py::test_graph_seed_candidates_accept_hydrated_vector_hits -q
```

Expected: FAIL because `_graph_seed_candidates()` only accepts metadata/lexical/reference tools.

- [ ] **Step 3: Update graph seed selection**

In `_graph_seed_candidates()` in `backend/src/ragstudio/services/retrieval_orchestrator.py`, replace:

```python
        if candidate.tool not in {"metadata", "lexical", "reference_exact", "arabic_lexical"}:
            continue
```

with:

```python
        hydrated_vector = (
            candidate.tool == "pgvector"
            and isinstance(candidate.metadata.get("vector_retrieval"), dict)
            and candidate.metadata["vector_retrieval"].get("hydrated_to_canonical") is True
        )
        if candidate.tool not in {"metadata", "lexical", "reference_exact", "arabic_lexical"} and not hydrated_vector:
            continue
```

- [ ] **Step 4: Run graph and orchestrator tests**

Run:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_retrieval_orchestrator.py backend/tests/test_graph_expansion_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: allow hydrated vector hits to seed graph expansion"
```

---

### Task 6: Breadcrumb-Aware Context Assembly And Answer Prompt

**Files:**
- Modify: `backend/src/ragstudio/services/context_assembly_service.py`
- Modify: `backend/src/ragstudio/services/runtime_answer_service.py`
- Test: `backend/tests/test_context_assembly_service.py`
- Test: `backend/tests/test_runtime_answer_service.py`

- [ ] **Step 1: Write failing tests for breadcrumb context**

Append to `backend/tests/test_context_assembly_service.py`:

```python
from ragstudio.services.context_assembly_service import ContextAssemblyService
from ragstudio.services.retrieval_evidence import EvidenceCandidate


def test_context_assembly_injects_breadcrumb_text_from_evidence_context():
    candidate = EvidenceCandidate(
        candidate_id="metadata:chunk-1",
        text="Guide us to the straight path.",
        document_id="doc-1",
        chunk_id="chunk-1",
        source_location={"page": 1},
        metadata={"evidence_context": {"breadcrumb": "Synthetic Tafseer > 1:5"}},
        tool="metadata",
        tool_rank=1,
        base_score=10,
    )

    context = ContextAssemblyService(max_context_tokens=200).assemble([candidate])

    assert context.evidence[0].breadcrumb == "Synthetic Tafseer > 1:5"
    assert context.evidence[0].context_text.startswith("[Synthetic Tafseer > 1:5]")
```

Create `backend/tests/test_runtime_answer_service.py` if it does not exist, or append:

```python
from ragstudio.services.retrieval_evidence import EvidenceCandidate
from ragstudio.services.runtime_answer_service import RuntimeAnswerService


def test_runtime_answer_prompt_includes_breadcrumb_when_available():
    service = RuntimeAnswerService()
    candidate = EvidenceCandidate(
        candidate_id="metadata:chunk-1",
        text="Guide us to the straight path.",
        document_id="doc-1",
        chunk_id="chunk-1",
        source_location={"page": 1},
        metadata={"evidence_context": {"breadcrumb": "Synthetic Tafseer > 1:5"}},
        tool="metadata",
        tool_rank=1,
        base_score=10,
    )

    prompt = service._prompt("What is 1:5?", [candidate])

    assert "context=Synthetic Tafseer > 1:5" in prompt
    assert "Guide us to the straight path." in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_context_assembly_service.py::test_context_assembly_injects_breadcrumb_text_from_evidence_context backend/tests/test_runtime_answer_service.py::test_runtime_answer_prompt_includes_breadcrumb_when_available -q
```

Expected: FAIL because `ContextEvidence` has no `breadcrumb` or `context_text`, and answer prompt headers do not include context.

- [ ] **Step 3: Add breadcrumb fields to `ContextEvidence`**

In `backend/src/ragstudio/services/context_assembly_service.py`, change `ContextEvidence` to:

```python
@dataclass(frozen=True)
class ContextEvidence:
    candidate_id: str
    chunk_id: str | None
    document_id: str | None
    page: int | None
    reference: str | None
    original_text: str
    normalized_text: None = None
    breadcrumb: str | None = None
    layout_summary: str | None = None
    context_text: str | None = None
    included_reason: str = "retrieval_fusion"
    retrieval_passes: list[str] = field(default_factory=list)
```

Before constructing `ContextEvidence`, add:

```python
            evidence_context = candidate.metadata.get("evidence_context")
            evidence_context = evidence_context if isinstance(evidence_context, dict) else {}
            breadcrumb = evidence_context.get("breadcrumb")
            breadcrumb = breadcrumb if isinstance(breadcrumb, str) and breadcrumb else None
            layout_summary = evidence_context.get("layout_summary")
            layout_summary = layout_summary if isinstance(layout_summary, str) and layout_summary else None
            context_text = _context_text(text, breadcrumb=breadcrumb, layout_summary=layout_summary)
```

Add these fields to the `ContextEvidence(...)` call:

```python
                breadcrumb=breadcrumb,
                layout_summary=layout_summary,
                context_text=context_text,
```

Add helper:

```python
def _context_text(
    text: str,
    *,
    breadcrumb: str | None,
    layout_summary: str | None,
) -> str:
    labels = [value for value in (breadcrumb, layout_summary) if value]
    if not labels:
        return text
    return f"[{' | '.join(labels)}]\n{text}"
```

- [ ] **Step 4: Include context labels in answer prompt**

In `backend/src/ragstudio/services/runtime_answer_service.py`, inside `_prompt()`, before `header = (...)`, add:

```python
            evidence_context = candidate.metadata.get("evidence_context")
            evidence_context = evidence_context if isinstance(evidence_context, dict) else {}
            breadcrumb = evidence_context.get("breadcrumb")
            context_label = (
                f" context={breadcrumb}"
                if isinstance(breadcrumb, str) and breadcrumb.strip()
                else ""
            )
```

Then add `{context_label}` to the `header` string after the chunk id:

```python
                f"chunk={candidate.chunk_id or 'unknown'}"
                f"{context_label}"
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_context_assembly_service.py backend/tests/test_runtime_answer_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add backend/src/ragstudio/services/context_assembly_service.py backend/src/ragstudio/services/runtime_answer_service.py backend/tests/test_context_assembly_service.py backend/tests/test_runtime_answer_service.py
git commit -m "feat: add breadcrumb-aware context assembly"
```

---

### Task 7: Diversity-Aware Candidate Selection After Fusion And Rerank

**Files:**
- Create: `backend/src/ragstudio/services/candidate_diversity.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Test: `backend/tests/test_candidate_diversity.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Write failing diversity tests**

Create `backend/tests/test_candidate_diversity.py`:

```python
from ragstudio.services.candidate_diversity import select_diverse_candidates
from ragstudio.services.retrieval_evidence import EvidenceCandidate


def candidate(chunk_id: str, text: str, score: float) -> EvidenceCandidate:
    return EvidenceCandidate(
        candidate_id=f"metadata:{chunk_id}",
        text=text,
        document_id="doc-1",
        chunk_id=chunk_id,
        source_location={},
        metadata={},
        tool="metadata",
        tool_rank=1,
        base_score=score,
        final_score=score,
    )


def test_select_diverse_candidates_keeps_best_and_suppresses_redundant_text():
    first = candidate("a", "alpha beta gamma delta", 20)
    duplicate = candidate("b", "alpha beta gamma delta repeated", 19)
    different = candidate("c", "zakat finance charitable obligation", 12)

    selected, trace = select_diverse_candidates([first, duplicate, different], limit=2)

    assert [item.chunk_id for item in selected] == ["a", "c"]
    assert trace["suppressed_candidate_ids"] == ["metadata:b"]
    assert trace["status"] == "ran"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_candidate_diversity.py -q
```

Expected: FAIL because `candidate_diversity.py` does not exist.

- [ ] **Step 3: Implement deterministic diversity selection**

Create `backend/src/ragstudio/services/candidate_diversity.py`:

```python
from __future__ import annotations

from ragstudio.services.retrieval_evidence import EvidenceCandidate


def select_diverse_candidates(
    candidates: list[EvidenceCandidate],
    *,
    limit: int,
    similarity_threshold: float = 0.65,
) -> tuple[list[EvidenceCandidate], dict[str, object]]:
    selected: list[EvidenceCandidate] = []
    suppressed: list[str] = []
    for candidate in sorted(candidates, key=lambda item: item.final_score, reverse=True):
        if len(selected) >= max(limit, 1):
            break
        if any(_jaccard(candidate.text, existing.text) >= similarity_threshold for existing in selected):
            suppressed.append(candidate.candidate_id)
            continue
        selected.append(candidate)
    return selected, {
        "stage": "candidate_diversity",
        "status": "ran",
        "input_count": len(candidates),
        "selected_count": len(selected),
        "suppressed_candidate_ids": suppressed,
        "similarity_threshold": similarity_threshold,
    }


def _jaccard(left: str, right: str) -> float:
    left_terms = _terms(left)
    right_terms = _terms(right)
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def _terms(value: str) -> set[str]:
    return {term.casefold() for term in value.split() if len(term) > 2}
```

- [ ] **Step 4: Wire diversity after reranking and before context assembly**

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, import:

```python
from ragstudio.services.candidate_diversity import select_diverse_candidates
```

In `RetrievalOrchestrator.query()`, immediately after this existing block:

```python
            reranked, parser_quality_trace = _annotate_parser_quality_warnings(reranked)
            if parser_quality_trace is not None:
                traces.append(parser_quality_trace)
```

add:

```python
        diversity_limit = int(query_config.get("diversity_limit") or limit)
        reranked, diversity_trace = select_diverse_candidates(
            reranked,
            limit=diversity_limit,
        )
        traces.append(diversity_trace)
```

- [ ] **Step 5: Add an orchestrator regression test**

Add a focused test in `backend/tests/test_retrieval_orchestrator.py` that calls the smallest function or orchestrator path available after Step 4 and asserts a trace with `stage == "candidate_diversity"` exists. Use existing fake services in that file rather than introducing live runtime dependencies.

```python
assert any(trace.get("stage") == "candidate_diversity" for trace in result.chunk_traces)
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_candidate_diversity.py backend/tests/test_retrieval_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add backend/src/ragstudio/services/candidate_diversity.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_candidate_diversity.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: add diversity-aware retrieval selection"
```

---

### Task 8: Regression-Lock Quality And Materialization Gate Boundaries

**Files:**
- Modify: `backend/tests/test_vector_retrieval_service.py`
- Modify: `backend/tests/test_vector_candidate_repository.py`
- Modify: `backend/tests/test_retrieval_route_planner.py`
- Modify: `backend/tests/test_domain_layout_retrieval_flow.py`
- Modify: `backend/tests/test_native_raganything_adapter.py`

- [ ] **Step 1: Add tests that prove the old "vector bypass" finding stays fixed**

In `backend/tests/test_vector_retrieval_service.py`, add:

```python
def test_vector_lane_rejects_action_block_even_when_baseline_passes():
    metadata = {"quality_action_policy": {"action": "block", "index_vector": True}}

    result = prepare_vector_candidates(
        [{"chunk_id": "chunk-1", "document_id": "doc-1", "text": "unsafe"}],
        metadata=metadata,
        baseline_gate={"passed": True},
    )

    assert result.status == "skipped"
    assert result.reason == "vector_lane_blocked_by_quality_policy"
```

In `backend/tests/test_native_raganything_adapter.py`, add:

```python
def test_preparsed_content_list_preserves_quality_policy_for_runtime_bridge(tmp_path):
    adapter = NativeRAGAnythingAdapter(_profile(tmp_path), AppSettings())
    chunk = AdapterChunk(
        text="Unsafe text",
        source_location={"page": 1},
        metadata={"quality_action_policy": {"index_vector": False, "project_graph": False}},
        content_type="text",
    )

    rows = adapter._content_list_from_preparsed_chunks([chunk], document_id="doc-1")

    assert rows[0]["metadata"]["quality_action_policy"]["index_vector"] is False
    assert rows[0]["metadata"]["quality_action_policy"]["project_graph"] is False
```

- [ ] **Step 2: Run the regression tests**

Run:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_vector_retrieval_service.py backend/tests/test_vector_candidate_repository.py backend/tests/test_retrieval_route_planner.py backend/tests/test_domain_layout_retrieval_flow.py backend/tests/test_native_raganything_adapter.py -q
```

Expected: PASS.

- [ ] **Step 3: Commit**

Run:

```bash
git add backend/tests/test_vector_retrieval_service.py backend/tests/test_vector_candidate_repository.py backend/tests/test_retrieval_route_planner.py backend/tests/test_domain_layout_retrieval_flow.py backend/tests/test_native_raganything_adapter.py
git commit -m "test: lock retrieval materialization quality boundaries"
```

---

### Task 9: Proof And Documentation Traceability Update

**Files:**
- Modify: `docs/benchmarks/ragstudio-oss-proof-v1/docs/LIMITATIONS.md`
- Modify: `docs/benchmarks/ragstudio-oss-proof-v1/docs/CLAIMS.md`
- Modify: `docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.registry.json`
- Test: `backend/tests/test_proof_packet_contract.py`
- Test: `backend/tests/test_sample_pack_contract.py`

- [ ] **Step 1: Add public-safe limitations for remaining non-goals**

In `docs/benchmarks/ragstudio-oss-proof-v1/docs/LIMITATIONS.md`, add a section:

```markdown
## Retrieval Architecture Limitations

- Domain-specific lexical expansion is registry-based, but only adapters present
  in the public fixture are proven by this packet.
- Native RAG-Anything is a secondary runtime lane. Public proof claims are made
  from canonical Ragstudio evidence and hydrated bridge metadata, not from opaque
  runtime snippets alone.
- Layout-aware retrieval uses canonical page, reference, content type, and
  provenance metadata. Query-time visual reinspection is not part of the V1
  static proof path.
- Context assembly includes safe breadcrumbs and dropped-evidence reasons, but
  does not claim full document summarization or unbounded sliding-window recall.
```

- [ ] **Step 2: Add or update a claim entry for the closed architecture gaps**

In `docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.registry.json`, add a claim object following the existing file's schema. Use this exact text for the claim if the registry stores text fields:

```json
"Ragstudio keeps canonical chunk identity, quality policy, layout provenance, and context breadcrumbs visible across retrieval lanes before answer assembly."
```

Set its status to `proven` only if Tasks 1-8 are complete and proof fixtures include the new traces. Otherwise set status to `roadmap` with a limitation pointing to `Retrieval Architecture Limitations`.

- [ ] **Step 3: Run proof validation**

Run:

```bash
./scripts/proof.sh --strict --json
```

Expected: PASS. If Windows shell cannot run the script, run:

```bash
bash ./scripts/proof.sh --strict --json
```

- [ ] **Step 4: Run proof packet tests**

Run:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_proof_packet_contract.py backend/tests/test_sample_pack_contract.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add docs/benchmarks/ragstudio-oss-proof-v1/docs/LIMITATIONS.md docs/benchmarks/ragstudio-oss-proof-v1/docs/CLAIMS.md docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.registry.json backend/tests/test_proof_packet_contract.py backend/tests/test_sample_pack_contract.py
git commit -m "docs: document retrieval architecture proof boundaries"
```

---

## Final Validation

Run these after all tasks are complete:

```bash
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; uv run pytest backend/tests/test_domain_query_expansion_service.py backend/tests/test_evidence_context.py backend/tests/test_native_raganything_adapter.py backend/tests/test_layout_neighbor_service.py backend/tests/test_candidate_diversity.py backend/tests/test_context_assembly_service.py backend/tests/test_runtime_answer_service.py backend/tests/test_retrieval_orchestrator.py backend/tests/test_vector_retrieval_service.py backend/tests/test_vector_candidate_repository.py backend/tests/test_domain_layout_retrieval_flow.py -q
```

Expected: PASS.

Run public proof validation:

```bash
bash ./scripts/proof.sh --strict --json
```

Expected: PASS.

Run frontend trace tests only if query/chunk UI fields are changed:

```bash
cd frontend
npm test -- query-page.test.tsx query-pathway-viewer.test.tsx chunk-inspector.test.tsx
```

Expected: PASS.

## Self-Review

- Spec coverage: Tasks 1-9 cover all high-confidence and partially stale findings: hardcoded domain expansion, layout stripping in native vector/runtime rows, hardcoded quality-bypass regression risk, missing spatial/layout neighbor retrieval, flat context assembly, reranker redundancy, vector-to-graph disconnect, and public proof limitations.
- Placeholder scan: This plan avoids deferred work. Task 7 Step 5 intentionally points to the existing fake-service pattern in `test_retrieval_orchestrator.py` because that file already contains local fake classes; the assertion is exact and must be attached to the smallest existing orchestrator path.
- Type consistency: New fields are consistently named `evidence_context`, `breadcrumb`, `layout_summary`, `context_text`, and `layout_neighbor`. New services are `DomainLexicalRegistry`, `LayoutNeighborService`, and `select_diverse_candidates`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-22-rag-architecture-gap-closure.md`. Two execution options:

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
