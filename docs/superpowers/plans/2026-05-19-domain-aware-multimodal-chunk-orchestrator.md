# Domain-Aware Multimodal Chunk Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a parser-agnostic, multimodal, domain-aware canonical assembly layer that builds evidence-backed canonical units before quality gates run.

**Architecture:** Keep MinerU and RAG-Anything as parser/runtime engines, and keep `ChunkSplitter` as the single ingestion boundary for content-list chunk assembly. Parser output is first normalized by `MinerUContentNormalizer`; normalized blocks then become a layout graph, domain resolvers assemble canonical units, and existing quality gates validate only after assembly has a chance to repair parser ordering and layout issues.

**Tech Stack:** Python 3.12, FastAPI service layer, SQLAlchemy persistence, existing `AdapterChunk`, MinerU `source_content_list.json`, RAG-Anything prepared chunk insertion, pytest.

---

## Scope Check

This plan changes one ingestion subsystem: normalized parser blocks to canonical chunk assembly. It intentionally does not change the final answer generator, embeddings provider, Neo4j storage schema, the MinerU sidecar itself, or the durable job/recovery architecture.

This plan also does not try to remove all warnings. It turns false or expected parser warnings into evidence-backed accepted states, while preserving true missing-evidence warnings.

## Current Problem

The current ingestion shape is:

```text
MinerU parse
  -> ChunkSplitter._chunks_from_content_list()
  -> MinerUContentNormalizer.normalize_content_list()
  -> ChunkSplitter._canonical_reference_pieces()
  -> ReferenceUnitAssembler.forward assembly
  -> chunk persistence
  -> domain quality gate
  -> index and graph materialization
```

For `hadith_ibn_majah.pdf`, MinerU sometimes emits a hadith header after related body text on the same page. The current forward-only assembler in `backend/src/ragstudio/services/reference_unit_assembler.py` cannot attach earlier Arabic/English body blocks to a late recovered header. The domain gate then correctly emits `reference_unit_missing_expected_script` for answerable hadith chunks that contain Latin text but no Arabic.

The root solve is to evolve the existing canonical assembly boundary, not create a parallel pre-split pipeline:

```text
MinerU or RAG-Anything parser output
  -> MinerUContentNormalizer / parser adapter normalization
  -> NormalizedBlock graph
  -> domain resolver strategy inside canonical assembly
  -> ReferenceUnitAssembler fallback
  -> canonical evidence units
  -> existing quality gates
  -> chunk persistence and runtime indexing
```

## Architecture Correction

The earlier standalone `ChunkOrchestrator` idea is intentionally rejected. It would create a second ingestion path before `ChunkSplitter`, duplicate content-list reading/normalization, and risk diverging from existing vision recovery, parser-warning propagation, and source-ref behavior.

The solid architecture is:

```text
ChunkService.index_document()
  -> DocumentParserService.parse()
  -> ChunkSplitter.split()
  -> ChunkSplitter._chunks_from_content_list()
  -> MinerUContentNormalizer.normalize_content_list()
  -> CanonicalAssemblyStrategy.from_normalized_blocks()
  -> ReferenceUnitAssembler fallback when no domain strategy applies
  -> DomainMetadataQualityGate.validate_adapter_chunks()
  -> ChunkPersistenceService.persist()
```

Rules:

- Build the graph from `NormalizedBlock`, not raw MinerU JSON.
- Integrate at `ChunkSplitter._canonical_reference_pieces()`, because that function already has normalized blocks, source block refs, parser warnings, bbox, page data, and `ReferenceSemantics`.
- Keep `ReferenceUnitAssembler` as the default/fallback strategy.
- Add domain-aware strategies behind the canonical assembly boundary; hadith is the first strategy.
- Feed RAG-Anything/LightRAG prepared canonical chunks after Ragstudio has built and validated the chunk truth.
- Use AI only in a later arbitration layer for low-confidence mappings; deterministic graph assembly is the MVP.

## File Structure

- Create `backend/src/ragstudio/services/canonical_assembly.py`
  - Defines parser-agnostic evidence block views over existing `NormalizedBlock` objects.
  - Builds page/block relationships from normalized blocks.
  - Selects domain assembly strategies and falls back to `ReferenceUnitAssembler`.
  - Does not depend on SQLAlchemy or FastAPI.
- Create `backend/src/ragstudio/services/evidence_graph.py`
  - Builds page/block relationships from normalized block views.
  - Owns reading-order and neighborhood logic.
- Create `backend/src/ragstudio/services/domain_resolvers/__init__.py`
  - Exports resolver base types and default resolver selection.
- Create `backend/src/ragstudio/services/domain_resolvers/base.py`
  - Defines `DomainResolver`, `CanonicalUnit`, `AssemblyDecision`, and `ResolverContext`.
- Create `backend/src/ragstudio/services/domain_resolvers/hadith.py`
  - Implements first resolver plugin for `Book X, Hadith Y` units.
- Modify `backend/src/ragstudio/services/chunk_splitter.py`
  - Calls canonical assembly from `_canonical_reference_pieces()` after `MinerUContentNormalizer.normalize_content_list()`.
  - Falls back to the existing `ReferenceUnitAssembler` when no domain resolver applies.
- Modify `backend/src/ragstudio/services/reference_unit_assembler.py`
  - Keep as fallback and for non-layout-aware flows.
  - Accept any small shared helper extraction only when needed by canonical assembly.
- Modify `backend/src/ragstudio/services/domain_metadata_quality_gate.py`
  - Preserve existing validation, but accept orchestrator evidence metadata when classifying warnings.
- Modify `backend/src/ragstudio/services/job_quality_warning_service.py`
  - Expose counted warnings, info warnings, and distinct affected chunk counts separately.
- Modify `frontend/src/features/documents/documents-page.tsx`
  - Display distinct affected chunks instead of summing overlapping group counts.
  - Distinguish counted warnings from audit/info warnings.
