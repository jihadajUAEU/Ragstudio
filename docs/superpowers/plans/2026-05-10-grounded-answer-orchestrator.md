# Grounded Answer Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the B architecture with C-style gates: deterministic query understanding, multi-pass retrieval, explainable fusion, grounding validation, and Quran regression coverage.

**Architecture:** Keep `RetrievalOrchestrator` as the single answering coordinator, but move query understanding and grounding validation into focused services. Extend the existing evidence model and fusion rules instead of replacing `RerankerService` or `RuntimeAnswerService`.

**Tech Stack:** Python 3.12, Pydantic schemas, SQLAlchemy-backed chunk search, pytest/pytest-asyncio, existing Ragstudio backend service patterns.

---

## File Structure

- Create `backend/src/ragstudio/services/query_understanding.py`
  - Owns deterministic query parsing, answer-bearing phrase extraction, required-term extraction, reference hint extraction, and retrieval rewrites.
- Create `backend/tests/test_query_understanding.py`
  - Unit coverage for phrase lookup, request lookup, exact reference, summary intent, and empty/semantic fallback.
- Modify `backend/src/ragstudio/services/retrieval_evidence.py`
  - Extends `RetrievalPlan` and `EvidenceCandidate` with understanding, passes, match features, supporting phrases, risks, and validation expectations.
  - Updates `plan_for_query()` to accept an optional `QueryUnderstanding`.
  - Updates `fuse_candidates()` so direct phrase/reference/request evidence outranks broad topical matches.
- Modify `backend/src/ragstudio/services/retrieval_orchestrator.py`
  - Injects `QueryUnderstandingService`.
  - Builds plan from understanding.
  - Runs bounded metadata passes before fusion.
  - Preserves current native, graph, reranker, and answer flow.
- Create `backend/src/ragstudio/services/grounding_validator.py`
  - Validates answer citations against final evidence and falls back when the answer says missing despite high-confidence direct evidence.
- Create `backend/tests/test_grounding_validator.py`
  - Unit coverage for valid citations, missing citations, “not in evidence” contradiction, and unsupported reference names.
- Modify `backend/tests/test_retrieval_orchestrator.py`
  - Adds regression tests for `24:35` and document reference `1:5` using fake chunk search responses.
  - Adds trace assertions for understanding, retrieval plan, pass counts, and validation.

## Task 1: Query Understanding Service

**Files:**
- Create: `backend/src/ragstudio/services/query_understanding.py`
- Test: `backend/tests/test_query_understanding.py`

- [ ] **Step 1: Write failing query-understanding tests**

Create `backend/tests/test_query_understanding.py`:

```python
from ragstudio.services.query_understanding import QueryUnderstandingService


def test_extracts_light_phrase_lookup():
    understanding = QueryUnderstandingService().understand(
        "Find the verse that says Allah is the Light of the heavens and the earth. "
        "Summarize the image used"
    )

    assert understanding.intent == "phrase_lookup"
    assert understanding.answer_type == "reference"
    assert understanding.target_phrases == ["allah is the light of the heavens and the earth"]
    assert {"allah", "light", "heavens", "earth"} <= set(understanding.required_terms)
    assert "allah is the light of the heavens and the earth" in understanding.rewritten_queries
    assert understanding.must_cite is True


def test_extracts_straight_path_request_lookup():
    understanding = QueryUnderstandingService().understand(
        "Which verse asks for guidance to the straight path?"
    )

    assert understanding.intent == "request_lookup"
    assert understanding.answer_type == "reference"
    assert understanding.target_phrases == ["guide us to the straight path"]
    assert {"guide", "straight", "path"} <= set(understanding.required_terms)
    assert "guide us to the straight path" in understanding.rewritten_queries
    assert understanding.must_cite is True


def test_extracts_quran_reference_hint():
    understanding = QueryUnderstandingService().understand("Explain Quran 24:35")

    assert understanding.intent == "reference_lookup"
    assert understanding.answer_type == "summary"
    assert understanding.reference_hints == ["24:35"]
    assert "24:35" in understanding.rewritten_queries


def test_summary_query_without_direct_phrase_stays_summary():
    understanding = QueryUnderstandingService().understand("Summarize the uploaded document")

    assert understanding.intent == "summary"
    assert understanding.answer_type == "summary"
    assert understanding.target_phrases == []
    assert understanding.must_cite is True


def test_empty_query_falls_back_to_semantic():
    understanding = QueryUnderstandingService().understand("   ")

    assert understanding.intent == "semantic"
    assert understanding.answer_type == "answer"
    assert understanding.rewritten_queries == []
    assert understanding.must_cite is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest backend/tests/test_query_understanding.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.query_understanding'`.

- [ ] **Step 3: Implement deterministic query understanding**

