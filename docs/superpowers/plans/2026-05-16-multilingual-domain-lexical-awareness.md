# Multilingual Domain Lexical Awareness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Ragstudio's existing domain-aware chunking and retrieval so Latin transliteration queries such as `hanan` can retrieve exact multilingual lexical evidence such as `وحنانا`, while preserving generic support for future languages.

**Architecture:** Keep the current domain metadata, reference semantics, Arabic token storage, and hybrid retrieval layers. Add a small query-time multilingual lexical awareness layer that reads selected-document domain hints, generates structured lexical expansions, injects exact lexical retrieval passes before semantic/vector search, and traces the expansion through the run evidence.

**Tech Stack:** Python 3.12, FastAPI service layer, SQLAlchemy async repositories, existing `DomainMetadata`, existing `QueryUnderstanding`, existing `ChunkService.search()`, pytest, Ruff.

---

## Existing Code To Reuse

- `backend/src/ragstudio/services/domain_metadata_service.py` already defines reusable domain profiles, including `quran_tafseer`, `hadith`, `policy`, `research`, and `fiqh`.
- `backend/src/ragstudio/services/domain_metadata_ai_suggester.py` already performs AI-assisted ingestion-time domain metadata suggestion.
- `backend/src/ragstudio/services/reference_metadata.py` already turns `DomainMetadata.custom_json` into `ReferenceSemantics`.
- `backend/src/ragstudio/services/arabic_text.py` already normalizes Arabic and generates Arabic query variants.
- `backend/src/ragstudio/services/query_understanding.py` already creates retrieval passes.
- `backend/src/ragstudio/services/metadata_retrieval_service.py` already executes exact metadata passes before semantic metadata passes.
- `backend/src/ragstudio/services/hybrid_chunk_search.py` already scores Arabic exact-token matches using `tokens_ar`.

## Files

- Create: `backend/src/ragstudio/services/lexical_language_adapters.py`
  - Own language/script-specific normalization and transliteration expansion.
- Create: `backend/src/ragstudio/services/domain_query_expansion_service.py`
  - Own query-time domain/language expansion orchestration.
- Modify: `backend/src/ragstudio/services/query_understanding.py`
  - Add lexical expansion fields and `lexical_expanded_token` retrieval passes.
- Modify: `backend/src/ragstudio/services/metadata_retrieval_service.py`
  - Allow `lexical_expanded_token` and trace expanded query metadata.
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`
  - Boost exact lexical expansion hits and expose reasons.
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
  - Load selected-document domain hints before planning and pass them into query understanding.
- Test: `backend/tests/test_domain_query_expansion_service.py`
- Test: `backend/tests/test_query_understanding.py`
- Test: `backend/tests/test_metadata_retrieval_service.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

---

### Task 1: Add Language Adapter Interface And Arabic Adapter

**Files:**
- Create: `backend/src/ragstudio/services/lexical_language_adapters.py`
- Test: `backend/tests/test_domain_query_expansion_service.py`

- [ ] **Step 1: Write failing adapter tests**

Create `backend/tests/test_domain_query_expansion_service.py` with:

```python
from ragstudio.services.lexical_language_adapters import (
    ArabicLexicalAdapter,
    GenericLatinAdapter,
)


def test_arabic_adapter_preserves_existing_arabic_variants():
    adapter = ArabicLexicalAdapter()

    expansion = adapter.expand_query("وحنانا")

    assert expansion.language == "arabic"
    assert expansion.script == "arab"
    assert expansion.normalized_query == "وحنانا"
    assert expansion.terms == ["وحنانا", "حنانا"]
    assert expansion.match_type == "exact_script"
    assert expansion.confidence == 1.0


def test_arabic_adapter_expands_known_latin_transliteration():
    adapter = ArabicLexicalAdapter()

    expansion = adapter.expand_query("hanan")

    assert expansion.language == "arabic"
    assert expansion.script == "arab"
    assert expansion.normalized_query == "hanan"
    assert expansion.terms == ["حنان", "حنانا", "وحنانا"]
    assert expansion.match_type == "transliteration"
    assert expansion.confidence >= 0.9


def test_generic_latin_adapter_does_not_invent_cross_script_terms():
    adapter = GenericLatinAdapter()

    expansion = adapter.expand_query("climate resilience")

    assert expansion.language == "unknown"
    assert expansion.script == "latin"
    assert expansion.normalized_query == "climate resilience"
    assert expansion.terms == ["climate resilience"]
    assert expansion.match_type == "normalized_text"
    assert expansion.confidence == 0.5
```