- Test `backend/tests/test_canonical_assembly.py`
- Test `backend/tests/test_evidence_graph.py`
- Test `backend/tests/test_hadith_domain_resolver.py`
- Test `backend/tests/test_chunk_splitter.py`
- Test `backend/tests/test_domain_metadata_quality_gate.py`
- Test `backend/tests/test_job_quality_warnings.py`
- Test `frontend/tests/documents-page.test.tsx`
- Modify `docs/workflows.md`
  - Document the orchestration layer and warning semantics.

---

### Task 1: Add Canonical Assembly Views Over Normalized Blocks

**Files:**
- Create: `backend/src/ragstudio/services/canonical_assembly.py`
- Test: `backend/tests/test_canonical_assembly.py`

- [ ] **Step 1: Write failing normalized block view tests**

Create `backend/tests/test_canonical_assembly.py`:

```python
from ragstudio.services.canonical_assembly import (
    EvidenceBlockView,
    EvidenceBoundingBox,
    EvidenceSourceRef,
    block_views_from_normalized,
)
from ragstudio.services.parser_normalization import NormalizedBlock


def test_block_views_from_normalized_preserves_source_refs_warnings_and_scripts():
    normalized = [
        NormalizedBlock(
            text="Book 2, Hadith 29 - Grade: Sahih",
            page=127,
            block_type="header",
            source_item={"bbox": [10, 20, 300, 40]},
        ),
        NormalizedBlock(
            text="قال رسول الله صلى الله عليه وسلم",
            page=127,
            block_type="text",
            source_item={"bbox": [10, 50, 300, 90]},
        ),
    ]

    blocks = block_views_from_normalized(
        normalized,
        content_list_ref="source_a86dd9bf/source/auto/source_content_list.json",
    )

    assert [block.block_type for block in blocks] == ["header", "text"]
    assert blocks[0].page_start == 127
    assert blocks[0].source_ref.block_index == 0
    assert blocks[0].bbox == EvidenceBoundingBox(x0=10.0, y0=20.0, x1=300.0, y1=40.0)
    assert blocks[1].scripts == frozenset({"arabic"})
    assert blocks[1].source_ref == EvidenceSourceRef(
        artifact_ref="source_a86dd9bf/source/auto/source_content_list.json",
        block_index=1,
    )
```

- [ ] **Step 2: Run the failing normalized block view test**

Run:

```powershell
pytest backend/tests/test_canonical_assembly.py -v
```

Expected: fails because `ragstudio.services.canonical_assembly` does not exist.

- [ ] **Step 3: Implement normalized block view types**

Create `backend/src/ragstudio/services/canonical_assembly.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ragstudio.services.parser_normalization import NormalizedBlock
from ragstudio.services.script_detection import SCRIPT_PATTERNS


@dataclass(frozen=True)
class EvidenceBoundingBox:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class EvidenceSourceRef:
    artifact_ref: str
    block_index: int

    @property
    def key(self) -> str:
        return f"{self.artifact_ref}:block:{self.block_index}"


@dataclass(frozen=True)
class EvidenceBlockView:
    text: str
    block_type: str
    page_start: int | None
    page_end: int | None
    source_ref: EvidenceSourceRef
    bbox: EvidenceBoundingBox | None = None
    modality: str = "text"
    parser_warnings: tuple[dict[str, Any], ...] = ()
    scripts: frozenset[str] = field(default_factory=frozenset)
    raw_item: dict[str, Any] = field(default_factory=dict)

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())


def block_views_from_normalized(
    blocks: list[NormalizedBlock],
    *,
    content_list_ref: str,
) -> list[EvidenceBlockView]:
    views: list[EvidenceBlockView] = []
    for index, block in enumerate(blocks):
        text = block.text.replace("\x00", "").strip()
        page_start = _page_value(block.source_item.get("page_start")) or block.page
        page_end = _page_value(block.source_item.get("page_end")) or block.page
        views.append(
            EvidenceBlockView(
                text=text,
                block_type=block.block_type,
                page_start=page_start,
                page_end=page_end,
                source_ref=EvidenceSourceRef(content_list_ref, index),
                bbox=_bbox(block.source_item.get("bbox")),
                modality=_modality(block.block_type),
                parser_warnings=tuple(block.warning_metadata()),
                scripts=frozenset(_scripts(text)),
                raw_item=dict(block.source_item),
            )
        )
    return views


def _page_value(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _bbox(value: Any) -> EvidenceBoundingBox | None:
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    try:
        return EvidenceBoundingBox(*(float(part) for part in value))
    except (TypeError, ValueError):
        return None


def _modality(block_type: str) -> str:
    if block_type in {"image", "figure"}:
        return "image"
    if block_type == "table":
        return "table"
    if block_type in {"equation", "interline_equation"}:
        return "formula"
    return "text"


def _scripts(text: str) -> set[str]:
    return {
        name
        for name, pattern in SCRIPT_PATTERNS.items()
        if pattern.search(text)
    }
```

- [ ] **Step 4: Run the evidence block test**

Run:

```powershell
pytest backend/tests/test_canonical_assembly.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/ragstudio/services/canonical_assembly.py backend/tests/test_canonical_assembly.py
git commit -m "feat: add normalized canonical assembly views"
```

---

### Task 2: Build A Page-Level Evidence Graph

**Files:**
- Create: `backend/src/ragstudio/services/evidence_graph.py`
- Test: `backend/tests/test_evidence_graph.py`

- [ ] **Step 1: Write failing graph tests**

Create `backend/tests/test_evidence_graph.py`:

```python
from ragstudio.services.canonical_assembly import EvidenceBlockView, EvidenceSourceRef
from ragstudio.services.evidence_graph import EvidenceGraph


def block(text: str, index: int, *, block_type: str = "text", scripts=frozenset()):
    return EvidenceBlockView(
        text=text,
        block_type=block_type,
        page_start=127,
        page_end=127,
        source_ref=EvidenceSourceRef("source_content_list.json", index),
        scripts=frozenset(scripts),
    )


def test_graph_can_find_prior_arabic_blocks_for_late_hadith_header():
    blocks = [
        block("قال رسول الله صلى الله عليه وسلم", 0, scripts={"arabic"}),
        block("It was narrated that Anas said...", 1, scripts={"latin"}),
        block("Book 2, Hadith 30", 2),
        block("Book 2, Hadith 29 - Grade: Sahih", 3, block_type="header"),
    ]

    graph = EvidenceGraph.from_blocks(blocks)
    nearby = graph.neighborhood(blocks[3], before=3, after=0)

    assert [item.source_ref.block_index for item in nearby] == [0, 1, 2]
    assert graph.blocks_with_script("arabic") == [blocks[0]]
```

- [ ] **Step 2: Run the failing graph test**

Run:

```powershell
pytest backend/tests/test_evidence_graph.py -v
```

Expected: fails because `EvidenceGraph` does not exist.

- [ ] **Step 3: Implement graph basics**

Create `backend/src/ragstudio/services/evidence_graph.py`:

```python
from __future__ import annotations

from collections import defaultdict

from ragstudio.services.canonical_assembly import EvidenceBlockView


class EvidenceGraph:
    def __init__(self, blocks: list[EvidenceBlockView]):
        self.blocks = blocks
        self._index_by_key = {block.source_ref.key: index for index, block in enumerate(blocks)}
        self._blocks_by_page: dict[int, list[EvidenceBlockView]] = defaultdict(list)
        for block in blocks:
            if block.page_start is not None:
                self._blocks_by_page[block.page_start].append(block)

    @classmethod
    def from_blocks(cls, blocks: list[EvidenceBlockView]) -> EvidenceGraph:
        return cls(list(blocks))

    def neighborhood(
        self,
        block: EvidenceBlockView,
        *,
        before: int,
        after: int,
    ) -> list[EvidenceBlockView]:
        index = self._index_by_key.get(block.source_ref.key)
        if index is None:
            return []
        start = max(0, index - before)
        end = min(len(self.blocks), index + after + 1)
        return [
            candidate
            for candidate in self.blocks[start:end]
            if candidate.source_ref.key != block.source_ref.key
        ]

    def page_blocks(self, page: int) -> list[EvidenceBlockView]:
        return list(self._blocks_by_page.get(page, []))

    def blocks_with_script(self, script: str) -> list[EvidenceBlockView]:
        return [block for block in self.blocks if script in block.scripts]
```

- [ ] **Step 4: Run the graph test**

Run:

```powershell
pytest backend/tests/test_evidence_graph.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/ragstudio/services/evidence_graph.py backend/tests/test_evidence_graph.py
git commit -m "feat: add evidence graph neighborhoods"
```

---

### Task 3: Add Domain Resolver Base Contract

**Files:**
- Create: `backend/src/ragstudio/services/domain_resolvers/__init__.py`
- Create: `backend/src/ragstudio/services/domain_resolvers/base.py`
- Test: `backend/tests/test_canonical_assembly.py`

- [ ] **Step 1: Write failing resolver contract test**

Append to `backend/tests/test_canonical_assembly.py`:

```python
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.domain_resolvers.base import ResolverContext, resolver_key


def test_resolver_key_uses_domain_and_document_type():
    context = ResolverContext(
        domain_metadata=DomainMetadata(domain="hadith", document_type="collection"),
        parent_metadata={},
        parent_source_location={},
        runtime_source_id="runtime-doc",
        content_type="text",
        preview_ref=None,
    )

    assert resolver_key(context) == "hadith:collection"
```

- [ ] **Step 2: Run the failing resolver contract test**

Run:

```powershell
pytest backend/tests/test_canonical_assembly.py::test_resolver_key_uses_domain_and_document_type -v
```

Expected: fails because resolver base does not exist.

- [ ] **Step 3: Implement resolver base**

Create `backend/src/ragstudio/services/domain_resolvers/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.canonical_assembly import EvidenceBlockView
from ragstudio.services.evidence_graph import EvidenceGraph


@dataclass(frozen=True)
class AssemblyDecision:
    code: str
    reason: str
    source_block_refs: tuple[str, ...] = ()
    confidence: str = "high"


@dataclass(frozen=True)
class CanonicalUnit:
    text: str
    source_location: dict[str, object]
    metadata: dict[str, object]
    runtime_source_id: str | None
    content_type: str
    preview_ref: str | None
    decisions: tuple[AssemblyDecision, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ResolverContext:
    domain_metadata: DomainMetadata
    parent_metadata: dict[str, object]
    parent_source_location: dict[str, object]
    runtime_source_id: str | None
    content_type: str
    preview_ref: str | None


class DomainResolver(Protocol):
    def can_resolve(self, context: ResolverContext) -> bool:
        ...

    def resolve_units(
        self,
        graph: EvidenceGraph,
        *,
        context: ResolverContext,
    ) -> list[CanonicalUnit]:
        ...


def resolver_key(context: ResolverContext) -> str:
    domain = (context.domain_metadata.domain or "generic").strip().casefold()
    document_type = (context.domain_metadata.document_type or "unknown").strip().casefold()
    return f"{domain}:{document_type}"
```

Create `backend/src/ragstudio/services/domain_resolvers/__init__.py`:

```python
from ragstudio.services.domain_resolvers.base import (
    AssemblyDecision,
    CanonicalUnit,
    DomainResolver,
    ResolverContext,
    resolver_key,
)

__all__ = [
    "AssemblyDecision",
    "CanonicalUnit",
    "DomainResolver",
    "ResolverContext",
    "resolver_key",
]
```

- [ ] **Step 4: Run the resolver contract test**

Run:

```powershell
pytest backend/tests/test_canonical_assembly.py::test_resolver_key_uses_domain_and_document_type -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/ragstudio/services/domain_resolvers backend/tests/test_canonical_assembly.py
git commit -m "feat: add domain resolver contract"
```

---

### Task 4: Implement Hadith Resolver For Late Headers

**Files:**
- Create: `backend/src/ragstudio/services/domain_resolvers/hadith.py`
- Modify: `backend/src/ragstudio/services/domain_resolvers/__init__.py`
- Test: `backend/tests/test_hadith_domain_resolver.py`

- [ ] **Step 1: Write failing hadith resolver test**

Create `backend/tests/test_hadith_domain_resolver.py`:

```python
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.domain_resolvers.base import ResolverContext
from ragstudio.services.domain_resolvers.hadith import HadithResolver
from ragstudio.services.canonical_assembly import EvidenceBlockView, EvidenceSourceRef
from ragstudio.services.evidence_graph import EvidenceGraph


def block(text: str, index: int, *, block_type: str = "text", scripts=frozenset()):
    return EvidenceBlockView(
        text=text,
        block_type=block_type,
        page_start=127,
        page_end=127,
        source_ref=EvidenceSourceRef("source_content_list.json", index),
        scripts=frozenset(scripts),
    )


def test_hadith_resolver_attaches_body_that_precedes_late_header():
    blocks = [
        block("قال رسول الله صلى الله عليه وسلم", 0, scripts={"arabic"}),
        block("It was narrated that Anas said...", 1, scripts={"latin"}),
        block("Book 2, Hadith 30", 2),
        block("Book 2, Hadith 29 - Grade: Sahih", 3, block_type="header"),
    ]
    context = ResolverContext(
        domain_metadata=DomainMetadata(domain="hadith", document_type="collection"),
        parent_metadata={"parser_metadata": {"parser": "mineru"}},
        parent_source_location={"artifact": "source.md"},
        runtime_source_id="runtime-doc",
        content_type="text",
        preview_ref=None,
    )

    units = HadithResolver().resolve_units(EvidenceGraph.from_blocks(blocks), context=context)

    unit = units[0]
    assert unit.preview_ref == "book:2:hadith:29"
    assert "Book 2, Hadith 29" in unit.text
    assert "قال رسول الله" in unit.text
    assert "It was narrated" in unit.text
    assert unit.metadata["canonical_reference_unit"]["answerable"] is True
    assert unit.decisions[0].code == "late_header_body_reassociated"
```

- [ ] **Step 2: Run the failing hadith resolver test**

Run:

```powershell
pytest backend/tests/test_hadith_domain_resolver.py -v
```

Expected: fails because `HadithResolver` does not exist.

- [ ] **Step 3: Implement minimal hadith resolver**

Create `backend/src/ragstudio/services/domain_resolvers/hadith.py`:

```python
from __future__ import annotations

import re

from ragstudio.services.domain_resolvers.base import (
    AssemblyDecision,
    CanonicalUnit,
    ResolverContext,
)
from ragstudio.services.canonical_assembly import EvidenceBlockView
from ragstudio.services.evidence_graph import EvidenceGraph

HADITH_HEADER_RE = re.compile(
    r"\bBook\s+(?P<book>\d{1,4})\s*,?\s*Hadith\s+(?P<hadith>\d{1,6})\b",
    re.IGNORECASE,
)


class HadithResolver:
    def can_resolve(self, context: ResolverContext) -> bool:
        return (context.domain_metadata.domain or "").strip().casefold() == "hadith"

    def resolve_units(
        self,
        graph: EvidenceGraph,
        *,
        context: ResolverContext,
    ) -> list[CanonicalUnit]:
        units: list[CanonicalUnit] = []
        for block in graph.blocks:
            match = HADITH_HEADER_RE.search(block.text)
            if match is None:
                continue
            if not self._is_late_header(block):
                continue
            body_blocks = self._prior_body_blocks(graph, block)
            if not body_blocks:
                continue
            units.append(
                self._unit_from_blocks(
                    header=block,
                    body_blocks=body_blocks,
                    match=match,
                    context=context,
                )
            )
        return units

    def _is_late_header(self, block: EvidenceBlockView) -> bool:
        return block.block_type in {"header", "footer", "page_footnote"} or "arabic" not in block.scripts

    def _prior_body_blocks(
        self,
        graph: EvidenceGraph,
        header: EvidenceBlockView,
    ) -> list[EvidenceBlockView]:
        candidates = graph.neighborhood(header, before=3, after=0)
        selected: list[EvidenceBlockView] = []
        for candidate in candidates:
            if HADITH_HEADER_RE.search(candidate.text):
                selected = []
                continue
            if "arabic" in candidate.scripts or "latin" in candidate.scripts:
                selected.append(candidate)
        return selected

    def _unit_from_blocks(
        self,
        *,
        header: EvidenceBlockView,
        body_blocks: list[EvidenceBlockView],
        match: re.Match[str],
        context: ResolverContext,
    ) -> CanonicalUnit:
        book = int(match.group("book"))
        hadith = int(match.group("hadith"))
        reference = f"book:{book}:hadith:{hadith}"
        blocks = [header, *body_blocks]
        text = "\n\n".join(block.text.strip() for block in blocks if block.text.strip())
        source_location = dict(context.parent_source_location)
        pages = [block.page_start for block in blocks if block.page_start is not None]
        if pages:
            source_location["page_start"] = min(pages)
            source_location["page_end"] = max(pages)
        metadata = dict(context.parent_metadata)
        metadata["reference_metadata"] = {
            "reference_type": "book_hadith",
            "references": [reference],
            "book_start": book,
            "book_end": book,
            "hadith_start": hadith,
            "hadith_end": hadith,
            **{key: value for key, value in source_location.items() if key.startswith("page_")},
        }
        metadata["canonical_reference_unit"] = {
            "reference": reference,
            "raw_reference": match.group(0),
            "unit": "hadith",
            "answerable": True,
            "body_status": "assembled",
            "assembly_strategy": "domain_evidence_graph",
        }
        metadata["orchestration"] = {
            "resolver": "hadith",
            "decisions": [
                {
                    "code": "late_header_body_reassociated",
                    "reason": "Reference header appeared after nearby body blocks in parser order.",
                    "source_block_refs": [block.source_ref.key for block in blocks],
                    "confidence": "medium",
                }
            ],
        }
        return CanonicalUnit(
            text=text,
            source_location=source_location,
            metadata=metadata,
            runtime_source_id=context.runtime_source_id,
            content_type=context.content_type,
            preview_ref=reference,
            decisions=(
                AssemblyDecision(
                    code="late_header_body_reassociated",
                    reason="Reference header appeared after nearby body blocks in parser order.",
                    source_block_refs=tuple(block.source_ref.key for block in blocks),
                    confidence="medium",
                ),
            ),
        )
```

