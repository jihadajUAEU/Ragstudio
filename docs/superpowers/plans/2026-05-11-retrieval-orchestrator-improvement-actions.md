# Retrieval Orchestrator Improvement Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a measurable, failure-aware retrieval orchestrator that separates metadata/lexical, vector DB, native RAG-Anything, and graph expansion retrieval lanes while preserving scoped fallback behavior and grounded answers.

**Architecture:** Keep `QueryService` as the API orchestration boundary and move retrieval-specific behavior into small services: planning, metrics, multi-pass metadata retrieval, vector/native readiness, fusion, context assembly, and grounding validation. The first retrieval phase produces primary candidates from metadata/lexical, vector DB, and scoped native lanes; seed fusion selects strong evidence for graph expansion; final fusion, reranking, context assembly, and validation produce the answer and trace.

**Tech Stack:** FastAPI service layer, SQLAlchemy async, Postgres/JSONB/PGVector, Neo4j, RAG-Anything/LightRAG adapter, pytest/pytest-asyncio, Playwright for UI smoke validation.

---

## Scope Check

The spec touches retrieval, answer validation, evaluation metrics, and UI smoke tests, but they are one runtime-query subsystem. This plan keeps ingestion/parser quality work out of scope except for regression checks that prove the retrieval path reports missing Arabic evidence clearly. Parser reindexing fixes belong to the existing parser-normalization plan.

## File Structure

- Create `backend/src/ragstudio/services/retrieval_metrics.py`
  - Owns Precision@K, Recall@K, MRR, NDCG, hit rate, and quality-gate threshold checks for candidate lists.
- Create `backend/src/ragstudio/services/query_understanding.py`
  - Owns deterministic query classification, Arabic token detection, exact-reference detection, and retrieval pass selection.
- Modify `backend/src/ragstudio/services/retrieval_evidence.py`
  - Extends `RetrievalPlan` and `EvidenceCandidate` with pass, match-feature, scope, index-shape, and risk metadata while keeping existing callers compatible.
- Create `backend/src/ragstudio/services/metadata_retrieval_service.py`
  - Runs bounded metadata/lexical retrieval passes and normalizes `ChunkOut` results into `EvidenceCandidate`.
- Modify `backend/src/ragstudio/services/native_raganything_adapter.py`
  - Adds explicit scoped vector/native preflight reporting and retrieval-only vector candidate support where LightRAG storage is available.
- Modify `backend/src/ragstudio/services/retrieval_fusion.py`
  - Accepts named ranked lists, applies deterministic RRF and direct-evidence boosts, and emits fusion reasons.
- Modify `backend/src/ragstudio/services/retrieval_orchestrator.py`
  - Replaces the current two-lane retrieval flow with the staged architecture: primary lanes, seed fusion, graph expansion, final fusion, rerank, context, answer, validation.
- Create `backend/src/ragstudio/services/grounding_validator.py`
  - Validates citations, exact-reference support, direct-evidence contradictions, and source/reference consistency.
- Modify `backend/src/ragstudio/services/runtime_answer_service.py`
  - Preserves source labels and retrieval reasons in the prompt, then returns validation metadata through the orchestrator.
- Modify `backend/src/ragstudio/services/retrieval_observability.py`
  - Records candidate counts, latency, cache policy, metrics, final evidence, and degradation status per run.
- Modify `backend/tests/test_retrieval_metrics.py`
  - New tests for metric formulas and thresholds.
- Modify `backend/tests/test_query_understanding.py`
  - New tests for deterministic query understanding and pass selection.
- Modify `backend/tests/test_retrieval_orchestrator.py`
  - Service-level tests for staged retrieval, degradation, graph hydration, and traces.
- Modify `backend/tests/test_native_raganything_adapter.py`
  - Tests for native/vector preflight and retrieval-only candidate path.
- Modify `backend/tests/test_rag_retrieval_fusion.py`
  - Tests for direct evidence outranking semantic and graph evidence.
- Modify `backend/tests/test_rag_evaluation_gates.py`
  - Tests for the known Quran/Bukhari regression gate rows.
- Create `e2e/arabic-hanana-query.spec.ts`
  - UI smoke test that runs `حنانا` against the Quran document and asserts trace behavior.

---

### Task 1: Retrieval Metrics And Quality Gates

**Files:**
- Create: `backend/src/ragstudio/services/retrieval_metrics.py`
- Create: `backend/tests/test_retrieval_metrics.py`
- Modify: `backend/tests/test_rag_evaluation_gates.py`

- [ ] **Step 1: Write the failing metrics tests**

Create `backend/tests/test_retrieval_metrics.py`:

```python
import pytest

from ragstudio.services.retrieval_evidence import EvidenceCandidate
from ragstudio.services.retrieval_metrics import (
    RetrievalQualityGate,
    assert_quality_gate,
    calculate_retrieval_metrics,
)


def candidate(chunk_id: str, refs: list[str], rank: int) -> EvidenceCandidate:
    return EvidenceCandidate(
        candidate_id=f"test:{chunk_id}",
        text=f"{chunk_id} text",
        document_id="doc-quran",
        chunk_id=chunk_id,
        source_location={"page": rank},
        metadata={"reference_metadata": {"references": refs}},
        tool="test",
        tool_rank=rank,
        base_score=1.0,
        final_score=1.0,
    )


def test_retrieval_metrics_calculate_precision_recall_mrr_ndcg_and_hit_rate():
    results = [
        candidate("chunk-1", ["19:12"], 1),
        candidate("chunk-2", ["19:13"], 2),
        candidate("chunk-3", ["19:14"], 3),
    ]

    metrics = calculate_retrieval_metrics(
        results,
        relevant_references={"19:13", "19:14"},
        k=3,
    )

    assert metrics.precision_at_k == pytest.approx(2 / 3)
    assert metrics.recall_at_k == pytest.approx(1.0)
    assert metrics.hit_rate == pytest.approx(1.0)
    assert metrics.mrr == pytest.approx(0.5)
    assert metrics.ndcg_at_k == pytest.approx(0.693426, rel=1e-4)


def test_quality_gate_reports_all_failed_thresholds():
    results = [candidate("chunk-1", ["19:12"], 1)]
    metrics = calculate_retrieval_metrics(
        results,
        relevant_references={"19:13"},
        k=5,
    )
    gate = RetrievalQualityGate(
        min_precision_at_k=0.75,
        min_recall_at_k=0.70,
        min_mrr=0.80,
        min_hit_rate=1.0,
    )

    report = assert_quality_gate(metrics, gate)

    assert report.passed is False
    assert report.failures == {
        "precision_at_k": {"actual": 0.0, "minimum": 0.75},
        "recall_at_k": {"actual": 0.0, "minimum": 0.70},
        "mrr": {"actual": 0.0, "minimum": 0.80},
        "hit_rate": {"actual": 0.0, "minimum": 1.0},
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_retrieval_metrics.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.retrieval_metrics'`.

- [ ] **Step 3: Implement retrieval metric helpers**