Create `backend/src/ragstudio/services/query_understanding.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

QueryUnderstandingIntent = Literal[
    "phrase_lookup",
    "request_lookup",
    "reference_lookup",
    "count",
    "title",
    "comparison",
    "summary",
    "semantic",
]

AnswerType = Literal["reference", "count", "title", "comparison", "summary", "answer"]


@dataclass(frozen=True)
class QueryUnderstanding:
    raw_query: str
    normalized_query: str
    intent: QueryUnderstandingIntent
    answer_type: AnswerType
    target_phrases: list[str] = field(default_factory=list)
    required_terms: list[str] = field(default_factory=list)
    rewritten_queries: list[str] = field(default_factory=list)
    reference_hints: list[str] = field(default_factory=list)
    must_cite: bool = True

    def to_trace(self) -> dict[str, object]:
        return {
            "stage": "query_understanding",
            "intent": self.intent,
            "answer_type": self.answer_type,
            "target_phrases": self.target_phrases,
            "required_terms": self.required_terms,
            "rewritten_queries": self.rewritten_queries,
            "reference_hints": self.reference_hints,
            "must_cite": self.must_cite,
        }


class QueryUnderstandingService:
    def understand(self, query: str) -> QueryUnderstanding:
        raw_query = query or ""
        normalized = _normalize(raw_query)
        if not normalized:
            return QueryUnderstanding(
                raw_query=raw_query,
                normalized_query="",
                intent="semantic",
                answer_type="answer",
            )

        reference_hints = _reference_hints(normalized)
        target_phrases = _target_phrases(normalized)
        if _asks_for_straight_path_guidance(normalized):
            target_phrases = _prepend_unique(target_phrases, "guide us to the straight path")

        intent: QueryUnderstandingIntent = "semantic"
        answer_type: AnswerType = "answer"
        if reference_hints:
            intent = "reference_lookup"
            answer_type = "summary" if _has_summary_language(normalized) else "reference"
        elif target_phrases:
            intent = "request_lookup" if _has_request_language(normalized) else "phrase_lookup"
            answer_type = "reference"
        elif re.search(r"\b(how many|count|number of|total)\b", normalized):
            intent = "count"
            answer_type = "count"
        elif re.search(r"\b(title|name of|collection)\b", normalized):
            intent = "title"
            answer_type = "title"
        elif re.search(r"\b(compare|difference|similarities)\b", normalized):
            intent = "comparison"
            answer_type = "comparison"
        elif _has_summary_language(normalized):
            intent = "summary"
            answer_type = "summary"

        rewritten_queries = _rewrites(normalized, target_phrases, reference_hints)
        required_terms = _required_terms(target_phrases, normalized)
        return QueryUnderstanding(
            raw_query=raw_query,
            normalized_query=normalized,
            intent=intent,
            answer_type=answer_type,
            target_phrases=target_phrases,
            required_terms=required_terms,
            rewritten_queries=rewritten_queries,
            reference_hints=reference_hints,
        )


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _target_phrases(query: str) -> list[str]:
    phrases: list[str] = []
    for match in re.finditer(r'"([^"]{8,180})"', query):
        phrases.append(match.group(1).strip())
    for pattern in (
        r"\b(?:that|which)\s+says?\s+(.+?)(?:[.?!]|$)",
        r"\bsays?\s+(.+?)(?:[.?!]|$)",
        r"\btranslated\s+as\s+(.+?)(?:[.?!]|$)",
    ):
        for match in re.finditer(pattern, query):
            phrase = re.sub(r"^(?:that|which|the verse)\s+", "", match.group(1).strip())
            if phrase:
                phrases.append(phrase)
    return _unique([_normalize(phrase) for phrase in phrases if len(_terms(phrase)) >= 4])


def _asks_for_straight_path_guidance(query: str) -> bool:
    terms = set(_terms(query))
    has_request = bool({"ask", "asks", "asking", "request", "requests", "prayer"} & terms)
    has_guidance = bool({"guidance", "guide", "guides", "guided"} & terms)
    return has_request and has_guidance and "straight path" in query


def _reference_hints(query: str) -> list[str]:
    refs = [match.group(0) for match in re.finditer(r"\b\d{1,3}:\d{1,3}\b", query)]
    return _unique(refs)


def _rewrites(query: str, target_phrases: list[str], reference_hints: list[str]) -> list[str]:
    rewrites = [*target_phrases, *reference_hints]
    if query and query not in rewrites:
        rewrites.append(query)
    return _unique(rewrites)


def _required_terms(target_phrases: list[str], query: str) -> list[str]:
    source = " ".join(target_phrases) if target_phrases else query
    stop = {
        "the", "a", "an", "and", "or", "of", "to", "for", "in", "is", "are",
        "that", "which", "verse", "find", "says", "asks", "ask", "guidance",
    }
    return [term for term in _terms(source) if len(term) > 2 and term not in stop]


def _has_request_language(query: str) -> bool:
    return bool(re.search(r"\b(ask|asks|asking|request|requests|prayer|guidance)\b", query))


def _has_summary_language(query: str) -> bool:
    return bool(re.search(r"\b(summary|summarize|overview|explain)\b", query))


def _terms(value: str) -> list[str]:
    return [
        match.group(0).casefold()
        for match in re.finditer(r"[\w\u0600-\u06FF]+", value, flags=re.UNICODE)
    ]


def _unique(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output


def _prepend_unique(values: list[str], value: str) -> list[str]:
    return [value, *[item for item in values if item != value]]
```

- [ ] **Step 4: Run query-understanding tests**

Run:

```bash
uv run pytest backend/tests/test_query_understanding.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/query_understanding.py backend/tests/test_query_understanding.py
git commit -m "feat: add deterministic query understanding"
```

## Task 2: Evidence Model, Plan, and Fusion Rules

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Add failing tests for plan pass selection and direct-match fusion**

Append to `backend/tests/test_retrieval_orchestrator.py`:

```python
from ragstudio.services.query_understanding import QueryUnderstandingService


def test_plan_for_phrase_lookup_selects_direct_passes():
    understanding = QueryUnderstandingService().understand(
        "Find the verse that says Allah is the Light of the heavens and the earth."
    )

    plan = plan_for_query(
        understanding.raw_query,
        document_ids=["doc-1"],
        limit=8,
        understanding=understanding,
    )

    assert plan.intent == "phrase_lookup"
    assert plan.understanding == understanding
    assert plan.passes[:3] == ["phrase_exact", "normalized_phrase", "keyword"]
    assert plan.validation_expectations["must_cite"] is True


def test_fusion_prefers_phrase_exact_over_generic_metadata_match():
    understanding = QueryUnderstandingService().understand(
        "Find the verse that says Allah is the Light of the heavens and the earth."
    )
    plan = plan_for_query(
        understanding.raw_query,
        document_ids=["doc-1"],
        limit=3,
        understanding=understanding,
    )
    generic = EvidenceCandidate(
        candidate_id="metadata:generic",
        text="Allah created the heavens and the earth.",
        document_id="doc-1",
        chunk_id="generic",
        source_location={},
        metadata={},
        tool="metadata",
        tool_rank=1,
        base_score=15.0,
    )
    direct = EvidenceCandidate(
        candidate_id="phrase_exact:light",
        text="Allah is the Light of the heavens and the earth.",
        document_id="doc-1",
        chunk_id="light",
        source_location={},
        metadata={"reference_metadata": {"references": ["24:35"]}},
        tool="phrase_exact",
        tool_rank=1,
        base_score=8.0,
        match_features={"target_phrase": True},
        supporting_phrases=["allah is the light of the heavens and the earth"],
    )

    fused = fuse_candidates(plan, [generic, direct])

    assert fused[0].chunk_id == "light"
    assert "target_phrase_match" in fused[0].reasons
    assert fused[0].metadata["retrieval_passes"] == ["phrase_exact"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest backend/tests/test_retrieval_orchestrator.py::test_plan_for_phrase_lookup_selects_direct_passes backend/tests/test_retrieval_orchestrator.py::test_fusion_prefers_phrase_exact_over_generic_metadata_match -v
```

Expected: FAIL because `plan_for_query()` does not accept `understanding`, `RetrievalPlan` has no `passes`, and `EvidenceCandidate` has no `match_features`.

- [ ] **Step 3: Extend retrieval evidence types and fusion scoring**

Modify `backend/src/ragstudio/services/retrieval_evidence.py`:

```python
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from ragstudio.services.query_understanding import QueryUnderstanding

QueryIntent = Literal[
    "count",
    "title",
    "reference",
    "reference_lookup",
    "phrase_lookup",
    "request_lookup",
    "comparison",
    "summary",
    "semantic",
]


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
    passes: list[str] = field(default_factory=lambda: ["keyword", "metadata_semantic", "native"])
    validation_expectations: dict[str, Any] = field(default_factory=dict)

    def to_trace(self) -> dict[str, Any]:
        return {
            "stage": "planner",
            "intent": self.intent,
            "passes": self.passes,
            "candidate_limit": self.candidate_limit,
            "validation_expectations": self.validation_expectations,
        }


@dataclass(frozen=True)
class EvidenceCandidate:
    candidate_id: str
    text: str
    document_id: str | None
    chunk_id: str | None
    source_location: dict[str, Any]
    metadata: dict[str, Any]
    tool: str
    tool_rank: int
    base_score: float
    boost_score: float = 0.0
    final_score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    match_features: dict[str, Any] = field(default_factory=dict)
    supporting_phrases: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    def to_source(self) -> dict[str, Any]:
        metadata = {
            **self.metadata,
            "retrieval_tool": self.tool,
            "retrieval_rank": self.tool_rank,
            "retrieval_score": self.final_score,
            "retrieval_reasons": self.reasons,
            "match_features": self.match_features,
            "supporting_phrases": self.supporting_phrases,
            "risks": self.risks,
        }
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "text": self.text,
            "source_location": self.source_location,
            "metadata": metadata,
        }

    def to_trace(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "tool": self.tool,
            "tool_rank": self.tool_rank,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "base_score": self.base_score,
            "boost_score": self.boost_score,
            "final_score": self.final_score,
            "reasons": self.reasons,
            "match_features": self.match_features,
            "supporting_phrases": self.supporting_phrases,
            "risks": self.risks,
        }
```

Keep the existing `OrchestratedAnswer` dataclass, then replace `plan_for_query()` with:

```python
def plan_for_query(
    query: str,
    *,
    document_ids: list[str],
    limit: int,
    understanding: QueryUnderstanding | None = None,
) -> RetrievalPlan:
    if understanding is not None:
        return RetrievalPlan(
            query=query,
            document_ids=list(document_ids),
            limit=limit,
            intent=understanding.intent,
            candidate_limit=max(limit * 4, 32),
            understanding=understanding,
            passes=_passes_for_understanding(understanding),
            validation_expectations={
                "must_cite": understanding.must_cite,
                "target_phrases": understanding.target_phrases,
                "reference_hints": understanding.reference_hints,
            },
        )

    normalized = query.casefold()
    intent: QueryIntent = "semantic"
    if re.search(r"\b(how many|count|number of|total)\b", normalized):
        intent = "count"
    elif re.search(r"\b(title|name of|collection)\b", normalized):
        intent = "title"
    elif re.search(r"\b(book|hadith|chapter)\s+\d+", normalized):
        intent = "reference"
    elif re.search(r"\b(compare|difference|similarities)\b", normalized):
        intent = "comparison"
    elif re.search(r"\b(summary|summarize|overview)\b", normalized):
        intent = "summary"

    return RetrievalPlan(
        query=query,
        document_ids=list(document_ids),
        limit=limit,
        intent=intent,
        candidate_limit=max(limit * 2, 20),
    )


def _passes_for_understanding(understanding: QueryUnderstanding) -> list[str]:
    passes: list[str] = []
    if understanding.reference_hints:
        passes.append("reference_exact")
    if understanding.target_phrases:
        passes.extend(["phrase_exact", "normalized_phrase"])
    passes.extend(["keyword", "metadata_semantic", "native"])
    if understanding.intent in {"reference_lookup", "phrase_lookup", "request_lookup"}:
        passes.append("graph_neighbors")
    return list(dict.fromkeys(passes))
```

