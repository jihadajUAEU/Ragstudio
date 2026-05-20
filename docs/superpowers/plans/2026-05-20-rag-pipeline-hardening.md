# RAG Pipeline Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Ragstudio toward a domain-aware, layout-aware evidence architecture while adding enterprise-grade hardening for CPU isolation, graph pagination/scoping, auditable layout repair, realtime parsing progress, and safer native runtime storage configuration.

**Architecture:** Implement this as a set of narrow, independently testable pipeline changes. Keep the durable job queue as the control plane, keep Postgres chunks as the source of truth, keep Neo4j as a rebuildable projection, and expose progress through job state plus SSE rather than introducing a new queue backend in the first pass. For native RAG-Anything storage, add an explicit storage-configuration seam and isolate the remaining environment fallback behind one adapter boundary so future driver-based storage can replace it cleanly.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async ORM, Pydantic, React/Vite, TanStack Query, Vitest, pytest, existing Ragstudio job queue and proof-oriented RAG services.

---

## Scope Check

This plan covers the five requested hardening enhancements:

- 4.1 Offload CPU-bound pipelines.
- 4.2 Replace scattered environment injection with scoped storage configuration seams.
- 4.3 Add local layout auto-repair between canonical assembly and quality gate.
- 4.4 Add scoped graph queries and pagination.
- 4.5 Expose real-time parsing event streams.

The work is intentionally staged. Tasks 1-4 are immediate hardening. Task 5 introduces the repair loop. Task 6 makes runtime storage safer without pretending third-party LightRAG storage is fully constructor-configurable until verified. Task 7 adds frontend visibility. Task 8 runs integration validation.

It also adds the architecture layer contracts needed to make those improvements coherent across the application. The target design is **Domain-Aware Layout Evidence RAG**: parse and normalize layout first, resolve domain semantics second, build canonical evidence units third, then materialize those units into RAG-Anything, lexical, graph, and metadata retrieval lanes with proof-grade traceability.

## Target Architecture: 10 Core Layers

Every pipeline change should map to one of these layers. If a change cannot be placed in this list, the design is probably introducing an unowned responsibility.

1. **Parse Layer**
   - Responsibility: run MinerU / RAG-Anything parsing, OCR, table/image extraction, and parser artifact capture.
   - Current anchors: `DocumentParserService`, `NativeRAGAnythingAdapter`, parser artifacts.
   - Output: raw content blocks, parser warnings, artifact references.

2. **Layout Normalization Layer**
   - Responsibility: normalize raw parser blocks into stable reading order, page spans, coordinates, block refs, and recovered text signals.
   - Current anchors: `MinerUContentNormalizer`, `ChunkSplitter._canonical_block_order`.
   - Output: layout-aware normalized blocks.

3. **Domain Resolver Layer**
   - Responsibility: choose domain behavior from document metadata: reference format, expected script, chunk unit strategy, graph rules, retrieval priorities, and quality policy.
   - Missing dot: behavior is currently spread across `DomainMetadata`, `ReferenceSemantics`, chunk profiles, and query expansion.
   - Output: a domain profile contract.

4. **Canonical Evidence Layer**
   - Responsibility: turn normalized blocks into answerable evidence units, not arbitrary text chunks.
   - Current anchors: `CanonicalAssemblyStrategy`, `ReferenceUnitAssembler`, `ChunkSplitter`.
   - Output: evidence units with unit type, provenance, source blocks, reference metadata, and answerability.

5. **Repair And Quality Layer**
   - Responsibility: perform deterministic local repair, preserve before/after audit metadata, then apply quality gates.
   - Current anchors: `DomainMetadataQualityGate`, `ChunkQualityGate`, `IndexQualityGate`.
   - Output: quality action policy and repair evidence.

6. **Materialization Policy Layer**
   - Responsibility: decide separately whether each evidence unit can enter vector, lexical, exact-reference, graph, answer-context, or provenance-only surfaces.
   - Missing dot: current gates exist, but the multi-index policy is not a first-class contract.
   - Output: explicit per-index materialization permissions.

7. **Retrieval Planner Layer**
   - Responsibility: convert query understanding and domain profile into retrieval lanes, budgets, and ordering.
   - Current anchors: `query_understanding.py`, `DomainQueryExpansionService`, `MetadataRetrievalService`.
   - Output: retrieval route plan for exact, lexical, metadata, native vector, graph, rerank, and context assembly.

8. **Fusion And Rerank Layer**
   - Responsibility: combine candidates from RAG-Anything, metadata, lexical/exact, and graph retrieval with explainable scoring and reranking.
   - Current anchors: `RetrievalFusion`, `RerankerService`, `RetrievalOrchestrator`.
   - Output: ranked evidence candidates with traceable score breakdown.

9. **Context Assembly Layer**
   - Responsibility: build the answer context from the ranked evidence while preserving citations, references, provenance, and dropped-candidate reasons.
   - Current anchors: `ContextAssemblyService`, `GroundingValidator`, `EvidenceFirstAnswerService`.
   - Output: grounded answer context and validation trace.

10. **Proof Trace Layer**
    - Responsibility: expose every public or user-visible claim from answer text back to source code, raw artifacts, chunk metadata, run traces, limitations, and redaction state.
    - Current anchors: `proof_packet`, `scripts/proof.sh`, document evidence UI, query pathway viewer.
    - Output: inspectable proof packet and runtime traces.

## RAG-Anything Integration Rule

RAG-Anything is a runtime and retrieval lane, not the only source of truth. Canonical evidence units in Postgres remain authoritative. Every unit sent to RAG-Anything / LightRAG must preserve a bridge identity:

- `document_id`
- canonical Ragstudio `chunk_id` when available
- `runtime_source_id`
- evidence unit type
- canonical reference
- page/block provenance
- quality action policy
- materialization policy

Native RAG-Anything retrieval results must be mapped back to canonical Ragstudio evidence before fusion, reranking, context assembly, or proof export.

## File Structure

- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
  - Owns pipeline orchestration. Add CPU offload and layout repair hook.
- Create: `backend/src/ragstudio/services/pipeline_architecture.py`
  - Defines the 10 core pipeline layers and their code ownership contracts.
- Create: `backend/src/ragstudio/services/domain_profile_registry.py`
  - Centralizes domain-aware chunking/retrieval defaults for generic, scripture/reference-heavy, hadith, paper, table, and policy-style documents.
- Create: `backend/src/ragstudio/services/evidence_unit_contract.py`
  - Defines evidence unit types and materialization policy names used by chunking, quality gates, RAG-Anything bridging, and retrieval.
- Create: `backend/src/ragstudio/services/retrieval_route_planner.py`
  - Turns query understanding plus domain profile into explicit retrieval lane plans.
- Test: `backend/tests/test_pipeline_architecture.py`
  - Verifies the 10-layer contract is stable.
- Test: `backend/tests/test_domain_profile_registry.py`
  - Verifies domain profile selection and defaults.
- Test: `backend/tests/test_evidence_unit_contract.py`
  - Verifies unit type and materialization policy serialization.
- Test: `backend/tests/test_retrieval_route_planner.py`
  - Verifies domain-aware retrieval routes for reference, phrase, table, graph, and summary queries.
- Create: `backend/src/ragstudio/services/layout_auto_repair.py`
  - Pure deterministic repair service that annotates, recovers, or preserves layout evidence before the quality gate.
- Test: `backend/tests/test_layout_auto_repair.py`
  - Unit tests for repair decisions and metadata.
- Modify: `backend/tests/test_index_lifecycle_service.py`
  - Regression tests for CPU offload and repair hook invocation.
- Modify: `backend/src/ragstudio/services/graph_service.py`
  - Add document-scoped fallback graph reads plus limit/offset metadata.
- Modify: `backend/src/ragstudio/api/routes/graph.py`
  - Add `document_id`, `limit`, and `offset` query parameters.
- Modify: `backend/src/ragstudio/schemas/graph.py`
  - Add optional `total`, `limit`, `offset`, and `truncated` fields.
- Test: `backend/tests/test_graph_service.py`
  - Add scoped fallback graph and pagination tests.
- Modify: `backend/src/ragstudio/schemas/chunks.py`
  - Add `offset` to chunk search input and output.