Create `backend/src/ragstudio/services/retrieval_metrics.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from math import log2

from ragstudio.services.retrieval_evidence import EvidenceCandidate


@dataclass(frozen=True)
class RetrievalMetrics:
    precision_at_k: float
    recall_at_k: float
    hit_rate: float
    mrr: float
    ndcg_at_k: float
    k: int
    relevant_found: int
    relevant_total: int


@dataclass(frozen=True)
class RetrievalQualityGate:
    min_precision_at_k: float = 0.75
    min_recall_at_k: float = 0.70
    min_mrr: float = 0.80
    min_hit_rate: float = 1.0


@dataclass(frozen=True)
class RetrievalQualityGateReport:
    passed: bool
    failures: dict[str, dict[str, float]]


def calculate_retrieval_metrics(
    candidates: list[EvidenceCandidate],
    *,
    relevant_references: set[str],
    k: int,
) -> RetrievalMetrics:
    top_k = candidates[: max(k, 0)]
    relevant_total = len(relevant_references)
    relevant_flags = [
        bool(candidate_references(candidate) & relevant_references)
        for candidate in top_k
    ]
    relevant_found = sum(1 for flag in relevant_flags if flag)
    precision = relevant_found / k if k > 0 else 0.0
    recall = relevant_found / relevant_total if relevant_total else 0.0
    hit_rate = 1.0 if relevant_found else 0.0
    mrr = _mrr(relevant_flags)
    ndcg = _ndcg(relevant_flags, min(k, relevant_total if relevant_total else k))
    return RetrievalMetrics(
        precision_at_k=round(precision, 6),
        recall_at_k=round(recall, 6),
        hit_rate=round(hit_rate, 6),
        mrr=round(mrr, 6),
        ndcg_at_k=round(ndcg, 6),
        k=k,
        relevant_found=relevant_found,
        relevant_total=relevant_total,
    )


def assert_quality_gate(
    metrics: RetrievalMetrics,
    gate: RetrievalQualityGate,
) -> RetrievalQualityGateReport:
    failures: dict[str, dict[str, float]] = {}
    _record_failure(
        failures,
        "precision_at_k",
        actual=metrics.precision_at_k,
        minimum=gate.min_precision_at_k,
    )
    _record_failure(
        failures,
        "recall_at_k",
        actual=metrics.recall_at_k,
        minimum=gate.min_recall_at_k,
    )
    _record_failure(failures, "mrr", actual=metrics.mrr, minimum=gate.min_mrr)
    _record_failure(
        failures,
        "hit_rate",
        actual=metrics.hit_rate,
        minimum=gate.min_hit_rate,
    )
    return RetrievalQualityGateReport(passed=not failures, failures=failures)


def candidate_references(candidate: EvidenceCandidate) -> set[str]:
    metadata = candidate.metadata
    refs = metadata.get("reference_metadata", {}).get("references", [])
    source_ref = candidate.source_location.get("reference")
    values: set[str] = set()
    if isinstance(refs, list):
        values.update(str(ref) for ref in refs if ref)
    if isinstance(source_ref, str) and source_ref:
        values.add(source_ref)
    return values


def _record_failure(
    failures: dict[str, dict[str, float]],
    key: str,
    *,
    actual: float,
    minimum: float,
) -> None:
    if actual < minimum:
        failures[key] = {"actual": actual, "minimum": minimum}


def _mrr(relevant_flags: list[bool]) -> float:
    for index, relevant in enumerate(relevant_flags, start=1):
        if relevant:
            return 1 / index
    return 0.0


def _ndcg(relevant_flags: list[bool], ideal_relevant_count: int) -> float:
    if ideal_relevant_count <= 0:
        return 0.0
    dcg = sum(
        (1.0 / log2(index + 1))
        for index, relevant in enumerate(relevant_flags, start=1)
        if relevant
    )
    ideal = sum(1.0 / log2(index + 1) for index in range(1, ideal_relevant_count + 1))
    return dcg / ideal if ideal else 0.0
```

- [ ] **Step 4: Replace the ad hoc metric helpers in evaluation gate tests**

Modify `backend/tests/test_rag_evaluation_gates.py` to use the new service:

```python
from ragstudio.services.retrieval_evidence import EvidenceCandidate
from ragstudio.services.retrieval_metrics import (
    RetrievalQualityGate,
    assert_quality_gate,
    calculate_retrieval_metrics,
)


def _source(reference, chunk_id, rank, *, direct=False):
    return EvidenceCandidate(
        candidate_id=f"test:{chunk_id}",
        text=f"[{reference}] sample text",
        document_id="doc-quran",
        chunk_id=chunk_id,
        source_location={"page": rank, "reference": reference},
        metadata={
            "reference_metadata": {"references": [reference]},
            "match_features": {"reference_exact": direct},
        },
        tool="test",
        tool_rank=rank,
        base_score=1.0,
        final_score=1.0,
    )


def test_quran_arabic_word_gate_metrics():
    results = [
        _source("19:13", "quran-19-13", 1, direct=True),
        _source("19:12", "quran-19-12", 2),
    ]

    metrics = calculate_retrieval_metrics(results, relevant_references={"19:13"}, k=5)
    report = assert_quality_gate(
        metrics,
        RetrievalQualityGate(
            min_precision_at_k=0.20,
            min_recall_at_k=1.00,
            min_mrr=1.00,
            min_hit_rate=1.00,
        ),
    )

    assert report.passed is True


def test_quran_light_reference_gate_metrics():
    results = [
        _source("24:35", "quran-24-35", 1, direct=True),
        _source("24:36", "quran-24-36", 2),
    ]

    metrics = calculate_retrieval_metrics(results, relevant_references={"24:35"}, k=5)
    report = assert_quality_gate(
        metrics,
        RetrievalQualityGate(
            min_precision_at_k=0.20,
            min_recall_at_k=1.00,
            min_mrr=1.00,
            min_hit_rate=1.00,
        ),
    )

    assert report.passed is True
```

- [ ] **Step 5: Run the metrics tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_retrieval_metrics.py backend/tests/test_rag_evaluation_gates.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/retrieval_metrics.py backend/tests/test_retrieval_metrics.py backend/tests/test_rag_evaluation_gates.py
git commit -m "feat: add retrieval quality metrics"
```

---

### Task 2: Deterministic Query Understanding And Retrieval Pass Planning

**Files:**
- Create: `backend/src/ragstudio/services/query_understanding.py`
- Create: `backend/tests/test_query_understanding.py`
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Write the failing query-understanding tests**

Create `backend/tests/test_query_understanding.py`:

```python
from ragstudio.services.query_understanding import understand_query


def test_understanding_detects_arabic_exact_token_and_variants():
    understanding = understand_query("وَحَنَانًا")

    assert understanding.intent == "arabic_exact_token"
    assert understanding.answer_type == "reference"
    assert understanding.direct_evidence_required is True
    assert understanding.arabic_query_variants == ["وحنانا", "حنانا"]
    assert [item.name for item in understanding.retrieval_passes] == [
        "arabic_exact_token",
        "semantic_metadata",
        "vector_db",
        "native_vector",
    ]


def test_understanding_detects_exact_quran_reference():
    understanding = understand_query("show Quran 19:13")

    assert understanding.intent == "reference"
    assert understanding.reference_hints == ["19:13"]
    assert understanding.direct_evidence_required is True
    assert [item.name for item in understanding.retrieval_passes][:2] == [
        "reference_exact",
        "semantic_metadata",
    ]