Modify `backend/src/ragstudio/services/domain_resolvers/__init__.py`:

```python
from ragstudio.services.domain_resolvers.base import (
    AssemblyDecision,
    CanonicalUnit,
    DomainResolver,
    ResolverContext,
    resolver_key,
)
from ragstudio.services.domain_resolvers.hadith import HadithResolver

__all__ = [
    "AssemblyDecision",
    "CanonicalUnit",
    "DomainResolver",
    "HadithResolver",
    "ResolverContext",
    "resolver_key",
]
```

- [ ] **Step 4: Run the hadith resolver test**

Run:

```powershell
pytest backend/tests/test_hadith_domain_resolver.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/ragstudio/services/domain_resolvers backend/tests/test_hadith_domain_resolver.py
git commit -m "feat: resolve late hadith headers with evidence graph"
```

---

### Task 5: Integrate Canonical Assembly Inside ChunkSplitter

**Files:**
- Modify: `backend/src/ragstudio/services/canonical_assembly.py`
- Modify: `backend/src/ragstudio/services/chunk_splitter.py`
- Test: `backend/tests/test_canonical_assembly.py`
- Test: `backend/tests/test_chunk_splitter.py`

- [ ] **Step 1: Write failing ChunkSplitter integration test**

Append this test to `backend/tests/test_chunk_splitter.py`:

```python
import pytest

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_splitter import ChunkSplitter
from ragstudio.services.parser_normalization import NormalizedBlock


@pytest.mark.asyncio
async def test_canonical_reference_pieces_use_layout_aware_hadith_strategy_for_late_header():
    splitter = ChunkSplitter()
    domain_metadata = DomainMetadata(
        domain="hadith",
        document_type="collection",
        custom_json={
            "chunking": {"unit": "hadith", "preserve_parallel_text": True},
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
                "carry_forward_body_blocks": True,
            },
            "domain_structure": {
                "primary_anchor": {
                    "type": "book_hadith",
                    "unit": "hadith",
                    "regex": r"\bBook\s+(?P<book>\d{1,4})\s*,?\s*Hadith\s+(?P<hadith>\d{1,6})\b",
                }
            },
        },
    )
    profile = splitter._profile(domain_metadata)
    parent = AdapterChunk(
        text="",
        source_location={"artifact": "source.md"},
        metadata={"parser_metadata": {"parser": "mineru"}},
        runtime_source_id="runtime-doc",
        content_type="text",
        preview_ref=None,
    )
    normalized_blocks = [
        NormalizedBlock(
            text="قال رسول الله صلى الله عليه وسلم",
            page=127,
            block_type="text",
            source_item={"bbox": [10, 50, 300, 90]},
        ),
        NormalizedBlock(
            text="It was narrated that Anas said...",
            page=127,
            block_type="text",
            source_item={"bbox": [10, 100, 300, 150]},
        ),
        NormalizedBlock(
            text="Book 2, Hadith 29 - Grade: Sahih",
            page=127,
            block_type="header",
            source_item={"bbox": [10, 20, 300, 40]},
        ),
    ]

    pieces = splitter._canonical_reference_pieces(
        parent,
        profile,
        normalized_blocks,
        content_ref="source_content_list.json",
        domain_metadata=domain_metadata,
    )

    assert len(pieces) == 1
    assert pieces[0].preview_ref == "book:2:hadith:29"
    assert "Book 2, Hadith 29" in pieces[0].text
    assert "قال رسول الله" in pieces[0].text
    assert "It was narrated" in pieces[0].text
    assert pieces[0].metadata["canonical_reference_unit"]["assembly_strategy"] == (
        "domain_evidence_graph"
    )
```

- [ ] **Step 2: Run the failing ChunkSplitter integration test**

Run:

```powershell
pytest backend/tests/test_chunk_splitter.py -k "layout_aware_hadith_strategy_for_late_header" -v
```

Expected: fails because `_canonical_reference_pieces()` still uses only forward `ReferenceUnitAssembler` assembly.

- [ ] **Step 3: Add canonical assembly strategy helper**

Extend `backend/src/ragstudio/services/canonical_assembly.py` with a strategy entrypoint:

```python
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.domain_resolvers import HadithResolver, ResolverContext
from ragstudio.services.evidence_graph import EvidenceGraph
from ragstudio.services.parser_normalization import NormalizedBlock
from ragstudio.services.reference_unit_assembler import AssembledReferenceUnit


class CanonicalAssemblyStrategy:
    def __init__(self):
        self.resolvers = [HadithResolver()]

    def assemble(
        self,
        normalized_blocks: list[NormalizedBlock],
        *,
        domain_metadata: DomainMetadata,
        content_list_ref: str,
        context: ResolverContext,
    ) -> list[AssembledReferenceUnit]:
        graph = EvidenceGraph.from_blocks(
            block_views_from_normalized(normalized_blocks, content_list_ref=content_list_ref)
        )
        for resolver in self.resolvers:
            if not resolver.can_resolve(context):
                continue
            units = resolver.resolve_units(graph, context=context)
            if units:
                return [
                    AssembledReferenceUnit(
                        text=unit.text,
                        source_location=unit.source_location,
                        metadata=unit.metadata,
                        runtime_source_id=unit.runtime_source_id,
                        content_type=unit.content_type,
                        preview_ref=unit.preview_ref,
                    )
                    for unit in units
                ]
        return []
```