- Modify: `backend/src/ragstudio/services/chunk_service.py`
  - Apply chunk search offset and total semantics.
- Modify: `backend/src/ragstudio/api/routes/jobs.py`
  - Add SSE endpoint for job stage events.
- Modify: `backend/src/ragstudio/schemas/jobs.py`
  - Add `JobStageEventOut`.
- Modify: `backend/src/ragstudio/services/index_progress.py`
  - Persist event history in `Job.result.stage_events`.
- Test: `backend/tests/test_index_progress.py`
  - Add event history tests.
- Test: `backend/tests/test_jobs.py`
  - Add SSE endpoint serialization tests.
- Modify: `backend/src/ragstudio/services/native_raganything_adapter.py`
  - Move env mutation behind a single scoped storage config object; expose explicit config for direct Neo4j/Postgres code paths.
- Create: `backend/src/ragstudio/services/native_storage_config.py`
  - Builds sanitized Postgres/Neo4j storage settings from runtime profile and app settings.
- Test: `backend/tests/test_native_storage_config.py`
  - Unit tests for no-secret leak and stable workspace config.
- Modify: `frontend/src/api/client.ts`
  - Add graph query options and job event URL helper.
- Modify: `frontend/src/features/documents/documents-page.tsx`
  - Use live job events where available and fall back to existing polling.
- Test: `frontend/tests/api-client.test.ts`
  - Add URL serialization tests.
- Test: `frontend/tests/documents-page.test.tsx`
  - Add live stage event display test.

---

### Task 0: Add The 10-Layer Pipeline Architecture Contract

**Files:**
- Create: `backend/src/ragstudio/services/pipeline_architecture.py`
- Test: `backend/tests/test_pipeline_architecture.py`

- [ ] **Step 1: Write the failing architecture contract test**

Create `backend/tests/test_pipeline_architecture.py`:

```python
from ragstudio.services.pipeline_architecture import (
    EvidencePipelineLayer,
    LAYER_ORDER,
    layer_contracts,
)


def test_pipeline_architecture_has_ten_ordered_layers():
    assert LAYER_ORDER == [
        EvidencePipelineLayer.PARSE,
        EvidencePipelineLayer.LAYOUT_NORMALIZATION,
        EvidencePipelineLayer.DOMAIN_RESOLVER,
        EvidencePipelineLayer.CANONICAL_EVIDENCE,
        EvidencePipelineLayer.REPAIR_AND_QUALITY,
        EvidencePipelineLayer.MATERIALIZATION_POLICY,
        EvidencePipelineLayer.RETRIEVAL_PLANNER,
        EvidencePipelineLayer.FUSION_AND_RERANK,
        EvidencePipelineLayer.CONTEXT_ASSEMBLY,
        EvidencePipelineLayer.PROOF_TRACE,
    ]


def test_pipeline_layer_contracts_name_owner_paths():
    contracts = layer_contracts()

    assert set(contracts) == {layer.value for layer in LAYER_ORDER}
    assert contracts["domain_resolver"]["owner_paths"] == [
        "backend/src/ragstudio/services/domain_profile_registry.py",
        "backend/src/ragstudio/services/reference_metadata.py",
    ]
    assert "canonical evidence units" in contracts["canonical_evidence"]["responsibility"]
    assert "RAG-Anything" in contracts["materialization_policy"]["responsibility"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_pipeline_architecture.py -q
```

Expected: FAIL because `ragstudio.services.pipeline_architecture` does not exist.

- [ ] **Step 3: Implement the architecture contract**

Create `backend/src/ragstudio/services/pipeline_architecture.py`:

```python
from __future__ import annotations

from enum import StrEnum
from typing import Any


class EvidencePipelineLayer(StrEnum):
    PARSE = "parse"
    LAYOUT_NORMALIZATION = "layout_normalization"
    DOMAIN_RESOLVER = "domain_resolver"
    CANONICAL_EVIDENCE = "canonical_evidence"
    REPAIR_AND_QUALITY = "repair_and_quality"
    MATERIALIZATION_POLICY = "materialization_policy"
    RETRIEVAL_PLANNER = "retrieval_planner"
    FUSION_AND_RERANK = "fusion_and_rerank"
    CONTEXT_ASSEMBLY = "context_assembly"
    PROOF_TRACE = "proof_trace"


LAYER_ORDER = [
    EvidencePipelineLayer.PARSE,
    EvidencePipelineLayer.LAYOUT_NORMALIZATION,
    EvidencePipelineLayer.DOMAIN_RESOLVER,
    EvidencePipelineLayer.CANONICAL_EVIDENCE,
    EvidencePipelineLayer.REPAIR_AND_QUALITY,
    EvidencePipelineLayer.MATERIALIZATION_POLICY,
    EvidencePipelineLayer.RETRIEVAL_PLANNER,
    EvidencePipelineLayer.FUSION_AND_RERANK,
    EvidencePipelineLayer.CONTEXT_ASSEMBLY,
    EvidencePipelineLayer.PROOF_TRACE,
]


def layer_contracts() -> dict[str, dict[str, Any]]:
    return {
        EvidencePipelineLayer.PARSE.value: {
            "responsibility": "Parse documents with MinerU and RAG-Anything and preserve raw artifacts.",
            "owner_paths": [
                "backend/src/ragstudio/services/document_parser_service.py",
                "backend/src/ragstudio/services/native_raganything_adapter.py",
            ],
        },
        EvidencePipelineLayer.LAYOUT_NORMALIZATION.value: {
            "responsibility": "Normalize parser blocks into reading order, source spans, coordinates, and recovered text signals.",
            "owner_paths": [
                "backend/src/ragstudio/services/parser_normalization.py",
                "backend/src/ragstudio/services/chunk_splitter.py",
            ],
        },
        EvidencePipelineLayer.DOMAIN_RESOLVER.value: {
            "responsibility": "Resolve domain-aware reference, script, chunking, graph, and retrieval defaults.",
            "owner_paths": [
                "backend/src/ragstudio/services/domain_profile_registry.py",
                "backend/src/ragstudio/services/reference_metadata.py",
            ],
        },
        EvidencePipelineLayer.CANONICAL_EVIDENCE.value: {
            "responsibility": "Build canonical evidence units from layout blocks with answerability and provenance.",
            "owner_paths": [
                "backend/src/ragstudio/services/canonical_assembly.py",
                "backend/src/ragstudio/services/reference_unit_assembler.py",
                "backend/src/ragstudio/services/evidence_unit_contract.py",
            ],
        },
        EvidencePipelineLayer.REPAIR_AND_QUALITY.value: {
            "responsibility": "Apply auditable local repair and quality gates before any materialization.",
            "owner_paths": [
                "backend/src/ragstudio/services/layout_auto_repair.py",
                "backend/src/ragstudio/services/domain_metadata_quality_gate.py",
                "backend/src/ragstudio/services/index_quality_gate.py",
            ],
        },
        EvidencePipelineLayer.MATERIALIZATION_POLICY.value: {
            "responsibility": "Decide which evidence units can enter RAG-Anything, vector, lexical, graph, answer, or provenance-only surfaces.",
            "owner_paths": [
                "backend/src/ragstudio/services/evidence_unit_contract.py",
                "backend/src/ragstudio/services/vector_index_policy.py",
                "backend/src/ragstudio/services/chunk_persistence_service.py",
            ],
        },
        EvidencePipelineLayer.RETRIEVAL_PLANNER.value: {
            "responsibility": "Turn query understanding and domain profiles into retrieval lanes, budgets, and route order.",
            "owner_paths": [
                "backend/src/ragstudio/services/retrieval_route_planner.py",
                "backend/src/ragstudio/services/query_understanding.py",
                "backend/src/ragstudio/services/domain_query_expansion_service.py",
            ],
        },
        EvidencePipelineLayer.FUSION_AND_RERANK.value: {
            "responsibility": "Fuse and rerank native, metadata, lexical, exact-reference, and graph candidates with traceable scoring.",
            "owner_paths": [
                "backend/src/ragstudio/services/retrieval_fusion.py",
                "backend/src/ragstudio/services/reranker_service.py",
                "backend/src/ragstudio/services/retrieval_orchestrator.py",
            ],
        },
        EvidencePipelineLayer.CONTEXT_ASSEMBLY.value: {
            "responsibility": "Assemble answer context with citations, dropped-candidate reasons, and grounding status.",
            "owner_paths": [
                "backend/src/ragstudio/services/context_assembly_service.py",
                "backend/src/ragstudio/services/grounding_validator.py",
                "backend/src/ragstudio/services/evidence_first_answer_service.py",
            ],
        },
        EvidencePipelineLayer.PROOF_TRACE.value: {
            "responsibility": "Expose claims and answers back to raw artifacts, source paths, limitations, and redaction state.",
            "owner_paths": [
                "backend/src/ragstudio/proof_packet",
                "scripts/proof.sh",
                "frontend/src/features/document-evidence",
                "frontend/src/features/query/query-pathway-viewer.tsx",
            ],
        },
    }
```