def test_understanding_detects_phrase_lookup():
    understanding = understand_query(
        "Find the verse that says Allah is the Light of the heavens and the earth"
    )

    assert understanding.intent == "phrase_lookup"
    assert "allah is the light of the heavens and the earth" in understanding.target_phrases
    assert [item.name for item in understanding.retrieval_passes][:2] == [
        "phrase_exact",
        "semantic_metadata",
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_query_understanding.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.query_understanding'`.

- [ ] **Step 3: Implement deterministic query understanding**

Create `backend/src/ragstudio/services/query_understanding.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from ragstudio.services.arabic_text import arabic_query_variants

QueryUnderstandingIntent = Literal[
    "arabic_exact_token",
    "reference",
    "phrase_lookup",
    "count",
    "summary",
    "semantic",
]


@dataclass(frozen=True)
class RetrievalPass:
    name: str
    query: str
    limit_multiplier: int = 1
    direct_evidence: bool = False


@dataclass(frozen=True)
class QueryUnderstanding:
    query: str
    intent: QueryUnderstandingIntent
    answer_type: str
    target_phrases: list[str] = field(default_factory=list)
    required_terms: list[str] = field(default_factory=list)
    reference_hints: list[str] = field(default_factory=list)
    arabic_query_variants: list[str] = field(default_factory=list)
    retrieval_passes: list[RetrievalPass] = field(default_factory=list)
    direct_evidence_required: bool = False


def understand_query(query: str) -> QueryUnderstanding:
    stripped = query.strip()
    normalized = stripped.casefold()
    refs = _reference_hints(stripped)
    arabic_variants = arabic_query_variants(stripped)
    target_phrases = _target_phrases(normalized)

    if arabic_variants and _is_compact_arabic_query(stripped):
        return QueryUnderstanding(
            query=stripped,
            intent="arabic_exact_token",
            answer_type="reference",
            arabic_query_variants=arabic_variants,
            retrieval_passes=[
                RetrievalPass("arabic_exact_token", arabic_variants[0], direct_evidence=True),
                RetrievalPass("semantic_metadata", stripped, limit_multiplier=2),
                RetrievalPass("vector_db", stripped, limit_multiplier=2),
                RetrievalPass("native_vector", stripped, limit_multiplier=2),
            ],
            direct_evidence_required=True,
        )

    if refs:
        return QueryUnderstanding(
            query=stripped,
            intent="reference",
            answer_type="reference",
            reference_hints=refs,
            retrieval_passes=[
                RetrievalPass("reference_exact", refs[0], direct_evidence=True),
                RetrievalPass("semantic_metadata", stripped, limit_multiplier=2),
                RetrievalPass("vector_db", stripped, limit_multiplier=2),
                RetrievalPass("native_vector", stripped, limit_multiplier=2),
            ],
            direct_evidence_required=True,
        )

    if target_phrases:
        return QueryUnderstanding(
            query=stripped,
            intent="phrase_lookup",
            answer_type="reference",
            target_phrases=target_phrases,
            required_terms=_terms(target_phrases[0]),
            retrieval_passes=[
                RetrievalPass("phrase_exact", target_phrases[0], direct_evidence=True),
                RetrievalPass("semantic_metadata", stripped, limit_multiplier=3),
                RetrievalPass("vector_db", stripped, limit_multiplier=2),
                RetrievalPass("native_vector", stripped, limit_multiplier=2),
            ],
            direct_evidence_required=True,
        )

    if re.search(r"\b(how many|count|number of|total)\b", normalized):
        return QueryUnderstanding(
            query=stripped,
            intent="count",
            answer_type="count",
            retrieval_passes=[
                RetrievalPass("title_count", stripped, direct_evidence=True),
                RetrievalPass("semantic_metadata", stripped, limit_multiplier=2),
                RetrievalPass("vector_db", stripped, limit_multiplier=2),
                RetrievalPass("native_vector", stripped, limit_multiplier=2),
            ],
            direct_evidence_required=True,
        )

    if re.search(r"\b(summary|summarize|overview)\b", normalized):
        intent: QueryUnderstandingIntent = "summary"
    else:
        intent = "semantic"

    return QueryUnderstanding(
        query=stripped,
        intent=intent,
        answer_type="text",
        retrieval_passes=[
            RetrievalPass("semantic_metadata", stripped, limit_multiplier=2),
            RetrievalPass("vector_db", stripped, limit_multiplier=2),
            RetrievalPass("native_vector", stripped, limit_multiplier=2),
        ],
        direct_evidence_required=False,
    )


def _reference_hints(query: str) -> list[str]:
    return list(dict.fromkeys(match.group(0) for match in re.finditer(r"\b\d{1,3}:\d{1,3}\b", query)))


def _target_phrases(normalized: str) -> list[str]:
    match = re.search(r"(?:says|say|phrase|quote)\s+(.+)$", normalized)
    if not match:
        return []
    phrase = re.sub(r"[^a-z0-9\u0600-\u06ff ]+", "", match.group(1)).strip()
    return [phrase] if phrase else []


def _is_compact_arabic_query(query: str) -> bool:
    return bool(query) and len(query.split()) <= 3 and any("\u0600" <= char <= "\u06ff" for char in query)


def _terms(value: str) -> list[str]:
    return re.findall(r"[\w\u0600-\u06ff]+", value, flags=re.UNICODE)
```

- [ ] **Step 4: Wire understanding into `RetrievalPlan` without breaking existing callers**

Modify `backend/src/ragstudio/services/retrieval_evidence.py`:

```python
from ragstudio.services.query_understanding import QueryUnderstanding, understand_query
```

Update the `RetrievalPlan` dataclass:

```python
@dataclass(frozen=True)
class RetrievalPlan:
    query: str
    document_ids: list[str]
    limit: int
    intent: QueryIntent
    use_native: bool = True
    use_metadata: bool = True
    use_relationships: bool = True
    candidate_limit: int = 20
    understanding: QueryUnderstanding | None = None
```

Update the end of `plan_for_query()`:

```python
    understanding = understand_query(query)
    mapped_intent: QueryIntent = (
        "reference"
        if understanding.intent in {"reference", "arabic_exact_token", "phrase_lookup"}
        else "count"
        if understanding.intent == "count"
        else "summary"
        if understanding.intent == "summary"
        else intent
    )

    return RetrievalPlan(
        query=query,
        document_ids=list(document_ids),
        limit=limit,
        intent=mapped_intent,
        candidate_limit=max(limit * 2, 20),
        understanding=understanding,
    )
```

- [ ] **Step 5: Add an orchestrator planner trace assertion**

Append to `backend/tests/test_retrieval_orchestrator.py`:

```python
def test_plan_for_arabic_token_carries_retrieval_passes():
    plan = plan_for_query("حنانا", document_ids=["doc-quran"], limit=5)

    assert plan.intent == "reference"
    assert plan.understanding is not None
    assert plan.understanding.intent == "arabic_exact_token"
    assert [item.name for item in plan.understanding.retrieval_passes] == [
        "arabic_exact_token",
        "semantic_metadata",
        "vector_db",
        "native_vector",
    ]
```

- [ ] **Step 6: Run the planner tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_query_understanding.py backend/tests/test_retrieval_orchestrator.py::test_plan_for_arabic_token_carries_retrieval_passes -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/query_understanding.py backend/src/ragstudio/services/retrieval_evidence.py backend/tests/test_query_understanding.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: add deterministic retrieval planning"
```

---

### Task 3: Evidence Candidate Schema And Trace Normalization

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`
- Test: `backend/tests/test_rag_retrieval_fusion.py`
- Test: `backend/tests/test_context_assembly_service.py`

- [ ] **Step 1: Write the failing serialization test**

Append to `backend/tests/test_retrieval_orchestrator.py`:

```python
def test_evidence_candidate_serializes_retrieval_pass_and_match_features():
    candidate = EvidenceCandidate(
        candidate_id="arabic:chunk-19-13",
        text="[19:13] وَحَنَانًا مِّن لَّدُنَّا",
        document_id="doc-quran",
        chunk_id="chunk-19-13",
        source_location={"page": 312, "reference": "19:13"},
        metadata={},
        tool="arabic_lexical",
        tool_rank=1,
        base_score=10.0,
        retrieval_pass="arabic_exact_token",
        match_features={"arabic_exact": True, "arabic_token": "حنانا"},
        canonical_reference="19:13",
        scope_status="in_scope",
        source_quality={"parser": "mineru", "warnings": 0},
        risk_flags=[],
    )

    source = candidate.to_source()
    trace = candidate.to_trace()

    assert source["metadata"]["retrieval_pass"] == "arabic_exact_token"
    assert source["metadata"]["match_features"] == {
        "arabic_exact": True,
        "arabic_token": "حنانا",
    }
    assert source["metadata"]["canonical_reference"] == "19:13"
    assert source["metadata"]["scope_status"] == "in_scope"
    assert trace["retrieval_pass"] == "arabic_exact_token"
    assert trace["match_features"]["arabic_exact"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_retrieval_orchestrator.py::test_evidence_candidate_serializes_retrieval_pass_and_match_features -q
```

Expected: FAIL with `TypeError: EvidenceCandidate.__init__() got an unexpected keyword argument 'retrieval_pass'`.

- [ ] **Step 3: Extend `EvidenceCandidate` with compatible default fields**

Modify the `EvidenceCandidate` dataclass in `backend/src/ragstudio/services/retrieval_evidence.py` by adding fields after `reasons`:

```python
    retrieval_pass: str | None = None
    match_features: dict[str, Any] = field(default_factory=dict)
    canonical_reference: str | None = None
    embedding_profile: dict[str, Any] = field(default_factory=dict)
    index_shape: dict[str, Any] = field(default_factory=dict)
    scope_status: str | None = None
    source_quality: dict[str, Any] = field(default_factory=dict)
    risk_flags: list[str] = field(default_factory=list)
```

Add this method inside `EvidenceCandidate`:

```python
    def normalized_metadata(self) -> dict[str, Any]:
        metadata = dict(self.metadata)
        if self.retrieval_pass:
            metadata["retrieval_pass"] = self.retrieval_pass
        if self.match_features:
            metadata["match_features"] = self.match_features
        if self.canonical_reference:
            metadata["canonical_reference"] = self.canonical_reference
        if self.embedding_profile:
            metadata["embedding_profile"] = self.embedding_profile
        if self.index_shape:
            metadata["index_shape"] = self.index_shape
        if self.scope_status:
            metadata["scope_status"] = self.scope_status
        if self.source_quality:
            metadata["source_quality"] = self.source_quality
        if self.risk_flags:
            metadata["risk_flags"] = self.risk_flags
        return metadata
```

Change `to_source()` to start with normalized metadata:

```python
    def to_source(self) -> dict[str, Any]:
        metadata = {
            **self.normalized_metadata(),
            "retrieval_tool": self.tool,
            "retrieval_rank": self.tool_rank,
            "retrieval_score": self.final_score,
            "retrieval_reasons": self.reasons,
        }
```

Change `to_trace()` to include the normalized fields:

```python
        if self.retrieval_pass:
            trace["retrieval_pass"] = self.retrieval_pass
        if self.match_features:
            trace["match_features"] = self.match_features
        if self.canonical_reference:
            trace["canonical_reference"] = self.canonical_reference
        if self.scope_status:
            trace["scope_status"] = self.scope_status
        if self.risk_flags:
            trace["risk_flags"] = self.risk_flags
```

- [ ] **Step 4: Update fusion and context helpers to read typed fields first**

Modify `_features()` in `backend/src/ragstudio/services/retrieval_fusion.py`:

```python
def _features(candidate: EvidenceCandidate) -> dict[str, Any]:
    if candidate.match_features:
        return candidate.match_features
    value = candidate.metadata.get("match_features")
    return value if isinstance(value, dict) else {}
```

Modify `_features()` in `backend/src/ragstudio/services/context_assembly_service.py`:

```python
def _features(candidate: EvidenceCandidate) -> dict[str, Any]:
    if candidate.match_features:
        return candidate.match_features
    value = candidate.metadata.get("match_features")
    return value if isinstance(value, dict) else {}
```

Modify `_retrieval_passes()` in `backend/src/ragstudio/services/context_assembly_service.py`:

```python
def _retrieval_passes(candidate: EvidenceCandidate) -> list[str]:
    passes = candidate.metadata.get("retrieval_passes")
    if isinstance(passes, list) and passes:
        return [str(item) for item in passes]
    if candidate.retrieval_pass:
        return [candidate.retrieval_pass]
    return [candidate.tool]
```

- [ ] **Step 5: Run schema and dependent tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_retrieval_orchestrator.py::test_evidence_candidate_serializes_retrieval_pass_and_match_features backend/tests/test_rag_retrieval_fusion.py backend/tests/test_context_assembly_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/retrieval_evidence.py backend/src/ragstudio/services/retrieval_fusion.py backend/src/ragstudio/services/context_assembly_service.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: normalize retrieval evidence metadata"
```

---

### Task 4: Multi-Pass Metadata And Lexical Retrieval Service

**Files:**
- Create: `backend/src/ragstudio/services/metadata_retrieval_service.py`
- Create: `backend/tests/test_metadata_retrieval_service.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`

- [ ] **Step 1: Write failing tests for metadata retrieval passes**

Create `backend/tests/test_metadata_retrieval_service.py`:

```python
import pytest
from ragstudio.schemas.chunks import ChunkOut
from ragstudio.services.metadata_retrieval_service import MetadataRetrievalService
from ragstudio.services.query_understanding import understand_query


class FakeChunkService:
    def __init__(self):
        self.calls = []

    async def search(self, search_in):
        self.calls.append(search_in)
        if search_in.query in {"حنانا", "وحنانا"}:
            return type(
                "SearchResult",
                (),
                {
                    "items": [
                        ChunkOut(
                            id="chunk-19-13",
                            document_id="doc-quran",
                            text="[19:13] وَحَنَانًا مِّن لَّدُنَّا",
                            source_location={"page": 312, "reference": "19:13"},
                            metadata={
                                "score": 100,
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
async def test_metadata_service_runs_arabic_exact_before_semantic():
    chunk_service = FakeChunkService()
    understanding = understand_query("حنانا")

    candidates, trace = await MetadataRetrievalService(chunk_service).retrieve(
        "حنانا",
        understanding=understanding,
        document_ids=["doc-quran"],
        variant_id="variant-1",
        limit=5,
    )

    assert [call.query for call in chunk_service.calls][:2] == ["حنانا", "حنانا"]
    assert candidates[0].chunk_id == "chunk-19-13"
    assert candidates[0].tool == "metadata"
    assert candidates[0].retrieval_pass == "arabic_exact_token"
    assert candidates[0].match_features == {
        "arabic_exact": True,
        "arabic_token": "حنانا",
    }
    assert trace["stage"] == "metadata_retrieval"
    assert trace["passes"][0]["name"] == "arabic_exact_token"
    assert trace["passes"][0]["candidate_count"] == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_metadata_retrieval_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.metadata_retrieval_service'`.

- [ ] **Step 3: Implement `MetadataRetrievalService`**

Create `backend/src/ragstudio/services/metadata_retrieval_service.py`:

```python
from __future__ import annotations

from time import perf_counter
from typing import Any

from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn
from ragstudio.services.query_understanding import QueryUnderstanding, RetrievalPass
from ragstudio.services.retrieval_evidence import EvidenceCandidate


class MetadataRetrievalService:
    def __init__(self, chunk_service: Any):
        self.chunk_service = chunk_service

    async def retrieve(
        self,
        query: str,
        *,
        understanding: QueryUnderstanding,
        document_ids: list[str],
        variant_id: str,
        limit: int,
    ) -> tuple[list[EvidenceCandidate], dict[str, Any]]:
        candidates: list[EvidenceCandidate] = []
        pass_traces: list[dict[str, Any]] = []
        seen_chunk_ids: set[str] = set()

        for retrieval_pass in self._metadata_passes(understanding):
            started = perf_counter()
            search = await self.chunk_service.search(
                ChunkSearchIn(
                    query=retrieval_pass.query or query,
                    document_ids=document_ids,
                    variant_id=variant_id,
                    limit=max(limit * retrieval_pass.limit_multiplier, limit),
                    explain=True,
                    include_neighbors=True,
                )
            )
            pass_candidates = [
                self._candidate_from_chunk(chunk, index, retrieval_pass)
                for index, chunk in enumerate(search.items, start=1)
                if chunk.id not in seen_chunk_ids
            ]
            for candidate in pass_candidates:
                if candidate.chunk_id:
                    seen_chunk_ids.add(candidate.chunk_id)
            candidates.extend(pass_candidates)
            pass_traces.append(
                {
                    "name": retrieval_pass.name,
                    "query": retrieval_pass.query,
                    "candidate_count": len(pass_candidates),
                    "latency_ms": _elapsed_ms(started),
                    "top_candidate_ids": [
                        candidate.candidate_id for candidate in pass_candidates[:5]
                    ],
                }
            )

        return candidates, {"stage": "metadata_retrieval", "passes": pass_traces}

    def _metadata_passes(self, understanding: QueryUnderstanding) -> list[RetrievalPass]:
        return [
            item
            for item in understanding.retrieval_passes
            if item.name
            in {
                "reference_exact",
                "arabic_exact_token",
                "phrase_exact",
                "title_count",
                "semantic_metadata",
            }
        ]

    def _candidate_from_chunk(
        self,
        chunk: ChunkOut,
        rank: int,
        retrieval_pass: RetrievalPass,
    ) -> EvidenceCandidate:
        score = chunk.metadata.get("score")
        base_score = float(score) if isinstance(score, (int, float)) else max(1.0, 20.0 - rank)
        match_features = self._match_features(chunk, retrieval_pass)
        return EvidenceCandidate(
            candidate_id=f"metadata:{retrieval_pass.name}:{chunk.id}",
            text=chunk.text,
            document_id=chunk.document_id,
            chunk_id=chunk.id,
            source_location=chunk.source_location,
            metadata=chunk.metadata,
            tool="metadata",
            tool_rank=rank,
            base_score=base_score,
            retrieval_pass=retrieval_pass.name,
            match_features=match_features,
            canonical_reference=self._first_reference(chunk),
            scope_status="in_scope",
            source_quality=self._source_quality(chunk),
        )

    def _match_features(
        self,
        chunk: ChunkOut,
        retrieval_pass: RetrievalPass,
    ) -> dict[str, Any]:
        if retrieval_pass.name == "arabic_exact_token":
            return {"arabic_exact": True, "arabic_token": retrieval_pass.query}
        if retrieval_pass.name == "reference_exact":
            return {"reference_exact": True, "reference": retrieval_pass.query}
        if retrieval_pass.name == "phrase_exact":
            return {"target_phrase": retrieval_pass.query}
        if retrieval_pass.name == "title_count":
            return {"title_count": True}
        return {}

    def _first_reference(self, chunk: ChunkOut) -> str | None:
        source_reference = chunk.source_location.get("reference")
        if isinstance(source_reference, str) and source_reference:
            return source_reference
        refs = chunk.metadata.get("reference_metadata", {}).get("references", [])
        if isinstance(refs, list) and refs:
            return str(refs[0])
        return None

    def _source_quality(self, chunk: ChunkOut) -> dict[str, Any]:
        extraction_quality = chunk.metadata.get("extraction_quality")
        warnings = []
        if isinstance(extraction_quality, dict):
            parser_warnings = extraction_quality.get("parser_warnings")
            warnings = parser_warnings if isinstance(parser_warnings, list) else []
        return {
            "parser": chunk.metadata.get("backend")
            or chunk.metadata.get("parser_metadata", {}).get("backend"),
            "warning_count": len(warnings),
        }


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 3)
```

- [ ] **Step 4: Replace orchestrator metadata candidate construction with the service**

Modify imports in `backend/src/ragstudio/services/retrieval_orchestrator.py`:

```python
from ragstudio.services.metadata_retrieval_service import MetadataRetrievalService
```

Add an optional constructor argument and field:

```python
        metadata_retrieval_service: MetadataRetrievalService | None = None,
```

```python
        self.metadata_retrieval_service = (
            metadata_retrieval_service or MetadataRetrievalService(chunk_service)
        )
```

Replace `_timed_metadata_candidates()` with:

```python
    async def _timed_metadata_candidates(
        self,
        query: str,
        document_ids: list[str],
        variant_id: str,
        limit: int,
        plan: Any | None = None,
    ) -> tuple[list[EvidenceCandidate], float, dict[str, Any]]:
        started = perf_counter()
        understanding = getattr(plan, "understanding", None)
        if understanding is None:
            understanding = plan_for_query(query, document_ids=document_ids, limit=limit).understanding
        candidates, trace = await self.metadata_retrieval_service.retrieve(
            query,
            understanding=understanding,
            document_ids=document_ids,
            variant_id=variant_id,
            limit=limit,
        )
        return candidates, _elapsed_ms(started), trace
```

Update each `_timed_metadata_candidates(...)` caller to pass `plan` and to unpack `(metadata_candidates, metadata_ms, metadata_trace)`. Add `metadata_trace` to the retrieval trace:

```python
metadata_candidates, metadata_ms, metadata_trace = metadata_result
timings["metadata_ms"] = metadata_ms
...
"metadata_trace": metadata_trace,
```

- [ ] **Step 5: Run metadata service tests and focused orchestrator tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_metadata_retrieval_service.py backend/tests/test_retrieval_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/metadata_retrieval_service.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_metadata_retrieval_service.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: add multi-pass metadata retrieval"
```

---

### Task 5: Scoped Native And Vector DB Preflight

**Files:**
- Modify: `backend/src/ragstudio/services/native_raganything_adapter.py`
- Modify: `backend/tests/test_native_raganything_adapter.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`

- [ ] **Step 1: Write failing native preflight tests**

Append to `backend/tests/test_native_raganything_adapter.py`:

```python
@pytest.mark.asyncio
async def test_native_adapter_preflight_reports_storage_filter_and_embedding_shape(tmp_path):
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    report = await adapter.preflight_scoped_retrieval(["doc-1"])

    assert report["status"] == "ok"
    assert report["storage_filter"] == "supported"
    assert report["embedding_dimensions"] == 1536
    assert report["send_dimensions"] is True
    assert report["scoped_cache_policy"] == "disabled_for_query"


@pytest.mark.asyncio
async def test_native_adapter_preflight_blocks_unfilterable_storage(tmp_path):
    rag = FakeRAGAnything()
    rag.lightrag.chunks_vdb = FakeChunkVectorStorage([])
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )
    adapter._rag = rag

    report = await adapter.preflight_scoped_retrieval(["doc-1"])

    assert report["status"] == "degraded"
    assert report["error_type"] == "native_document_scope_unsupported"
    assert "full_doc_id filtering" in report["detail"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_native_raganything_adapter.py -q -k preflight
```

Expected: FAIL with `AttributeError: 'NativeRAGAnythingAdapter' object has no attribute 'preflight_scoped_retrieval'`.

- [ ] **Step 3: Implement preflight reporting**

Add this method to `NativeRAGAnythingAdapter` in `backend/src/ragstudio/services/native_raganything_adapter.py`:

```python
    async def preflight_scoped_retrieval(self, document_ids: list[str]) -> dict[str, Any]:
        if not document_ids:
            return {
                "status": "ok",
                "storage_filter": "not_required",
                "embedding_dimensions": self.profile.embedding_dimensions,
                "send_dimensions": True,
                "scoped_cache_policy": "not_required",
            }
        rag = self._raganything()
        async with self._storage_env():
            try:
                await self._ensure_lightrag(rag)
                lightrag = getattr(rag, "lightrag", None)
                chunks_vdb = getattr(lightrag, "chunks_vdb", None)
                if chunks_vdb is None:
                    raise NativeScopedStorageUnsupported(
                        "LightRAG chunks vector storage is not initialized."
                    )
                proxy = ScopedVectorStorageProxy(
                    chunks_vdb,
                    document_ids,
                    require_storage_filter=True,
                )
                if not proxy.supports_storage_filter():
                    raise NativeScopedStorageUnsupported(
                        "LightRAG vector storage does not support storage-level full_doc_id filtering."
                    )
            except NativeScopedStorageUnsupported as exc:
                return {
                    "status": "degraded",
                    "error_type": "native_document_scope_unsupported",
                    "detail": str(exc),
                    "embedding_dimensions": self.profile.embedding_dimensions,
                    "send_dimensions": True,
                    "scoped_cache_policy": "disabled_for_query",
                }
        return {
            "status": "ok",
            "storage_filter": "supported",
            "embedding_dimensions": self.profile.embedding_dimensions,
            "send_dimensions": True,
            "scoped_cache_policy": "disabled_for_query",
        }
```

- [ ] **Step 4: Add orchestrator preflight trace before native scoped retrieval**

Modify `_timed_native_candidates()` in `backend/src/ragstudio/services/retrieval_orchestrator.py` before `runtime.query(...)`:

```python
            preflight = None
            preflight_fn = getattr(runtime, "preflight_scoped_retrieval", None)
            if document_ids and callable(preflight_fn):
                preflight = await preflight_fn(document_ids)
                native_timings["native_preflight"] = preflight
                if preflight.get("status") == "degraded":
                    raise NativeRuntimeQueryFailed(
                        str(preflight.get("detail") or "Native scoped retrieval preflight failed."),
                        str(preflight.get("error_type") or "native_preflight_failed"),
                        native_timings,
                    )
```

- [ ] **Step 5: Run native and orchestrator fallback tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_native_raganything_adapter.py -q -k 'preflight or scoped' && PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_retrieval_orchestrator.py -q -k 'degrades or unsupported or timeout'
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/native_raganything_adapter.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_native_raganything_adapter.py
git commit -m "feat: preflight scoped native retrieval"
```

---

### Task 6: Staged Orchestrator Flow And Graph Expansion Boundary

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`
- Modify: `backend/src/ragstudio/services/retrieval_observability.py`

- [ ] **Step 1: Write failing test for staged retrieval trace**

Append to `backend/tests/test_retrieval_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_orchestrator_emits_primary_seed_expansion_and_final_fusion_stages():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=FakeRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8},
    )

    stages = [trace.get("stage") for trace in result.chunk_traces if isinstance(trace, dict)]
    assert "primary_retrieval" in stages
    assert "seed_fusion" in stages
    assert "graph_expansion" in stages
    assert "final_fusion" in stages
    assert result.error is None
    assert answer_service.called is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_retrieval_orchestrator.py::test_orchestrator_emits_primary_seed_expansion_and_final_fusion_stages -q
```

Expected: FAIL because `primary_retrieval`, `seed_fusion`, and `final_fusion` stages are not emitted.

- [ ] **Step 3: Add richer observability stage details**

Modify `record_stage()` in `backend/src/ragstudio/services/retrieval_observability.py`:

```python
    def record_stage(
        self,
        stage: str,
        *,
        candidate_count: int,
        latency_ms: float,
        detail: dict[str, Any] | None = None,
    ) -> None:
        item = {
            "stage": stage,
            "candidate_count": candidate_count,
            "latency_ms": latency_ms,
        }
        if detail:
            item.update(detail)
        self.trace["stages"].append(item)
```

- [ ] **Step 4: Emit staged trace entries in the orchestrator**

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, after primary retrieval and before graph expansion, add:

```python
            traces.append(
                {
                    "stage": "primary_retrieval",
                    "metadata_candidates": len(metadata_candidates),
                    "native_candidates": len(native_candidates),
                    "vector_candidates": len(
                        [
                            candidate
                            for candidate in native_candidates
                            if candidate.retrieval_pass in {"vector_db", "native_vector"}
                            or candidate.tool in {"pgvector", "native"}
                        ]
                    ),
                }
            )
```

After initial seed fusion, add:

```python
            traces.append(
                {
                    "stage": "seed_fusion",
                    "seed_candidates": len(seed_candidates),
                    "seed_candidate_ids": [
                        candidate.candidate_id for candidate in seed_candidates[:limit]
                    ],
                }
            )
```

Rename the final fusion trace stage from `"retrieval_fusion"` to `"final_fusion"` while keeping a compatibility alias:

```python
            traces.append(
                {
                    "stage": "final_fusion",
                    "compat_stage": "retrieval_fusion",
                    "native_candidates": len(native_candidates),
                    "metadata_candidates": len(metadata_candidates),
                    "graph_candidates": len(graph_candidates),
                    "fused_candidates": len(fused),
                }
            )
```

- [ ] **Step 5: Run focused staged-flow tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_retrieval_orchestrator.py::test_orchestrator_emits_primary_seed_expansion_and_final_fusion_stages backend/tests/test_retrieval_observability.py -q
```

Expected: PASS.

- [ ] **Step 6: Run full orchestrator tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_retrieval_orchestrator.py -q
```

Expected: PASS. If old tests search for stage `"retrieval_fusion"`, update them to accept `trace.get("stage") == "final_fusion" or trace.get("compat_stage") == "retrieval_fusion"`.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/retrieval_orchestrator.py backend/src/ragstudio/services/retrieval_observability.py backend/tests/test_retrieval_orchestrator.py backend/tests/test_retrieval_observability.py
git commit -m "feat: trace staged retrieval orchestration"
```

---

### Task 7: Grounding Validation

**Files:**
- Create: `backend/src/ragstudio/services/grounding_validator.py`
- Create: `backend/tests/test_grounding_validator.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`

- [ ] **Step 1: Write failing validator tests**

Create `backend/tests/test_grounding_validator.py`:

```python
from ragstudio.services.grounding_validator import GroundingValidator
from ragstudio.services.retrieval_evidence import EvidenceCandidate


def candidate(label_ref="19:13", *, direct=True):
    return EvidenceCandidate(
        candidate_id="metadata:chunk-19-13",
        text="[19:13] وَحَنَانًا مِّن لَّدُنَّا",
        document_id="doc-quran",
        chunk_id="chunk-19-13",
        source_location={"page": 312, "reference": label_ref},
        metadata={"reference_metadata": {"references": [label_ref]}},
        tool="metadata",
        tool_rank=1,
        base_score=10,
        final_score=100,
        match_features={"reference_exact": direct},
        canonical_reference=label_ref,
    )


def test_validator_passes_answer_with_existing_source_label():
    result = GroundingValidator().validate(
        answer="The evidence is from 19:13. [S1]",
        evidence=[candidate()],
        expected_references={"19:13"},
    )

    assert result.status == "grounded"
    assert result.failures == []


def test_validator_flags_missing_source_label():
    result = GroundingValidator().validate(
        answer="The evidence is from 19:13. [S2]",
        evidence=[candidate()],
        expected_references={"19:13"},
    )

    assert result.status == "failed"
    assert result.failures == [
        {
            "code": "unknown_source_label",
            "detail": "Answer cites [S2], but only [S1] are available.",
        }
    ]


def test_validator_flags_not_found_answer_when_direct_evidence_exists():
    result = GroundingValidator().validate(
        answer="The available evidence does not support an answer to this question.",
        evidence=[candidate()],
        expected_references={"19:13"},
    )

    assert result.status == "failed"
    assert result.failures[0]["code"] == "direct_evidence_ignored"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_grounding_validator.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.grounding_validator'`.

- [ ] **Step 3: Implement `GroundingValidator`**

Create `backend/src/ragstudio/services/grounding_validator.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ragstudio.services.retrieval_evidence import EvidenceCandidate
from ragstudio.services.retrieval_metrics import candidate_references


@dataclass(frozen=True)
class GroundingValidationResult:
    status: str
    failures: list[dict[str, Any]]
    cited_labels: list[str]
    available_labels: list[str]

    def to_trace(self) -> dict[str, Any]:
        return {
            "stage": "grounding_validation",
            "status": self.status,
            "failures": self.failures,
            "cited_labels": self.cited_labels,
            "available_labels": self.available_labels,
        }


class GroundingValidator:
    SOURCE_RE = re.compile(r"\[S(\d+)\]")

    def validate(
        self,
        *,
        answer: str,
        evidence: list[EvidenceCandidate],
        expected_references: set[str] | None = None,
    ) -> GroundingValidationResult:
        expected_references = expected_references or set()
        available_labels = [f"S{index}" for index, _ in enumerate(evidence, start=1)]
        cited_labels = list(dict.fromkeys(f"S{match}" for match in self.SOURCE_RE.findall(answer)))
        failures: list[dict[str, Any]] = []

        for label in cited_labels:
            if label not in available_labels:
                failures.append(
                    {
                        "code": "unknown_source_label",
                        "detail": (
                            f"Answer cites [{label}], but only "
                            f"{', '.join(f'[{item}]' for item in available_labels)} are available."
                        ),
                    }
                )

        if _is_no_evidence_answer(answer) and any(_is_direct(candidate) for candidate in evidence):
            failures.append(
                {
                    "code": "direct_evidence_ignored",
                    "detail": "Answer says evidence is unavailable, but direct evidence was retrieved.",
                }
            )

        available_references = set().union(
            *(candidate_references(candidate) for candidate in evidence)
        ) if evidence else set()
        missing_expected = sorted(expected_references - available_references)
        if missing_expected:
            failures.append(
                {
                    "code": "expected_reference_not_in_sources",
                    "detail": f"Expected references missing from sources: {', '.join(missing_expected)}",
                }
            )

        return GroundingValidationResult(
            status="failed" if failures else "grounded",
            failures=failures,
            cited_labels=cited_labels,
            available_labels=available_labels,
        )


def _is_no_evidence_answer(answer: str) -> bool:
    normalized = answer.casefold()
    return "does not support" in normalized or "no evidence" in normalized or "not found" in normalized


def _is_direct(candidate: EvidenceCandidate) -> bool:
    features = candidate.match_features or candidate.metadata.get("match_features") or {}
    return bool(features.get("reference_exact") or features.get("arabic_exact") or features.get("target_phrase"))
```

- [ ] **Step 4: Add validation result to `OrchestratedAnswer`**

Modify `OrchestratedAnswer` in `backend/src/ragstudio/services/retrieval_evidence.py`:

```python
    validation: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 5: Wire validation into `RetrievalOrchestrator`**

Modify imports in `backend/src/ragstudio/services/retrieval_orchestrator.py`:

```python
from ragstudio.services.grounding_validator import GroundingValidator
from ragstudio.services.retrieval_metrics import candidate_references
```

Add constructor argument and field:

```python
        grounding_validator: GroundingValidator | None = None,
```

```python
        self.grounding_validator = grounding_validator or GroundingValidator()
```

After `answer, token_metadata = await self.answer_service.answer(...)`, add:

```python
            expected_references = set().union(
                *(candidate_references(candidate) for candidate in final_evidence)
            ) if final_evidence else set()
            validation = self.grounding_validator.validate(
                answer=answer,
                evidence=final_evidence,
                expected_references=expected_references,
            )
            traces.append(validation.to_trace())
```

Add `validation=validation.to_trace()` to the successful `OrchestratedAnswer(...)`.

In `_failed_orchestrated_answer()`, add `validation={}`.

- [ ] **Step 6: Add an orchestrator validation trace test**

Append to `backend/tests/test_retrieval_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_orchestrator_records_grounding_validation_trace():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=FakeRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8},
    )

    validation_trace = next(
        trace for trace in result.chunk_traces if trace.get("stage") == "grounding_validation"
    )
    assert validation_trace["status"] in {"grounded", "failed"}
    assert "available_labels" in validation_trace
```

- [ ] **Step 7: Run validator and orchestrator tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_grounding_validator.py backend/tests/test_retrieval_orchestrator.py::test_orchestrator_records_grounding_validation_trace -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/src/ragstudio/services/grounding_validator.py backend/src/ragstudio/services/retrieval_evidence.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_grounding_validator.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: validate grounded answers"
```

---

### Task 8: Arabic Live-Data Regression And UI Smoke Test

**Files:**
- Create: `backend/tests/test_quran_arabic_live_index_gate.py`
- Create: `e2e/arabic-hanana-query.spec.ts`
- Modify: `e2e/playwright.config.ts`
- Docs: `docs/superpowers/specs/2026-05-11-retrieval-orchestrator-improvement-actions.md`

- [ ] **Step 1: Write a backend regression that exposes missing Arabic tokens**

Create `backend/tests/test_quran_arabic_live_index_gate.py`:

```python
import pytest
from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.chunks import ChunkSearchIn
from ragstudio.services.arabic_text import arabic_tokens, normalize_arabic_text
from ragstudio.services.chunk_service import ChunkService
from sqlalchemy import select


@pytest.mark.asyncio
async def test_indexed_quran_hanana_chunk_is_searchable(session, tmp_path):
    document = Document(
        id="quran-doc",
        filename="quran_arabic_english.pdf",
        content_type="application/pdf",
        sha256="quran-sha",
        artifact_path=str(tmp_path / "quran_arabic_english.pdf"),
        status="succeeded",
    )
    text = "[19:13]\n\nوَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً\n\nAnd affection from Us and purity."
    session.add(document)
    session.add(
        Chunk(
            id="quran-19-13",
            document_id=document.id,
            text=text,
            source_location={"page": 312, "reference": "19:13"},
            metadata_json={
                "reference_metadata": {"references": ["19:13"]},
                "parser_metadata": {"backend": "mineru"},
            },
            text_search_ar=normalize_arabic_text(text),
            tokens_ar=arabic_tokens(text),
        )
    )
    await session.commit()

    stored = await session.scalar(select(Chunk).where(Chunk.id == "quran-19-13"))
    assert stored is not None
    assert "حنانا" in stored.tokens_ar

    result = await ChunkService(session, tmp_path).search(
        ChunkSearchIn(
            query="حنانا",
            document_ids=[document.id],
            limit=5,
            explain=True,
            include_neighbors=True,
        )
    )

    assert result.total == 1
    assert result.items[0].id == "quran-19-13"
    assert result.items[0].source_location["reference"] == "19:13"
```

- [ ] **Step 2: Run the backend regression**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_quran_arabic_live_index_gate.py -q
```

Expected: PASS. This test proves the retrieval layer works when the indexed chunk has valid Arabic text. If this fails, fix retrieval before changing parser or reindex behavior.

- [ ] **Step 3: Add UI smoke test for the running app**

Create `e2e/arabic-hanana-query.spec.ts`:

```typescript
import { expect, test } from "@playwright/test";

test("Quran Arabic lexical query shows trace and sources when live data contains the token", async ({ page }) => {
  await page.goto("/query");
  await page.getByLabel("Question").fill("حنانا");
  await page.locator('label:has-text("quran_arabic_english.pdf") input[type="checkbox"]').check();
  await page.locator('label:has-text("Quran fast lexical") input[type="checkbox"]').check();
  await page.getByLabel("Chunk limit").fill("5");

  const responsePromise = page.waitForResponse(
    (response) => response.url().includes("/api/query") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /run/i }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);

  await expect(page.getByText("Run complete")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText("حنانا")).toBeVisible();

  const body = await page.locator("body").innerText();
  expect(body).toContain("CHUNK TRACES");
  expect(body).toContain("metadata_candidates");
  if (body.includes("No sources returned.")) {
    expect(body).toContain("metadata_candidates\": 0");
  } else {
    expect(body).toContain("19:13");
  }
});
```

- [ ] **Step 4: Make Playwright use the existing Vite URL**

Ensure `e2e/playwright.config.ts` has this base URL:

```typescript
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  use: {
    baseURL: process.env.RAGSTUDIO_E2E_BASE_URL ?? "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
```

If the config already has equivalent settings, only add the `baseURL` line and keep existing projects/reporters.

- [ ] **Step 5: Run the UI smoke test against the running stack**

Run:

```bash
cd frontend && npx playwright test ../e2e/arabic-hanana-query.spec.ts --config ../e2e/playwright.config.ts
```

Expected with current live data: PASS if the UI reports a trace. The test allows either a source with `19:13` or an explicit zero-candidate trace, because the current live Quran index may still contain parser-corrupted Arabic for `[19:13]`.

- [ ] **Step 6: Document the live-data interpretation**

Append to `docs/superpowers/specs/2026-05-11-retrieval-orchestrator-improvement-actions.md` under `Evaluation Plan`:

```markdown
### Live Arabic Data Gate

The retrieval layer is considered correct when a persisted chunk containing `[19:13] وَحَنَانًا` stores normalized tokens `وحنانا` and `حنانا`, and `ChunkService.search(query="حنانا")` returns that chunk. If the live UI returns zero sources while the regression passes, treat the failure as an indexing/parser data-quality issue and reindex the Quran document with the parser-normalization quality gates before tuning retrieval.
```

- [ ] **Step 7: Commit**

```bash
git add backend/tests/test_quran_arabic_live_index_gate.py e2e/arabic-hanana-query.spec.ts e2e/playwright.config.ts docs/superpowers/specs/2026-05-11-retrieval-orchestrator-improvement-actions.md
git commit -m "test: gate arabic lexical query in ui"
```

---

### Task 9: Full Regression Suite And Final Verification

**Files:**
- Modify only files touched by previous tasks if tests expose integration drift.

- [ ] **Step 1: Run focused backend retrieval tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest \
  backend/tests/test_query_understanding.py \
  backend/tests/test_retrieval_metrics.py \
  backend/tests/test_metadata_retrieval_service.py \
  backend/tests/test_native_raganything_adapter.py \
  backend/tests/test_retrieval_orchestrator.py \
  backend/tests/test_rag_retrieval_fusion.py \
  backend/tests/test_context_assembly_service.py \
  backend/tests/test_grounding_validator.py \
  backend/tests/test_rag_evaluation_gates.py \
  backend/tests/test_quran_arabic_live_index_gate.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run runtime query service regression tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_runtime_query_service.py -q
```

Expected: PASS. Pay special attention to tests covering `metadata_fallback`, graph degradation, and native scoped query degradation.

- [ ] **Step 3: Run backend lint**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH ruff check backend/src backend/tests
```

Expected: PASS.

- [ ] **Step 4: Run frontend checks**

Run:

```bash
cd frontend && npm run lint && npm run build
```

Expected: PASS.

- [ ] **Step 5: Run UI smoke test when the stack is up**

Run:

```bash
cd frontend && npx playwright test ../e2e/arabic-hanana-query.spec.ts --config ../e2e/playwright.config.ts
```

Expected: PASS.

- [ ] **Step 6: Capture final live API evidence**

Run:

```bash
curl -s -X POST 'http://127.0.0.1:8000/api/query' \
  -H 'content-type: application/json' \
  --data '{
    "query":"حنانا",
    "document_ids":["07fc5d41-7b14-4367-9d4c-d2151b02378b"],
    "variant_ids":["0e09bb38-46d5-4226-846a-99f217195812"],
    "limit":5
  }' | python -m json.tool
```

Expected: Response status is `200`. If sources are empty, timings and chunk traces must show `metadata_candidates: 0` and `grounding_status: insufficient_evidence`. If sources are present after reindexing, first source should cite `19:13`.

- [ ] **Step 7: Commit final integration fixes**

Only run this if previous steps required changes:

```bash
git add backend/src backend/tests frontend e2e docs/superpowers/specs/2026-05-11-retrieval-orchestrator-improvement-actions.md
git commit -m "test: verify retrieval orchestrator quality gates"
```

---

## Self-Review

**Spec coverage:** The plan covers retrieval SLAs in Task 1, scoped native preflight in Task 5, degradation and staged orchestration in Tasks 4-6, candidate schema in Task 3, deterministic fusion in Tasks 3 and 6, context behavior in existing context tests plus Task 6, grounding validation in Task 7, and regression/UI monitoring in Tasks 8-9.

**Placeholder scan:** The plan avoids placeholder instructions and vague implementation notes. Each code-changing task includes concrete tests, implementation snippets, commands, expected results, and commit commands.

**Type consistency:** `QueryUnderstanding`, `RetrievalPass`, `RetrievalMetrics`, `RetrievalQualityGate`, `EvidenceCandidate` fields, and `GroundingValidator` method signatures are introduced before later tasks reference them. Later tasks read `candidate.match_features` first and keep compatibility with existing `metadata["match_features"]`.