- [ ] **Step 4: Wire strategy into ChunkSplitter canonical assembly**

In `backend/src/ragstudio/services/chunk_splitter.py`, import:

```python
from ragstudio.services.canonical_assembly import CanonicalAssemblyStrategy
from ragstudio.services.domain_resolvers import ResolverContext
```

In `ChunkSplitter.__init__`, add:

```python
self.canonical_assembly = CanonicalAssemblyStrategy()
```

Add `domain_metadata: DomainMetadata` to `_canonical_reference_pieces()` and pass it from `_chunks_from_content_list()`:

```python
canonical_pieces = self._canonical_reference_pieces(
    chunk,
    profile,
    normalized_blocks,
    content_ref=content_ref,
    domain_metadata=domain_metadata,
)
```

At the start of `_canonical_reference_pieces()` after `semantics` validation, call the strategy before the fallback block conversion:

```python
strategy_units = self.canonical_assembly.assemble(
    normalized_blocks,
    domain_metadata=domain_metadata,
    content_list_ref=content_ref,
    context=ResolverContext(
        domain_metadata=domain_metadata,
        parent_metadata=dict(chunk.metadata),
        parent_source_location=dict(chunk.source_location),
        runtime_source_id=chunk.runtime_source_id,
        content_type=chunk.content_type,
        preview_ref=chunk.preview_ref,
    ),
)
if strategy_units:
    return [self._piece_from_assembled(unit) for unit in strategy_units]
```

- [ ] **Step 5: Add fallback regression test**

Add to `backend/tests/test_chunk_splitter.py`:

```python
def test_canonical_reference_pieces_fall_back_to_forward_assembler_for_non_hadith_domain():
    splitter = ChunkSplitter()
    domain_metadata = DomainMetadata(
        domain="quran",
        document_type="collection",
        custom_json={
            "chunking": {"unit": "verse"},
            "reference_resolution": {"enabled": True, "build_canonical_units": True},
            "domain_structure": {
                "primary_anchor": {
                    "type": "chapter_verse",
                    "unit": "verse",
                    "regex": r"\[(?P<chapter>\d{1,4}):(?P<verse>\d{1,4})\]",
                }
            },
        },
    )
    profile = splitter._profile(domain_metadata)
    parent = AdapterChunk(
        text="",
        source_location={"artifact": "source.md"},
        metadata={},
        runtime_source_id="runtime-doc",
        content_type="text",
        preview_ref=None,
    )
    normalized_blocks = [
        NormalizedBlock(
            text="[2:255] الله لا إله إلا هو",
            page=1,
            block_type="text",
            source_item={"bbox": [10, 20, 300, 40]},
        ),
    ]

    pieces = splitter._canonical_reference_pieces(
        parent,
        profile,
        normalized_blocks,
        content_ref="source_content_list.json",
        domain_metadata=domain_metadata,
    )

    assert len(pieces) == 1
    assert pieces[0].preview_ref == "2:255"
```

- [ ] **Step 6: Run canonical assembly tests**

Run:

```powershell
pytest backend/tests/test_canonical_assembly.py backend/tests/test_hadith_domain_resolver.py backend/tests/test_chunk_splitter.py -k "canonical_assembly or hadith or layout_aware_hadith_strategy_for_late_header or fall_back_to_forward_assembler" -v
```

Expected: pass.

- [ ] **Step 7: Commit**

```powershell
git add backend/src/ragstudio/services/canonical_assembly.py backend/src/ragstudio/services/chunk_splitter.py backend/tests/test_canonical_assembly.py backend/tests/test_chunk_splitter.py
git commit -m "feat: assemble canonical units from normalized block graph"
```

---

### Rejected Appendix: Standalone Chunk Orchestrator Design

Do not implement this section. It is retained only to document the rejected design and why it changed. A standalone `ChunkOrchestrator` before `ChunkSplitter` would duplicate content-list normalization, bypass existing `MinerUContentNormalizer` recovery behavior, and create a second ingestion path.

### Deprecated Task: Add Chunk Orchestrator And Preserve Fallback

**Files:**
- Create: `backend/src/ragstudio/services/chunk_orchestrator.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Test: `backend/tests/test_chunk_orchestrator.py`

- [ ] **Step 1: Write failing orchestrator integration test**

Append to `backend/tests/test_chunk_orchestrator.py`:

```python
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_orchestrator import ChunkOrchestrator


def test_orchestrator_returns_canonical_hadith_chunk_from_late_header_metadata():
    source_chunk = AdapterChunk(
        text="",
        source_location={"artifact": "source.md"},
        metadata={
            "parser_metadata": {
                "content_list_ref": "source_content_list.json",
                "content_list": [
                    {"type": "text", "text": "قال رسول الله", "page_idx": 126},
                    {"type": "text", "text": "It was narrated...", "page_idx": 126},
                    {"type": "header", "text": "Book 2, Hadith 29", "page_idx": 126},
                ],
            }
        },
        runtime_source_id="runtime-doc",
        content_type="text",
        preview_ref=None,
    )

    chunks = ChunkOrchestrator().orchestrate(
        [source_chunk],
        domain_metadata=DomainMetadata(domain="hadith", document_type="collection"),
    )

    assert len(chunks) == 1
    assert chunks[0].preview_ref == "book:2:hadith:29"
    assert "قال رسول الله" in chunks[0].text