- [ ] **Step 4: Run the architecture tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_pipeline_architecture.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/pipeline_architecture.py backend/tests/test_pipeline_architecture.py
git commit -m "docs: codify evidence pipeline architecture"
```

---

### Task 0.1: Add Domain Profile Registry

**Files:**
- Create: `backend/src/ragstudio/services/domain_profile_registry.py`
- Test: `backend/tests/test_domain_profile_registry.py`

- [ ] **Step 1: Write the failing domain profile tests**

Create `backend/tests/test_domain_profile_registry.py`:

```python
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.domain_profile_registry import DomainProfileRegistry


def test_domain_profile_registry_selects_scripture_reference_profile():
    metadata = DomainMetadata(
        domain="quran_tafseer",
        document_type="scripture",
        tags=["arabic"],
        custom_json={"reference_schema": {"type": "chapter_verse"}},
    )

    profile = DomainProfileRegistry().resolve(metadata)

    assert profile.name == "scripture_reference"
    assert profile.expected_scripts == ["arabic"]
    assert profile.evidence_unit_strategy == "canonical_reference_unit"
    assert profile.retrieval_priorities[:3] == ["reference_exact", "arabic_exact_token", "lexical"]
    assert profile.graph_projection is True


def test_domain_profile_registry_selects_table_profile():
    metadata = DomainMetadata(domain="finance", document_type="table", tags=[])

    profile = DomainProfileRegistry().resolve(metadata)

    assert profile.name == "table_document"
    assert profile.evidence_unit_strategy == "table_unit"
    assert "table_exact" in profile.retrieval_priorities


def test_domain_profile_registry_defaults_to_generic_document():
    profile = DomainProfileRegistry().resolve(DomainMetadata())

    assert profile.name == "generic_document"
    assert profile.evidence_unit_strategy == "section_unit"
    assert profile.expected_scripts == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_domain_profile_registry.py -q
```

Expected: FAIL because `domain_profile_registry.py` does not exist.

- [ ] **Step 3: Implement the registry**

Create `backend/src/ragstudio/services/domain_profile_registry.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

from ragstudio.schemas.parsing import DomainMetadata


@dataclass(frozen=True)
class DomainProfileContract:
    name: str
    evidence_unit_strategy: str
    expected_scripts: list[str] = field(default_factory=list)
    retrieval_priorities: list[str] = field(default_factory=list)
    graph_projection: bool = False
    layout_sensitive: bool = True


class DomainProfileRegistry:
    def resolve(self, metadata: DomainMetadata) -> DomainProfileContract:
        combined = " ".join(
            value
            for value in [
                metadata.domain,
                metadata.document_type,
                metadata.collection,
                metadata.content_role,
                *metadata.tags,
                str(metadata.custom_json.get("reference_schema", "")),
            ]
            if value
        ).casefold()

        if any(token in combined for token in ("quran", "scripture", "chapter_verse")):
            return DomainProfileContract(
                name="scripture_reference",
                evidence_unit_strategy="canonical_reference_unit",
                expected_scripts=["arabic"],
                retrieval_priorities=[
                    "reference_exact",
                    "arabic_exact_token",
                    "lexical",
                    "native_vector",
                    "graph",
                ],
                graph_projection=True,
            )
        if any(token in combined for token in ("hadith", "bukhari", "book_hadith")):
            return DomainProfileContract(
                name="hadith_reference",
                evidence_unit_strategy="canonical_reference_unit",
                expected_scripts=["arabic"],
                retrieval_priorities=[
                    "reference_exact",
                    "phrase_exact",
                    "lexical",
                    "native_vector",
                    "graph",
                ],
                graph_projection=True,
            )
        if "table" in combined:
            return DomainProfileContract(
                name="table_document",
                evidence_unit_strategy="table_unit",
                retrieval_priorities=["table_exact", "metadata", "native_vector"],
                graph_projection=False,
            )
        if "paper" in combined or "academic" in combined:
            return DomainProfileContract(
                name="academic_paper",
                evidence_unit_strategy="section_unit",
                retrieval_priorities=["section_title", "semantic_metadata", "native_vector"],
                graph_projection=True,
            )
        if "policy" in combined:
            return DomainProfileContract(
                name="policy_document",
                evidence_unit_strategy="section_unit",
                retrieval_priorities=["section_title", "phrase_exact", "native_vector"],
                graph_projection=True,
            )
        return DomainProfileContract(
            name="generic_document",
            evidence_unit_strategy="section_unit",
            retrieval_priorities=["semantic_metadata", "native_vector", "lexical"],
            graph_projection=False,
        )
```

- [ ] **Step 4: Run profile tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_domain_profile_registry.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/domain_profile_registry.py backend/tests/test_domain_profile_registry.py
git commit -m "feat: add domain profile registry"
```

---

### Task 0.2: Add Evidence Unit And Materialization Contracts

**Files:**
- Create: `backend/src/ragstudio/services/evidence_unit_contract.py`
- Test: `backend/tests/test_evidence_unit_contract.py`

- [ ] **Step 1: Write the failing evidence unit contract tests**

Create `backend/tests/test_evidence_unit_contract.py`:

```python
from ragstudio.services.evidence_unit_contract import (
    EvidenceUnitType,
    MaterializationPolicy,
    evidence_unit_metadata,
)


def test_materialization_policy_serializes_per_surface_permissions():
    policy = MaterializationPolicy.blocked(reason="missing_expected_script")

    assert policy.as_metadata() == {
        "index_vector": False,
        "index_lexical": True,
        "index_exact_reference": False,
        "project_graph": False,
        "answer_context": False,
        "provenance_only": True,
        "reason": "missing_expected_script",
    }


def test_evidence_unit_metadata_includes_type_and_policy():
    metadata = evidence_unit_metadata(
        unit_type=EvidenceUnitType.CANONICAL_REFERENCE,
        policy=MaterializationPolicy.answerable(),
        domain_profile="scripture_reference",
    )

    assert metadata["evidence_unit"]["type"] == "canonical_reference_unit"
    assert metadata["evidence_unit"]["domain_profile"] == "scripture_reference"
    assert metadata["quality_action_policy"]["index_vector"] is True
    assert metadata["quality_action_policy"]["answer_context"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_evidence_unit_contract.py -q
```

Expected: FAIL because `evidence_unit_contract.py` does not exist.

- [ ] **Step 3: Implement the contract**

Create `backend/src/ragstudio/services/evidence_unit_contract.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class EvidenceUnitType(StrEnum):
    CANONICAL_REFERENCE = "canonical_reference_unit"
    SECTION = "section_unit"
    TABLE = "table_unit"
    FIGURE_CONTEXT = "figure_context_unit"
    PROVENANCE_ONLY = "provenance_only"
    WARNING_ONLY = "warning_only"
    REPAIR_CANDIDATE = "repair_candidate"


@dataclass(frozen=True)
class MaterializationPolicy:
    index_vector: bool
    index_lexical: bool
    index_exact_reference: bool
    project_graph: bool
    answer_context: bool
    provenance_only: bool
    reason: str | None = None

    @classmethod
    def answerable(cls) -> "MaterializationPolicy":
        return cls(
            index_vector=True,
            index_lexical=True,
            index_exact_reference=True,
            project_graph=True,
            answer_context=True,
            provenance_only=False,
        )

    @classmethod
    def blocked(cls, *, reason: str) -> "MaterializationPolicy":
        return cls(
            index_vector=False,
            index_lexical=True,
            index_exact_reference=False,
            project_graph=False,
            answer_context=False,
            provenance_only=True,
            reason=reason,
        )

    def as_metadata(self) -> dict[str, Any]:
        payload = {
            "index_vector": self.index_vector,
            "index_lexical": self.index_lexical,
            "index_exact_reference": self.index_exact_reference,
            "project_graph": self.project_graph,
            "answer_context": self.answer_context,
            "provenance_only": self.provenance_only,
        }
        if self.reason:
            payload["reason"] = self.reason
        return payload


def evidence_unit_metadata(
    *,
    unit_type: EvidenceUnitType,
    policy: MaterializationPolicy,
    domain_profile: str,
) -> dict[str, Any]:
    return {
        "evidence_unit": {
            "type": unit_type.value,
            "domain_profile": domain_profile,
        },
        "quality_action_policy": policy.as_metadata(),
    }
```