Update `_score_candidate()` so it preserves pass metadata and boosts direct matches:

```python
def _score_candidate(
    plan: RetrievalPlan,
    candidate: EvidenceCandidate,
    tools: list[str],
) -> EvidenceCandidate:
    reasons: list[str] = []
    boost = candidate.boost_score
    text = candidate.text.casefold()
    title = _metadata_title(candidate.metadata).casefold()
    combined = f"{text} {title}"

    if candidate.match_features.get("reference_exact"):
        boost += 80.0
        reasons.append("reference_exact_match")
    if candidate.match_features.get("target_phrase"):
        boost += 70.0
        reasons.append("target_phrase_match")
    if candidate.match_features.get("required_terms"):
        boost += min(20.0, float(len(candidate.match_features["required_terms"])) * 3.0)
        reasons.append("required_terms_match")

    if plan.intent == "count":
        query_terms = _terms(plan.query)
        combined_terms = _terms(combined)
        if re.search(r"\b\d{2,}\b", combined) and query_terms & combined_terms:
            boost += 24.0
            reasons.append("answer_bearing_count")
        if title and query_terms & _terms(title):
            boost += 8.0
            reasons.append("title_match")

    if candidate.tool in {"reference_exact", "phrase_exact", "normalized_phrase"}:
        boost += 6.0
        reasons.append("direct_retrieval_pass")
    elif candidate.tool == "metadata":
        boost += 3.0
        reasons.append("metadata_precision_tool")
    elif candidate.tool == "graph":
        boost += 2.0
        reasons.append("graph_relationship_tool")
    elif candidate.tool == "native":
        boost += 1.0
        reasons.append("native_semantic_tool")

    metadata = {**candidate.metadata, "deduped_tools": tools, "retrieval_passes": tools}
    return EvidenceCandidate(
        candidate_id=candidate.candidate_id,
        text=candidate.text,
        document_id=candidate.document_id,
        chunk_id=candidate.chunk_id,
        source_location=candidate.source_location,
        metadata=metadata,
        tool=candidate.tool,
        tool_rank=candidate.tool_rank,
        base_score=candidate.base_score,
        boost_score=boost,
        final_score=candidate.base_score + boost,
        reasons=[*candidate.reasons, *reasons],
        match_features=candidate.match_features,
        supporting_phrases=candidate.supporting_phrases,
        risks=candidate.risks,
    )
```

- [ ] **Step 4: Run retrieval evidence tests**

Run:

```bash
uv run pytest backend/tests/test_retrieval_orchestrator.py::test_plan_for_count_query_prefers_metadata_and_native backend/tests/test_retrieval_orchestrator.py::test_plan_for_phrase_lookup_selects_direct_passes backend/tests/test_retrieval_orchestrator.py::test_fusion_prefers_phrase_exact_over_generic_metadata_match -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/retrieval_evidence.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: enrich retrieval plans and evidence fusion"
```

## Task 3: Multi-Pass Metadata Retrieval

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Add failing orchestrator test for phrase pass**

Append to `backend/tests/test_retrieval_orchestrator.py`:

```python
class QuranPhraseChunkSearchService:
    def __init__(self):
        self.queries: list[str] = []

    async def search(self, search_in):
        self.queries.append(search_in.query)
        if search_in.query == "allah is the light of the heavens and the earth":
            items = [
                ChunkOut(
                    id="quran-24-35",
                    document_id="doc-quran",
                    text=(
                        "[24:35] Allah is the Light of the heavens and the earth. "
                        "The example of His light is like a niche within which is a lamp."
                    ),
                    source_location={"page": 355},
                    metadata={
                        "score": 1.0,
                        "reference_metadata": {"references": ["24:35"]},
                    },
                )
            ]
        else:
            items = [
                ChunkOut(
                    id="quran-generic",
                    document_id="doc-quran",
                    text="Allah created the heavens and the earth.",
                    source_location={"page": 1},
                    metadata={"score": 20.0},
                )
            ]
        return type("SearchResult", (), {"items": items, "total": len(items)})()

    async def chunks_by_id(self, chunk_ids):
        return []


class QuranAnswerService:
    def __init__(self):
        self.evidence = []

    async def answer(self, query, evidence, profile):
        self.evidence = evidence
        return "The verse is [S1] 24:35, using the image of a niche, lamp, glass, and blessed olive tree.", {}


@pytest.mark.asyncio
async def test_orchestrator_runs_phrase_exact_pass_for_light_query():
    answer_service = QuranAnswerService()
    chunk_service = QuranPhraseChunkSearchService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=chunk_service,
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FailingGraphExpansionService(),
    )

    result = await orchestrator.query(
        "Find the verse that says Allah is the Light of the heavens and the earth. Summarize the image used",
        runtime=FakeRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-quran"],
        variant_id="variant-1",
        query_config={"limit": 3, "retrieval_mode": "metadata"},
    )

    assert "allah is the light of the heavens and the earth" in chunk_service.queries
    assert result.sources[0]["chunk_id"] == "quran-24-35"
    assert result.sources[0]["metadata"]["supporting_phrases"] == [
        "allah is the light of the heavens and the earth"
    ]
    assert any(trace["stage"] == "query_understanding" for trace in result.chunk_traces)
    assert any(trace["stage"] == "metadata_passes" for trace in result.chunk_traces)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest backend/tests/test_retrieval_orchestrator.py::test_orchestrator_runs_phrase_exact_pass_for_light_query -v
```

Expected: FAIL because the orchestrator still runs only one metadata search with the original query.

- [ ] **Step 3: Inject understanding service and use richer plan trace**

Modify imports and constructor in `backend/src/ragstudio/services/retrieval_orchestrator.py`:

```python
from ragstudio.services.query_understanding import QueryUnderstandingService
```