- [ ] **Step 2: Run adapter tests and verify failure**

Run:

```bash
PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest backend/tests/test_domain_query_expansion_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.lexical_language_adapters'`.

- [ ] **Step 3: Implement adapters**

Create `backend/src/ragstudio/services/lexical_language_adapters.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from ragstudio.services.arabic_text import arabic_query_variants, normalize_arabic_text

_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
_LATIN_RE = re.compile(r"[A-Za-z]")

_ARABIC_TRANSLITERATION_LEXICON: dict[str, list[str]] = {
    "hanan": ["حنان", "حنانا", "وحنانا"],
    "hananan": ["حنانا", "وحنانا"],
    "hanana": ["حنانا", "وحنانا"],
}


@dataclass(frozen=True)
class LexicalExpansion:
    original_query: str
    normalized_query: str
    language: str
    script: str
    terms: list[str]
    match_type: str
    confidence: float
    source: str
    trace: dict[str, object] = field(default_factory=dict)


class LexicalLanguageAdapter(Protocol):
    language: str
    scripts: tuple[str, ...]

    def supports_query(self, query: str) -> bool:
        ...

    def expand_query(self, query: str) -> LexicalExpansion:
        ...


class ArabicLexicalAdapter:
    language = "arabic"
    scripts = ("arab",)

    def supports_query(self, query: str) -> bool:
        normalized = query.strip().casefold()
        return bool(_ARABIC_RE.search(query)) or normalized in _ARABIC_TRANSLITERATION_LEXICON

    def expand_query(self, query: str) -> LexicalExpansion:
        stripped = query.strip()
        if _ARABIC_RE.search(stripped):
            terms = arabic_query_variants(stripped)
            return LexicalExpansion(
                original_query=query,
                normalized_query=normalize_arabic_text(stripped),
                language=self.language,
                script="arab",
                terms=terms,
                match_type="exact_script",
                confidence=1.0,
                source="arabic_adapter",
                trace={"adapter": "arabic", "input_script": "arab"},
            )

        normalized = stripped.casefold()
        terms = _ARABIC_TRANSLITERATION_LEXICON.get(normalized, [])
        return LexicalExpansion(
            original_query=query,
            normalized_query=normalized,
            language=self.language,
            script="arab",
            terms=terms,
            match_type="transliteration",
            confidence=0.95 if terms else 0.0,
            source="arabic_transliteration_lexicon",
            trace={
                "adapter": "arabic",
                "input_script": "latin",
                "lexicon_hit": bool(terms),
            },
        )


class GenericLatinAdapter:
    language = "unknown"
    scripts = ("latin",)

    def supports_query(self, query: str) -> bool:
        return bool(_LATIN_RE.search(query))

    def expand_query(self, query: str) -> LexicalExpansion:
        normalized = " ".join(query.strip().casefold().split())
        terms = [normalized] if normalized else []
        return LexicalExpansion(
            original_query=query,
            normalized_query=normalized,
            language=self.language,
            script="latin",
            terms=terms,
            match_type="normalized_text",
            confidence=0.5 if terms else 0.0,
            source="generic_latin_adapter",
            trace={"adapter": "generic_latin", "input_script": "latin"},
        )
```

- [ ] **Step 4: Run adapter tests and verify pass**

Run:

```bash
PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest backend/tests/test_domain_query_expansion_service.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/lexical_language_adapters.py backend/tests/test_domain_query_expansion_service.py
git commit -m "feat: add lexical language adapters"
```

---

### Task 2: Add Domain Query Expansion Service

**Files:**
- Create: `backend/src/ragstudio/services/domain_query_expansion_service.py`
- Modify: `backend/tests/test_domain_query_expansion_service.py`

- [ ] **Step 1: Add failing service tests**

Append to `backend/tests/test_domain_query_expansion_service.py`:

```python
from ragstudio.services.domain_query_expansion_service import DomainQueryExpansionService


def quran_domain_metadata() -> dict[str, object]:
    return {
        "domain": "quran_tafseer",
        "document_type": "commentary",
        "language": "mixed",
        "tags": ["quran", "tafseer", "arabic"],
        "script": "mixed",
    }


def research_domain_metadata() -> dict[str, object]:
    return {
        "domain": "research",
        "document_type": "paper",
        "language": "english",
        "tags": ["research", "paper"],
    }


def test_domain_query_expansion_prefers_arabic_for_quran_transliteration():
    service = DomainQueryExpansionService()

    result = service.expand("hanan", domain_metadata=[quran_domain_metadata()])

    assert result.original_query == "hanan"
    assert result.domain_family == "arabic_religious"
    assert result.expansions[0].terms == ["حنان", "حنانا", "وحنانا"]
    assert result.retrieval_passes[0].name == "lexical_expanded_token"
    assert result.retrieval_passes[0].query == "حنان"
    assert result.retrieval_passes[0].direct_evidence is True
    assert result.trace["expanded_terms"] == ["حنان", "حنانا", "وحنانا"]


def test_domain_query_expansion_does_not_cross_script_expand_research_text():
    service = DomainQueryExpansionService()

    result = service.expand("hanan", domain_metadata=[research_domain_metadata()])

    assert result.domain_family == "generic"
    assert result.expansions == []
    assert result.retrieval_passes == []
    assert result.trace["expanded_terms"] == []
```

- [ ] **Step 2: Run service tests and verify failure**

Run:

```bash
PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest backend/tests/test_domain_query_expansion_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.domain_query_expansion_service'`.

- [ ] **Step 3: Implement service**

Create `backend/src/ragstudio/services/domain_query_expansion_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ragstudio.services.lexical_language_adapters import (
    ArabicLexicalAdapter,
    LexicalExpansion,
)
from ragstudio.services.query_understanding import RetrievalPass


@dataclass(frozen=True)
class DomainQueryExpansion:
    original_query: str
    domain_family: str
    expansions: list[LexicalExpansion] = field(default_factory=list)
    retrieval_passes: list[RetrievalPass] = field(default_factory=list)
    trace: dict[str, object] = field(default_factory=dict)


class DomainQueryExpansionService:
    def __init__(self, arabic_adapter: ArabicLexicalAdapter | None = None):
        self.arabic_adapter = arabic_adapter or ArabicLexicalAdapter()

    def expand(
        self,
        query: str,
        *,
        domain_metadata: list[dict[str, Any]],
    ) -> DomainQueryExpansion:
        domain_family = _domain_family(domain_metadata)
        expansions: list[LexicalExpansion] = []
        retrieval_passes: list[RetrievalPass] = []

        if domain_family == "arabic_religious" and self.arabic_adapter.supports_query(query):
            expansion = self.arabic_adapter.expand_query(query)
            if expansion.terms and expansion.match_type in {"exact_script", "transliteration"}:
                expansions.append(expansion)
                retrieval_passes.extend(
                    RetrievalPass(
                        "lexical_expanded_token",
                        term,
                        direct_evidence=True,
                    )
                    for term in expansion.terms
                )

        expanded_terms = [
            term
            for expansion in expansions
            for term in expansion.terms
        ]
        return DomainQueryExpansion(
            original_query=query,
            domain_family=domain_family,
            expansions=expansions,
            retrieval_passes=retrieval_passes,
            trace={
                "stage": "domain_query_expansion",
                "original_query": query,
                "domain_family": domain_family,
                "expanded_terms": expanded_terms,
                "expansions": [
                    {
                        "language": expansion.language,
                        "script": expansion.script,
                        "match_type": expansion.match_type,
                        "confidence": expansion.confidence,
                        "source": expansion.source,
                        "terms": expansion.terms,
                    }
                    for expansion in expansions
                ],
            },
        )


def _domain_family(domain_metadata: list[dict[str, Any]]) -> str:
    tokens: set[str] = set()
    for metadata in domain_metadata:
        if not isinstance(metadata, dict):
            continue
        raw_tags = metadata.get("tags")
        tags = raw_tags if isinstance(raw_tags, list) else []
        tokens.update(
            str(value).casefold()
            for value in [
                metadata.get("domain"),
                metadata.get("document_type"),
                metadata.get("language"),
                metadata.get("script"),
                metadata.get("content_role"),
                *tags,
            ]
            if value
        )

    if tokens & {
        "arabic",
        "mixed",
        "quran",
        "tafseer",
        "quran_tafseer",
        "hadith",
        "islamic_text",
        "religious_text",
    }:
        return "arabic_religious"
    return "generic"
```

- [ ] **Step 4: Run service tests and verify pass**

Run:

```bash
PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest backend/tests/test_domain_query_expansion_service.py -q
```

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/domain_query_expansion_service.py backend/tests/test_domain_query_expansion_service.py
git commit -m "feat: add domain query expansion service"
```

---

### Task 3: Extend Query Understanding With Lexical Expansions

**Files:**
- Modify: `backend/src/ragstudio/services/query_understanding.py`
- Modify: `backend/tests/test_query_understanding.py`

- [ ] **Step 1: Add failing query-understanding tests**

Append to `backend/tests/test_query_understanding.py`:

```python
from ragstudio.services.domain_query_expansion_service import DomainQueryExpansionService
from ragstudio.services.query_understanding import understand_query


def test_understand_query_accepts_domain_expansion_passes():
    expansion = DomainQueryExpansionService().expand(
        "hanan",
        domain_metadata=[
            {
                "domain": "quran_tafseer",
                "document_type": "commentary",
                "language": "mixed",
                "tags": ["quran", "arabic"],
            }
        ],
    )

    understanding = understand_query("hanan", domain_expansion=expansion)

    assert understanding.intent == "lexical_expanded_token"
    assert understanding.answer_type == "reference"
    assert understanding.retrieval_strategy == "reference_first_hybrid"
    assert understanding.direct_evidence_required is True
    assert understanding.expanded_terms == ["حنان", "حنانا", "وحنانا"]
    assert [item.name for item in understanding.retrieval_passes[:3]] == [
        "lexical_expanded_token",
        "lexical_expanded_token",
        "lexical_expanded_token",
    ]
    assert understanding.retrieval_passes[0].query == "حنان"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest backend/tests/test_query_understanding.py::test_understand_query_accepts_domain_expansion_passes -q
```

Expected: FAIL because `understand_query()` does not accept `domain_expansion`.

- [ ] **Step 3: Modify query understanding**

In `backend/src/ragstudio/services/query_understanding.py`, make these changes:

```python
from typing import Any, Literal
```

Update `QueryUnderstandingIntent`:

```python
QueryUnderstandingIntent = Literal[
    "arabic_exact_token",
    "lexical_expanded_token",
    "reference",
    "phrase_lookup",
    "count",
    "summary",
    "semantic",
]
```

Add fields to `QueryUnderstanding`:

```python
    expanded_terms: list[str] = field(default_factory=list)
    expansion_trace: dict[str, Any] = field(default_factory=dict)
```

Change the function signature and add the expansion branch at the top after graph detection:

```python
def understand_query(query: str, *, domain_expansion: Any | None = None) -> QueryUnderstanding:
    normalized = query.casefold()
    reference_hints = _reference_hints(query)
    graph_context_required = _needs_graph_context(query)
    expansion_passes = list(getattr(domain_expansion, "retrieval_passes", []) or [])
    if expansion_passes:
        expanded_terms = [
            item.query
            for item in expansion_passes
            if getattr(item, "query", "")
        ]
        return QueryUnderstanding(
            query=query,
            intent="lexical_expanded_token",
            answer_type="reference",
            retrieval_strategy=(
                "graph_context_hybrid" if graph_context_required else "reference_first_hybrid"
            ),
            graph_context_required=graph_context_required,
            required_terms=expanded_terms,
            expanded_terms=expanded_terms,
            retrieval_passes=[*expansion_passes, *_semantic_passes(query)],
            direct_evidence_required=True,
            expansion_trace=dict(getattr(domain_expansion, "trace", {}) or {}),
        )
```

- [ ] **Step 4: Run query-understanding tests**

Run:

```bash
PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest backend/tests/test_query_understanding.py -q
```

Expected: all tests pass, including the new expansion test.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/query_understanding.py backend/tests/test_query_understanding.py
git commit -m "feat: add lexical expansion query understanding"
```

---

### Task 4: Execute Expanded Lexical Passes In Metadata Retrieval

**Files:**
- Modify: `backend/src/ragstudio/services/metadata_retrieval_service.py`
- Modify: `backend/tests/test_metadata_retrieval_service.py`

- [ ] **Step 1: Add failing metadata retrieval test**

Append to `backend/tests/test_metadata_retrieval_service.py`:

```python
class TransliterationChunkService:
    def __init__(self):
        self.calls = []

    async def search(self, search_in):
        self.calls.append(search_in)
        if search_in.query == "وحنانا":
            return type(
                "SearchResult",
                (),
                {
                    "items": [
                        ChunkOut(
                            id="chunk-19-13",
                            document_id="doc-quran",
                            text="[19:13] وحنانا من لدنا وزكوة وكان تقيا",
                            source_location={"reference": "19:13"},
                            metadata={
                                "score": 157.0,
                                "score_breakdown": {
                                    "arabic_exact": 40.0,
                                    "arabic_token": 24.0,
                                },
                                "reference_metadata": {"references": ["19:13"]},
                                "tokens_ar": ["وحنانا", "حنانا"],
                            },
                        )
                    ],
                    "total": 1,
                },
            )()
        return type("SearchResult", (), {"items": [], "total": 0})()


@pytest.mark.asyncio
async def test_metadata_service_runs_lexical_expanded_token_passes():
    expansion = DomainQueryExpansionService().expand(
        "hanan",
        domain_metadata=[
            {
                "domain": "quran_tafseer",
                "language": "mixed",
                "tags": ["quran", "arabic"],
            }
        ],
    )
    understanding = understand_query("hanan", domain_expansion=expansion)
    chunk_service = TransliterationChunkService()

    candidates, trace = await MetadataRetrievalService(chunk_service).retrieve(
        "hanan",
        understanding=understanding,
        document_ids=["doc-quran"],
        variant_id="variant-1",
        limit=5,
    )

    assert [call.query for call in chunk_service.calls][:3] == ["حنان", "حنانا", "وحنانا"]
    assert len(candidates) == 1
    assert candidates[0].chunk_id == "chunk-19-13"
    assert candidates[0].retrieval_pass == "lexical_expanded_token"
    assert candidates[0].match_features == {
        "lexical_expanded": True,
        "expanded_token": "وحنانا",
        "match_type": "transliteration",
    }
    assert trace["passes"][2]["name"] == "lexical_expanded_token"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest backend/tests/test_metadata_retrieval_service.py::test_metadata_service_runs_lexical_expanded_token_passes -q
```

Expected: FAIL because `lexical_expanded_token` is not in `_METADATA_PASS_NAMES`.

- [ ] **Step 3: Implement metadata retrieval support**

In `backend/src/ragstudio/services/metadata_retrieval_service.py`, update `_METADATA_PASS_NAMES`:

```python
_METADATA_PASS_NAMES = {
    "reference_exact",
    "arabic_exact_token",
    "lexical_expanded_token",
    "phrase_exact",
    "title_count",
    "semantic_metadata",
}
```

Update `_match_features()`:

```python
        if effective_pass == "lexical_expanded_token":
            return {
                "lexical_expanded": True,
                "expanded_token": retrieval_pass.query,
                "match_type": "transliteration",
            }
```

Place this before the `phrase_exact` branch.

- [ ] **Step 4: Run metadata tests**

Run:

```bash
PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest backend/tests/test_metadata_retrieval_service.py -q
```

Expected: all metadata retrieval tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/metadata_retrieval_service.py backend/tests/test_metadata_retrieval_service.py
git commit -m "feat: run lexical expansion metadata passes"
```

---

### Task 5: Boost Expanded Lexical Evidence In Fusion

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Add failing fusion test**

Append near the fusion unit tests in `backend/tests/test_retrieval_orchestrator.py`:

```python
def test_fusion_boosts_lexical_expanded_token_above_semantic_match():
    expansion = DomainQueryExpansionService().expand(
        "hanan",
        domain_metadata=[
            {
                "domain": "quran_tafseer",
                "language": "mixed",
                "tags": ["quran", "arabic"],
            }
        ],
    )
    plan = plan_for_query(
        "hanan",
        document_ids=["doc-quran"],
        limit=5,
        domain_expansion=expansion,
    )
    semantic = EvidenceCandidate(
        candidate_id="metadata:semantic",
        text="A broad English discussion using the word hanan in unrelated notes.",
        document_id="doc-quran",
        chunk_id="chunk-semantic",
        source_location={},
        metadata={},
        tool="metadata",
        tool_rank=1,
        base_score=30.0,
        retrieval_pass="semantic_metadata",
    )
    exact = EvidenceCandidate(
        candidate_id="metadata:19-13",
        text="[19:13] وحنانا من لدنا وزكوة وكان تقيا",
        document_id="doc-quran",
        chunk_id="chunk-19-13",
        source_location={"reference": "19:13"},
        metadata={"domain_metadata": {"domain": "quran_tafseer"}},
        tool="metadata",
        tool_rank=2,
        base_score=20.0,
        retrieval_pass="lexical_expanded_token",
        match_features={
            "lexical_expanded": True,
            "expanded_token": "وحنانا",
            "match_type": "transliteration",
        },
    )

    fused = fuse_candidates(plan, [semantic, exact])

    assert fused[0].chunk_id == "chunk-19-13"
    assert "lexical_expanded_exact" in fused[0].reasons