- [ ] **Step 4: Run evidence unit tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_evidence_unit_contract.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/evidence_unit_contract.py backend/tests/test_evidence_unit_contract.py
git commit -m "feat: define evidence unit contract"
```

---

### Task 0.3: Add Domain-Aware Retrieval Route Planner

**Files:**
- Create: `backend/src/ragstudio/services/retrieval_route_planner.py`
- Test: `backend/tests/test_retrieval_route_planner.py`

- [ ] **Step 1: Write the failing retrieval route tests**

Create `backend/tests/test_retrieval_route_planner.py`:

```python
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.domain_profile_registry import DomainProfileRegistry
from ragstudio.services.query_understanding import understand_query
from ragstudio.services.retrieval_route_planner import RetrievalRoutePlanner


def test_reference_query_prioritizes_exact_reference_then_native_vector():
    domain_profile = DomainProfileRegistry().resolve(
        DomainMetadata(domain="quran_tafseer", document_type="scripture", tags=["arabic"])
    )
    understanding = understand_query("19:13")

    plan = RetrievalRoutePlanner().plan(understanding, domain_profile=domain_profile, limit=8)

    assert [route.name for route in plan.routes[:4]] == [
        "reference_exact",
        "arabic_exact_token",
        "lexical",
        "native_vector",
    ]
    assert plan.candidate_budget == 64
    assert plan.requires_graph is False


def test_graph_query_keeps_graph_lane_enabled():
    domain_profile = DomainProfileRegistry().resolve(
        DomainMetadata(domain="hadith", document_type="book", tags=["arabic"])
    )
    understanding = understand_query("what is connected to book 1 hadith 3")

    plan = RetrievalRoutePlanner().plan(understanding, domain_profile=domain_profile, limit=5)

    assert plan.requires_graph is True
    assert any(route.name == "graph" for route in plan.routes)


def test_table_query_uses_table_route_first():
    domain_profile = DomainProfileRegistry().resolve(
        DomainMetadata(domain="finance", document_type="table", tags=[])
    )
    understanding = understand_query("show the revenue table")

    plan = RetrievalRoutePlanner().plan(understanding, domain_profile=domain_profile, limit=5)

    assert plan.routes[0].name == "table_exact"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_retrieval_route_planner.py -q
```

Expected: FAIL because `retrieval_route_planner.py` does not exist.

- [ ] **Step 3: Implement the route planner**

Create `backend/src/ragstudio/services/retrieval_route_planner.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RetrievalRoute:
    name: str
    budget_multiplier: int = 1
    direct_evidence: bool = False


@dataclass(frozen=True)
class RetrievalRoutePlan:
    routes: list[RetrievalRoute]
    candidate_budget: int
    requires_graph: bool
    domain_profile: str


class RetrievalRoutePlanner:
    def plan(
        self,
        understanding: Any,
        *,
        domain_profile: Any,
        limit: int,
    ) -> RetrievalRoutePlan:
        route_names = list(domain_profile.retrieval_priorities)
        if getattr(understanding, "graph_context_required", False) and "graph" not in route_names:
            route_names.append("graph")

        routes = [
            RetrievalRoute(
                name=name,
                budget_multiplier=2 if name in {"native_vector", "semantic_metadata"} else 1,
                direct_evidence=name in {"reference_exact", "arabic_exact_token", "phrase_exact", "table_exact"},
            )
            for name in route_names
        ]
        candidate_budget = max(limit * 8, limit)
        return RetrievalRoutePlan(
            routes=routes,
            candidate_budget=candidate_budget,
            requires_graph=getattr(understanding, "graph_context_required", False),
            domain_profile=domain_profile.name,
        )
```

- [ ] **Step 4: Run planner tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_retrieval_route_planner.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/retrieval_route_planner.py backend/tests/test_retrieval_route_planner.py
git commit -m "feat: add domain-aware retrieval route planner"
```

---

### Task 1: Offload Canonical Chunk Processing

**Files:**
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
- Test: `backend/tests/test_index_lifecycle_service.py`

- [ ] **Step 1: Write the failing test**

Add this test to `backend/tests/test_index_lifecycle_service.py`. If the file already has service fixtures, place the helper classes near existing fakes and adapt only constructor arguments to local fixtures.

```python
import asyncio

from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.index_lifecycle_service import IndexLifecycleService


class ThreadRecordingSplitter:
    def __init__(self):
        self.thread_names: list[str] = []

    def split(self, chunks, *, domain_metadata, parser_mode):
        import threading

        self.thread_names.append(threading.current_thread().name)
        return [
            AdapterChunk(
                text="canonical text",
                source_location={"page": 1},
                metadata={},
                runtime_source_id="chunk-1",
            )
        ]


class ThreadRecordingRelationshipBuilder:
    def __init__(self):
        self.thread_names: list[str] = []

    def annotate(self, chunks, domain_metadata):
        import threading

        self.thread_names.append(threading.current_thread().name)
        return chunks


async def test_canonical_processing_runs_in_worker_thread():
    splitter = ThreadRecordingSplitter()
    relationship_builder = ThreadRecordingRelationshipBuilder()
    service = IndexLifecycleService.__new__(IndexLifecycleService)

    chunks = await service._build_canonical_chunks_in_thread(
        splitter=splitter,
        relationship_builder=relationship_builder,
        normalized_chunks=[],
        domain_metadata={},
        parser_mode="mineru_strict",
    )

    assert [chunk.text for chunk in chunks] == ["canonical text"]
    assert splitter.thread_names
    assert relationship_builder.thread_names
    assert all(name != "MainThread" for name in splitter.thread_names)
    assert all(name != "MainThread" for name in relationship_builder.thread_names)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_index_lifecycle_service.py::test_canonical_processing_runs_in_worker_thread -q
```

Expected: FAIL with `AttributeError: 'IndexLifecycleService' object has no attribute '_build_canonical_chunks_in_thread'`.

- [ ] **Step 3: Add the offload helper**

In `backend/src/ragstudio/services/index_lifecycle_service.py`, add this method inside `IndexLifecycleService`:

```python
    async def _build_canonical_chunks_in_thread(
        self,
        *,
        splitter: Any,
        relationship_builder: Any,
        normalized_chunks: list[AdapterChunk],
        domain_metadata: DomainMetadata,
        parser_mode: str,
    ) -> list[AdapterChunk]:
        return await asyncio.to_thread(
            self._build_canonical_chunks_sync,
            splitter,
            relationship_builder,
            normalized_chunks,
            domain_metadata,
            parser_mode,
        )

    def _build_canonical_chunks_sync(
        self,
        splitter: Any,
        relationship_builder: Any,
        normalized_chunks: list[AdapterChunk],
        domain_metadata: DomainMetadata,
        parser_mode: str,
    ) -> list[AdapterChunk]:
        adapter_chunks = splitter.split(
            normalized_chunks,
            domain_metadata=domain_metadata,
            parser_mode=parser_mode,
        )
        return relationship_builder.annotate(adapter_chunks, domain_metadata)
```

- [ ] **Step 4: Use the helper in `reindex_document`**

Replace the current direct `ChunkSplitter(...).split(...)` and `MinerURelationshipBuilder().annotate(...)` block with:

```python
        adapter_chunks = await self._build_canonical_chunks_in_thread(
            splitter=ChunkSplitter(
                vision_recovery_config=VisionRecoveryConfig.from_runtime_profile(
                    options.domain_metadata,
                    profile,
                )
            ),
            relationship_builder=MinerURelationshipBuilder(),
            normalized_chunks=normalized_chunks,
            domain_metadata=options.domain_metadata,
            parser_mode=options.parser_mode,
        )
```

- [ ] **Step 5: Run the focused test**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_index_lifecycle_service.py::test_canonical_processing_runs_in_worker_thread -q
```

Expected: PASS.

- [ ] **Step 6: Run adjacent indexing tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_index_lifecycle_service.py backend/tests/test_chunk_splitter.py backend/tests/test_chunk_persistence_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/index_lifecycle_service.py backend/tests/test_index_lifecycle_service.py
git commit -m "perf: offload canonical chunk processing"
```

---

### Task 2: Persist Stage Event History For Live Progress

**Files:**
- Modify: `backend/src/ragstudio/services/index_progress.py`
- Modify: `backend/src/ragstudio/schemas/jobs.py`
- Test: `backend/tests/test_index_progress.py`

- [ ] **Step 1: Write the failing event history test**

Add to `backend/tests/test_index_progress.py`:

```python
from ragstudio.services.index_progress import IndexStage, update_job_stage


def test_update_job_stage_appends_stage_event_history():
    job = FakeJob()

    update_job_stage(job, IndexStage.MINERU_PARSING, detail="Parsing page 1.")
    update_job_stage(
        job,
        IndexStage.MINERU_VALIDATED,
        detail="Validated 2 chunks.",
        chunk_count=2,
    )

    events = job.result["stage_events"]
    assert [event["stage"] for event in events] == ["mineru_parsing", "mineru_validated"]
    assert events[0]["detail"] == "Parsing page 1."
    assert events[1]["chunk_count"] == 2
    assert events[1]["sequence"] == 2
    assert "timestamp" in events[1]
```

- [ ] **Step 2: Run it to verify it fails**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_index_progress.py::test_update_job_stage_appends_stage_event_history -q
```

Expected: FAIL with missing `stage_events`.

- [ ] **Step 3: Add event history to `update_job_stage`**

Modify `backend/src/ragstudio/services/index_progress.py`:

```python
from ragstudio.schemas.common import now_utc
```

Then replace the bottom half of `update_job_stage` after `result = dict(job.result or {})` with:

```python
    result["indexing_stage"] = payload
    events = list(result.get("stage_events") or [])
    event = {
        **payload,
        "sequence": len(events) + 1,
        "timestamp": now_utc().isoformat(),
    }
    events.append(event)
    result["stage_events"] = events[-200:]
    if warning:
        warnings = list(result.get("warnings") or [])
        if warning not in warnings:
            warnings.append(warning)
        result["warnings"] = warnings
    job.result = result
```

- [ ] **Step 4: Add the Pydantic event schema**

In `backend/src/ragstudio/schemas/jobs.py`, add:

```python
class JobStageEventOut(StudioModel):
    stage: str
    label: str
    detail: str
    progress: int
    sequence: int
    timestamp: str
    chunk_count: int | None = None
    warning: str | None = None
```

- [ ] **Step 5: Run progress tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_index_progress.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/index_progress.py backend/src/ragstudio/schemas/jobs.py backend/tests/test_index_progress.py
git commit -m "feat: persist indexing stage events"
```

---

### Task 3: Add Job SSE Event Stream

**Files:**
- Modify: `backend/src/ragstudio/api/routes/jobs.py`
- Test: `backend/tests/test_jobs.py`

- [ ] **Step 1: Write the failing API test**

Add to `backend/tests/test_jobs.py`. If the file does not exist, create it using the same `client` fixture used by other backend API tests.

```python
import pytest

from ragstudio.db.models import Job


@pytest.mark.asyncio
async def test_job_events_stream_returns_stage_events(client, session):
    job = Job(
        id="job-events",
        type="index_document",
        status="running",
        target_id="doc-1",
        progress=45,
        logs=[],
        result={
            "stage_events": [
                {
                    "stage": "mineru_parsing",
                    "label": "MinerU parsing",
                    "detail": "Parsing page 1.",
                    "progress": 25,
                    "sequence": 1,
                    "timestamp": "2026-05-20T04:00:00+00:00",
                }
            ]
        },
    )
    session.add(job)
    await session.commit()

    response = await client.get("/api/jobs/job-events/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: stage" in response.text
    assert '"stage":"mineru_parsing"' in response.text
```

- [ ] **Step 2: Run it to verify it fails**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_jobs.py::test_job_events_stream_returns_stage_events -q
```

Expected: FAIL with `404`.

- [ ] **Step 3: Add the SSE endpoint**

In `backend/src/ragstudio/api/routes/jobs.py`, add imports:

```python
import asyncio
import json