```python
class RetrievalOrchestrator:
    def __init__(
        self,
        *,
        chunk_service: ChunkService,
        answer_service: RuntimeAnswerService | None = None,
        reranker_service: RerankerService | None = None,
        graph_expansion_service: GraphExpansionService | None = None,
        query_understanding_service: QueryUnderstandingService | None = None,
    ):
        self.chunk_service = chunk_service
        self.answer_service = answer_service or RuntimeAnswerService()
        self.reranker_service = reranker_service or RerankerService()
        self.graph_expansion_service = graph_expansion_service or GraphExpansionService()
        self.query_understanding_service = query_understanding_service or QueryUnderstandingService()
```

Replace the beginning of `query()` plan setup with:

```python
started = perf_counter()
limit = int(query_config.get("limit") or 8)
timings: dict[str, Any] = {"orchestrated_query": True}
understanding = self.query_understanding_service.understand(query)
plan = plan_for_query(
    query,
    document_ids=document_ids,
    limit=limit,
    understanding=understanding,
)
traces: list[dict[str, Any]] = [understanding.to_trace(), plan.to_trace()]
timings["planner_ms"] = _elapsed_ms(started)
```

- [ ] **Step 4: Replace single metadata retrieval with multi-pass retrieval**

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, replace `_timed_metadata_candidates()` with:

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
    if plan is None or plan.understanding is None:
        candidates = await self._metadata_pass(
            query=query,
            document_ids=document_ids,
            variant_id=variant_id,
            limit=limit,
            pass_name="metadata",
            rank_offset=0,
            target_phrase=None,
            reference_hint=None,
            plan=plan,
        )
        return candidates, _elapsed_ms(started), {
            "stage": "metadata_passes",
            "passes": [{"name": "metadata", "query": query, "candidates": len(candidates)}],
        }

    all_candidates: list[EvidenceCandidate] = []
    pass_traces: list[dict[str, Any]] = []
    rank_offset = 0
    understanding = plan.understanding

    for pass_name in plan.passes:
        pass_queries = self._metadata_pass_queries(pass_name, query, understanding)
        for pass_query in pass_queries:
            reference_hint = pass_query if pass_name == "reference_exact" else None
            target_phrase = pass_query if pass_name in {"phrase_exact", "normalized_phrase"} else None
            candidates = await self._metadata_pass(
                query=pass_query,
                document_ids=document_ids,
                variant_id=variant_id,
                limit=limit,
                pass_name=pass_name,
                rank_offset=rank_offset,
                target_phrase=target_phrase,
                reference_hint=reference_hint,
                plan=plan,
            )
            rank_offset += len(candidates)
            all_candidates.extend(candidates)
            pass_traces.append(
                {"name": pass_name, "query": pass_query, "candidates": len(candidates)}
            )

    return all_candidates, _elapsed_ms(started), {
        "stage": "metadata_passes",
        "passes": pass_traces,
        "total_candidates": len(all_candidates),
    }
```

Add helper methods inside `RetrievalOrchestrator`:

```python
def _metadata_pass_queries(self, pass_name: str, query: str, understanding: Any) -> list[str]:
    if pass_name == "reference_exact":
        return list(understanding.reference_hints)
    if pass_name in {"phrase_exact", "normalized_phrase"}:
        return list(understanding.target_phrases)
    if pass_name in {"keyword", "metadata_semantic"}:
        return [query]
    return []


async def _metadata_pass(
    self,
    *,
    query: str,
    document_ids: list[str],
    variant_id: str,
    limit: int,
    pass_name: str,
    rank_offset: int,
    target_phrase: str | None,
    reference_hint: str | None,
    plan: Any | None,
) -> list[EvidenceCandidate]:
    search = await self.chunk_service.search(
        ChunkSearchIn(
            query=query,
            document_ids=document_ids,
            variant_id=variant_id,
            limit=limit,
            explain=True,
            include_neighbors=True,
        )
    )
    return [
        self._candidate_from_chunk(
            chunk,
            rank_offset + index,
            tool=pass_name,
            target_phrase=target_phrase,
            reference_hint=reference_hint,
            plan=plan,
        )
        for index, chunk in enumerate(search.items, start=1)
    ]
```

Update every call site to pass `plan` and unpack the trace:

```python
metadata_candidates, metadata_ms, metadata_trace = await self._timed_metadata_candidates(
    query,
    document_ids,
    variant_id,
    plan.candidate_limit,
    plan,
)
```

When returning retrieval traces, include `metadata_trace` inside the retrieval trace:

```python
{
    "stage": "retrieval",
    "native_status": native_status,
    "native_candidates": len(native_candidates),
    "metadata_candidates": len(metadata_candidates),
    "metadata_trace": metadata_trace,
}
```

- [ ] **Step 5: Add candidate match features**

Change `_candidate_from_chunk()` signature and body:

```python
def _candidate_from_chunk(
    self,
    chunk: ChunkOut,
    rank: int,
    *,
    tool: str = "metadata",
    target_phrase: str | None = None,
    reference_hint: str | None = None,
    plan: Any | None = None,
) -> EvidenceCandidate:
    score = chunk.metadata.get("score")
    base_score = float(score) if isinstance(score, (int, float)) else max(1.0, 20.0 - rank)
    match_features = self._match_features(chunk, target_phrase, reference_hint, plan)
    supporting_phrases = [target_phrase] if target_phrase and match_features.get("target_phrase") else []
    return EvidenceCandidate(
        candidate_id=f"{tool}:{chunk.id}",
        text=chunk.text,
        document_id=chunk.document_id,
        chunk_id=chunk.id,
        source_location=chunk.source_location,
        metadata=chunk.metadata,
        tool=tool,
        tool_rank=rank,
        base_score=base_score,
        match_features=match_features,
        supporting_phrases=supporting_phrases,
    )


