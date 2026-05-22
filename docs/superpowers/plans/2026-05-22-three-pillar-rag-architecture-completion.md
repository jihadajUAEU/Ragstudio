# Three-Pillar Rag Architecture Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish Ragstudio's domain-aware, layout-aware, and context-aware RAG architecture so it is implemented in runtime retrieval and proven by public-safe static proof artifacts.

**Architecture:** Keep canonical Ragstudio chunks in Postgres as the source of truth. Domain classification and profiles choose lane policy; layout metadata expands candidates through canonical neighbors; context assembly adds bounded parent and sibling context before answer generation. Runtime, vector, and graph lanes must preserve bridge identifiers and visible lane-result traces before final fusion.

**Tech Stack:** Python 3.12, FastAPI service layer, SQLAlchemy async ORM, Pydantic schemas, PostgreSQL JSON/JSONB metadata, pytest, Ruff, Ragstudio proof packet validator.

---

## Current State Guardrails

This plan starts from the current `main` working tree after commit `f7d686a`.

Already present and must not be duplicated:

- `backend/src/ragstudio/services/domain_classifier.py`
- `backend/src/ragstudio/services/retrieval_route_input.py`
- `RetrievalLaneResult` inside `backend/src/ragstudio/services/retrieval_route_planner.py`
- `backend/src/ragstudio/services/vector_candidate_repository.py`
- `backend/src/ragstudio/services/layout_neighbor_service.py`
- `backend/src/ragstudio/services/evidence_context.py`
- `backend/src/ragstudio/services/context_assembly_service.py`

Known current problems to fix first:

- Ruff line-length failures in `backend/src/ragstudio/services/domain_lexical_registry.py`.
- Ruff line-length failure in `backend/tests/test_context_assembly_service.py`.
- `backend/tests/test_retrieval_orchestrator.py::test_orchestrator_fuses_native_metadata_and_graph_before_answering` expects raw graph text, but current context assembly intentionally prefixes evidence with breadcrumb and layout summary.
- The public proof claim `RAGSTUDIO-RETRIEVAL-ARCHITECTURE` remains `roadmap`.

Completion rules:

- Do not add a second `retrieval_lane_result.py`; use the existing `RetrievalLaneResult`.
- Do not add a second classifier; extend `DomainClassifier`.
- Every task ends with focused tests and a commit.
- Do not upgrade the proof claim to `proven` until runtime tests pass and static proof validation passes.

---

## File Structure

- Modify `backend/src/ragstudio/services/domain_classifier.py`: align domain families with lexical adapter families and add materialization hints.
- Modify `backend/src/ragstudio/services/domain_profile_registry.py`: add executable legal, medical, financial, and code profiles.
- Create `backend/src/ragstudio/services/domain_lexical_adapters.py`: keyword adapters for legal, medical, financial, and code retrieval expansion.
- Modify `backend/src/ragstudio/services/domain_lexical_registry.py`: register new adapters and use the shared classifier.
- Modify `backend/src/ragstudio/services/retrieval_route_input.py`: use classifier materialization hints when query config does not override them.
- Modify `backend/src/ragstudio/services/layout_neighbor_service.py`: add layout-group and reading-order neighbors.
- Create `backend/src/ragstudio/services/context_window_service.py`: fetch bounded previous/next canonical chunks.
- Modify `backend/src/ragstudio/services/retrieval_orchestrator.py`: include context-window neighbors and standard lane traces.
- Modify `backend/src/ragstudio/services/native_raganything_adapter.py`: preserve layout/context bridge fields in native content-list metadata.
- Modify proof files under `docs/benchmarks/ragstudio-oss-proof-v1/`: add all-lane architecture evidence and upgrade the architecture claim after validation.

---

### Task 1: Stabilize Current Tests And Lint

**Files:**
- Modify: `backend/src/ragstudio/services/domain_lexical_registry.py`
- Modify: `backend/tests/test_context_assembly_service.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Reproduce the current failures**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run ruff check backend/src/ragstudio/services/domain_lexical_registry.py backend/tests/test_context_assembly_service.py
uv run pytest backend/tests/test_retrieval_orchestrator.py::test_orchestrator_fuses_native_metadata_and_graph_before_answering -q
```

Expected: Ruff reports `E501`; the orchestrator test fails because graph evidence text is now context-prefixed.

- [ ] **Step 2: Format the domain trigger table**

In `backend/src/ragstudio/services/domain_lexical_registry.py`, replace the `_family_triggers` assignment with:

```python
        self._family_triggers: dict[str, set[str]] = {
            "arabic_religious": {
                "quran",
                "tafseer",
                "quran_tafseer",
                "hadith",
                "islamic_text",
                "religious_text",
                "fiqh",
                "fatwa",
                "islamic_law",
            },
            "legal_reference": {
                "case_law",
                "contract",
                "law",
                "legal",
                "legal_reference",
                "regulation",
                "statute",
            },
            "medical_reference": {
                "clinical",
                "diagnosis",
                "healthcare",
                "medical",
                "medical_reference",
                "medicine",
                "patient",
                "treatment",
            },
            "financial_reference": {
                "accounting",
                "banking",
                "finance",
                "financial",
                "financial_reference",
                "investment",
                "invoice",
                "tax",
            },
            "code_reference": {
                "api",
                "code",
                "code_reference",
                "programming",
                "software",
                "source_code",
                "stacktrace",
            },
        }
```

- [ ] **Step 3: Wrap the long assertion**

In `backend/tests/test_context_assembly_service.py`, replace the long `startswith` assertion with:

```python
    assert context.evidence[0].context_text.startswith(
        "[Holy Book > Surah Al-Baqarah > 2:45 | page=2]"
    )
```

- [ ] **Step 4: Assert the intended context-prefixed graph evidence**

In `backend/tests/test_retrieval_orchestrator.py`, inside `test_orchestrator_fuses_native_metadata_and_graph_before_answering`, replace the raw graph text assertion with:

```python
    assert graph_evidence.text.startswith("[collection:bukhari | page=9]\n")
    assert graph_evidence.text.endswith(
        "Full hydrated graph chunk confirms 7277 hadith in Sahih al-Bukhari."
    )
    assert graph_evidence.metadata["assembled_context"] == {
        "breadcrumb": "collection:bukhari",
        "layout_summary": "page=9",
        "context_text_applied": True,
    }
```

- [ ] **Step 5: Verify the stabilization**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run ruff check backend/src/ragstudio/services/domain_lexical_registry.py backend/tests/test_context_assembly_service.py
uv run pytest backend/tests/test_context_assembly_service.py backend/tests/test_retrieval_orchestrator.py::test_orchestrator_fuses_native_metadata_and_graph_before_answering -q
```

Expected: both commands pass.

- [ ] **Step 6: Commit**

Run:

```powershell
git add backend/src/ragstudio/services/domain_lexical_registry.py backend/tests/test_context_assembly_service.py backend/tests/test_retrieval_orchestrator.py
git commit -m "test: align retrieval context expectations"
```

---

### Task 2: Align Domain Classification With Executable Profiles

**Files:**
- Modify: `backend/src/ragstudio/services/domain_classifier.py`
- Modify: `backend/src/ragstudio/services/domain_profile_registry.py`
- Modify: `backend/src/ragstudio/services/retrieval_route_input.py`
- Test: `backend/tests/test_domain_classifier.py`
- Test: `backend/tests/test_domain_profile_registry.py`
- Test: `backend/tests/test_retrieval_route_input.py`

- [ ] **Step 1: Add failing classifier tests**

Append to `backend/tests/test_domain_classifier.py`:

```python
def test_domain_classifier_maps_specialized_non_arabic_profiles():
    classifier = DomainClassifier()

    legal = classifier.classify([{"domain": "legal", "document_type": "contract"}])
    medical = classifier.classify([{"domain": "medical", "layout_types": ["figure"]}])
    financial = classifier.classify([{"domain": "finance", "layout_types": ["table"]}])
    code = classifier.classify([{"domain": "code", "tags": ["api"]}])

    assert legal.domain_family == "legal_reference"
    assert legal.domain_profile_id == "legal_reference"
    assert legal.materialization_hint == "graph"
    assert medical.domain_family == "medical_reference"
    assert medical.domain_profile_id == "medical_reference"
    assert medical.materialization_hint == "full"
    assert financial.domain_family == "financial_reference"
    assert financial.domain_profile_id == "financial_reference"
    assert financial.materialization_hint == "full"
    assert code.domain_family == "code_reference"
    assert code.domain_profile_id == "code_reference"
    assert code.materialization_hint == "vector"


def test_domain_classifier_uses_adapter_family_for_arabic_reference_domains():
    result = DomainClassifier().classify(
        [{"domain": "quran_tafseer", "tags": ["quran", "tafseer"]}]
    )

    assert result.domain_family == "arabic_religious"
    assert result.domain_profile_id == "reference_heavy"
    assert result.materialization_hint == "graph"
```

- [ ] **Step 2: Add failing profile tests**

Append to `backend/tests/test_domain_profile_registry.py`:

```python
def test_registry_exposes_specialized_domain_profiles():
    registry = DomainProfileRegistry()

    legal = registry.get("legal_reference")
    medical = registry.get("medical_reference")
    financial = registry.get("financial_reference")
    code = registry.get("code_reference")

    assert legal.chunking_strategy == "reference_anchored"
    assert legal.supports_materialization("graph")
    assert medical.supports_layout("figure")
    assert medical.supports_materialization("runtime")
    assert financial.supports_layout("table")
    assert financial.supports_materialization("graph")
    assert code.supports_materialization("vector")
```

- [ ] **Step 3: Add failing route input test**

Append to `backend/tests/test_retrieval_route_input.py`:

```python
def test_route_input_uses_classifier_materialization_hint_when_not_overridden():
    request = build_retrieval_route_request(
        query="medical figure diagnosis",
        document_ids=["doc-med"],
        runtime_profile_id="profile-med",
        variant_id="variant-med",
        query_intent="semantic",
        retrieval_strategy="semantic_hybrid",
        query_understanding=None,
        domain_metadata=[{"domain": "medical", "layout_types": ["figure"]}],
        query_config={"limit": 8},
        runtime_readiness={"state": "ready", "safe_to_run": True},
        reranker_readiness={"state": "disabled", "safe_to_run": False},
    )

    assert request.domain_id == "medical_reference"
    assert request.layout_hint == "figure"
    assert request.materialization_hint == "full"
```

- [ ] **Step 4: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run pytest backend/tests/test_domain_classifier.py backend/tests/test_domain_profile_registry.py backend/tests/test_retrieval_route_input.py -q
```

Expected: fail because `DomainClassification` lacks `materialization_hint` and the specialized profiles are absent.

- [ ] **Step 5: Extend `DomainClassification`**

In `backend/src/ragstudio/services/domain_classifier.py`, change the dataclass to:

```python
@dataclass(frozen=True, slots=True)
class DomainClassification:
    domain_profile_id: str
    domain_family: str
    layout_hint: str | None
    materialization_hint: str | None
    reference_heavy: bool
    signals: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "domain_profile_id": self.domain_profile_id,
            "domain_family": self.domain_family,
            "layout_hint": self.layout_hint,
            "materialization_hint": self.materialization_hint,
            "reference_heavy": self.reference_heavy,
            "signals": list(self.signals),
        }
```

- [ ] **Step 6: Replace classification branches**

In `DomainClassifier.classify()`, replace the branch body after `layout_hint = _layout_hint(signals)` with:

```python
        if {"quran_tafseer", "tafseer", "quran", "hadith"} & signals:
            return self._remember(
                cache_key,
                DomainClassification(
                    domain_profile_id="reference_heavy",
                    domain_family="arabic_religious",
                    layout_hint=layout_hint or "reference",
                    materialization_hint="graph",
                    reference_heavy=True,
                    signals=tuple(sorted(signals)),
                ),
            )
        if {"legal", "law", "statute", "policy", "contract"} & signals:
            return self._remember(
                cache_key,
                DomainClassification(
                    domain_profile_id="legal_reference",
                    domain_family="legal_reference",
                    layout_hint=layout_hint or "reference",
                    materialization_hint="graph",
                    reference_heavy=True,
                    signals=tuple(sorted(signals)),
                ),
            )
        if {"medical", "clinical", "medicine", "diagnosis", "patient"} & signals:
            return self._remember(
                cache_key,
                DomainClassification(
                    domain_profile_id="medical_reference",
                    domain_family="medical_reference",
                    layout_hint=layout_hint,
                    materialization_hint=_materialization_hint(layout_hint, "vector"),
                    reference_heavy=False,
                    signals=tuple(sorted(signals)),
                ),
            )
        if {"finance", "financial", "invoice", "tax", "accounting"} & signals:
            return self._remember(
                cache_key,
                DomainClassification(
                    domain_profile_id="financial_reference",
                    domain_family="financial_reference",
                    layout_hint=layout_hint or "table",
                    materialization_hint=_materialization_hint(layout_hint or "table", "vector"),
                    reference_heavy=False,
                    signals=tuple(sorted(signals)),
                ),
            )
        if {"code", "api", "source_code", "stacktrace", "software"} & signals:
            return self._remember(
                cache_key,
                DomainClassification(
                    domain_profile_id="code_reference",
                    domain_family="code_reference",
                    layout_hint=layout_hint,
                    materialization_hint="vector",
                    reference_heavy=False,
                    signals=tuple(sorted(signals)),
                ),
            )
        if layout_hint in {"table", "figure", "equation"}:
            return self._remember(
                cache_key,
                DomainClassification(
                    domain_profile_id="multimodal_layout",
                    domain_family="generic",
                    layout_hint=layout_hint,
                    materialization_hint="full",
                    reference_heavy=False,
                    signals=tuple(sorted(signals)),
                ),
            )
        if {"research", "paper", "report", "scientific"} & signals:
            return self._remember(
                cache_key,
                DomainClassification(
                    domain_profile_id="general",
                    domain_family="research_semantic",
                    layout_hint=layout_hint,
                    materialization_hint="vector",
                    reference_heavy=False,
                    signals=tuple(sorted(signals)),
                ),
            )
        return self._remember(
            cache_key,
            DomainClassification(
                domain_profile_id="general",
                domain_family="generic",
                layout_hint=layout_hint,
                materialization_hint="vector",
                reference_heavy=False,
                signals=tuple(sorted(signals)),
            ),
        )
```

Add this helper below `_layout_hint()`:

```python
def _materialization_hint(layout_hint: str | None, fallback: str) -> str:
    if layout_hint in {"table", "figure", "equation"}:
        return "full"
    return fallback
```

- [ ] **Step 7: Add specialized profiles**

In `backend/src/ragstudio/services/domain_profile_registry.py`, add these entries before the closing `)` of `DEFAULT_DOMAIN_PROFILES`:

```python
    DomainProfile(
        id="legal_reference",
        label="Legal Reference",
        chunking_strategy="reference_anchored",
        retrieval_priority=("postgres_canonical", "lexical_reference", "metadata", "graph", "vector"),
        supported_layouts=("plain_text", "reference", "table", "mixed"),
        materialization_hints=("canonical_only", "vector", "graph", "full"),
        reference_patterns=("section", "article", "clause", "regulation"),
        default_top_k=10,
    ),
    DomainProfile(
        id="medical_reference",
        label="Medical Reference",
        chunking_strategy="layout_block",
        retrieval_priority=("postgres_canonical", "metadata", "vector", "graph", "raganything_runtime"),
        supported_layouts=("plain_text", "table", "figure", "reference", "mixed"),
        materialization_hints=("canonical_only", "vector", "runtime", "full"),
        reference_patterns=("diagnosis", "treatment", "dose", "figure"),
        default_top_k=10,
    ),
    DomainProfile(
        id="financial_reference",
        label="Financial Reference",
        chunking_strategy="layout_block",
        retrieval_priority=("postgres_canonical", "metadata", "vector", "graph"),
        supported_layouts=("plain_text", "table", "reference", "mixed"),
        materialization_hints=("canonical_only", "vector", "graph", "full"),
        reference_patterns=("invoice", "account", "line_item", "tax"),
        default_top_k=10,
    ),
    DomainProfile(
        id="code_reference",
        label="Code Reference",
        chunking_strategy="semantic_window",
        retrieval_priority=("postgres_canonical", "metadata", "vector", "graph"),
        supported_layouts=("plain_text", "reference", "mixed"),
        materialization_hints=("canonical_only", "vector", "graph", "full"),
        reference_patterns=("symbol", "function", "class", "stacktrace"),
        default_top_k=12,
    ),
```

If Ruff reports line length in the two `retrieval_priority` tuples, split the tuple across lines.

- [ ] **Step 8: Use classifier materialization hint in route input**

In `backend/src/ragstudio/services/retrieval_route_input.py`, replace this payload field:

```python
        "materialization_hint": _materialization_hint(query_config),
```

with:

```python
        "materialization_hint": (
            _materialization_hint(query_config) or classification.materialization_hint
        ),
```