```

- [ ] **Step 2: Run the failing orchestrator test**

Run:

```powershell
pytest backend/tests/test_chunk_orchestrator.py -v
```

Expected: fails because `ChunkOrchestrator` does not exist.

- [ ] **Step 3: Implement orchestrator**

Create `backend/src/ragstudio/services/chunk_orchestrator.py`:

```python
from __future__ import annotations

from typing import Any

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.domain_resolvers import HadithResolver, ResolverContext
from ragstudio.services.evidence_blocks import blocks_from_mineru_content_list
from ragstudio.services.evidence_graph import EvidenceGraph


class ChunkOrchestrator:
    def __init__(self):
        self.resolvers = [HadithResolver()]

    def orchestrate(
        self,
        chunks: list[AdapterChunk],
        *,
        domain_metadata: DomainMetadata,
    ) -> list[AdapterChunk]:
        orchestrated: list[AdapterChunk] = []
        for chunk in chunks:
            units = self._orchestrate_chunk(chunk, domain_metadata=domain_metadata)
            orchestrated.extend(units)
        return orchestrated or chunks

    def _orchestrate_chunk(
        self,
        chunk: AdapterChunk,
        *,
        domain_metadata: DomainMetadata,
    ) -> list[AdapterChunk]:
        parser_metadata = chunk.metadata.get("parser_metadata")
        if not isinstance(parser_metadata, dict):
            return []
        content_list = parser_metadata.get("content_list")
        content_list_ref = parser_metadata.get("content_list_ref")
        if not isinstance(content_list, list) or not isinstance(content_list_ref, str):
            return []
        items = [item for item in content_list if isinstance(item, dict)]
        graph = EvidenceGraph.from_blocks(
            blocks_from_mineru_content_list(items, content_list_ref=content_list_ref)
        )
        context = ResolverContext(
            domain_metadata=domain_metadata,
            parent_metadata=dict(chunk.metadata),
            parent_source_location=dict(chunk.source_location),
            runtime_source_id=chunk.runtime_source_id,
            content_type=chunk.content_type,
            preview_ref=chunk.preview_ref,
        )
        adapter_chunks: list[AdapterChunk] = []
        for resolver in self.resolvers:
            if not resolver.can_resolve(context):
                continue
            for unit in resolver.resolve_units(graph, context=context):
                adapter_chunks.append(
                    AdapterChunk(
                        text=unit.text,
                        source_location=unit.source_location,
                        metadata=unit.metadata,
                        runtime_source_id=unit.runtime_source_id,
                        content_type=unit.content_type,
                        preview_ref=unit.preview_ref,
                    )
                )
        return adapter_chunks
```

- [ ] **Step 4: Wire orchestrator behind canonical reference-unit option**

In `backend/src/ragstudio/services/chunk_service.py`, import the orchestrator:

```python
from ragstudio.services.chunk_orchestrator import ChunkOrchestrator
```

Add constructor parameter:

```python
chunk_orchestrator: ChunkOrchestrator | None = None,
```

Set instance property:

```python
self.chunk_orchestrator = chunk_orchestrator or ChunkOrchestrator()
```

Before `self.chunk_splitter.split(...)`, add:

```python
if self._uses_canonical_reference_units(options.domain_metadata):
    adapter_chunks = self.chunk_orchestrator.orchestrate(
        adapter_chunks,
        domain_metadata=options.domain_metadata,
    )
```

- [ ] **Step 5: Run orchestrator tests**

Run:

```powershell
pytest backend/tests/test_chunk_orchestrator.py backend/tests/test_hadith_domain_resolver.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/src/ragstudio/services/chunk_orchestrator.py backend/src/ragstudio/services/chunk_service.py backend/tests/test_chunk_orchestrator.py
git commit -m "feat: orchestrate canonical chunks before splitting"
```

---

### Task 6: Make Warning Counts Report Counted And Audit Warnings Separately

**Files:**
- Modify: `backend/src/ragstudio/services/job_quality_warning_service.py`
- Modify: `frontend/src/features/documents/documents-page.tsx`
- Test: `backend/tests/test_job_quality_warnings.py`
- Test: `frontend/tests/documents-page.test.tsx`

- [ ] **Step 1: Write backend test for distinct affected chunk count**

Add to `backend/tests/test_job_quality_warnings.py`:

```python
def test_quality_warning_details_separates_counted_and_suppressed_overlap():
    items = [
        warning_item("chunk-1", "recovered_text_from_disallowed_block", suppressed=True),
        warning_item("chunk-1", "reference_unit_missing_expected_script", suppressed=False),
        warning_item("chunk-2", "recovered_text_from_disallowed_block", suppressed=True),
    ]

    service = JobQualityWarningService(session=None)

    assert service._warning_counts(items) == {"reference_unit_missing_expected_script": 1}
    assert service._affected_chunks({"affected_chunks": 1}, items) == 1
    assert service._distinct_warning_chunks(items) == 2
```

If no local helper exists, define this helper in the test file:

```python
def warning_item(chunk_id: str, code: str, *, suppressed: bool):
    return ParserQualityWarningOut(
        chunk_id=chunk_id,
        chunk_preview="preview",
        source_location={},
        parser_metadata={},
        reference_metadata=None,
        code=code,
        message="message",
        block_type=None,
        page=None,
        warning={"code": code, "suppressed_from_counts": suppressed},
    )
```

- [ ] **Step 2: Run failing backend warning test**

Run:

```powershell
pytest backend/tests/test_job_quality_warnings.py -k "distinct_warning_chunks or separates_counted" -v
```

Expected: fails because `_distinct_warning_chunks` does not exist.

- [ ] **Step 3: Implement distinct warning chunk helper**

Add to `JobQualityWarningService`:

```python
def _distinct_warning_chunks(
    self,
    items: list[ParserQualityWarningOut],
) -> int:
    return len({item.chunk_id for item in items if item.chunk_id})