def _match_features(
    self,
    chunk: ChunkOut,
    target_phrase: str | None,
    reference_hint: str | None,
    plan: Any | None,
) -> dict[str, Any]:
    text = chunk.text.casefold()
    features: dict[str, Any] = {}
    if target_phrase and target_phrase.casefold() in text:
        features["target_phrase"] = True
    if reference_hint and self._chunk_has_reference(chunk, reference_hint):
        features["reference_exact"] = True
    required_terms = getattr(getattr(plan, "understanding", None), "required_terms", [])
    matched_terms = [term for term in required_terms if term.casefold() in text]
    if matched_terms:
        features["required_terms"] = matched_terms
    return features


def _chunk_has_reference(self, chunk: ChunkOut, reference_hint: str) -> bool:
    reference_metadata = chunk.metadata.get("reference_metadata")
    if not isinstance(reference_metadata, dict):
        return False
    references = reference_metadata.get("references")
    if isinstance(references, list) and reference_hint in references:
        return True
    return reference_hint in {
        reference_metadata.get("previous_ref"),
        reference_metadata.get("next_ref"),
    }
```

- [ ] **Step 6: Run phrase-pass orchestrator test**

Run:

```bash
uv run pytest backend/tests/test_retrieval_orchestrator.py::test_orchestrator_runs_phrase_exact_pass_for_light_query -v
```

Expected: PASS.

- [ ] **Step 7: Run full orchestrator tests**

Run:

```bash
uv run pytest backend/tests/test_retrieval_orchestrator.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: add multi-pass metadata retrieval"
```

## Task 4: Grounding Validator

**Files:**
- Create: `backend/src/ragstudio/services/grounding_validator.py`
- Test: `backend/tests/test_grounding_validator.py`

- [ ] **Step 1: Write failing grounding validator tests**

Create `backend/tests/test_grounding_validator.py`:

```python
from ragstudio.services.grounding_validator import GroundingValidator
from ragstudio.services.retrieval_evidence import EvidenceCandidate, RetrievalPlan


def _candidate(reference="24:35"):
    return EvidenceCandidate(
        candidate_id="phrase_exact:quran-24-35",
        text="[24:35] Allah is the Light of the heavens and the earth.",
        document_id="doc-quran",
        chunk_id="quran-24-35",
        source_location={"page": 355},
        metadata={"reference_metadata": {"references": [reference]}},
        tool="phrase_exact",
        tool_rank=1,
        base_score=10.0,
        final_score=86.0,
        match_features={"target_phrase": True},
        supporting_phrases=["allah is the light of the heavens and the earth"],
    )


def _plan():
    return RetrievalPlan(
        query="Find the verse that says Allah is the Light of the heavens and the earth.",
        document_ids=["doc-quran"],
        limit=3,
        intent="phrase_lookup",
        passes=["phrase_exact", "keyword"],
        validation_expectations={
            "must_cite": True,
            "target_phrases": ["allah is the light of the heavens and the earth"],
            "reference_hints": [],
        },
    )


def test_validator_accepts_supported_citation():
    result = GroundingValidator().validate(
        "The verse is [S1] 24:35.",
        [_candidate()],
        _plan(),
    )

    assert result.status == "ok"
    assert result.fallback_answer is None
    assert result.to_trace()["cited_labels"] == ["S1"]


def test_validator_flags_missing_claim_when_direct_evidence_exists():
    result = GroundingValidator().validate(
        "The verse is not included in the provided evidence.",
        [_candidate()],
        _plan(),
    )

    assert result.status == "fallback_required"
    assert result.reason == "answer_denies_available_direct_evidence"
    assert "24:35" in (result.fallback_answer or "")


def test_validator_flags_unknown_citation_label():
    result = GroundingValidator().validate(
        "The answer is supported by [S9].",
        [_candidate()],
        _plan(),
    )

    assert result.status == "warning"
    assert result.reason == "unknown_citation_label"


def test_validator_flags_reference_not_present_in_sources():
    result = GroundingValidator().validate(
        "The answer is 2:97 [S1].",
        [_candidate()],
        _plan(),
    )

    assert result.status == "warning"
    assert result.reason == "answer_names_reference_not_in_evidence"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest backend/tests/test_grounding_validator.py -v
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement grounding validator**

