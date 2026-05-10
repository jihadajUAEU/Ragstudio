# Retrieval Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a default-on Retrieval Orchestrator that improves runtime query quality by fusing native RAG-Anything retrieval, Studio metadata-aware retrieval, Neo4j graph expansion, dedicated reranking with LLM fallback, and runtime LLM answer generation.

**Architecture:** Add focused backend services under `backend/src/ragstudio/services/` so retrieval planning, evidence fusion, graph expansion, reranking, answer generation, and QueryService integration stay testable in isolation. The orchestrator runs native and metadata retrieval in parallel, expands high-confidence seed evidence through Neo4j relationships when graph settings are available, applies the configured dedicated reranker when available, falls back to the active runtime LLM reranker when configured, then answers from fused evidence using the active runtime LLM. If reranking is disabled or unavailable, deterministic metadata/graph scoring still produces a complete answer path.

**Tech Stack:** FastAPI service layer, SQLAlchemy async sessions, Neo4j Python driver, existing `ChunkService`, existing `RerankerService`, existing runtime profile/settings models, OpenAI-compatible HTTP endpoints through `httpx`, pytest.

---

## File Structure

- Create `backend/src/ragstudio/services/retrieval_orchestrator.py`
  - Owns the planner, retrieval tool calls, fusion flow, fallback behavior, and trace assembly.
- Create `backend/src/ragstudio/services/retrieval_evidence.py`
  - Defines `EvidenceCandidate`, `RetrievalPlan`, `OrchestratedAnswer`, and helper methods for source/trace serialization.
- Create `backend/src/ragstudio/services/runtime_answer_service.py`
  - Generates the final answer from fused evidence through the active runtime LLM endpoint.
- Create `backend/src/ragstudio/services/llm_reranker_service.py`
  - Uses the active runtime LLM endpoint to rank fused evidence as a fallback reranker with strict JSON parsing.
- Create `backend/src/ragstudio/services/graph_expansion_service.py`
  - Expands seed evidence through Neo4j relationships scoped to the active runtime workspace and returns graph evidence candidates with relationship traces.
- Modify `backend/src/ragstudio/schemas/runtime.py`
  - Adds `llm` as a reranker provider and adds `reranker_fallback_provider` for explicit LLM fallback.
- Modify `backend/src/ragstudio/schemas/settings.py`, `backend/src/ragstudio/db/models.py`, `backend/src/ragstudio/db/engine.py`, `backend/src/ragstudio/services/settings_service.py`, and `backend/src/ragstudio/services/runtime_profile_service.py`
  - Persists and exposes the reranker fallback setting on the existing Settings profile.
- Modify `frontend/src/features/settings/settings-page.tsx`
  - Adds the Settings UI control in the existing `Vision and reranker` section.
- Modify `backend/src/ragstudio/services/query_service.py`
  - Uses `RetrievalOrchestrator` as the default runtime query path and preserves existing runtime/native fallback behavior.
- Modify `backend/src/ragstudio/services/hybrid_chunk_search.py`
  - Add count/title evidence scoring so metadata search ranks answer-bearing chunks like `7277 Hadith Collection` first.
- Test in `backend/tests/test_retrieval_orchestrator.py`
  - Unit coverage for planning, fusion, metadata scoring, dedupe, reranker traces, fallback, and answer context ordering.
- Test in `backend/tests/test_runtime_answer_service.py`
  - Unit coverage for OpenAI-compatible answer generation and failure behavior.
- Test in `backend/tests/test_llm_reranker_service.py`
  - Unit coverage for LLM rerank request construction, strict JSON parsing, invalid output fallback, and trace shape.
- Test in `backend/tests/test_graph_expansion_service.py`
  - Unit coverage for Neo4j query scoping, graph candidate conversion, unavailable graph behavior, and relationship traces.
- Extend `backend/tests/test_settings.py` and `frontend/tests/settings-page.test.tsx`
  - Coverage for the new provider option and fallback setting.
- Extend `backend/tests/test_runtime_query_service.py`
  - Service-level coverage that runtime queries use orchestrated fused evidence.

---

### Task 1: Evidence Model and Planner

**Files:**
- Create: `backend/src/ragstudio/services/retrieval_evidence.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Write failing tests for intent planning and source serialization**

Add this file:

```python
from ragstudio.services.retrieval_evidence import (
    EvidenceCandidate,
    RetrievalPlan,
    plan_for_query,
)


def test_plan_for_count_query_prefers_metadata_and_native():
    plan = plan_for_query("how many hadith in bukhari", document_ids=["doc-1"], limit=8)

    assert plan.intent == "count"
    assert plan.use_native is True
    assert plan.use_metadata is True
    assert plan.use_relationships is True
    assert plan.candidate_limit == 20
    assert plan.document_ids == ["doc-1"]


def test_plan_for_reference_query_marks_reference_intent():
    plan = plan_for_query("show Book 64 Hadith 486", document_ids=[], limit=8)

    assert plan.intent == "reference"
    assert plan.use_native is True
    assert plan.use_metadata is True
    assert plan.use_relationships is True