from fastapi.responses import StreamingResponse
from ragstudio.db.models import Job
from sqlalchemy import select
```

Then add this route before the quality warnings route:

```python
@router.get("/{job_id}/events")
async def job_events(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    async def stream():
        emitted = 0
        while True:
            job = await session.scalar(select(Job).where(Job.id == job_id))
            if job is None:
                yield "event: error\ndata: {\"detail\":\"Job not found\"}\n\n"
                return
            events = list((job.result or {}).get("stage_events") or [])
            for event in events[emitted:]:
                yield f"event: stage\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"
            emitted = len(events)
            if job.status in {"succeeded", "failed"}:
                yield (
                    "event: done\n"
                    f"data: {json.dumps({'status': job.status}, separators=(',', ':'))}\n\n"
                )
                return
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")
```

- [ ] **Step 4: Run the endpoint test**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_jobs.py::test_job_events_stream_returns_stage_events -q
```

Expected: PASS.

- [ ] **Step 5: Run jobs and progress tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_jobs.py backend/tests/test_index_progress.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/api/routes/jobs.py backend/tests/test_jobs.py
git commit -m "feat: stream indexing stage events"
```

---

### Task 4: Add Scoped Graph Query Pagination

**Files:**
- Modify: `backend/src/ragstudio/schemas/graph.py`
- Modify: `backend/src/ragstudio/services/graph_service.py`
- Modify: `backend/src/ragstudio/api/routes/graph.py`
- Test: `backend/tests/test_graph_service.py`

- [ ] **Step 1: Write the failing graph service test**

Add to `backend/tests/test_graph_service.py`:

```python
import pytest

from ragstudio.db.models import Chunk, Document
from ragstudio.services.graph_service import GraphService


@pytest.mark.asyncio
async def test_relationship_metadata_graph_scopes_to_document_and_paginates(session, tmp_path):
    doc_a = Document(
        id="doc-a",
        filename="a.pdf",
        content_type="application/pdf",
        sha256="sha-a",
        artifact_path=str(tmp_path / "a.pdf"),
        status="succeeded",
    )
    doc_b = Document(
        id="doc-b",
        filename="b.pdf",
        content_type="application/pdf",
        sha256="sha-b",
        artifact_path=str(tmp_path / "b.pdf"),
        status="succeeded",
    )
    session.add_all([doc_a, doc_b])
    session.add_all(
        [
            Chunk(
                id="chunk-a-1",
                document_id="doc-a",
                text="A",
                metadata_json={
                    "relationship_metadata": {
                        "graph_relationships": [
                            {"source": "a1", "target": "a2", "type": "references"}
                        ]
                    }
                },
                source_location={"page": 1},
            ),
            Chunk(
                id="chunk-b-1",
                document_id="doc-b",
                text="B",
                metadata_json={
                    "relationship_metadata": {
                        "graph_relationships": [
                            {"source": "b1", "target": "b2", "type": "references"}
                        ]
                    }
                },
                source_location={"page": 1},
            ),
        ]
    )
    await session.commit()

    graph = await GraphService(session=session)._relationship_metadata_graph(
        document_id="doc-a",
        limit=1,
        offset=0,
    )

    assert graph["total"] == 1
    assert graph["limit"] == 1
    assert graph["offset"] == 0
    assert graph["truncated"] is False
    assert {node["properties"]["document_id"] for node in graph["nodes"]} == {"doc-a"}
    assert {edge["properties"]["document_id"] for edge in graph["edges"]} == {"doc-a"}
```

- [ ] **Step 2: Run it to verify it fails**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_graph_service.py::test_relationship_metadata_graph_scopes_to_document_and_paginates -q
```

Expected: FAIL because `_relationship_metadata_graph` has no `document_id` or `offset`.

- [ ] **Step 3: Extend `GraphOut`**

In `backend/src/ragstudio/schemas/graph.py`, change `GraphOut` to:

```python
class GraphOut(StudioModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    detail: str | None = None
    total: int | None = None
    limit: int | None = None
    offset: int | None = None
    truncated: bool = False
```

- [ ] **Step 4: Update service signatures**

In `backend/src/ragstudio/services/graph_service.py`, change:

```python
    async def get_graph(
        self,
        *,
        document_id: str | None = None,
        limit: int = 2_000,
        offset: int = 0,
    ) -> GraphOut:
        graph = await self._graph(document_id=document_id, limit=limit, offset=offset)
        return GraphOut(
            nodes=list(graph.get("nodes") or []),
            edges=list(graph.get("edges") or []),
            detail=graph.get("detail"),
            total=graph.get("total"),
            limit=graph.get("limit"),
            offset=graph.get("offset"),
            truncated=bool(graph.get("truncated")),
        )
```

Also update `_graph`, `_graph_projection_not_ready`, and fallback calls to pass `document_id`, `limit`, and `offset`.

- [ ] **Step 5: Implement scoped fallback pagination**

Replace `_relationship_metadata_graph` query setup with:

```python
    async def _relationship_metadata_graph(
        self,
        *,
        document_id: str | None = None,
        limit: int = 2_000,
        offset: int = 0,
    ) -> dict[str, Any]:
        if self.session is None:
            return {
                "nodes": [],
                "edges": [],
                "detail": "No database session is available for relationship metadata graph.",
                "total": 0,
                "limit": limit,
                "offset": offset,
                "truncated": False,
            }
        statement = select(Chunk).where(
            Chunk.metadata_json["relationship_metadata"].as_string().is_not(None)
        )
        if document_id is not None:
            statement = statement.where(Chunk.document_id == document_id)
        total_rows = await self.session.execute(statement)
        total = len(total_rows.scalars().all())
        result = await self.session.execute(
            statement.order_by(Chunk.created_at.desc()).offset(offset).limit(limit)
        )
```

At the return, include:

```python
        return {
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
            "detail": detail,
            "total": total,
            "limit": limit,
            "offset": offset,
            "truncated": offset + limit < total,
        }
```

- [ ] **Step 6: Add route query params**

In `backend/src/ragstudio/api/routes/graph.py`, import `Query` and update:

```python
async def get_graph(
    request: Request,
    document_id: str | None = Query(default=None),
    limit: int = Query(default=2_000, ge=1, le=5_000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> GraphOut:
    try:
        return await GraphService(session, request.app.state.settings).get_graph(
            document_id=document_id,
            limit=limit,
            offset=offset,
        )
```

- [ ] **Step 7: Run graph tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_graph_service.py backend/tests/test_graph_expansion_service.py backend/tests/test_graph_materialization_service.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/src/ragstudio/schemas/graph.py backend/src/ragstudio/services/graph_service.py backend/src/ragstudio/api/routes/graph.py backend/tests/test_graph_service.py
git commit -m "feat: scope graph fallback queries"
```

---

### Task 5: Add Chunk Search Offset Pagination

**Files:**
- Modify: `backend/src/ragstudio/schemas/chunks.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Test: `backend/tests/test_chunks.py`

- [ ] **Step 1: Write the failing schema test**

Add to `backend/tests/test_chunks.py`:

```python
from ragstudio.schemas.chunks import ChunkSearchIn


def test_chunk_search_input_accepts_offset():
    payload = ChunkSearchIn(query="reference", limit=25, offset=50)

    assert payload.limit == 25
    assert payload.offset == 50
```

- [ ] **Step 2: Run it to verify it fails**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_chunks.py::test_chunk_search_input_accepts_offset -q
```

Expected: FAIL because `offset` is not present.

- [ ] **Step 3: Add offset to schemas**

In `backend/src/ragstudio/schemas/chunks.py`:

```python
class ChunkSearchIn(StudioModel):
    query: str
    document_ids: list[str] = []
    variant_id: str | None = None
    limit: int = 10
    offset: int = 0
    explain: bool = True
    include_neighbors: bool = True
```

Change output:

```python
class ChunkSearchOut(StudioModel):
    items: list[ChunkOut]
    total: int
    offset: int = 0
    limit: int | None = None
    truncated: bool = False
```

- [ ] **Step 4: Apply offset in `ChunkService.search`**

In `backend/src/ragstudio/services/chunk_service.py`, find where search results are sliced or limited. Ensure the return uses:

```python
        total = len(items)
        offset = max(search_in.offset, 0)
        limit = max(search_in.limit, 1)
        page_items = items[offset : offset + limit]
        return ChunkSearchOut(
            items=page_items,
            total=total,
            offset=offset,
            limit=limit,
            truncated=offset + limit < total,
        )
```

If the query already applies SQL `limit`, move that limit to a candidate cap only when needed and keep the response `total` meaningful for UI pagination.

- [ ] **Step 5: Run chunk tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_chunks.py backend/tests/test_chunk_service_arabic_search.py backend/tests/test_chunk_lexical_search_repository.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/schemas/chunks.py backend/src/ragstudio/services/chunk_service.py backend/tests/test_chunks.py
git commit -m "feat: paginate chunk search results"
```

---

### Task 6: Add Auditable Local Layout Auto-Repair

**Files:**
- Create: `backend/src/ragstudio/services/layout_auto_repair.py`
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
- Test: `backend/tests/test_layout_auto_repair.py`
- Test: `backend/tests/test_index_lifecycle_service.py`

- [ ] **Step 1: Write the repair unit tests**

Create `backend/tests/test_layout_auto_repair.py`:

```python
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.layout_auto_repair import LayoutAutoRepairService


def test_layout_auto_repair_marks_empty_reference_unit_as_unrepaired():
    chunk = AdapterChunk(
        text="Book 1, Hadith 3",
        source_location={"page": 4},
        metadata={
            "reference_metadata": {"references": ["book:1:hadith:3"]},
            "canonical_reference_unit": {"answerable": False, "body_status": "missing"},
            "quality_action_policy": {"index_vector": False},
        },
        runtime_source_id="chunk-1",
    )

    repaired = LayoutAutoRepairService().repair([chunk], domain_metadata={})

    assert repaired[0].metadata["layout_auto_repair"]["status"] == "unrepaired"
    assert repaired[0].metadata["layout_auto_repair"]["reason"] == "missing_reference_body"
    assert repaired[0].metadata["quality_action_policy"]["index_vector"] is False


def test_layout_auto_repair_accepts_parser_recovered_text_as_audit_evidence():
    chunk = AdapterChunk(
        text="Recovered Arabic body text",
        source_location={"page": 4},
        metadata={
            "parser_warnings": [
                {
                    "code": "recovered_text_from_disallowed_block",
                    "quality_gate_action": "accepted_recovery",
                    "suppressed_from_counts": True,
                }
            ],
            "quality_action_policy": {"index_vector": True},
        },
        runtime_source_id="chunk-2",
    )

    repaired = LayoutAutoRepairService().repair([chunk], domain_metadata={})

    assert repaired[0].metadata["layout_auto_repair"]["status"] == "accepted_recovery"
    assert repaired[0].metadata["layout_auto_repair"]["auditable"] is True
    assert repaired[0].metadata["quality_action_policy"]["index_vector"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_layout_auto_repair.py -q
```

Expected: FAIL because `layout_auto_repair.py` does not exist.

- [ ] **Step 3: Implement the repair service**

Create `backend/src/ragstudio/services/layout_auto_repair.py`:

```python
from __future__ import annotations

from typing import Any

from ragstudio.services.adapter import AdapterChunk


class LayoutAutoRepairService:
    def repair(
        self,
        chunks: list[AdapterChunk],
        *,
        domain_metadata: Any,
    ) -> list[AdapterChunk]:
        return [self._repair_chunk(chunk) for chunk in chunks]

    def _repair_chunk(self, chunk: AdapterChunk) -> AdapterChunk:
        metadata = dict(chunk.metadata or {})
        repair = self._repair_metadata(metadata)
        metadata["layout_auto_repair"] = repair
        return AdapterChunk(
            text=chunk.text,
            source_location=chunk.source_location,
            metadata=metadata,
            runtime_source_id=chunk.runtime_source_id,
            content_type=chunk.content_type,
            preview_ref=chunk.preview_ref,
        )

    def _repair_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        canonical = metadata.get("canonical_reference_unit")
        canonical = canonical if isinstance(canonical, dict) else {}
        if canonical.get("answerable") is False and canonical.get("body_status") == "missing":
            return {
                "status": "unrepaired",
                "reason": "missing_reference_body",
                "auditable": True,
            }

        warnings = metadata.get("parser_warnings")
        warnings = warnings if isinstance(warnings, list) else []
        for warning in warnings:
            if not isinstance(warning, dict):
                continue
            if (
                warning.get("code") == "recovered_text_from_disallowed_block"
                or warning.get("quality_gate_action") == "accepted_recovery"
            ):
                return {
                    "status": "accepted_recovery",
                    "reason": "parser_recovered_text",
                    "auditable": True,
                }

        return {
            "status": "not_needed",
            "reason": "no_repair_signal",
            "auditable": True,
        }
```

- [ ] **Step 4: Run repair tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_layout_auto_repair.py -q
```

Expected: PASS.

- [ ] **Step 5: Insert repair before quality gate**

In `backend/src/ragstudio/services/index_lifecycle_service.py`, import:

```python
from ragstudio.services.layout_auto_repair import LayoutAutoRepairService
```

Add constructor parameter:

```python
        layout_repair: LayoutAutoRepairService | None = None,
```

Set:

```python
        self.layout_repair = layout_repair or LayoutAutoRepairService()
```

After canonical chunk processing and before `quality_report = self.quality_gate...`, add:

```python
        adapter_chunks = self.layout_repair.repair(
            adapter_chunks,
            domain_metadata=options.domain_metadata,
        )
```

- [ ] **Step 6: Add lifecycle hook test**

Add to `backend/tests/test_index_lifecycle_service.py`:

```python
from ragstudio.services.layout_auto_repair import LayoutAutoRepairService


def test_layout_auto_repair_service_preserves_quality_policy():
    chunk = AdapterChunk(
        text="Book 1, Hadith 3",
        source_location={"page": 4},
        metadata={
            "canonical_reference_unit": {"answerable": False, "body_status": "missing"},
            "quality_action_policy": {"index_vector": False},
        },
        runtime_source_id="chunk-1",
    )

    repaired = LayoutAutoRepairService().repair([chunk], domain_metadata={})[0]

    assert repaired.metadata["layout_auto_repair"]["status"] == "unrepaired"
    assert repaired.metadata["quality_action_policy"]["index_vector"] is False
```

- [ ] **Step 7: Run repair and chunk tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_layout_auto_repair.py backend/tests/test_chunk_persistence_service.py backend/tests/test_index_quality_gate.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/src/ragstudio/services/layout_auto_repair.py backend/src/ragstudio/services/index_lifecycle_service.py backend/tests/test_layout_auto_repair.py backend/tests/test_index_lifecycle_service.py
git commit -m "feat: add auditable layout auto repair stage"
```

---

### Task 7: Add Native Storage Configuration Boundary

**Files:**
- Create: `backend/src/ragstudio/services/native_storage_config.py`
- Modify: `backend/src/ragstudio/services/native_raganything_adapter.py`
- Test: `backend/tests/test_native_storage_config.py`

- [ ] **Step 1: Write storage config tests**

Create `backend/tests/test_native_storage_config.py`:

```python
from types import SimpleNamespace

from ragstudio.services.native_storage_config import NativeStorageConfig


def test_native_storage_config_builds_postgres_and_neo4j_settings():
    settings = SimpleNamespace(resolved_database_url="postgresql+asyncpg://user:pass@db.example/rag")
    profile = SimpleNamespace(
        id="default",
        neo4j_uri="bolt://neo4j.example:7687",
        neo4j_username="neo4j",
        neo4j_password="secret",
    )

    config = NativeStorageConfig.from_profile(profile, settings)

    assert config.postgres["POSTGRES_HOST"] == "db.example"
    assert config.postgres["POSTGRES_USER"] == "user"
    assert config.postgres["POSTGRES_DATABASE"] == "rag"
    assert config.neo4j["NEO4J_URI"] == "bolt://neo4j.example:7687"
    assert config.workspace == "ragstudio_default"


def test_native_storage_config_redacted_summary_hides_secrets():
    settings = SimpleNamespace(resolved_database_url="postgresql+asyncpg://user:pass@db.example/rag")
    profile = SimpleNamespace(
        id="default",
        neo4j_uri="bolt://neo4j.example:7687",
        neo4j_username="neo4j",
        neo4j_password="secret",
    )

    summary = NativeStorageConfig.from_profile(profile, settings).redacted_summary()

    assert "pass" not in str(summary)
    assert "secret" not in str(summary)
    assert summary["postgres_host"] == "db.example"
    assert summary["neo4j_configured"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_native_storage_config.py -q
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement `NativeStorageConfig`**

Create `backend/src/ragstudio/services/native_storage_config.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from ragstudio.services.graph_workspace import workspace_label
from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class NativeStorageConfig:
    postgres: dict[str, str]
    neo4j: dict[str, str]
    workspace: str

    @classmethod
    def from_profile(cls, profile: Any, settings: Any) -> "NativeStorageConfig":
        url = make_url(settings.resolved_database_url)
        workspace = workspace_label(profile)
        return cls(
            postgres={
                "POSTGRES_HOST": url.host or "127.0.0.1",
                "POSTGRES_PORT": str(url.port or 5432),
                "POSTGRES_USER": unquote(url.username or "postgres"),
                "POSTGRES_PASSWORD": unquote(url.password or ""),
                "POSTGRES_DATABASE": url.database or "ragstudio",
                "POSTGRES_WORKSPACE": workspace,
            },
            neo4j={
                "NEO4J_URI": getattr(profile, "neo4j_uri", None) or "",
                "NEO4J_USERNAME": getattr(profile, "neo4j_username", None) or "",
                "NEO4J_PASSWORD": getattr(profile, "neo4j_password", None) or "",
                "NEO4J_WORKSPACE": workspace,
            },
            workspace=workspace,
        )

    def as_env(self) -> dict[str, str]:
        return {**self.postgres, **self.neo4j}

    def redacted_summary(self) -> dict[str, Any]:
        return {
            "postgres_host": self.postgres["POSTGRES_HOST"],
            "postgres_port": self.postgres["POSTGRES_PORT"],
            "postgres_database": self.postgres["POSTGRES_DATABASE"],
            "postgres_user_configured": bool(self.postgres["POSTGRES_USER"]),
            "neo4j_configured": bool(self.neo4j["NEO4J_URI"]),
            "neo4j_username_configured": bool(self.neo4j["NEO4J_USERNAME"]),
            "workspace": self.workspace,
        }
```

- [ ] **Step 4: Use config in native adapter**

In `backend/src/ragstudio/services/native_raganything_adapter.py`, import:

```python
from ragstudio.services.native_storage_config import NativeStorageConfig
```

In `__init__`, add:

```python
        self.storage_config = NativeStorageConfig.from_profile(self.profile, self.settings)
```

Replace `_postgres_env` usage and `_storage_env` update construction with:

```python
        updates = self.storage_config.as_env()
```

Keep `_storage_env` as the single fallback boundary for third-party LightRAG storage. Do not call `_postgres_env` elsewhere.

- [ ] **Step 5: Remove dead `_postgres_env` if unused**

If no code uses `_postgres_env`, delete it and the now-unused `make_url` and `unquote` imports from `native_raganything_adapter.py`.

- [ ] **Step 6: Run storage config and adapter tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_native_storage_config.py backend/tests/test_runtime_query_service.py backend/tests/test_runtime_health_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/native_storage_config.py backend/src/ragstudio/services/native_raganything_adapter.py backend/tests/test_native_storage_config.py
git commit -m "refactor: isolate native runtime storage configuration"
```

---

### Task 8: Wire Frontend To Job Events And Graph Options

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/features/documents/documents-page.tsx`
- Test: `frontend/tests/api-client.test.ts`
- Test: `frontend/tests/documents-page.test.tsx`

- [ ] **Step 1: Write API client URL tests**

Add to `frontend/tests/api-client.test.ts`:

```typescript
describe("apiClient graph and job event URLs", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("serializes graph query options", async () => {
    let calledUrl = "";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url) => {
        calledUrl = String(url);
        return new Response(
          JSON.stringify({ nodes: [], edges: [], total: 0, limit: 25, offset: 50 }),
          { headers: { "Content-Type": "application/json" }, status: 200 },
        );
      }),
    );

    await apiClient.graph({ documentId: "doc 1", limit: 25, offset: 50 });

    expect(calledUrl).toBe("/api/graph?document_id=doc+1&limit=25&offset=50");
  });

  it("builds a job event stream URL", () => {
    expect(apiClient.jobEventsUrl("job 1")).toBe("/api/jobs/job%201/events");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `frontend/`:

```bash
npm run test -- --run ../frontend/tests/api-client.test.ts
```

Expected: FAIL because `graph` does not accept options and `jobEventsUrl` does not exist.

- [ ] **Step 3: Update API client**

In `frontend/src/api/client.ts`, replace:

```typescript
  graph: () => request<GraphOut>("/api/graph"),
```

with:

```typescript
  graph: (options: { documentId?: string; limit?: number; offset?: number } = {}) => {
    const params = new URLSearchParams();
    if (options.documentId) {
      params.set("document_id", options.documentId);
    }
    if (typeof options.limit === "number") {
      params.set("limit", String(options.limit));
    }
    if (typeof options.offset === "number") {
      params.set("offset", String(options.offset));
    }
    const query = params.toString();
    return request<GraphOut>(query ? `/api/graph?${query}` : "/api/graph");
  },
  jobEventsUrl: (jobId: string) =>
    `${API_BASE_URL}/api/jobs/${encodeURIComponent(jobId)}/events`,
```

- [ ] **Step 4: Add live event state to DocumentsPage**

In `frontend/src/features/documents/documents-page.tsx`, add a local state:

```typescript
const [liveJobStages, setLiveJobStages] = useState<Record<string, Record<string, unknown>>>({});
```

Add this effect after `activeJobs` is computed:

```typescript
useEffect(() => {
  const runningJobs = jobs.filter(isActiveJob);
  if (!runningJobs.length || typeof EventSource === "undefined") {
    return;
  }
  const sources = runningJobs.map((job) => {
    const source = new EventSource(apiClient.jobEventsUrl(job.id));
    source.addEventListener("stage", (event) => {
      const parsed = JSON.parse((event as MessageEvent).data) as Record<string, unknown>;
      setLiveJobStages((current) => ({ ...current, [job.id]: parsed }));
    });
    source.addEventListener("done", () => {
      source.close();
      void jobsQuery.refetch();
      void documentsQuery.refetch();
    });
    source.onerror = () => {
      source.close();
    };
    return source;
  });
  return () => {
    sources.forEach((source) => source.close());
  };
}, [documentsQuery, jobs, jobsQuery]);
```

When rendering job stage details, prefer `liveJobStages[job.id]` over `job.result.indexing_stage`.

- [ ] **Step 5: Add frontend display test**

In `frontend/tests/documents-page.test.tsx`, add a fake EventSource:

```typescript
it("shows live indexing stage events from the job stream", async () => {
  class FakeEventSource {
    static instances: FakeEventSource[] = [];
    listeners: Record<string, Array<(event: MessageEvent) => void>> = {};
    url: string;

    constructor(url: string) {
      this.url = url;
      FakeEventSource.instances.push(this);
    }

    addEventListener(name: string, callback: (event: MessageEvent) => void) {
      this.listeners[name] = [...(this.listeners[name] ?? []), callback];
    }

    close() {}

    emit(name: string, data: unknown) {
      for (const listener of this.listeners[name] ?? []) {
        listener(new MessageEvent(name, { data: JSON.stringify(data) }));
      }
    }
  }

  vi.stubGlobal("EventSource", FakeEventSource);
  vi.mocked(apiClient.jobs).mockResolvedValue({
    items: [
      {
        ...jobDefaults,
        id: "job-live",
        type: "index_document",
        status: "running",
        target_id: "doc-1",
        progress: 25,
        logs: [],
        result: {},
      },
    ],
    total: 1,
  });

  renderDocumentsPage();
  openJobsWarningsTab();

  await screen.findByText("Index doc-1");
  act(() => {
    FakeEventSource.instances[0].emit("stage", {
      stage: "chunks_persisted",
      label: "Chunks persisted",
      detail: "Persisted 42 canonical chunks.",
      progress: 65,
      chunk_count: 42,
    });
  });

  expect(await screen.findByText("Chunks persisted Â· Persisted 42 canonical chunks. Â· 42 chunks")).toBeVisible();
});
```

If the page currently renders `Index doc-1` differently when documents are empty, adjust the assertion to the existing fallback job title.

- [ ] **Step 6: Run frontend tests**

Run from `frontend/`:

```bash
npm run test -- --run ../frontend/tests/api-client.test.ts ../frontend/tests/documents-page.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/features/documents/documents-page.tsx frontend/tests/api-client.test.ts frontend/tests/documents-page.test.tsx
git commit -m "feat: show live indexing progress"
```

---

### Task 9: Integration Validation

**Files:**
- No new files unless a previous task exposed missing docs.

- [ ] **Step 1: Run backend focused suite**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_index_progress.py backend/tests/test_index_lifecycle_service.py backend/tests/test_layout_auto_repair.py backend/tests/test_graph_service.py backend/tests/test_chunks.py backend/tests/test_jobs.py backend/tests/test_native_storage_config.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend focused suite**

Run:

```bash
cd frontend
npm run test -- --run ../frontend/tests/api-client.test.ts ../frontend/tests/documents-page.test.tsx ../frontend/tests/graph-page.test.tsx
```

Expected: PASS.

- [ ] **Step 3: Run proof validation**

Run:

```bash
./scripts/proof.sh --strict --json
```

Expected: PASS. This should remain static-fixture only and must not require live Docker services or private providers.

- [ ] **Step 4: Run full validation if time and Docker are available**

Run:

```bash
./scripts/test-all.sh
```

Expected: PASS.

- [ ] **Step 5: Commit validation/doc adjustments**

If no files changed, skip this commit. If docs or small test adjustments were needed:

```bash
git add docs backend frontend
git commit -m "test: validate pipeline hardening"
```

---

## Self-Review

Spec coverage:

- The 10 core layers are covered by the "Target Architecture: 10 Core Layers" section and Task 0.
- Domain Resolver Layer is implemented by Task 0.1.
- Canonical Evidence Layer and Materialization Policy Layer are supported by Task 0.2 and later integrated through Task 6.
- Retrieval Planner Layer is implemented by Task 0.3.
- Parse Layer, Layout Normalization Layer, Repair And Quality Layer, Fusion And Rerank Layer, Context Assembly Layer, and Proof Trace Layer are mapped in Task 0, then exercised by the focused hardening tasks.
- 4.1 is covered by Task 1.
- 4.2 is covered by Task 7 as a safe first step: explicit storage config and a single env fallback boundary. A later phase can replace the fallback entirely if LightRAG exposes direct storage constructors for every backend.
- 4.3 is covered by Task 6.
- 4.4 is covered by Tasks 4 and 5.
- 4.5 is covered by Tasks 2, 3, and 8.

Placeholder scan:

- No placeholder markers or undefined “add tests later” steps remain.
- Each code-changing task includes concrete code or exact insertion guidance.

Type consistency:

- `IndexStage`, `Job.result.indexing_stage`, and `Job.result.stage_events` are used consistently.
- `GraphOut` pagination fields match `GraphService.get_graph` return fields and frontend graph query options.
- `ChunkSearchIn.offset` and `ChunkSearchOut.offset/limit/truncated` match the service pagination guidance.