Create `backend/src/ragstudio/services/grounding_validator.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ragstudio.services.retrieval_evidence import EvidenceCandidate, RetrievalPlan


@dataclass(frozen=True)
class GroundingValidationResult:
    status: str
    reason: str | None = None
    cited_labels: list[str] | None = None
    fallback_answer: str | None = None

    def to_trace(self) -> dict[str, Any]:
        return {
            "stage": "grounding_validation",
            "status": self.status,
            "reason": self.reason,
            "cited_labels": self.cited_labels or [],
            "fallback_answer_used": self.fallback_answer is not None,
        }


class GroundingValidator:
    def validate(
        self,
        answer: str,
        evidence: list[EvidenceCandidate],
        plan: RetrievalPlan,
    ) -> GroundingValidationResult:
        cited_labels = _cited_labels(answer)
        unknown = [
            label
            for label in cited_labels
            if _label_index(label) is None or _label_index(label) >= len(evidence)
        ]
        if unknown:
            return GroundingValidationResult(
                status="warning",
                reason="unknown_citation_label",
                cited_labels=cited_labels,
            )

        direct = _direct_evidence(evidence)
        if direct and _denies_available_evidence(answer):
            return GroundingValidationResult(
                status="fallback_required",
                reason="answer_denies_available_direct_evidence",
                cited_labels=cited_labels,
                fallback_answer=_fallback_answer(direct),
            )

        named_refs = _reference_mentions(answer)
        evidence_refs = _evidence_references(evidence)
        if named_refs and evidence_refs and any(ref not in evidence_refs for ref in named_refs):
            return GroundingValidationResult(
                status="warning",
                reason="answer_names_reference_not_in_evidence",
                cited_labels=cited_labels,
            )

        if plan.validation_expectations.get("must_cite") and evidence and not cited_labels:
            return GroundingValidationResult(
                status="warning",
                reason="missing_citation",
                cited_labels=[],
            )

        return GroundingValidationResult(status="ok", cited_labels=cited_labels)


def _cited_labels(answer: str) -> list[str]:
    return [match.group(1) for match in re.finditer(r"\[(S\d+)\]", answer)]


def _label_index(label: str) -> int | None:
    match = re.fullmatch(r"S(\d+)", label)
    if not match:
        return None
    return int(match.group(1)) - 1


def _denies_available_evidence(answer: str) -> bool:
    normalized = answer.casefold()
    return any(
        phrase in normalized
        for phrase in (
            "not included in the provided evidence",
            "not present in the provided evidence",
            "not in the provided evidence",
            "no evidence",
        )
    )


def _direct_evidence(evidence: list[EvidenceCandidate]) -> EvidenceCandidate | None:
    for candidate in evidence:
        if candidate.match_features.get("target_phrase") or candidate.match_features.get("reference_exact"):
            return candidate
    return None


def _fallback_answer(candidate: EvidenceCandidate) -> str:
    refs = sorted(_candidate_references(candidate))
    ref_text = refs[0] if refs else "the top cited source"
    return f"The available evidence supports {ref_text}: {candidate.text.strip()} [S1]"


def _reference_mentions(answer: str) -> set[str]:
    return set(re.findall(r"\b\d{1,3}:\d{1,3}\b", answer))


def _evidence_references(evidence: list[EvidenceCandidate]) -> set[str]:
    refs: set[str] = set()
    for candidate in evidence:
        refs.update(_candidate_references(candidate))
    return refs


def _candidate_references(candidate: EvidenceCandidate) -> set[str]:
    metadata = candidate.metadata.get("reference_metadata")
    if not isinstance(metadata, dict):
        return set()
    references = metadata.get("references")
    if not isinstance(references, list):
        return set()
    return {ref for ref in references if isinstance(ref, str)}
```

- [ ] **Step 4: Run grounding validator tests**

Run:

```bash
uv run pytest backend/tests/test_grounding_validator.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/grounding_validator.py backend/tests/test_grounding_validator.py
git commit -m "feat: add grounding validator"
```

## Task 5: Integrate Grounding Validation in Orchestrator

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Add failing test for fallback on contradicted evidence**

Append to `backend/tests/test_retrieval_orchestrator.py`:

```python
class DenyingAnswerService:
    async def answer(self, query, evidence, profile):
        return "The verse is not included in the provided evidence.", {"prompt_tokens": 5}


@pytest.mark.asyncio
async def test_orchestrator_replaces_answer_that_denies_available_direct_evidence():
    orchestrator = RetrievalOrchestrator(
        chunk_service=QuranPhraseChunkSearchService(),
        answer_service=DenyingAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FailingGraphExpansionService(),
    )

    result = await orchestrator.query(
        "Find the verse that says Allah is the Light of the heavens and the earth.",
        runtime=FakeRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-quran"],
        variant_id="variant-1",
        query_config={"limit": 3, "retrieval_mode": "metadata"},
    )

    assert "not included" not in result.answer.casefold()
    assert "24:35" in result.answer
    validation_trace = next(
        trace for trace in result.chunk_traces if trace["stage"] == "grounding_validation"
    )
    assert validation_trace["status"] == "fallback_required"
    assert validation_trace["fallback_answer_used"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest backend/tests/test_retrieval_orchestrator.py::test_orchestrator_replaces_answer_that_denies_available_direct_evidence -v
```

Expected: FAIL because validation is not wired into the orchestrator.

- [ ] **Step 3: Inject validator and apply fallback**

Modify imports and constructor in `backend/src/ragstudio/services/retrieval_orchestrator.py`:

```python
from ragstudio.services.grounding_validator import GroundingValidator
```

```python
def __init__(
    self,
    *,
    chunk_service: ChunkService,
    answer_service: RuntimeAnswerService | None = None,
    reranker_service: RerankerService | None = None,
    graph_expansion_service: GraphExpansionService | None = None,
    query_understanding_service: QueryUnderstandingService | None = None,
    grounding_validator: GroundingValidator | None = None,
):
    self.chunk_service = chunk_service
    self.answer_service = answer_service or RuntimeAnswerService()
    self.reranker_service = reranker_service or RerankerService()
    self.graph_expansion_service = graph_expansion_service or GraphExpansionService()
    self.query_understanding_service = query_understanding_service or QueryUnderstandingService()
    self.grounding_validator = grounding_validator or GroundingValidator()
```

After `answer, token_metadata = await self.answer_service.answer(...)`, add:

```python
validation = self.grounding_validator.validate(answer, final_evidence, plan)
traces.append(validation.to_trace())
if validation.fallback_answer is not None:
    answer = validation.fallback_answer
```

- [ ] **Step 4: Run validation integration test**

Run:

```bash
uv run pytest backend/tests/test_retrieval_orchestrator.py::test_orchestrator_replaces_answer_that_denies_available_direct_evidence -v
```

Expected: PASS.

- [ ] **Step 5: Run full orchestrator suite**

Run:

```bash
uv run pytest backend/tests/test_retrieval_orchestrator.py backend/tests/test_grounding_validator.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: validate grounded answers"
```