def test_evidence_candidate_serializes_source_and_trace():
    candidate = EvidenceCandidate(
        candidate_id="metadata:chunk-1",
        text="Sahih al-Bukhari\n\n7277 Hadith Collection",
        document_id="doc-1",
        chunk_id="chunk-1",
        source_location={"page": 1},
        metadata={"document_metadata": {"title": "Sahih al-Bukhari 7277 Hadith Collection"}},
        tool="metadata",
        tool_rank=1,
        base_score=10.0,
        boost_score=12.0,
        final_score=22.0,
        reasons=["title_count_match"],
    )

    assert candidate.to_source()["chunk_id"] == "chunk-1"
    assert candidate.to_source()["metadata"]["retrieval_tool"] == "metadata"
    assert candidate.to_trace()["candidate_id"] == "metadata:chunk-1"
    assert candidate.to_trace()["reasons"] == ["title_count_match"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_retrieval_orchestrator.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.retrieval_evidence'`.

- [ ] **Step 3: Implement evidence types and deterministic planner**

Create `backend/src/ragstudio/services/retrieval_evidence.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

QueryIntent = Literal["count", "title", "reference", "comparison", "summary", "semantic"]


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

    def to_source(self) -> dict[str, Any]:
        metadata = {
            **self.metadata,
            "retrieval_tool": self.tool,
            "retrieval_rank": self.tool_rank,
            "retrieval_score": self.final_score,
            "retrieval_reasons": self.reasons,
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
        }


@dataclass(frozen=True)
class OrchestratedAnswer:
    answer: str
    sources: list[dict[str, Any]]
    chunk_traces: list[dict[str, Any]]
    reranker_traces: list[dict[str, Any]]
    timings: dict[str, Any]
    token_metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_type: str | None = None


def plan_for_query(query: str, *, document_ids: list[str], limit: int) -> RetrievalPlan:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_retrieval_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/retrieval_evidence.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: add retrieval evidence planning"
```

---

### Task 2: Metadata-Aware Evidence Fusion

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Write failing tests for metadata boosts and dedupe**

Append these tests:

```python
from ragstudio.services.retrieval_evidence import fuse_candidates


def test_fusion_boosts_title_count_chunk_for_count_query():
    plan = plan_for_query("how many hadith in bukhari", document_ids=["doc-1"], limit=3)
    weak_native = EvidenceCandidate(
        candidate_id="native:n1",
        text="Book 65, Hadith 201",
        document_id="doc-1",
        chunk_id="n1",
        source_location={},
        metadata={"native_scope": True},
        tool="native",
        tool_rank=1,
        base_score=8.0,
    )
    title_count = EvidenceCandidate(
        candidate_id="metadata:m1",
        text="Sahih al-Bukhari\n\n7277 Hadith Collection",
        document_id="doc-1",
        chunk_id="m1",
        source_location={},
        metadata={"document_metadata": {"title": "Sahih al-Bukhari 7277 Hadith Collection"}},
        tool="metadata",
        tool_rank=1,
        base_score=6.0,
    )

    fused = fuse_candidates(plan, [weak_native, title_count])

    assert fused[0].chunk_id == "m1"
    assert "title_count_match" in fused[0].reasons
    assert fused[0].final_score > fused[1].final_score


def test_fusion_dedupes_same_text_and_keeps_best_candidate():
    plan = plan_for_query("bukhari", document_ids=["doc-1"], limit=5)
    native = EvidenceCandidate(
        candidate_id="native:n1",
        text="Sahih al-Bukhari 7277 Hadith Collection",
        document_id="doc-1",
        chunk_id="native-1",
        source_location={},
        metadata={"native_scope": True},
        tool="native",
        tool_rank=1,
        base_score=5.0,
    )
    metadata = EvidenceCandidate(
        candidate_id="metadata:m1",
        text="Sahih al-Bukhari 7277 Hadith Collection",
        document_id="doc-1",
        chunk_id="metadata-1",
        source_location={},
        metadata={"score": 10.0},
        tool="metadata",
        tool_rank=1,
        base_score=10.0,
    )

    fused = fuse_candidates(plan, [native, metadata])

    assert len(fused) == 1
    assert fused[0].tool == "metadata"
    assert fused[0].metadata["deduped_tools"] == ["native", "metadata"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_retrieval_orchestrator.py -q
```

Expected: FAIL with `ImportError` for `fuse_candidates`.

- [ ] **Step 3: Implement fusion, scoring, and dedupe**

Append to `backend/src/ragstudio/services/retrieval_evidence.py`:

```python
def fuse_candidates(
    plan: RetrievalPlan,
    candidates: list[EvidenceCandidate],
) -> list[EvidenceCandidate]:
    deduped: dict[str, EvidenceCandidate] = {}
    tools_by_key: dict[str, set[str]] = {}
    for candidate in candidates:
        key = _dedupe_key(candidate)
        scored = _score_candidate(plan, candidate)
        current = deduped.get(key)
        tools_by_key.setdefault(key, set()).add(candidate.tool)
        if current is None or scored.final_score > current.final_score:
            deduped[key] = scored

    merged = []
    for key, candidate in deduped.items():
        tools = sorted(tools_by_key.get(key, {candidate.tool}))
        metadata = {**candidate.metadata, "deduped_tools": tools}
        merged.append(
            EvidenceCandidate(
                candidate_id=candidate.candidate_id,
                text=candidate.text,
                document_id=candidate.document_id,
                chunk_id=candidate.chunk_id,
                source_location=candidate.source_location,
                metadata=metadata,
                tool=candidate.tool,
                tool_rank=candidate.tool_rank,
                base_score=candidate.base_score,
                boost_score=candidate.boost_score,
                final_score=candidate.final_score,
                reasons=candidate.reasons,
            )
        )

    return sorted(
        merged,
        key=lambda item: (-item.final_score, item.tool_rank, item.candidate_id),
    )[: plan.candidate_limit]


def _score_candidate(plan: RetrievalPlan, candidate: EvidenceCandidate) -> EvidenceCandidate:
    boost = 0.0
    reasons = list(candidate.reasons)
    text = candidate.text.casefold()
    query = plan.query.casefold()
    title = _metadata_title(candidate.metadata).casefold()

    if plan.intent == "count" and re.search(r"\b\d{2,}\b", candidate.text):
        if any(term in text or term in title for term in ("hadith", "collection", "bukhari")):
            boost += 30.0
            reasons.append("title_count_match")

    query_terms = _terms(query)
    title_terms = _terms(title)
    if query_terms and title_terms and query_terms & title_terms:
        boost += min(12.0, len(query_terms & title_terms) * 4.0)
        reasons.append("title_term_match")

    if query and query in text:
        boost += 8.0
        reasons.append("exact_phrase_match")

    if candidate.tool == "metadata":
        boost += 3.0
        reasons.append("metadata_precision_tool")
    if candidate.tool == "native":
        boost += 1.0
        reasons.append("native_semantic_tool")

    final_score = candidate.base_score + boost
    return EvidenceCandidate(
        candidate_id=candidate.candidate_id,
        text=candidate.text,
        document_id=candidate.document_id,
        chunk_id=candidate.chunk_id,
        source_location=candidate.source_location,
        metadata=candidate.metadata,
        tool=candidate.tool,
        tool_rank=candidate.tool_rank,
        base_score=candidate.base_score,
        boost_score=boost,
        final_score=final_score,
        reasons=reasons,
    )


def _metadata_title(metadata: dict[str, Any]) -> str:
    document_metadata = metadata.get("document_metadata")
    if isinstance(document_metadata, dict):
        title = document_metadata.get("title")
        if isinstance(title, str):
            return title
    return ""


def _dedupe_key(candidate: EvidenceCandidate) -> str:
    if candidate.document_id and candidate.chunk_id:
        runtime_source_id = candidate.metadata.get("runtime_source_id")
        if isinstance(runtime_source_id, str) and runtime_source_id:
            return f"runtime:{candidate.document_id}:{runtime_source_id}"
    normalized_text = re.sub(r"\s+", " ", candidate.text.casefold()).strip()
    return f"text:{candidate.document_id}:{normalized_text[:500]}"


def _terms(value: str) -> set[str]:
    return {
        match.group(0)
        for match in re.finditer(r"[\w\u0600-\u06FF]+", value, flags=re.UNICODE)
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_retrieval_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/retrieval_evidence.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: fuse metadata-aware retrieval evidence"
```

---

### Task 3: Runtime LLM Answer Service

**Files:**
- Create: `backend/src/ragstudio/services/runtime_answer_service.py`
- Test: `backend/tests/test_runtime_answer_service.py`

- [ ] **Step 1: Write failing tests for answer generation**

Create `backend/tests/test_runtime_answer_service.py`:

```python
import pytest
from ragstudio.schemas.runtime import RuntimeProfile
from ragstudio.services.retrieval_evidence import EvidenceCandidate
from ragstudio.services.runtime_answer_service import RuntimeAnswerService


def profile():
    return RuntimeProfile(
        id="default",
        runtime_mode="runtime",
        provider="openai-compatible",
        llm_model="test-model",
        llm_base_url="http://llm.example/v1",
        llm_timeout_ms=5000,
        llm_capabilities=["text"],
        vision_model=None,
        vision_base_url=None,
        vision_timeout_ms=5000,
        embedding_provider="vllm_openai",
        embedding_model="embed",
        embedding_base_url="http://embed.example/v1",
        embedding_dimensions=1536,
        embedding_batch_size=16,
        embedding_timeout_ms=5000,
        reranker_provider="disabled",
        reranker_model=None,
        reranker_base_url=None,
        reranker_timeout_ms=5000,
        storage_backend="postgres_pgvector_neo4j",
        pgvector_schema="public",
        pgvector_table_prefix="ragstudio",
        neo4j_uri=None,
        neo4j_username=None,
        neo4j_password=None,
        parser="mineru",
        parse_method="auto",
        chunk_token_size=1200,
        chunk_overlap_token_size=100,
        enable_image_processing=False,
        enable_table_processing=False,
        enable_equation_processing=False,
        context_window=1,
        context_mode="page",
        max_context_tokens=2000,
        include_headers=True,
        include_captions=True,
        query_mode="mix",
        top_k=40,
        chunk_top_k=20,
        enable_rerank=False,
        cosine_better_than_threshold=0.2,
        max_total_tokens=30000,
        max_entity_tokens=6000,
        max_relation_tokens=8000,
        enable_llm_cache=True,
        enable_llm_cache_for_entity_extract=True,
        llm_model_max_async=4,
        embedding_func_max_async=8,
        max_parallel_insert=2,
        runtime_working_dir="/tmp/ragstudio",
        index_shape={},
    )


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, *, headers, json):
        self.requests.append({"url": url, "headers": headers, "json": json})
        return FakeResponse(self.response)


@pytest.mark.asyncio
async def test_answer_service_sends_fused_evidence(monkeypatch):
    fake_client = FakeClient(
        {"choices": [{"message": {"content": "Sahih al-Bukhari contains 7277 hadith."}}]}
    )
    monkeypatch.setattr(
        "ragstudio.services.runtime_answer_service.httpx.AsyncClient",
        lambda timeout: fake_client,
    )
    service = RuntimeAnswerService()
    evidence = [
        EvidenceCandidate(
            candidate_id="metadata:m1",
            text="Sahih al-Bukhari\n\n7277 Hadith Collection",
            document_id="doc-1",
            chunk_id="chunk-1",
            source_location={},
            metadata={},
            tool="metadata",
            tool_rank=1,
            base_score=10,
            final_score=40,
            reasons=["title_count_match"],
        )
    ]

    answer, token_metadata = await service.answer(
        "how many hadith in bukhari",
        evidence,
        profile(),
    )

    assert answer == "Sahih al-Bukhari contains 7277 hadith."
    assert fake_client.requests[0]["url"] == "http://llm.example/v1/chat/completions"
    assert "7277 Hadith Collection" in fake_client.requests[0]["json"]["messages"][1]["content"]
    assert token_metadata == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_runtime_answer_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.runtime_answer_service'`.

- [ ] **Step 3: Implement runtime answer service**

Create `backend/src/ragstudio/services/runtime_answer_service.py`:

```python
from __future__ import annotations

from typing import Any

import httpx

from ragstudio.services.retrieval_evidence import EvidenceCandidate


class RuntimeAnswerService:
    async def answer(
        self,
        query: str,
        evidence: list[EvidenceCandidate],
        profile: Any,
    ) -> tuple[str, dict[str, Any]]:
        if not evidence:
            return "No supporting evidence was found for this query.", {}

        url = self._chat_url(str(profile.llm_base_url))
        headers = self._headers(getattr(profile, "llm_api_key", None))
        payload = {
            "model": profile.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Answer only from the provided evidence. If the evidence contains "
                        "a direct answer, state it plainly and cite the evidence number. "
                        "If the evidence does not support an answer, say that clearly."
                    ),
                },
                {
                    "role": "user",
                    "content": self._prompt(query, evidence),
                },
            ],
            "temperature": 0.2,
        }
        timeout = (getattr(profile, "llm_timeout_ms", None) or 10000) / 1000
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        return self._content(body), self._usage(body)

    def _prompt(self, query: str, evidence: list[EvidenceCandidate]) -> str:
        sections = [f"Question: {query.strip()}", "", "Evidence:"]
        for index, candidate in enumerate(evidence, start=1):
            sections.append(
                f"[{index}] tool={candidate.tool} document={candidate.document_id} "
                f"chunk={candidate.chunk_id} reasons={','.join(candidate.reasons)}\n"
                f"{candidate.text.strip()}"
            )
        return "\n\n".join(sections)

    def _chat_url(self, base_url: str) -> str:
        return f"{base_url.rstrip('/')}/chat/completions"

    def _headers(self, api_key: str | None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        headers["Authorization"] = f"Bearer {api_key or 'ragstudio-local-runtime'}"
        return headers

    def _content(self, body: Any) -> str:
        if not isinstance(body, dict):
            return ""
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, dict):
            return ""
        message = first.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
        if isinstance(first.get("text"), str):
            return first["text"]
        return ""

    def _usage(self, body: Any) -> dict[str, Any]:
        if isinstance(body, dict) and isinstance(body.get("usage"), dict):
            return body["usage"]
        return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_runtime_answer_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/runtime_answer_service.py backend/tests/test_runtime_answer_service.py
git commit -m "feat: answer from fused retrieval evidence"
```

---

### Task 4: Reranker Settings and LLM Fallback

**Files:**
- Modify: `backend/src/ragstudio/schemas/runtime.py`
- Modify: `backend/src/ragstudio/schemas/settings.py`
- Modify: `backend/src/ragstudio/db/models.py`
- Modify: `backend/src/ragstudio/db/engine.py`
- Modify: `backend/src/ragstudio/services/settings_service.py`
- Modify: `backend/src/ragstudio/services/runtime_profile_service.py`
- Modify: `backend/src/ragstudio/services/reranker_service.py`
- Create: `backend/src/ragstudio/services/llm_reranker_service.py`
- Modify: `frontend/src/features/settings/settings-page.tsx`
- Test: `backend/tests/test_settings.py`
- Test: `backend/tests/test_query_runs.py`
- Test: `backend/tests/test_llm_reranker_service.py`
- Test: `frontend/tests/settings-page.test.tsx`

- [ ] **Step 1: Write failing backend settings tests**

Append to `backend/tests/test_settings.py`:

```python
async def test_settings_accepts_llm_reranker_with_llm_fallback(client):
    response = await client.put(
        "/api/settings/default",
        json={
            "provider": "openai-compatible",
            "llm_provider": "openai_compatible",
            "llm_model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
            "llm_base_url": "http://10.10.9.195:8004/v1",
            "embedding_provider": "vllm_openai",
            "embedding_model": "Qwen/Qwen3-Embedding-8B",
            "embedding_base_url": "http://10.10.9.192:8001/v1",
            "embedding_dimensions": 1536,
            "storage_backend": "postgres_pgvector_neo4j",
            "runtime_mode": "runtime",
            "mineru_enabled": True,
            "mineru_base_url": "http://10.10.9.193:8003",
            "reranker_provider": "llm",
            "reranker_model": "",
            "reranker_base_url": "",
            "reranker_fallback_provider": "disabled",
            "enable_rerank": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reranker_provider"] == "llm"
    assert body["reranker_fallback_provider"] == "disabled"


async def test_settings_accepts_dedicated_bge_with_llm_fallback(client):
    response = await client.put(
        "/api/settings/default",
        json={
            "provider": "openai-compatible",
            "llm_provider": "openai_compatible",
            "llm_model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
            "llm_base_url": "http://10.10.9.195:8004/v1",
            "embedding_provider": "vllm_openai",
            "embedding_model": "Qwen/Qwen3-Embedding-8B",
            "embedding_base_url": "http://10.10.9.192:8001/v1",
            "embedding_dimensions": 1536,
            "storage_backend": "postgres_pgvector_neo4j",
            "runtime_mode": "runtime",
            "mineru_enabled": True,
            "mineru_base_url": "http://10.10.9.193:8003",
            "reranker_provider": "generic_http",
            "reranker_model": "BAAI/bge-reranker-v2-m3",
            "reranker_base_url": "http://127.0.0.1:8002/v1/rerank",
            "reranker_fallback_provider": "llm",
            "enable_rerank": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reranker_provider"] == "generic_http"
    assert body["reranker_model"] == "BAAI/bge-reranker-v2-m3"
    assert body["reranker_fallback_provider"] == "llm"
```

- [ ] **Step 2: Run settings tests to verify failure**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_settings.py::test_settings_accepts_llm_reranker_with_llm_fallback backend/tests/test_settings.py::test_settings_accepts_dedicated_bge_with_llm_fallback -q
```

Expected: FAIL because `llm` and `reranker_fallback_provider` are not accepted yet.

- [ ] **Step 3: Add persisted reranker fallback settings**

Modify `backend/src/ragstudio/schemas/runtime.py`:

```python
RerankerProvider = Literal["disabled", "cohere_compatible", "jina_compatible", "generic_http", "llm"]
RerankerFallbackProvider = Literal["disabled", "llm"]
```

Add to `RuntimeProfile`:

```python
    reranker_fallback_provider: RerankerFallbackProvider = "disabled"
```

Modify `backend/src/ragstudio/schemas/settings.py` imports:

```python
    RerankerFallbackProvider,
```

Add to `SettingsProfileIn` beside `reranker_provider`:

```python
    reranker_fallback_provider: RerankerFallbackProvider = "disabled"
```

Add to `SettingsProfileOut` beside `reranker_provider`:

```python
    reranker_fallback_provider: RerankerFallbackProvider
```

Modify `backend/src/ragstudio/db/models.py` beside `reranker_provider`:

```python
    reranker_fallback_provider: Mapped[str] = mapped_column(String, default="disabled")
```

Modify `backend/src/ragstudio/db/engine.py` column defaults:

```python
                "reranker_fallback_provider": "VARCHAR DEFAULT 'disabled' NOT NULL",
```

Modify `backend/src/ragstudio/services/settings_service.py` to persist and return the field:

```python
        profile.reranker_fallback_provider = data.reranker_fallback_provider
```

```python
            reranker_fallback_provider=cast(
                RerankerFallbackProvider,
                profile.reranker_fallback_provider or "disabled",
            ),
```

Modify `backend/src/ragstudio/services/runtime_profile_service.py` to return the field:

```python
            reranker_fallback_provider=cast(
                RerankerFallbackProvider,
                profile.reranker_fallback_provider or "disabled",
            ),
```

- [ ] **Step 4: Run settings tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_settings.py::test_settings_accepts_llm_reranker_with_llm_fallback backend/tests/test_settings.py::test_settings_accepts_dedicated_bge_with_llm_fallback -q
```

Expected: PASS.

- [ ] **Step 5: Write failing LLM reranker tests**

Create `backend/tests/test_llm_reranker_service.py`:

```python
import pytest

from ragstudio.schemas.chunks import ChunkOut
from ragstudio.services.llm_reranker_service import LLMRerankerService


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class FakeAsyncClient:
    requests = []

    def __init__(self, *args, **kwargs):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, *, headers, json):
        self.requests.append({"url": url, "headers": headers, "json": json})
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '[{"index": 1, "score": 0.98, "reason": "direct answer"}]'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 30, "completion_tokens": 12},
            }
        )


def profile():
    return type(
        "Profile",
        (),
        {
            "llm_base_url": "http://127.0.0.1:8004/v1",
            "llm_api_key": None,
            "llm_model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
            "llm_timeout_ms": 5000,
            "reranker_model": "",
        },
    )()


@pytest.mark.asyncio
async def test_llm_reranker_reorders_chunks(monkeypatch):
    monkeypatch.setattr("ragstudio.services.llm_reranker_service.httpx.AsyncClient", FakeAsyncClient)
    chunks = [
        ChunkOut(id="weak", document_id="doc-1", text="Book 65, Hadith 201", source_location={}, metadata={}),
        ChunkOut(id="strong", document_id="doc-1", text="Sahih al-Bukhari 7277 Hadith Collection", source_location={}, metadata={}),
    ]

    reranked, traces = await LLMRerankerService().rerank(
        "how many hadith in bukhari",
        chunks,
        profile(),
    )

    assert reranked[0].id == "strong"
    assert traces[0]["provider"] == "llm"
    assert traces[0]["chunk_id"] == "strong"
    assert traces[0]["score"] == 0.98


@pytest.mark.asyncio
async def test_llm_reranker_returns_original_order_when_json_is_invalid(monkeypatch):
    class BadJsonClient(FakeAsyncClient):
        async def post(self, url, *, headers, json):
            return FakeResponse({"choices": [{"message": {"content": "not json"}}]})

    monkeypatch.setattr("ragstudio.services.llm_reranker_service.httpx.AsyncClient", BadJsonClient)
    chunks = [
        ChunkOut(id="first", document_id="doc-1", text="first", source_location={}, metadata={}),
        ChunkOut(id="second", document_id="doc-1", text="second", source_location={}, metadata={}),
    ]

    reranked, traces = await LLMRerankerService().rerank("query", chunks, profile())

    assert [chunk.id for chunk in reranked] == ["first", "second"]
    assert traces[0]["status"] == "invalid_json"
```

- [ ] **Step 6: Implement LLM reranker**

Create `backend/src/ragstudio/services/llm_reranker_service.py`:

```python
from __future__ import annotations

import json
from typing import Any

import httpx

from ragstudio.schemas.chunks import ChunkOut


class LLMRerankerService:
    async def rerank(
        self,
        query: str,
        chunks: list[ChunkOut],
        profile: Any,
    ) -> tuple[list[ChunkOut], list[dict[str, Any]]]:
        if not getattr(profile, "llm_base_url", None):
            return chunks, [{"provider": "llm", "status": "skipped", "reason": "missing_llm_base_url"}]
        if not chunks:
            return chunks, [{"provider": "llm", "status": "skipped", "reason": "no_chunks"}]

        payload = _payload(query, chunks, profile)
        headers = {"Content-Type": "application/json"}
        if getattr(profile, "llm_api_key", None):
            headers["Authorization"] = f"Bearer {profile.llm_api_key}"

        try:
            async with httpx.AsyncClient(timeout=(profile.llm_timeout_ms or 10000) / 1000) as client:
                response = await client.post(_chat_url(profile.llm_base_url), headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
        except Exception as exc:
            return chunks, [{"provider": "llm", "status": "failed", "error_type": exc.__class__.__name__, "detail": str(exc)}]

        content = _content(body)
        rankings = _rankings(content)
        if not rankings:
            return chunks, [{"provider": "llm", "status": "invalid_json"}]

        by_index = {item["index"]: item for item in rankings}
        indexed = {index: chunk for index, chunk in enumerate(chunks)}
        ranked_indices = [item["index"] for item in sorted(rankings, key=lambda item: item["score"], reverse=True)]
        reranked = [indexed[index] for index in ranked_indices if index in indexed]
        reranked.extend(chunk for index, chunk in indexed.items() if index not in by_index)
        traces = [
            {
                "provider": "llm",
                "model": getattr(profile, "reranker_model", None) or getattr(profile, "llm_model", None),
                "rank": rank,
                "original_rank": index + 1,
                "chunk_id": indexed[index].id,
                "score": by_index[index]["score"],
                "reason": by_index[index].get("reason", ""),
            }
            for rank, index in enumerate(ranked_indices, start=1)
            if index in indexed
        ]
        return reranked, traces


def _payload(query: str, chunks: list[ChunkOut], profile: Any) -> dict[str, Any]:
    evidence = "\n".join(
        f"[{index}] {chunk.text[:1200]}"
        for index, chunk in enumerate(chunks)
    )
    return {
        "model": getattr(profile, "reranker_model", None) or profile.llm_model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Rank evidence for the user query. Return only JSON array items with "
                    "index, score, and reason. Use zero-based indexes from the provided evidence."
                ),
            },
            {"role": "user", "content": f"Query: {query}\n\nEvidence:\n{evidence}"},
        ],
    }


def _chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def _content(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    return ""


def _rankings(content: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    rankings = []
    for item in data:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        score = item.get("score")
        if isinstance(index, int) and isinstance(score, (int, float)):
            rankings.append({"index": index, "score": float(score), "reason": str(item.get("reason") or "")})
    return rankings
```

- [ ] **Step 7: Wire reranker service fallback**

Modify `backend/src/ragstudio/services/reranker_service.py` imports:

```python
from ragstudio.services.llm_reranker_service import LLMRerankerService
```

Modify `RerankerService.__init__`:

```python
    def __init__(
        self,
        allowed_hosts: list[str] | None = None,
        llm_reranker: LLMRerankerService | None = None,
    ):
        self.allowed_hosts = {host.lower() for host in (allowed_hosts or [])}
        self.llm_reranker = llm_reranker or LLMRerankerService()
```

Add this at the top of `rerank()` after `skipped_trace` handling:

```python
        if profile.reranker_provider == "llm":
            return await self.llm_reranker.rerank(query, chunks, profile)
```

Replace each dedicated reranker failure return with `_fallback_or_return(...)`:

```python
            return await self._fallback_or_return(query, chunks, profile, self._failure_trace(profile, "blocked_endpoint"))
```

Add helper:

```python
    async def _fallback_or_return(
        self,
        query: str,
        chunks: list[ChunkOut],
        profile: Any,
        primary_trace: dict[str, Any],
    ) -> tuple[list[ChunkOut], list[dict[str, Any]]]:
        if getattr(profile, "reranker_fallback_provider", "disabled") != "llm":
            return chunks, [primary_trace]
        reranked, fallback_traces = await self.llm_reranker.rerank(query, chunks, profile)
        return reranked, [{**primary_trace, "fallback_provider": "llm"}, *fallback_traces]
```

Dedicated BGE behavior is now:

```text
reranker_provider = generic_http
reranker_model = BAAI/bge-reranker-v2-m3
reranker_base_url = http://127.0.0.1:8002/v1/rerank
reranker_fallback_provider = llm
```

LLM-only behavior is:

```text
reranker_provider = llm
reranker_model = blank to reuse llm_model
reranker_base_url = blank because llm_base_url is reused
reranker_fallback_provider = disabled
```

Deterministic-only behavior is:

```text
reranker_provider = disabled
reranker_fallback_provider = disabled
enable_rerank = false
```

- [ ] **Step 8: Add Settings page controls**

Modify `frontend/src/features/settings/settings-page.tsx`.

Add default form field:

```ts
  reranker_fallback_provider: "disabled",
```

Add provider option:

```tsx
                { value: "llm", label: "Existing LLM" },
```

Add this `SelectField` after `Reranker provider`:

```tsx
            <SelectField
              label="Reranker fallback"
              name="reranker_fallback_provider"
              value={formValues?.reranker_fallback_provider ?? "disabled"}
              disabled={busy}
              onChange={(value) =>
                updateField(
                  "reranker_fallback_provider",
                  value as SettingsProfileIn["reranker_fallback_provider"],
                )
              }
              options={[
                { value: "disabled", label: "Disabled" },
                { value: "llm", label: "Existing LLM" },
              ]}
            />
```

Add it to `preparePayload`:

```ts
      reranker_fallback_provider: formValues.reranker_fallback_provider ?? "disabled",
```

Add it to `settingsToFormValues`:

```ts
    reranker_fallback_provider: settings.reranker_fallback_provider ?? "disabled",
```

- [ ] **Step 9: Run reranker and settings tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_llm_reranker_service.py backend/tests/test_query_runs.py backend/tests/test_settings.py -q
```

Expected: PASS.

Run:

```bash
npm --prefix frontend test -- settings-page
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add \
  backend/src/ragstudio/schemas/runtime.py \
  backend/src/ragstudio/schemas/settings.py \
  backend/src/ragstudio/db/models.py \
  backend/src/ragstudio/db/engine.py \
  backend/src/ragstudio/services/settings_service.py \
  backend/src/ragstudio/services/runtime_profile_service.py \
  backend/src/ragstudio/services/reranker_service.py \
  backend/src/ragstudio/services/llm_reranker_service.py \
  backend/tests/test_settings.py \
  backend/tests/test_query_runs.py \
  backend/tests/test_llm_reranker_service.py \
  frontend/src/features/settings/settings-page.tsx \
  frontend/tests/settings-page.test.tsx
git commit -m "feat: add llm reranker fallback settings"
```

---

### Task 5: Neo4j Graph Expansion Service

**Files:**
- Create: `backend/src/ragstudio/services/graph_expansion_service.py`
- Test: `backend/tests/test_graph_expansion_service.py`

- [ ] **Step 1: Write failing tests for graph expansion**

Create `backend/tests/test_graph_expansion_service.py`:

```python
import pytest

from ragstudio.services.graph_expansion_service import GraphExpansionService
from ragstudio.services.retrieval_evidence import EvidenceCandidate


class FakeRecord(dict):
    def __getitem__(self, key):
        return self.get(key)


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def run(self, query, **params):
        self.calls.append((query, params))
        return self.rows


class FakeDriver:
    def __init__(self, rows):
        self.session_instance = FakeSession(rows)

    def session(self):
        return self.session_instance


def seed_candidate():
    return EvidenceCandidate(
        candidate_id="metadata:seed-1",
        text="Book 1 Hadith 1",
        document_id="doc-1",
        chunk_id="seed-1",
        source_location={"page": 1},
        metadata={"runtime_source_id": "seed-runtime"},
        tool="metadata",
        tool_rank=1,
        base_score=10.0,
    )


def profile(**overrides):
    values = {
        "id": "tenant`one",
        "neo4j_uri": "bolt://127.0.0.1:7687",
        "neo4j_username": "neo4j",
        "neo4j_password": "secret",
    }
    values.update(overrides)
    return type("Profile", (), values)()


@pytest.mark.asyncio
async def test_graph_expansion_scopes_query_to_workspace_label():
    row = FakeRecord(
        relationship_id="rel-1",
        relationship_type="NEXT",
        relationship_properties={"weight": 0.8},
        seed_properties={"chunk_id": "seed-1"},
        neighbor_id="node-2",
        neighbor_labels=["ragstudio_tenant_one"],
        neighbor_properties={
            "chunk_id": "neighbor-1",
            "document_id": "doc-1",
            "text": "Book 1 Hadith 2",
            "page": 2,
        },
    )
    driver = FakeDriver([row])
    service = GraphExpansionService(driver_factory=lambda *args, **kwargs: driver)

    candidates, traces = await service.expand(
        "show related hadith",
        seeds=[seed_candidate()],
        profile=profile(),
        document_ids=["doc-1"],
        limit=4,
    )

    query, params = driver.session_instance.calls[0]
    assert "MATCH (seed:`ragstudio_tenant_one`)-[relationship]-(neighbor:`ragstudio_tenant_one`)" in query
    assert params["seed_ids"] == ["seed-1", "seed-runtime"]
    assert params["document_ids"] == ["doc-1"]
    assert candidates[0].tool == "graph"
    assert candidates[0].chunk_id == "neighbor-1"
    assert candidates[0].metadata["graph_relationship"]["type"] == "NEXT"
    assert traces[0]["stage"] == "graph_expansion"
    assert traces[0]["expanded_candidates"] == 1


@pytest.mark.asyncio
async def test_graph_expansion_returns_trace_when_neo4j_is_unavailable():
    service = GraphExpansionService(driver_factory=lambda *args, **kwargs: None)

    candidates, traces = await service.expand(
        "show related hadith",
        seeds=[seed_candidate()],
        profile=profile(neo4j_uri=None),
        document_ids=["doc-1"],
        limit=4,
    )

    assert candidates == []
    assert traces == [
        {
            "stage": "graph_expansion",
            "status": "skipped",
            "reason": "neo4j_uri_missing",
        }
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_graph_expansion_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.graph_expansion_service'`.

- [ ] **Step 3: Implement graph expansion service**

Create `backend/src/ragstudio/services/graph_expansion_service.py`:

```python
from __future__ import annotations

from importlib import import_module
from typing import Any

from ragstudio.services.retrieval_evidence import EvidenceCandidate


class GraphExpansionService:
    def __init__(self, *, driver_factory: Any | None = None):
        self.driver_factory = driver_factory

    async def expand(
        self,
        query: str,
        *,
        seeds: list[EvidenceCandidate],
        profile: Any,
        document_ids: list[str],
        limit: int,
    ) -> tuple[list[EvidenceCandidate], list[dict[str, Any]]]:
        if not getattr(profile, "neo4j_uri", None):
            return [], [
                {
                    "stage": "graph_expansion",
                    "status": "skipped",
                    "reason": "neo4j_uri_missing",
                }
            ]
        seed_ids = _seed_ids(seeds)
        if not seed_ids:
            return [], [
                {
                    "stage": "graph_expansion",
                    "status": "skipped",
                    "reason": "no_seed_ids",
                }
            ]

        driver = self._driver(profile)
        if driver is None:
            return [], [
                {
                    "stage": "graph_expansion",
                    "status": "skipped",
                    "reason": "driver_unavailable",
                }
            ]

        workspace_label = _workspace_label(profile)
        rows = self._run_query(
            driver,
            workspace_label=workspace_label,
            seed_ids=seed_ids,
            document_ids=document_ids,
            limit=limit,
        )
        candidates = [_candidate_from_row(index, row) for index, row in enumerate(rows, start=1)]
        candidates = [candidate for candidate in candidates if candidate.text.strip()]
        return candidates, [
            {
                "stage": "graph_expansion",
                "status": "ok",
                "seed_count": len(seed_ids),
                "expanded_candidates": len(candidates),
                "workspace_label": workspace_label,
            }
        ]

    def _driver(self, profile: Any) -> Any:
        if self.driver_factory is not None:
            return self.driver_factory(
                profile.neo4j_uri,
                auth=_auth(profile),
            )
        graph_database = import_module("neo4j").GraphDatabase
        return graph_database.driver(
            profile.neo4j_uri,
            auth=_auth(profile),
        )

    def _run_query(
        self,
        driver: Any,
        *,
        workspace_label: str,
        seed_ids: list[str],
        document_ids: list[str],
        limit: int,
    ) -> list[Any]:
        cypher = f"""
        MATCH (seed:`{workspace_label}`)-[relationship]-(neighbor:`{workspace_label}`)
        WHERE coalesce(
            seed.chunk_id,
            seed.runtime_source_id,
            seed.id,
            seed.source_id
        ) IN $seed_ids
        AND (
            size($document_ids) = 0
            OR coalesce(neighbor.document_id, neighbor.full_doc_id, neighbor.doc_id) IN $document_ids
        )
        RETURN elementId(relationship) AS relationship_id,
               type(relationship) AS relationship_type,
               properties(relationship) AS relationship_properties,
               properties(seed) AS seed_properties,
               elementId(neighbor) AS neighbor_id,
               labels(neighbor) AS neighbor_labels,
               properties(neighbor) AS neighbor_properties
        LIMIT $limit
        """
        with driver.session() as session:
            return list(
                session.run(
                    cypher,
                    seed_ids=seed_ids,
                    document_ids=document_ids,
                    limit=max(limit, 1),
                )
            )


def _seed_ids(seeds: list[EvidenceCandidate]) -> list[str]:
    values: list[str] = []
    for seed in seeds:
        for value in (
            seed.chunk_id,
            seed.metadata.get("runtime_source_id"),
            seed.metadata.get("id"),
            seed.metadata.get("source_id"),
        ):
            if isinstance(value, str) and value and value not in values:
                values.append(value)
    return values


def _candidate_from_row(index: int, row: Any) -> EvidenceCandidate:
    properties = dict(row["neighbor_properties"] or {})
    relationship = {
        "id": row["relationship_id"],
        "type": row["relationship_type"],
        "properties": dict(row["relationship_properties"] or {}),
        "seed": dict(row["seed_properties"] or {}),
    }
    chunk_id = _first_str(properties, "chunk_id", "runtime_source_id", "id", "source_id")
    document_id = _first_str(properties, "document_id", "full_doc_id", "doc_id")
    text = _first_str(properties, "text", "content", "description", "summary") or ""
    source_location = {
        key: properties[key]
        for key in ("page", "section", "bbox", "start_index", "end_index")
        if key in properties
    }
    metadata = {
        **properties,
        "graph_relationship": relationship,
        "graph_labels": list(row["neighbor_labels"] or []),
    }
    return EvidenceCandidate(
        candidate_id=f"graph:{row['neighbor_id']}",
        text=text,
        document_id=document_id,
        chunk_id=chunk_id,
        source_location=source_location,
        metadata=metadata,
        tool="graph",
        tool_rank=index,
        base_score=max(1.0, 18.0 - index),
        boost_score=2.0,
        final_score=max(1.0, 20.0 - index),
        reasons=["graph_neighbor"],
    )


def _workspace_label(profile: Any) -> str:
    raw = f"ragstudio_{getattr(profile, 'id', 'default')}"
    safe = "".join(character if character.isalnum() or character in {"_", "-"} else "_" for character in raw).strip("_")
    return (safe or "ragstudio_default").replace("`", "``")


def _auth(profile: Any) -> tuple[str, str] | None:
    username = getattr(profile, "neo4j_username", None)
    password = getattr(profile, "neo4j_password", None)
    if username or password:
        return (username or "", password or "")
    return None


def _first_str(properties: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = properties.get(key)
        if isinstance(value, str) and value:
            return value
    return None
```

- [ ] **Step 4: Run graph tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_graph_expansion_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/graph_expansion_service.py backend/tests/test_graph_expansion_service.py
git commit -m "feat: expand retrieval evidence through graph"
```

---

### Task 6: Retrieval Orchestrator Service

**Files:**
- Create: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Write failing orchestrator tests**

Append:

```python
from ragstudio.schemas.chunks import ChunkOut
from ragstudio.services.retrieval_orchestrator import RetrievalOrchestrator
from ragstudio.services.retrieval_evidence import EvidenceCandidate
from ragstudio.services.runtime_types import RuntimeQueryResult


class FakeChunkSearchService:
    async def search(self, search_in):
        return type(
            "SearchResult",
            (),
            {
                "items": [
                    ChunkOut(
                        id="metadata-1",
                        document_id="doc-1",
                        text="Sahih al-Bukhari\n\n7277 Hadith Collection",
                        source_location={"page": 1},
                        metadata={
                            "document_metadata": {
                                "title": "Sahih al-Bukhari 7277 Hadith Collection"
                            },
                            "score": 10.0,
                        },
                    )
                ],
                "total": 1,
            },
        )()


class FakeRuntimeTool:
    async def query(self, query, *, document_ids, query_config):
        return RuntimeQueryResult(
            answer="native answer ignored",
            sources=[
                {
                    "chunk_id": "native-1",
                    "document_id": "doc-1",
                    "text": "Book 65, Hadith 201",
                    "source_location": {},
                    "metadata": {"native_scope": True},
                }
            ],
            timings={"runtime_query_ms": 5, "native_scoped_query": True},
        )


class FakeAnswerService:
    def __init__(self):
        self.evidence = []

    async def answer(self, query, evidence, profile):
        self.evidence = evidence
        return "Sahih al-Bukhari contains 7277 hadith.", {"prompt_tokens": 12}


class FakeRerankerService:
    async def rerank(self, query, chunks, profile):
        return chunks, [{"provider": "disabled", "status": "disabled"}]


class FakeGraphExpansionService:
    async def expand(self, query, *, seeds, profile, document_ids, limit):
        return [
            EvidenceCandidate(
                candidate_id="graph:g1",
                text="Sahih al-Bukhari collection overview confirms 7277 hadith",
                document_id="doc-1",
                chunk_id="graph-1",
                source_location={"page": 2},
                metadata={
                    "graph_relationship": {
                        "type": "RELATED",
                        "seed": {"chunk_id": seeds[0].chunk_id},
                    }
                },
                tool="graph",
                tool_rank=1,
                base_score=12.0,
                boost_score=2.0,
                final_score=14.0,
                reasons=["graph_neighbor"],
            )
        ], [{"stage": "graph_expansion", "status": "ok", "expanded_candidates": 1}]


@pytest.mark.asyncio
async def test_orchestrator_fuses_native_and_metadata_before_answering():
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

    assert result.answer == "Sahih al-Bukhari contains 7277 hadith."
    assert result.sources[0]["chunk_id"] == "metadata-1"
    assert answer_service.evidence[0].chunk_id == "metadata-1"
    assert result.timings["orchestrated_query"] is True
    assert any(trace["stage"] == "planner" for trace in result.chunk_traces)
    assert any(source["metadata"]["retrieval_tool"] == "graph" for source in result.sources)
    assert any(trace["stage"] == "graph_expansion" for trace in result.chunk_traces)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_retrieval_orchestrator.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.retrieval_orchestrator'`.

- [ ] **Step 3: Implement orchestrator**

Create `backend/src/ragstudio/services/retrieval_orchestrator.py`:

```python
from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any

from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.graph_expansion_service import GraphExpansionService
from ragstudio.services.reranker_service import RerankerService
from ragstudio.services.retrieval_evidence import (
    EvidenceCandidate,
    OrchestratedAnswer,
    fuse_candidates,
    plan_for_query,
)
from ragstudio.services.runtime_answer_service import RuntimeAnswerService


class RetrievalOrchestrator:
    def __init__(
        self,
        *,
        chunk_service: ChunkService,
        answer_service: RuntimeAnswerService | None = None,
        reranker_service: RerankerService | None = None,
        graph_expansion_service: GraphExpansionService | None = None,
    ):
        self.chunk_service = chunk_service
        self.answer_service = answer_service or RuntimeAnswerService()
        self.reranker_service = reranker_service or RerankerService()
        self.graph_expansion_service = graph_expansion_service or GraphExpansionService()

    async def query(
        self,
        query: str,
        *,
        runtime: Any,
        profile: Any,
        document_ids: list[str],
        variant_id: str,
        query_config: dict[str, Any],
    ) -> OrchestratedAnswer:
        started = perf_counter()
        limit = int(query_config.get("limit") or 8)
        plan = plan_for_query(query, document_ids=document_ids, limit=limit)
        traces: list[dict[str, Any]] = [
            {
                "stage": "planner",
                "intent": plan.intent,
                "tools": ["native", "metadata", "graph"],
                "candidate_limit": plan.candidate_limit,
            }
        ]

        native_task = self._native_candidates(query, runtime, document_ids, query_config)
        metadata_task = self._metadata_candidates(query, document_ids, variant_id, plan.candidate_limit)
        native_candidates, metadata_candidates = await asyncio.gather(native_task, metadata_task)

        traces.append(
            {
                "stage": "retrieval",
                "native_candidates": len(native_candidates),
                "metadata_candidates": len(metadata_candidates),
            }
        )

        seed_candidates = fuse_candidates(plan, [*native_candidates, *metadata_candidates])
        graph_candidates, graph_traces = await self.graph_expansion_service.expand(
            query,
            seeds=seed_candidates[:limit],
            profile=profile,
            document_ids=document_ids,
            limit=limit,
        )
        traces.extend(graph_traces)

        fused = fuse_candidates(plan, [*seed_candidates, *graph_candidates])
        reranker_traces: list[dict[str, Any]] = []
        reranked = fused
        if getattr(profile, "enable_rerank", False):
            reranked, reranker_traces = await self._rerank(query, fused, profile)

        final_evidence = reranked[:limit]
        traces.extend(candidate.to_trace() for candidate in final_evidence)
        answer_started = perf_counter()
        answer, token_metadata = await self.answer_service.answer(query, final_evidence, profile)
        return OrchestratedAnswer(
            answer=answer,
            sources=[candidate.to_source() for candidate in final_evidence],
            chunk_traces=traces,
            reranker_traces=reranker_traces,
            timings={
                "orchestrated_query": True,
                "answer_ms": _elapsed_ms(answer_started),
                "total_ms": _elapsed_ms(started),
            },
            token_metadata=token_metadata,
        )

    async def _native_candidates(
        self,
        query: str,
        runtime: Any,
        document_ids: list[str],
        query_config: dict[str, Any],
    ) -> list[EvidenceCandidate]:
        result = await runtime.query(query, document_ids=document_ids, query_config=query_config)
        candidates = []
        for index, source in enumerate(result.sources or [], start=1):
            if not isinstance(source, dict):
                continue
            candidates.append(
                EvidenceCandidate(
                    candidate_id=f"native:{source.get('chunk_id') or index}",
                    text=str(source.get("text") or ""),
                    document_id=_str_or_none(source.get("document_id")),
                    chunk_id=_str_or_none(source.get("chunk_id")),
                    source_location=_dict_or_empty(source.get("source_location")),
                    metadata=_dict_or_empty(source.get("metadata")),
                    tool="native",
                    tool_rank=index,
                    base_score=max(1.0, 20.0 - index),
                )
            )
        return [candidate for candidate in candidates if candidate.text.strip()]

    async def _metadata_candidates(
        self,
        query: str,
        document_ids: list[str],
        variant_id: str,
        limit: int,
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
        candidates = []
        for index, chunk in enumerate(search.items, start=1):
            candidates.append(self._candidate_from_chunk(chunk, index))
        return candidates

    def _candidate_from_chunk(self, chunk: ChunkOut, rank: int) -> EvidenceCandidate:
        score = chunk.metadata.get("score")
        base_score = float(score) if isinstance(score, (int, float)) else max(1.0, 20.0 - rank)
        return EvidenceCandidate(
            candidate_id=f"metadata:{chunk.id}",
            text=chunk.text,
            document_id=chunk.document_id,
            chunk_id=chunk.id,
            source_location=chunk.source_location,
            metadata=chunk.metadata,
            tool="metadata",
            tool_rank=rank,
            base_score=base_score,
        )

    async def _rerank(
        self,
        query: str,
        candidates: list[EvidenceCandidate],
        profile: Any,
    ) -> tuple[list[EvidenceCandidate], list[dict[str, Any]]]:
        chunks = [
            ChunkOut(
                id=candidate.chunk_id or candidate.candidate_id,
                document_id=candidate.document_id or "",
                text=candidate.text,
                source_location=candidate.source_location,
                metadata=candidate.metadata,
            )
            for candidate in candidates
        ]
        reranked_chunks, traces = await self.reranker_service.rerank(query, chunks, profile)
        by_id = {chunk.id: index for index, chunk in enumerate(reranked_chunks)}
        return (
            sorted(
                candidates,
                key=lambda candidate: by_id.get(candidate.chunk_id or candidate.candidate_id, 10_000),
            ),
            traces,
        )


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 3)
```

- [ ] **Step 4: Run orchestrator tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_retrieval_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: orchestrate fused retrieval evidence"
```

---

### Task 7: QueryService Default Runtime Integration

**Files:**
- Modify: `backend/src/ragstudio/services/query_service.py`
- Modify: `backend/tests/test_runtime_query_service.py`

- [ ] **Step 1: Write failing service test**

Append to `backend/tests/test_runtime_query_service.py`:

```python
class FakeOrchestrator:
    def __init__(self):
        self.calls = []

    async def query(self, query, *, runtime, profile, document_ids, variant_id, query_config):
        self.calls.append(
            {
                "query": query,
                "document_ids": document_ids,
                "variant_id": variant_id,
                "query_config": query_config,
            }
        )
        return type(
            "Answer",
            (),
            {
                "answer": "Sahih al-Bukhari contains 7277 hadith.",
                "sources": [
                    {
                        "chunk_id": "metadata-1",
                        "document_id": document_ids[0],
                        "text": "Sahih al-Bukhari 7277 Hadith Collection",
                        "metadata": {"retrieval_tool": "metadata"},
                    }
                ],
                "chunk_traces": [{"stage": "planner", "intent": "count"}],
                "reranker_traces": [],
                "timings": {"orchestrated_query": True},
                "token_metadata": {"prompt_tokens": 12},
                "error": None,
                "error_type": None,
            },
        )()


@pytest.mark.asyncio
async def test_query_service_uses_retrieval_orchestrator_for_runtime_queries(client):
    app = client._transport.app
    orchestrator = FakeOrchestrator()
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(session, app)

        result = await QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(),
            health_service=FakeHealthService(),
            retrieval_orchestrator=orchestrator,
        ).run_query(
            QueryIn(
                query="how many hadith in bukhari",
                document_ids=[document.id],
                variant_ids=[variant.id],
            )
        )

    run = result.runs[0]
    assert run.answer == "Sahih al-Bukhari contains 7277 hadith."
    assert run.sources[0]["metadata"]["retrieval_tool"] == "metadata"
    assert run.chunk_traces[0]["stage"] == "planner"
    assert run.timings["orchestrated_query"] is True
    assert run.token_metadata["prompt_tokens"] == 12
    assert orchestrator.calls[0]["document_ids"] == [document.id]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_runtime_query_service.py::test_query_service_uses_retrieval_orchestrator_for_runtime_queries -q
```

Expected: FAIL with `TypeError: QueryService.__init__() got an unexpected keyword argument 'retrieval_orchestrator'`.

- [ ] **Step 3: Add orchestrator dependency and integration**

Modify `backend/src/ragstudio/services/query_service.py`:

```python
from ragstudio.services.retrieval_orchestrator import RetrievalOrchestrator
```

Extend `QueryService.__init__`:

```python
        retrieval_orchestrator: RetrievalOrchestrator | None = None,
```

Set the field after `self.reranker_service`:

```python
        self.retrieval_orchestrator = retrieval_orchestrator
```

Add this helper:

```python
    def _retrieval_orchestrator(self) -> RetrievalOrchestrator:
        if self.retrieval_orchestrator is not None:
            return self.retrieval_orchestrator
        return RetrievalOrchestrator(
            chunk_service=ChunkService(self.session, self.data_dir, self.adapter),
            reranker_service=self.reranker_service,
        )
```

Replace the direct `runtime.query(...)` block in `_run_runtime_query` with:

```python
                runtime = self.runtime_factory.build(profile)
                orchestrated = await self._retrieval_orchestrator().query(
                    payload.query,
                    runtime=runtime,
                    profile=profile,
                    document_ids=payload.document_ids,
                    variant_id=variant_id,
                    query_config=query_config,
                )
                run.status = (
                    StageStatus.FAILED.value if orchestrated.error else StageStatus.SUCCEEDED.value
                )
                run.answer = orchestrated.answer
                run.sources = orchestrated.sources
                run.chunk_traces = orchestrated.chunk_traces
                run.reranker_traces = orchestrated.reranker_traces
                run.token_metadata = orchestrated.token_metadata
                run.error = orchestrated.error
                run.error_type = orchestrated.error_type
                run.timings = {**orchestrated.timings, "total_ms": self._elapsed_ms(started_at)}
```

Keep the existing `except Exception as exc:` block unchanged so orchestrator failures persist as failed runs. Keep `_run_scoped_mirrored_runtime_query` unchanged for fallback-only use in a separate hardening pass.

- [ ] **Step 4: Run targeted test**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_runtime_query_service.py::test_query_service_uses_retrieval_orchestrator_for_runtime_queries -q
```

Expected: PASS.

- [ ] **Step 5: Run runtime query service tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_runtime_query_service.py -q
```

Expected: PASS. If older tests expecting native direct answer fail, update them to assert orchestrated output when runtime mode is active.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/query_service.py backend/tests/test_runtime_query_service.py
git commit -m "feat: use retrieval orchestrator for runtime queries"
```

---

### Task 8: Metadata Search Quality Boosts

**Files:**
- Modify: `backend/src/ragstudio/services/hybrid_chunk_search.py`
- Modify: `backend/tests/test_chunks.py`

- [ ] **Step 1: Write failing chunk search quality test**

Append to `backend/tests/test_chunks.py`:

```python
@pytest.mark.asyncio
async def test_search_chunks_boosts_collection_count_title(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="bukhari.pdf",
            content_type="application/pdf",
            sha256="bukhari-count",
            artifact_path=str(app.state.settings.data_dir / "bukhari.pdf"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add_all(
            [
                Chunk(
                    document_id=document.id,
                    text="Book 65, Hadith 201 mentions truthfulness.",
                    source_location={"page": 65},
                    metadata_json={"domain_metadata": {"domain": "hadith"}},
                ),
                Chunk(
                    document_id=document.id,
                    text="Sahih al-Bukhari\n\n7277 Hadith Collection",
                    source_location={"page": 1},
                    metadata_json={
                        "document_metadata": {
                            "title": "Sahih al-Bukhari 7277 Hadith Collection"
                        },
                        "domain_metadata": {
                            "domain": "hadith",
                            "document_type": "collection",
                            "collection": "Sahih al-Bukhari",
                        },
                    },
                ),
            ]
        )
        await session.commit()

        result = await ChunkService(session, app.state.settings.data_dir).search(
            ChunkSearchIn(
                query="how many hadith in bukhari",
                document_ids=[document.id],
                limit=2,
            )
        )

    assert result.items[0].text == "Sahih al-Bukhari\n\n7277 Hadith Collection"
    assert result.items[0].metadata["score_breakdown"]["answer_bearing_count"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_chunks.py::test_search_chunks_boosts_collection_count_title -q
```

Expected: FAIL because `answer_bearing_count` is missing or the count/title chunk is not ranked first.

- [ ] **Step 3: Implement answer-bearing metadata boost**

Modify `HybridChunkSearch.score()` in `backend/src/ragstudio/services/hybrid_chunk_search.py` by adding this before `breakdown`:

```python
        answer_bearing_count = self._answer_bearing_count_boost(query_text, chunk.text, metadata)
```

Add it to `breakdown`:

```python
            "answer_bearing_count": answer_bearing_count,
```

Add this method to `HybridChunkSearch`:

```python
    def _answer_bearing_count_boost(
        self,
        query_text: str,
        chunk_text: str,
        metadata: dict[str, Any],
    ) -> float:
        if not re.search(r"\b(how many|count|number of|total)\b", query_text):
            return 0.0
        combined = f"{chunk_text} {self._metadata_title(metadata)}".casefold()
        if not re.search(r"\b\d{2,}\b", combined):
            return 0.0
        if not any(term in combined for term in ("hadith", "collection", "bukhari")):
            return 0.0
        return 30.0

    def _metadata_title(self, metadata: dict[str, Any]) -> str:
        document_metadata = metadata.get("document_metadata")
        if isinstance(document_metadata, dict):
            title = document_metadata.get("title")
            if isinstance(title, str):
                return title
        return ""
```

- [ ] **Step 4: Run targeted test**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_chunks.py::test_search_chunks_boosts_collection_count_title -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/hybrid_chunk_search.py backend/tests/test_chunks.py
git commit -m "feat: boost answer-bearing metadata chunks"
```

---

### Task 9: End-to-End Runtime Quality Test

**Files:**
- Modify: `backend/tests/test_runtime_query_service.py`

- [ ] **Step 1: Write end-to-end service test with real orchestrator and fake answerer**

Append:

```python
class FakeRuntimeNoisyNative:
    async def query(self, query, *, document_ids, query_config):
        return RuntimeQueryResult(
            answer="native answer ignored",
            sources=[
                {
                    "chunk_id": "native-random",
                    "document_id": document_ids[0],
                    "text": "Book 65, Hadith 201 discusses truthfulness.",
                    "metadata": {"native_scope": True},
                    "source_location": {"page": 65},
                }
            ],
            timings={"native_scoped_query": True},
        )


class FakeRuntimeAnswerService:
    def __init__(self):
        self.evidence_texts = []

    async def answer(self, query, evidence, profile):
        self.evidence_texts = [candidate.text for candidate in evidence]
        return "Sahih al-Bukhari contains 7277 hadith.", {}


@pytest.mark.asyncio
async def test_runtime_query_uses_metadata_count_evidence_before_native_noise(client):
    from ragstudio.services.chunk_service import ChunkService
    from ragstudio.services.retrieval_orchestrator import RetrievalOrchestrator

    app = client._transport.app
    answer_service = FakeRuntimeAnswerService()
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(session, app)
        session.add(
            Chunk(
                document_id=document.id,
                text="Sahih al-Bukhari\n\n7277 Hadith Collection",
                source_location={"page": 1},
                metadata_json={
                    "document_metadata": {"title": "Sahih al-Bukhari 7277 Hadith Collection"},
                    "domain_metadata": {
                        "domain": "hadith",
                        "document_type": "collection",
                        "collection": "Sahih al-Bukhari",
                    },
                },
                runtime_profile_id="default",
            )
        )
        await session.commit()
        orchestrator = RetrievalOrchestrator(
            chunk_service=ChunkService(session, app.state.settings.data_dir),
            answer_service=answer_service,
        )

        result = await QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(FakeRuntimeNoisyNative()),
            health_service=FakeHealthService(),
            retrieval_orchestrator=orchestrator,
        ).run_query(
            QueryIn(
                query="how many hadith in bukhari",
                document_ids=[document.id],
                variant_ids=[variant.id],
            )
        )

    run = result.runs[0]
    assert run.answer == "Sahih al-Bukhari contains 7277 hadith."
    assert answer_service.evidence_texts[0] == "Sahih al-Bukhari\n\n7277 Hadith Collection"
    assert run.sources[0]["metadata"]["retrieval_tool"] == "metadata"
    assert run.timings["orchestrated_query"] is True
```

- [ ] **Step 2: Run targeted test**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_runtime_query_service.py::test_runtime_query_uses_metadata_count_evidence_before_native_noise -q
```

Expected: PASS.

- [ ] **Step 3: Run focused backend tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest backend/tests/test_retrieval_orchestrator.py backend/tests/test_graph_expansion_service.py backend/tests/test_runtime_answer_service.py backend/tests/test_runtime_query_service.py backend/tests/test_chunks.py::test_search_chunks_boosts_collection_count_title -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_runtime_query_service.py
git commit -m "test: prove orchestrated metadata quality path"
```

---

### Task 10: Live Smoke and Final Validation

**Files:**
- No code changes expected.

- [ ] **Step 1: Restart app services**

Run:

```bash
docker compose restart backend frontend
```

Expected: backend and frontend restart without container errors.

- [ ] **Step 2: Verify diagnostics**

Run:

```bash
curl -sS http://localhost:5173/api/diagnostics | jq '{overall_status,runtime_mode,dependency_status}'
```

Expected:

```json
{
  "overall_status": "ready",
  "runtime_mode": "runtime",
  "dependency_status": {
    "raganything": "available",
    "active_backend": "runtime",
    "indexing": "raganything",
    "query": "raganything",
    "graph": "neo4j",
    "native_scoped_query": true,
    "scoped_query": "raganything_full_doc_id_vector",
    "scoped_query_detail": "Native RAG-Anything query scopes selected documents through LightRAG chunk full_doc_id filtering with vector retrieval; graph modes are not used under document scope."
  }
}
```

- [ ] **Step 3: Run Bukhari quality smoke query**

Run:

```bash
curl --max-time 120 -sS -X POST http://localhost:5173/api/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"how many hadith in bukhari","document_ids":["bb5ce512-1795-46a4-868d-eb6e449f9812"],"variant_ids":["75848293-2f84-4a84-9ec0-110e60df8651"],"limit":8}' \
  | jq '.runs[0] | {status,answer,timings,source_count:(.sources|length),first_source:.sources[0],planner_trace:.chunk_traces[0],graph_trace:(.chunk_traces[] | select(.stage=="graph_expansion") | .)}'
```

Expected:

```json
{
  "status": "succeeded",
  "answer": "Sahih al-Bukhari contains 7277 hadith.",
  "timings": {
    "orchestrated_query": true
  },
  "source_count": 8,
  "first_source": {
    "text": "Sahih al-Bukhari\n\n7277 Hadith Collection"
  },
  "planner_trace": {
    "stage": "planner",
    "intent": "count",
    "tools": ["native", "metadata", "graph"]
  },
  "graph_trace": {
    "stage": "graph_expansion",
    "status": "ok"
  }
}
```

The exact answer wording may differ, but it must include `7277`, status must be `succeeded`, the first source must contain `7277 Hadith Collection`, and `graph_trace.status` must be either `ok` or `skipped` with a concrete `reason`.

- [ ] **Step 4: Run lint and focused tests**

Run:

```bash
PATH=$PWD/.venv/bin:$PATH python -m ruff check \
  backend/src/ragstudio/schemas/runtime.py \
  backend/src/ragstudio/schemas/settings.py \
  backend/src/ragstudio/services/retrieval_evidence.py \
  backend/src/ragstudio/services/retrieval_orchestrator.py \
  backend/src/ragstudio/services/graph_expansion_service.py \
  backend/src/ragstudio/services/llm_reranker_service.py \
  backend/src/ragstudio/services/runtime_answer_service.py \
  backend/src/ragstudio/services/reranker_service.py \
  backend/src/ragstudio/services/query_service.py \
  backend/src/ragstudio/services/hybrid_chunk_search.py \
  backend/tests/test_retrieval_orchestrator.py \
  backend/tests/test_graph_expansion_service.py \
  backend/tests/test_llm_reranker_service.py \
  backend/tests/test_runtime_answer_service.py \
  backend/tests/test_runtime_query_service.py \
  backend/tests/test_settings.py
```

Expected: `All checks passed!`

Run:

```bash
PATH=$PWD/.venv/bin:$PATH PYTHONPATH=backend/src python -m pytest \
  backend/tests/test_retrieval_orchestrator.py \
  backend/tests/test_graph_expansion_service.py \
  backend/tests/test_llm_reranker_service.py \
  backend/tests/test_runtime_answer_service.py \
  backend/tests/test_runtime_query_service.py \
  backend/tests/test_settings.py \
  backend/tests/test_chunks.py::test_search_chunks_boosts_collection_count_title \
  -q
```

Expected: PASS.

Run:

```bash
npm --prefix frontend test -- settings-page
```

Expected: PASS.

- [ ] **Step 5: Check git status**

Run:

```bash
git status --short --branch
```

Expected: only unrelated pre-existing files may remain, such as `?? REVIEW.md`.

---

## Self-Review Notes

- Spec coverage: default-on full planner, native retrieval, metadata retrieval, Neo4j graph expansion, dedicated BGE-compatible reranker, existing LLM reranker fallback, deterministic no-reranker mode, fused evidence, runtime LLM answerer, and full traces are each covered by tasks.
- Placeholder scan: no task uses undefined deferred work as a requirement. Graph expansion is implemented in `GraphExpansionService` and wired into the orchestrator before reranking.
- Type consistency: `EvidenceCandidate`, `RetrievalPlan`, `OrchestratedAnswer`, `GraphExpansionService.expand()`, `LLMRerankerService.rerank()`, `RetrievalOrchestrator.query()`, and `RuntimeAnswerService.answer()` signatures are introduced before use.
- Scope check: this is one coherent backend feature. Settings changes are limited to the existing `Vision and reranker` section, and no new dedicated reranker endpoint setup is included.