```

Also update the imports in that test file:

```python
from ragstudio.services.domain_query_expansion_service import DomainQueryExpansionService
```

- [ ] **Step 2: Run fusion test and verify failure**

Run:

```bash
PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest backend/tests/test_retrieval_orchestrator.py::test_fusion_boosts_lexical_expanded_token_above_semantic_match -q
```

Expected: FAIL because `plan_for_query()` does not accept `domain_expansion` and fusion has no lexical boost.

- [ ] **Step 3: Update plan construction**

In `backend/src/ragstudio/services/retrieval_evidence.py`, update `plan_for_query()` signature:

```python
def plan_for_query(
    query: str,
    *,
    document_ids: list[str],
    limit: int,
    domain_expansion: Any | None = None,
) -> RetrievalPlan:
    understanding = understand_query(query, domain_expansion=domain_expansion)
```

- [ ] **Step 4: Add fusion boost**

In `_score_candidate()` in `backend/src/ragstudio/services/retrieval_evidence.py`, after the reference-first boost block, add:

```python
    if candidate.retrieval_pass == "lexical_expanded_token":
        boost += 28.0
        reasons.append("lexical_expanded_exact")
```

- [ ] **Step 5: Run fusion tests**

Run:

```bash
PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest backend/tests/test_retrieval_orchestrator.py::test_fusion_boosts_lexical_expanded_token_above_semantic_match -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/retrieval_evidence.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: boost lexical expansion evidence"
```

---

### Task 6: Wire Selected-Document Domain Metadata Into Orchestrator Planning

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Add failing orchestrator test**

Append to `backend/tests/test_retrieval_orchestrator.py`:

```python
class QuranDomainChunkSearchService(FakeChunkSearchService):
    async def domain_metadata_for_documents(self, document_ids):
        return [
            {
                "domain": "quran_tafseer",
                "document_type": "commentary",
                "language": "mixed",
                "tags": ["quran", "arabic"],
            }
            for _document_id in document_ids
        ]

    async def search(self, search_in):
        self.calls += 1
        if search_in.query == "وحنانا":
            return type(
                "SearchResult",
                (),
                {
                    "items": [
                        ChunkOut(
                            id="chunk-19-13",
                            document_id="doc-quran",
                            text="[19:13] وحنانا من لدنا وزكوة وكان تقيا",
                            source_location={"reference": "19:13"},
                            metadata={
                                "score": 157.0,
                                "score_breakdown": {
                                    "arabic_exact": 40.0,
                                    "arabic_token": 24.0,
                                },
                                "domain_metadata": {"domain": "quran_tafseer"},
                                "reference_metadata": {"references": ["19:13"]},
                            },
                        )
                    ],
                    "total": 1,
                },
            )()
        return type("SearchResult", (), {"items": [], "total": 0})()


@pytest.mark.asyncio
async def test_orchestrator_expands_latin_transliteration_for_domain_documents():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=QuranDomainChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "hanan",
        runtime=NativeSearchShouldNotRun(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-quran"],
        variant_id="variant-1",
        query_config={
            "limit": 5,
            "retrieval_mode": "metadata",
            "reference_query_mode": "lexical",
            "graph_expansion_enabled": False,
        },
    )

    retrieval_trace = next(trace for trace in result.chunk_traces if trace["stage"] == "retrieval")
    expansion_trace = next(
        trace for trace in result.chunk_traces if trace.get("stage") == "domain_query_expansion"
    )

    assert result.error is None
    assert result.sources[0]["chunk_id"] == "chunk-19-13"
    assert result.sources[0]["metadata"]["retrieval_pass"] == "lexical_expanded_token"
    assert result.sources[0]["metadata"]["match_features"]["expanded_token"] == "وحنانا"
    assert expansion_trace["expanded_terms"] == ["حنان", "حنانا", "وحنانا"]
    assert retrieval_trace["metadata_candidates"] == 1