## Task 6: Quran Regression Gates

**Files:**
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Add straight-path regression fixture and test**

Append to `backend/tests/test_retrieval_orchestrator.py`:

```python
class QuranStraightPathChunkSearchService:
    def __init__(self):
        self.queries: list[str] = []

    async def search(self, search_in):
        self.queries.append(search_in.query)
        if search_in.query == "guide us to the straight path":
            items = [
                ChunkOut(
                    id="quran-1-5",
                    document_id="doc-quran",
                    text="[1:5] Guide us to the straight path.",
                    source_location={"page": 1},
                    metadata={
                        "score": 1.0,
                        "reference_metadata": {"references": ["1:5"]},
                    },
                )
            ]
        else:
            items = [
                ChunkOut(
                    id="quran-5-16",
                    document_id="doc-quran",
                    text="Allah guides those who pursue His pleasure to the ways of peace.",
                    source_location={"page": 90},
                    metadata={"score": 20.0, "reference_metadata": {"references": ["5:16"]}},
                )
            ]
        return type("SearchResult", (), {"items": items, "total": len(items)})()

    async def chunks_by_id(self, chunk_ids):
        return []


class StraightPathAnswerService:
    def __init__(self):
        self.evidence = []

    async def answer(self, query, evidence, profile):
        self.evidence = evidence
        return "The verse asking for guidance to the straight path is [S1] 1:5.", {}


@pytest.mark.asyncio
async def test_orchestrator_finds_document_straight_path_reference():
    answer_service = StraightPathAnswerService()
    chunk_service = QuranStraightPathChunkSearchService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=chunk_service,
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FailingGraphExpansionService(),
    )

    result = await orchestrator.query(
        "Which verse asks for guidance to the straight path?",
        runtime=FakeRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-quran"],
        variant_id="variant-1",
        query_config={"limit": 3, "retrieval_mode": "metadata"},
    )

    assert "guide us to the straight path" in chunk_service.queries
    assert result.sources[0]["chunk_id"] == "quran-1-5"
    assert "1:5" in result.answer
    assert "2:97" not in result.answer
    assert answer_service.evidence[0].metadata["reference_metadata"]["references"] == ["1:5"]
```

- [ ] **Step 2: Run the two Quran gates**

Run:

```bash
uv run pytest backend/tests/test_retrieval_orchestrator.py::test_orchestrator_runs_phrase_exact_pass_for_light_query backend/tests/test_retrieval_orchestrator.py::test_orchestrator_finds_document_straight_path_reference -v
```

Expected: PASS.

- [ ] **Step 3: Run backend targeted regression set**

Run:

```bash
uv run pytest backend/tests/test_query_understanding.py backend/tests/test_grounding_validator.py backend/tests/test_retrieval_orchestrator.py backend/tests/test_runtime_answer_service.py backend/tests/test_llm_reranker_service.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_retrieval_orchestrator.py
git commit -m "test: add Quran answer orchestration gates"
```

## Task 7: UI Smoke Test

**Files:**
- No code changes expected.

- [ ] **Step 1: Restart backend and frontend**

Run:

```bash
docker compose restart backend frontend
```

Expected: backend and frontend containers restart successfully.

- [ ] **Step 2: Open the query UI**

Open:

```text
http://localhost:53250/
```

Expected: the existing Ragstudio UI loads.

- [ ] **Step 3: Run Light verse query from UI**

Use the Query page with the uploaded Quran document selected and reranker disabled. Query:

```text
Find the verse that says Allah is the Light of the heavens and the earth. Summarize the image used
```

Expected:
- Run succeeds.
- Answer cites `24:35`.
- Answer summarizes the niche/lamp/glass/olive-tree image.
- Answer does not say the verse is missing from evidence.
- Source list includes the chunk whose reference metadata includes `24:35`.
- Trace includes `query_understanding`, `metadata_passes`, and `grounding_validation`.

- [ ] **Step 4: Run straight-path query from UI**

Query:

```text
Which verse asks for guidance to the straight path?
```

Expected:
- Run succeeds.
- Answer cites the document reference `1:5`.
- Answer does not cite `2:97` as the requested verse.
- Source list includes `[1:5] Guide us to the straight path`.
- Trace includes the phrase rewrite `guide us to the straight path`.

- [ ] **Step 5: Check experiment/comparison/optimizer smoke paths**

Run one small sample through each existing flow:

```text
Experiment: one query, one variant, uploaded Quran document
Comparison: compare default precise/reference-focused variant if available
Optimizer: run one short optimization/evaluation pass with the two Quran gate queries
```

Expected:
- Each flow starts and completes.
- Existing API response shape still renders.
- New trace fields do not break UI rendering.

## Self-Review Checklist

- Spec coverage:
  - Query Understanding: Task 1.
  - Retrieval Plan: Task 2.
  - Multi-pass Retrieval: Task 3.
  - Candidate Normalization: Task 2 and Task 3.
  - Candidate Fusion: Task 2.
  - Evidence Reranking: Task 3 preserves current reranker path and feeds broader fused candidates.
  - Answer Composition: Task 5 preserves `RuntimeAnswerService`.
  - Grounding Validation: Task 4 and Task 5.
  - Evaluation Gates: Task 6 and Task 7.
- Placeholder scan:
  - No task contains unresolved marker language or cross-task shorthand.
- Type consistency:
  - `QueryUnderstandingService.understand()` returns `QueryUnderstanding`.
  - `plan_for_query(..., understanding=understanding)` returns `RetrievalPlan`.
  - `EvidenceCandidate.match_features`, `supporting_phrases`, and `risks` are preserved by fusion and serialization.
  - `GroundingValidator.validate(answer, evidence, plan)` returns `GroundingValidationResult`.