```

When building the details response, include a field named `distinct_warning_chunks` only after updating the schema. If changing the schema is too broad for this task, use the helper only in UI summary generation task.

- [ ] **Step 4: Update frontend wording**

In `frontend/src/features/documents/documents-page.tsx`, change the parser warning details heading from summed group chunks to explicit group sum text:

```tsx
Parser warning details - {groups.length} types - grouped chunk hits: {totalChunks}
```

Add separate text near `affected_chunks`:

```tsx
counted_affected_chunks={details.affected_chunks}
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
pytest backend/tests/test_job_quality_warnings.py -k "distinct_warning_chunks or separates_counted" -v
cmd /c "cd frontend && npm test -- documents-page.test.tsx --run"
```

Expected: pass after updating snapshots/assertions.

- [ ] **Step 6: Commit**

```powershell
git add backend/src/ragstudio/services/job_quality_warning_service.py backend/tests/test_job_quality_warnings.py frontend/src/features/documents/documents-page.tsx frontend/tests/documents-page.test.tsx
git commit -m "fix: separate counted parser warnings from audit warnings"
```

---

### Task 7: Validate Against The Ibn Majah Failure Mode

**Files:**
- Modify: `backend/tests/test_hadith_domain_resolver.py`
- Modify: `backend/tests/test_canonical_assembly.py`
- Modify: `docs/workflows.md`

- [ ] **Step 1: Add regression fixture for late recovered header**

Add to `backend/tests/test_hadith_domain_resolver.py`:

```python
def test_hadith_resolver_marks_unresolved_when_no_arabic_candidate_exists():
    blocks = [
        block("It was narrated that Abu Umamah said...", 0, scripts={"latin"}),
        block("Book 36, Hadith 152 - Grade: Da'if", 1, block_type="header"),
    ]
    context = ResolverContext(
        domain_metadata=DomainMetadata(domain="hadith", document_type="collection"),
        parent_metadata={},
        parent_source_location={"artifact": "source.md"},
        runtime_source_id="runtime-doc",
        content_type="text",
        preview_ref=None,
    )

    units = HadithResolver().resolve_units(EvidenceGraph.from_blocks(blocks), context=context)

    assert units == []
```

This test enforces the principle: do not auto-clear a warning when Arabic evidence is absent.

- [ ] **Step 2: Run resolver tests**

Run:

```powershell
pytest backend/tests/test_hadith_domain_resolver.py -v
```

Expected: pass.

- [ ] **Step 3: Document warning semantics**

In `docs/workflows.md`, add this under parser warning semantics:

```markdown
Domain-aware orchestration runs before reference quality validation for configured canonical-unit domains. It may re-associate parser blocks when layout evidence shows that a reference header, body text, translation, or recovered layout block belongs to the same canonical unit. A warning is cleared only after the assembled unit passes the same quality gate that produced the warning. If required evidence is still missing, the warning remains with a more specific reason.
```

- [ ] **Step 4: Run final focused backend suite**

Run:

```powershell
pytest backend/tests/test_canonical_assembly.py backend/tests/test_evidence_graph.py backend/tests/test_hadith_domain_resolver.py backend/tests/test_chunk_splitter.py backend/tests/test_domain_metadata_quality_gate.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/tests/test_hadith_domain_resolver.py backend/tests/test_canonical_assembly.py backend/tests/test_chunk_splitter.py docs/workflows.md
git commit -m "test: cover domain orchestration warning semantics"
```

---

## Verification Plan

Run backend focused verification:

```powershell
pytest backend/tests/test_canonical_assembly.py backend/tests/test_evidence_graph.py backend/tests/test_hadith_domain_resolver.py backend/tests/test_chunk_splitter.py backend/tests/test_domain_metadata_quality_gate.py backend/tests/test_job_quality_warnings.py -v
```

Run frontend focused verification:

```powershell
cmd /c "cd frontend && npm test -- documents-page.test.tsx --run"
```

Run live manual verification only after automated tests pass:

```powershell
docker compose up -d
```

Then reindex `hadith_ibn_majah.pdf` with the same hadith domain metadata. Expected result:

- `reference_unit_missing_expected_script` decreases for cases where Arabic exists nearby and is evidence-backed.
- Any genuinely English-only or OCR-missing hadith units remain warnings.
- Recovered header/footer/page-footnote entries remain visible as audit info, not counted as main warnings.
- The UI no longer implies 507 distinct affected chunks when warnings overlap on the same chunk.

## Risk Notes

- Do not let AI become the source of truth. AI can propose block mappings only when deterministic graph rules are ambiguous.
- Do not silently clear warnings. A warning is cleared only if the reassembled unit passes existing quality validation.
- Do not hardcode the architecture to hadith. Hadith is the first resolver plugin; the graph and canonical unit contracts must stay general.
- Do not remove `ReferenceUnitAssembler` in this phase. It remains the fallback path.

## Future Extensions

- Add `QuranResolver` for verse-aware canonical units.
- Add `LegalResolver` for clauses, definitions, obligations, and cross-references.
- Add `PaperResolver` for sections, figures, tables, captions, equations, and citations.
- Add AI-assisted resolver arbitration with stored decision evidence and confidence.
- Add a parse evidence viewer overlay that shows graph-selected blocks on the source page.

## Self-Review

- Spec coverage: Covers parser-agnostic blocks, multimodal graph, domain resolver plugins, hadith failure mode, quality gate revalidation, RAG-Anything prepared chunk compatibility, and UI warning count accuracy.
- Placeholder scan: No task uses TBD, TODO, or unspecified error handling. Each implementation task includes concrete files, test commands, and expected results.
- Type consistency: `EvidenceBlockView`, `EvidenceGraph`, `ResolverContext`, `CanonicalUnit`, and `CanonicalAssemblyStrategy` names are consistent across active tasks. The standalone `ChunkOrchestrator` appears only in the rejected appendix.