```

- [ ] **Step 2: Run orchestrator test and verify failure**

Run:

```bash
PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest backend/tests/test_retrieval_orchestrator.py::test_orchestrator_expands_latin_transliteration_for_domain_documents -q
```

Expected: FAIL because the orchestrator does not load domain metadata or add an expansion trace.

- [ ] **Step 3: Add domain metadata lookup to orchestrator**

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, import:

```python
from ragstudio.services.domain_query_expansion_service import DomainQueryExpansionService
```

Add constructor parameter and field:

```python
        domain_query_expansion_service: DomainQueryExpansionService | None = None,
```

```python
        self.domain_query_expansion_service = (
            domain_query_expansion_service or DomainQueryExpansionService()
        )
```

Before `plan = plan_for_query(...)` inside `query()`, add:

```python
        domain_metadata = await self._domain_metadata_for_documents(document_ids)
        domain_expansion = self.domain_query_expansion_service.expand(
            query,
            domain_metadata=domain_metadata,
        )
```

Change plan creation:

```python
        plan = plan_for_query(
            query,
            document_ids=document_ids,
            limit=limit,
            domain_expansion=domain_expansion,
        )
```

After the planner trace is created, append the expansion trace only when there are expansions:

```python
        if domain_expansion.expansions:
            traces.append(domain_expansion.trace)
```

Add helper method:

```python
    async def _domain_metadata_for_documents(self, document_ids: list[str]) -> list[dict[str, Any]]:
        if not document_ids:
            return []
        lookup = getattr(self.chunk_service, "domain_metadata_for_documents", None)
        if not callable(lookup):
            return []
        try:
            values = await lookup(document_ids)
        except Exception:
            return []
        return [dict(item) for item in values if isinstance(item, dict)]
```

- [ ] **Step 4: Run orchestrator test**

Run:

```bash
PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest backend/tests/test_retrieval_orchestrator.py::test_orchestrator_expands_latin_transliteration_for_domain_documents -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: apply domain query expansion in orchestrator"
```

---

### Task 7: Add Real ChunkService Domain Metadata Lookup

**Files:**
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Test: `backend/tests/test_chunks.py`

- [ ] **Step 1: Add failing ChunkService test**

Append to `backend/tests/test_chunks.py`:

```python
@pytest.mark.asyncio
async def test_chunk_service_returns_domain_metadata_for_documents(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="quran.txt",
            content_type="text/plain",
            sha256="domain-metadata-doc",
            artifact_path=str(app.state.settings.data_dir / "quran.txt"),
            status="succeeded",
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="[19:13] وحنانا من لدنا",
                metadata_json={
                    "domain_metadata": {
                        "domain": "quran_tafseer",
                        "document_type": "commentary",
                        "language": "mixed",
                        "tags": ["quran", "arabic"],
                    }
                },
                source_location={"reference": "19:13"},
            )
        )
        await session.commit()

        service = ChunkService(session, app.state.settings.data_dir)
        values = await service.domain_metadata_for_documents([document.id])

    assert values == [
        {
            "domain": "quran_tafseer",
            "document_type": "commentary",
            "language": "mixed",
            "tags": ["quran", "arabic"],
        }
    ]