- [ ] **Step 9: Verify domain classification and route input**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run pytest backend/tests/test_domain_classifier.py backend/tests/test_domain_profile_registry.py backend/tests/test_retrieval_route_input.py backend/tests/test_retrieval_route_planner.py -q
uv run ruff check backend/src/ragstudio/services/domain_classifier.py backend/src/ragstudio/services/domain_profile_registry.py backend/src/ragstudio/services/retrieval_route_input.py backend/tests/test_domain_classifier.py backend/tests/test_domain_profile_registry.py backend/tests/test_retrieval_route_input.py
```

Expected: all tests and Ruff pass.

- [ ] **Step 10: Commit**

Run:

```powershell
git add backend/src/ragstudio/services/domain_classifier.py backend/src/ragstudio/services/domain_profile_registry.py backend/src/ragstudio/services/retrieval_route_input.py backend/tests/test_domain_classifier.py backend/tests/test_domain_profile_registry.py backend/tests/test_retrieval_route_input.py
git commit -m "feat: make domain profiles executable"
```

---

### Task 3: Add Non-Arabic Domain Lexical Adapters

**Files:**
- Create: `backend/src/ragstudio/services/domain_lexical_adapters.py`
- Modify: `backend/src/ragstudio/services/domain_lexical_registry.py`
- Test: `backend/tests/test_domain_query_expansion_service.py`

- [ ] **Step 1: Add failing adapter tests**

Append to `backend/tests/test_domain_query_expansion_service.py`:

```python
def test_domain_query_expansion_uses_legal_keyword_adapter():
    expansion = DomainQueryExpansionService().expand(
        "breach of contract section 12",
        domain_metadata=[{"domain": "legal", "document_type": "contract"}],
    )

    assert expansion.domain_family == "legal_reference"
    assert "agreement" in expansion.expanded_terms
    assert "article" in expansion.expanded_terms
    assert any(pass_.name == "lexical_expanded_token" for pass_ in expansion.retrieval_passes)


def test_domain_query_expansion_uses_financial_keyword_adapter():
    expansion = DomainQueryExpansionService().expand(
        "invoice tax amount",
        domain_metadata=[{"domain": "finance", "document_type": "invoice"}],
    )

    assert expansion.domain_family == "financial_reference"
    assert "bill" in expansion.expanded_terms
    assert "vat" in expansion.expanded_terms
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run pytest backend/tests/test_domain_query_expansion_service.py -q
```

Expected: fail because the registry has no legal or financial adapters.

- [ ] **Step 3: Create keyword adapters**

Create `backend/src/ragstudio/services/domain_lexical_adapters.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from ragstudio.services.lexical_language_adapters import LexicalExpansion


@dataclass(frozen=True, slots=True)
class KeywordLexicalAdapter:
    source: str
    keyword_map: dict[str, tuple[str, ...]]

    def supports_query(self, query: str) -> bool:
        normalized = query.casefold()
        return any(keyword in normalized for keyword in self.keyword_map)

    def expand_query(self, query: str) -> LexicalExpansion:
        normalized = " ".join(query.strip().casefold().split())
        terms: list[str] = []
        for keyword, expansions in self.keyword_map.items():
            if keyword in normalized:
                terms.extend(expansions)
        return LexicalExpansion(
            original_query=query,
            normalized_query=normalized,
            language="english",
            script="latin",
            terms=_dedupe(terms),
            match_type="domain_keyword",
            confidence=0.8 if terms else 0.0,
            source=self.source,
            trace={"adapter": self.source, "keywords": list(self.keyword_map)},
        )


LEGAL_LEXICAL_ADAPTER = KeywordLexicalAdapter(
    source="legal_keyword_adapter",
    keyword_map={
        "contract": ("contract", "agreement", "clause"),
        "section": ("section", "article", "provision"),
        "statute": ("statute", "regulation", "law"),
        "breach": ("breach", "violation", "default"),
    },
)

MEDICAL_LEXICAL_ADAPTER = KeywordLexicalAdapter(
    source="medical_keyword_adapter",
    keyword_map={
        "diagnosis": ("diagnosis", "condition", "finding"),
        "treatment": ("treatment", "therapy", "intervention"),
        "patient": ("patient", "clinical", "case"),
        "dose": ("dose", "dosage", "medication"),
    },
)

FINANCIAL_LEXICAL_ADAPTER = KeywordLexicalAdapter(
    source="financial_keyword_adapter",
    keyword_map={
        "invoice": ("invoice", "bill", "amount"),
        "tax": ("tax", "vat", "withholding"),
        "revenue": ("revenue", "income", "sales"),
        "expense": ("expense", "cost", "liability"),
    },
)

CODE_LEXICAL_ADAPTER = KeywordLexicalAdapter(
    source="code_keyword_adapter",
    keyword_map={
        "api": ("api", "endpoint", "request"),
        "error": ("error", "exception", "stacktrace"),
        "function": ("function", "method", "call"),
        "class": ("class", "object", "type"),
    },
)


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
```

- [ ] **Step 4: Register keyword adapters**

In `backend/src/ragstudio/services/domain_lexical_registry.py`, add imports:

```python
from ragstudio.services.domain_classifier import DomainClassifier
from ragstudio.services.domain_lexical_adapters import (
    CODE_LEXICAL_ADAPTER,
    FINANCIAL_LEXICAL_ADAPTER,
    LEGAL_LEXICAL_ADAPTER,
    MEDICAL_LEXICAL_ADAPTER,
)
```

After `self.register("arabic_religious", ArabicLexicalAdapter())`, add:

```python
        self.register("legal_reference", LEGAL_LEXICAL_ADAPTER)
        self.register("medical_reference", MEDICAL_LEXICAL_ADAPTER)
        self.register("financial_reference", FINANCIAL_LEXICAL_ADAPTER)
        self.register("code_reference", CODE_LEXICAL_ADAPTER)
```

Replace `resolve_domain_family()` with:

```python
    def resolve_domain_family(self, domain_metadata: list[dict[str, Any]]) -> str:
        return DomainClassifier().classify(domain_metadata).domain_family