```

Ensure imports exist in `backend/tests/test_chunks.py`:

```python
from ragstudio.db.models import Chunk, Document
from ragstudio.services.chunk_service import ChunkService
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest backend/tests/test_chunks.py::test_chunk_service_returns_domain_metadata_for_documents -q
```

Expected: FAIL because `ChunkService.domain_metadata_for_documents()` does not exist.

- [ ] **Step 3: Implement lookup**

In `backend/src/ragstudio/services/chunk_service.py`, add:

```python
    async def domain_metadata_for_documents(self, document_ids: list[str]) -> list[dict[str, Any]]:
        if not document_ids:
            return []
        result = await self.session.execute(
            select(Chunk.metadata_json).where(Chunk.document_id.in_(document_ids))
        )
        by_document_family: list[dict[str, Any]] = []
        seen: set[str] = set()
        for metadata in result.scalars().all():
            if not isinstance(metadata, dict):
                continue
            domain_metadata = metadata.get("domain_metadata")
            if not isinstance(domain_metadata, dict):
                continue
            key = json.dumps(domain_metadata, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            by_document_family.append(dict(domain_metadata))
        return by_document_family
```

Add `import json` at the top if the file does not already import it.

- [ ] **Step 4: Run ChunkService test**

Run:

```bash
PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest backend/tests/test_chunks.py::test_chunk_service_returns_domain_metadata_for_documents -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/chunk_service.py backend/tests/test_chunks.py
git commit -m "feat: expose chunk domain metadata lookup"
```

---

### Task 8: Full Verification And Live Query Proof

**Files:**
- No new source files.
- Use current local Compose app and focused test suite.

- [ ] **Step 1: Run backend tests**

Run:

```bash
PYTHONPATH=$PWD/backend/src .venv/bin/python -m pytest \
  backend/tests/test_domain_query_expansion_service.py \
  backend/tests/test_query_understanding.py \
  backend/tests/test_metadata_retrieval_service.py \
  backend/tests/test_retrieval_orchestrator.py \
  backend/tests/test_chunks.py \
  backend/tests/test_runtime_query_service.py \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run Ruff**

Run:

```bash
PYTHONPATH=$PWD/backend/src .venv/bin/python -m ruff check \
  backend/src/ragstudio/services/lexical_language_adapters.py \
  backend/src/ragstudio/services/domain_query_expansion_service.py \
  backend/src/ragstudio/services/query_understanding.py \
  backend/src/ragstudio/services/metadata_retrieval_service.py \
  backend/src/ragstudio/services/retrieval_evidence.py \
  backend/src/ragstudio/services/retrieval_orchestrator.py \
  backend/src/ragstudio/services/chunk_service.py \
  backend/tests/test_domain_query_expansion_service.py \
  backend/tests/test_query_understanding.py \
  backend/tests/test_metadata_retrieval_service.py \
  backend/tests/test_retrieval_orchestrator.py \
  backend/tests/test_chunks.py
```

Expected: `All checks passed!`

- [ ] **Step 3: Restart backend for live proof**

Run:

```bash
docker compose -p ragstudio up -d --force-recreate backend
curl -sS http://127.0.0.1:8000/api/health
```

Expected:

```json
{"status":"ok","service":"rag-anything-studio"}
```

- [ ] **Step 4: Run live `hanan` query**

Use the current Quran document and fast lexical variant IDs from `/api/documents` and `/api/variants`.

Run:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/query \
  -H 'Content-Type: application/json' \
  --max-time 15 \
  -d '{
    "query": "hanan",
    "document_ids": ["357385ad-f6d1-4c81-af8a-a7385e20e3cc"],
    "variant_ids": ["0e09bb38-46d5-4226-846a-99f217195812"],
    "limit": 5,
    "response_mode": "fast",
    "answer_budget_ms": 1000,
    "response_budget_ms": 8000
  }' > /tmp/hanan-expanded-query.json

jq '{
  run_id: .runs[0].id,
  status: .runs[0].status,
  total_ms: .runs[0].timings.total_ms,
  first_chunk: .runs[0].sources[0].chunk_id,
  first_reference: .runs[0].sources[0].source_location.reference,
  first_pass: .runs[0].sources[0].metadata.retrieval_pass,
  match_features: .runs[0].sources[0].metadata.match_features,
  expansion_trace: [
    .runs[0].chunk_traces[]
    | select(.stage == "domain_query_expansion")
  ][0]
}' /tmp/hanan-expanded-query.json
```

Expected:

```json
{
  "status": "succeeded",
  "first_pass": "lexical_expanded_token",
  "match_features": {
    "lexical_expanded": true,
    "expanded_token": "وحنانا",
    "match_type": "transliteration"
  },
  "expansion_trace": {
    "stage": "domain_query_expansion",
    "original_query": "hanan",
    "expanded_terms": ["حنان", "حنانا", "وحنانا"]
  }
}
```

- [ ] **Step 5: Commit verification notes if docs changed**

If implementation updates this plan status or adds a review artifact:

```bash
git add docs/superpowers/plans/2026-05-16-multilingual-domain-lexical-awareness.md
git commit -m "docs: record multilingual lexical awareness verification"
```

If no docs changed, skip this commit.

---

## Self-Review

**Spec coverage:** This plan extends the existing domain layer instead of replacing it, supports the live `hanan → وحنانا` issue, keeps the design generic through language adapters, includes query-time expansion, evidence traceability, ranking, and live proof.

**Placeholder scan:** No task uses `TBD`, `TODO`, or vague "add tests" instructions. Each task contains exact files, code, commands, and expected results.

**Type consistency:** `LexicalExpansion`, `DomainQueryExpansion`, `RetrievalPass`, `expanded_terms`, `expansion_trace`, and `lexical_expanded_token` are introduced before later tasks consume them. The same retrieval pass name is used in query understanding, metadata retrieval, fusion, and tests.