```

- [ ] **Step 5: Verify domain expansion**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run pytest backend/tests/test_domain_query_expansion_service.py backend/tests/test_domain_classifier.py -q
uv run ruff check backend/src/ragstudio/services/domain_lexical_adapters.py backend/src/ragstudio/services/domain_lexical_registry.py backend/src/ragstudio/services/domain_query_expansion_service.py
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```powershell
git add backend/src/ragstudio/services/domain_lexical_adapters.py backend/src/ragstudio/services/domain_lexical_registry.py backend/tests/test_domain_query_expansion_service.py
git commit -m "feat: add domain lexical adapters"
```

---

### Task 4: Complete Layout-Aware Neighbor Expansion

**Files:**
- Modify: `backend/src/ragstudio/services/layout_neighbor_service.py`
- Test: `backend/tests/test_layout_neighbor_service.py`

- [ ] **Step 1: Add failing layout group test**

Append to `backend/tests/test_layout_neighbor_service.py`:

```python
@pytest.mark.asyncio
async def test_layout_neighbor_service_returns_same_layout_group_caption(
    database_url, tmp_path
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        session.add(
            Document(
                id="doc-layout-group",
                filename="layout-group.pdf",
                content_type="application/pdf",
                sha256="layout-group-sha",
                artifact_path=str(tmp_path / "layout-group.pdf"),
            )
        )
        session.add_all(
            [
                Chunk(
                    id="seed-cell",
                    document_id="doc-layout-group",
                    text="Net revenue was 120.",
                    source_location={"page": 3, "bbox": [100, 200, 220, 240]},
                    metadata_json={
                        "layout_group_id": "table-7",
                        "layout_role": "table_cell",
                    },
                ),
                Chunk(
                    id="caption",
                    document_id="doc-layout-group",
                    text="Table 7. Consolidated revenue.",
                    source_location={"page": 8, "bbox": [90, 160, 300, 185]},
                    metadata_json={
                        "layout_group_id": "table-7",
                        "layout_role": "caption",
                    },
                ),
            ]
        )
        await session.commit()

        neighbors = await LayoutNeighborService(session).neighbors_for(
            seed_chunk_ids=["seed-cell"],
            document_ids=["doc-layout-group"],
            limit=5,
        )

    await engine.dispose()

    assert [candidate.chunk_id for candidate in neighbors] == ["caption"]
    assert "layout_group" in neighbors[0].reasons
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run pytest backend/tests/test_layout_neighbor_service.py::test_layout_neighbor_service_returns_same_layout_group_caption -q
```

Expected: fail because layout groups are not considered when page/reference do not match.

- [ ] **Step 3: Add layout group helpers**

In `backend/src/ragstudio/services/layout_neighbor_service.py`, add:

```python
def _layout_group(chunk: Chunk) -> str | None:
    metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
    for key in ("layout_group_id", "table_id", "figure_id", "caption_group_id"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
```

After the `references = {...}` block in `neighbors_for()`, add:

```python
        layout_groups = {
            group
            for seed in seed_rows
            if (group := _layout_group(seed)) is not None
        }
```

Replace:

```python
        if not pages and not references:
            return []
```

with:

```python
        if not pages and not references and not layout_groups:
            return []
```

Inside the row loop, replace:

```python
            if not same_page and not same_reference:
                continue
```

with:

```python
            same_layout_group = _layout_group(row) in layout_groups
            if not same_page and not same_reference and not same_layout_group:
                continue
```

After `if is_spatial_proximity:` block, add:

```python
            if same_layout_group:
                reasons.append("layout_group")
                boost_score += 2.0
                final_score += 2.0
```

- [ ] **Step 4: Verify layout expansion**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run pytest backend/tests/test_layout_neighbor_service.py -q
uv run ruff check backend/src/ragstudio/services/layout_neighbor_service.py backend/tests/test_layout_neighbor_service.py
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add backend/src/ragstudio/services/layout_neighbor_service.py backend/tests/test_layout_neighbor_service.py
git commit -m "feat: add layout group neighbor expansion"
```

---

### Task 5: Add Context Window Expansion From Canonical Chunks

**Files:**
- Create: `backend/src/ragstudio/services/context_window_service.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Test: `backend/tests/test_context_window_service.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Add context window service test**

Create `backend/tests/test_context_window_service.py`:

```python
import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.services.context_window_service import ContextWindowService
from ragstudio.services.retrieval_evidence import EvidenceCandidate


@pytest.mark.asyncio
async def test_context_window_service_returns_adjacent_reading_order_chunks(
    database_url, tmp_path
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        session.add(
            Document(
                id="doc-context-window",
                filename="context.pdf",
                content_type="application/pdf",
                sha256="context-sha",
                artifact_path=str(tmp_path / "context.pdf"),
            )
        )
        session.add_all(
            [
                Chunk(
                    id="prev",
                    document_id="doc-context-window",
                    text="Previous section defines the key term.",
                    source_location={"page": 1},
                    metadata_json={"reading_order": 1},
                ),
                Chunk(
                    id="seed",
                    document_id="doc-context-window",
                    text="Seed section answers the question.",
                    source_location={"page": 1},
                    metadata_json={"reading_order": 2},
                ),
                Chunk(
                    id="next",
                    document_id="doc-context-window",
                    text="Next section lists the exception.",
                    source_location={"page": 1},
                    metadata_json={"reading_order": 3},
                ),
            ]
        )
        await session.commit()
        seed = EvidenceCandidate(
            candidate_id="metadata:seed",
            text="Seed section answers the question.",
            document_id="doc-context-window",
            chunk_id="seed",
            source_location={"page": 1},
            metadata={"reading_order": 2},
            tool="metadata",
            tool_rank=1,
            base_score=10.0,
        )

        neighbors = await ContextWindowService(session).window_for(
            [seed],
            document_ids=["doc-context-window"],
            limit=4,
        )

    await engine.dispose()

    assert [candidate.chunk_id for candidate in neighbors] == ["prev", "next"]
    assert all("context_window" in candidate.reasons for candidate in neighbors)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run pytest backend/tests/test_context_window_service.py -q
```

Expected: fail because `context_window_service.py` does not exist.

- [ ] **Step 3: Implement `ContextWindowService`**

Create `backend/src/ragstudio/services/context_window_service.py`:

```python
from __future__ import annotations

from typing import Any

from ragstudio.db.models import Chunk
from ragstudio.services.evidence_context import evidence_context_from_metadata
from ragstudio.services.retrieval_evidence import EvidenceCandidate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class ContextWindowService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def window_for(
        self,
        seeds: list[EvidenceCandidate],
        *,
        document_ids: list[str],
        limit: int,
    ) -> list[EvidenceCandidate]:
        seed_orders = {
            (seed.document_id, _reading_order(seed.metadata))
            for seed in seeds
            if seed.document_id and _reading_order(seed.metadata) is not None
        }
        if not seed_orders:
            return []
        scoped_documents = [document_id for document_id in document_ids if document_id]
        if not scoped_documents:
            return []
        rows = (
            await self.session.execute(
                select(Chunk)
                .where(Chunk.document_id.in_(scoped_documents))
                .order_by(Chunk.document_id.asc(), Chunk.created_at.asc(), Chunk.id.asc())
            )
        ).scalars().all()
        seed_chunk_ids = {seed.chunk_id for seed in seeds if seed.chunk_id}
        candidates: list[EvidenceCandidate] = []
        for row in rows:
            if row.id in seed_chunk_ids:
                continue
            metadata = dict(row.metadata_json) if isinstance(row.metadata_json, dict) else {}
            order = _reading_order(metadata)
            if order is None:
                continue
            if not _is_adjacent(row.document_id, order, seed_orders):
                continue
            evidence_context = evidence_context_from_metadata(
                metadata,
                source_location=row.source_location,
                content_type=row.content_type,
            )
            if evidence_context:
                metadata["evidence_context"] = evidence_context
            candidates.append(
                EvidenceCandidate(
                    candidate_id=f"context-window:{row.id}",
                    text=row.text,
                    document_id=row.document_id,
                    chunk_id=row.id,
                    source_location=(
                        row.source_location if isinstance(row.source_location, dict) else {}
                    ),
                    metadata=metadata,
                    tool="metadata",
                    tool_rank=len(candidates) + 1,
                    base_score=8.0,
                    boost_score=1.0,
                    final_score=9.0,
                    reasons=["context_window"],
                    retrieval_pass="context_window",
                    scope_status="in_scope",
                )
            )
            if len(candidates) >= max(limit, 1):
                break
        return candidates


def _reading_order(metadata: dict[str, Any]) -> int | None:
    value = metadata.get("reading_order") or metadata.get("block_index")
    return value if isinstance(value, int) else None


def _is_adjacent(
    document_id: str,
    order: int,
    seed_orders: set[tuple[str | None, int | None]],
) -> bool:
    return any(
        document_id == seed_document_id and seed_order is not None and abs(order - seed_order) == 1
        for seed_document_id, seed_order in seed_orders
    )
```

- [ ] **Step 4: Wire context windows into retrieval orchestration**

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, add the import:

```python
from ragstudio.services.context_window_service import ContextWindowService
```

After layout neighbor retrieval and `traces.extend(layout_neighbor_traces)`, add:

```python
        context_neighbors, context_neighbor_traces = await self._safe_context_neighbors(
            [*metadata_candidates, *vector_candidates, *layout_neighbors],
            document_ids=document_ids,
            limit=max(limit, 1),
            timings=timings,
        )
        traces.extend(context_neighbor_traces)
```

In the `primary_retrieval` candidate count, add `+ len(context_neighbors)`.

In the `primary_retrieval` detail payloads, add:

```python
                "context_neighbor_candidates": len(context_neighbors),
```

In the first `fuse_candidates()` call, add `*context_neighbors` to the candidate list.

Before final fusion, add:

```python
            context_neighbor_ranked = (
                fuse_candidates(plan, context_neighbors) if context_neighbors else []
            )
```

In `self.retrieval_fusion.fuse([...])`, add `context_neighbor_ranked` as the last ranked list.

Add this method after `_safe_layout_neighbors()`:

```python
    async def _safe_context_neighbors(
        self,
        seeds: list[EvidenceCandidate],
        *,
        document_ids: list[str],
        limit: int,
        timings: dict[str, Any],
    ) -> tuple[list[EvidenceCandidate], list[dict[str, Any]]]:
        started = perf_counter()
        if not seeds or not hasattr(self.chunk_service, "session"):
            timings["context_window_ms"] = _elapsed_ms(started)
            return [], [
                _lane_result_trace(
                    lane="context_window",
                    status="skipped",
                    reason="no_seed_chunks_or_session",
                    candidates=[],
                    latency_ms=timings["context_window_ms"],
                )
            ]
        try:
            candidates = await ContextWindowService(
                self.chunk_service.session
            ).window_for(
                seeds,
                document_ids=document_ids,
                limit=limit,
            )
        except Exception as exc:
            timings["context_window_ms"] = _elapsed_ms(started)
            return [], [
                _lane_result_trace(
                    lane="context_window",
                    status="failed",
                    reason=exc.__class__.__name__,
                    candidates=[],
                    latency_ms=timings["context_window_ms"],
                    error_type=exc.__class__.__name__,
                )
            ]
        timings["context_window_ms"] = _elapsed_ms(started)
        return candidates, [
            _lane_result_trace(
                lane="context_window",
                status="ran" if candidates else "skipped",
                reason=(
                    "adjacent_context_window"
                    if candidates
                    else "no_adjacent_context_window"
                ),
                candidates=candidates,
                latency_ms=timings["context_window_ms"],
            )
        ]
```

- [ ] **Step 5: Verify context windows**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run pytest backend/tests/test_context_window_service.py backend/tests/test_retrieval_orchestrator.py -q
uv run ruff check backend/src/ragstudio/services/context_window_service.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_context_window_service.py
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```powershell
git add backend/src/ragstudio/services/context_window_service.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_context_window_service.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: add context-window retrieval expansion"
```

---

### Task 6: Preserve Native Runtime Bridge Layout Metadata

**Files:**
- Modify: `backend/src/ragstudio/services/native_raganything_adapter.py`
- Test: `backend/tests/test_native_raganything_adapter.py`

- [ ] **Step 1: Add failing bridge metadata test**

Append to `backend/tests/test_native_raganything_adapter.py`:

```python
def test_preparsed_content_list_preserves_layout_bridge_fields():
    adapter = NativeRAGAnythingAdapter(settings=FakeSettings())
    chunk = AdapterChunk(
        id="chunk-layout",
        text="Figure caption text.",
        document_id="doc-layout",
        content_type="figure",
        source_location={"page": 4, "bbox": [10, 20, 200, 80]},
        metadata={
            "quality_action_policy": {"index_vector": True, "project_graph": True},
            "layout_group_id": "figure-1",
            "layout_role": "caption",
            "reading_order": 7,
            "provenance": {"blocks": [{"block_type": "caption", "role": "figure"}]},
        },
    )

    content_list = adapter._content_list_from_preparsed_chunks(
        [chunk],
        document_id="doc-layout",
    )

    metadata = content_list[0]["metadata"]
    assert metadata["layout_group_id"] == "figure-1"
    assert metadata["layout_role"] == "caption"
    assert metadata["reading_order"] == 7
    assert metadata["quality_action_policy"]["index_vector"] is True
    assert metadata["evidence_context"]["layout_summary"] == (
        "figure; page=4; block=caption; role=figure"
    )
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run pytest backend/tests/test_native_raganything_adapter.py::test_preparsed_content_list_preserves_layout_bridge_fields -q
```

Expected: fail because layout bridge fields are not copied into content-list metadata.

- [ ] **Step 3: Add bridge metadata fields**

In `_content_list_from_preparsed_chunks()` in `backend/src/ragstudio/services/native_raganything_adapter.py`, add these keys to the metadata allow-list:

```python
                        "layout_group_id",
                        "layout_role",
                        "reading_order",
                        "block_index",
                        "parent_chunk_id",
                        "previous_chunk_id",
                        "next_chunk_id",
```

- [ ] **Step 4: Verify native bridge metadata**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run pytest backend/tests/test_native_raganything_adapter.py -q
uv run ruff check backend/src/ragstudio/services/native_raganything_adapter.py backend/tests/test_native_raganything_adapter.py
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add backend/src/ragstudio/services/native_raganything_adapter.py backend/tests/test_native_raganything_adapter.py
git commit -m "feat: preserve native bridge layout metadata"
```

---

### Task 7: Upgrade Static Proof Evidence For The Retrieval Architecture Claim

**Files:**
- Modify: `docs/benchmarks/ragstudio-oss-proof-v1/fixtures/retrieval-traces.synthetic.json`
- Modify: `docs/benchmarks/ragstudio-oss-proof-v1/artifacts/retrieval-run.export.json`
- Modify: `docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.registry.json`
- Modify: `docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.matrix.md`
- Modify: `docs/benchmarks/ragstudio-oss-proof-v1/docs/CLAIMS.md`
- Modify: `docs/benchmarks/ragstudio-oss-proof-v1/docs/LIMITATIONS.md`
- Modify: `docs/benchmarks/ragstudio-oss-proof-v1/manifest.json`

- [ ] **Step 1: Capture source commit for proof source references**

Run:

```powershell
$sourceCommit = git rev-parse HEAD
$sourceCommit
```

Expected: prints the latest implementation commit from Tasks 1-6.

- [ ] **Step 2: Add all-lane architecture traces to retrieval fixture**

Update `docs/benchmarks/ragstudio-oss-proof-v1/fixtures/retrieval-traces.synthetic.json` so it contains these trace objects inside the existing trace array:

```json
{
  "stage": "retrieval_route_plan",
  "domain_profile_id": "reference_heavy",
  "source_of_truth": "postgres_canonical_evidence",
  "direct_evidence_required": true,
  "graph_context_required": true
}
```

```json
{
  "stage": "retrieval_lane_result",
  "lane": "metadata",
  "status": "ran",
  "reason": "metadata_lane_completed",
  "candidate_count": 1,
  "candidate_ids": ["metadata:synthetic-chunk-001"],
  "canonical_chunk_ids": ["synthetic-chunk-001"],
  "document_ids": ["synthetic-doc-001"],
  "latency_ms": 2.1,
  "timed_out": false,
  "partial": false
}
```

```json
{
  "stage": "retrieval_lane_result",
  "lane": "vector",
  "status": "ran",
  "reason": "retrieval_quality_baseline_gate_passed",
  "candidate_count": 1,
  "candidate_ids": ["vector:synthetic-chunk-001"],
  "canonical_chunk_ids": ["synthetic-chunk-001"],
  "document_ids": ["synthetic-doc-001"],
  "latency_ms": 1.9,
  "timed_out": false,
  "partial": false
}
```

```json
{
  "stage": "retrieval_lane_result",
  "lane": "graph",
  "status": "ran",
  "reason": "graph_expansion_completed",
  "candidate_count": 1,
  "candidate_ids": ["graph:synthetic-chunk-001"],
  "canonical_chunk_ids": ["synthetic-chunk-001"],
  "document_ids": ["synthetic-doc-001"],
  "latency_ms": 3.2,
  "timed_out": false,
  "partial": false
}
```

```json
{
  "stage": "retrieval_lane_result",
  "lane": "raganything_runtime",
  "status": "degraded",
  "reason": "canonical_bridge_ready",
  "candidate_count": 1,
  "candidate_ids": ["native:synthetic-chunk-001"],
  "canonical_chunk_ids": ["synthetic-chunk-001"],
  "document_ids": ["synthetic-doc-001"],
  "latency_ms": 4.0,
  "timed_out": false,
  "partial": true,
  "warning_flags": ["secondary_runtime_lane"]
}
```

```json
{
  "stage": "context_assembly",
  "included_candidates": 1,
  "dropped_candidates": 0,
  "assembled_context": {
    "evidence_ids": ["metadata:synthetic-chunk-001"],
    "grounding_status": "grounded",
    "breadcrumbs_visible": true,
    "layout_summary_visible": true
  }
}
```

- [ ] **Step 3: Add architecture evidence to retrieval-run artifact**

In `docs/benchmarks/ragstudio-oss-proof-v1/artifacts/retrieval-run.export.json`, add a top-level `architecture_trace` field with the same trace objects from Step 2.

- [ ] **Step 4: Upgrade the claim registry**

In `docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.registry.json`, update:

```json
"claim_counts": {
  "proven": 3,
  "roadmap": 1,
  "disabled": 1,
  "total": 5
}
```

For claim `RAGSTUDIO-RETRIEVAL-ARCHITECTURE`, set:

```json
"status": "proven",
"evidence": [
  {
    "artifact_path": "artifacts/retrieval-run.export.json",
    "evidence_type": "retrieval_trace",
    "redaction_status": "passed",
    "summary": "Public retrieval-run artifact carries canonical identity, quality policy, layout provenance, lane decisions, and context breadcrumbs across metadata, vector, graph, runtime, reranker, and context assembly traces."
  }
],
"limitations": [
  "The proof uses deterministic synthetic fixtures and does not claim production corpus retrieval quality."
],
"missing_evidence": [],
"planned_proof_path": []
```

Set that claim's `source.source_commit` to `$sourceCommit` from Step 1.

- [ ] **Step 5: Update manifest claim counts and artifact hash**

Run this PowerShell command:

```powershell
@'
import hashlib
import json
from pathlib import Path

root = Path("docs/benchmarks/ragstudio-oss-proof-v1")
manifest_path = root / "manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
manifest["claim_counts"] = {
    "proven": 3,
    "roadmap": 1,
    "disabled": 1,
    "total": 5,
}
for artifact_path, recorded in manifest["artifact_hashes"].items():
    digest = hashlib.sha256((root / artifact_path).read_bytes()).hexdigest()
    recorded["value"] = digest
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
'@ | python -
```

- [ ] **Step 6: Update human-readable claim docs**

In `docs/benchmarks/ragstudio-oss-proof-v1/docs/CLAIMS.md`, replace the `RAGSTUDIO-RETRIEVAL-ARCHITECTURE` roadmap paragraph with:

```markdown
`RAGSTUDIO-RETRIEVAL-ARCHITECTURE` is proven by:

- `artifacts/retrieval-run.export.json`
- `fixtures/retrieval-traces.synthetic.json`

It demonstrates canonical identity, quality policy, layout provenance, lane
decisions, reranker state, and context breadcrumbs across the public synthetic
retrieval trace.
```

In `docs/benchmarks/ragstudio-oss-proof-v1/docs/LIMITATIONS.md`, keep this limitation under `Retrieval Architecture Limitations`:

```markdown
- Retrieval architecture proof uses deterministic synthetic fixtures. It proves
  trace shape and public-safe propagation of architecture metadata, not production
  retrieval quality over a customer corpus.
```

Update `docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.matrix.md` so the row for `RAGSTUDIO-RETRIEVAL-ARCHITECTURE` has status `proven` and points to `artifacts/retrieval-run.export.json`.

- [ ] **Step 7: Validate proof packet**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run python -m ragstudio.proof_packet.cli --packet docs/benchmarks/ragstudio-oss-proof-v1 --strict --json
```

Expected: JSON includes `"status":"passed"` and `"errors":[]`.

- [ ] **Step 8: Commit**

Run:

```powershell
git add docs/benchmarks/ragstudio-oss-proof-v1
git commit -m "docs: prove retrieval architecture trace propagation"
```

---

### Task 8: Final Compliance Gate

**Files:**
- Modify only files required by failing validation output.

- [ ] **Step 1: Run focused architecture tests**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run pytest backend/tests/test_domain_classifier.py backend/tests/test_domain_query_expansion_service.py backend/tests/test_domain_profile_registry.py backend/tests/test_retrieval_route_input.py backend/tests/test_retrieval_route_planner.py backend/tests/test_layout_neighbor_service.py backend/tests/test_context_window_service.py backend/tests/test_context_assembly_service.py backend/tests/test_retrieval_orchestrator.py backend/tests/test_vector_retrieval_service.py backend/tests/test_vector_candidate_repository.py backend/tests/test_native_raganything_adapter.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run lint**

Run:

```powershell
uv run ruff check backend/src/ragstudio backend/tests
```

Expected: Ruff reports no errors.

- [ ] **Step 3: Run strict proof validation**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'
uv run python -m ragstudio.proof_packet.cli --packet docs/benchmarks/ragstudio-oss-proof-v1 --strict --json
```

Expected: JSON includes `"status":"passed"` and `"warnings":[]`.

- [ ] **Step 4: Record final architecture status**

Append this section to `docs/architecture/query-retrieval-architecture.md`:

```markdown
## Implementation Compliance Status

Ragstudio's retrieval architecture is implemented against the three-pillar
contract:

- Domain-aware ingestion and retrieval is implemented through domain
  classification, executable profiles, domain lexical adapters, route input,
  quality policy, materialization policy, and public lane traces.
- Layout-aware ingestion and retrieval is implemented through canonical source
  location, provenance, layout group expansion, bbox proximity, native bridge
  metadata, and context-visible layout summaries.
- Context-aware ingestion and retrieval is implemented through evidence context,
  adjacent context-window expansion, graph-seeded canonical hydration, context
  assembly, direct-evidence preservation, and dropped/truncated evidence reasons.

The public proof packet validates this with deterministic synthetic fixtures.
Production retrieval quality over customer corpora remains measured by separate
retrieval quality baselines.
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add docs/architecture/query-retrieval-architecture.md
git commit -m "docs: record three-pillar architecture compliance"
```

---

## Self-Review

Spec coverage:

- Domain-aware completion is covered by Tasks 2 and 3.
- Layout-aware completion is covered by Tasks 4 and 6.
- Context-aware completion is covered by Tasks 1 and 5.
- Planner/lane trace authority is preserved through existing `RetrievalLaneResult` usage and verified in Tasks 5, 7, and 8.
- Public proof upgrade is covered by Task 7.

Placeholder scan:

- No task asks for undefined "appropriate" behavior.
- Existing modules are extended instead of duplicated.
- Every task contains exact files, code snippets, commands, expected results, and commit messages.

Execution readiness risks:

- `backend/tests/test_native_raganything_adapter.py` may use local fake helper names that differ from the snippets. If helper names differ, adapt only the test setup objects, not the asserted behavior.
- Proof JSON edits must preserve valid JSON shape. Run the proof validator before committing Task 7.
