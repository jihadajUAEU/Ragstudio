# Tokenizer-Aware Context Scaling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent large query candidate sets from blocking request handling while supporting a tokenizer-aware counter that is more accurate than the current character and word heuristics when the optional tokenizer extra is installed.

**Architecture:** Keep `ContextAssemblyService` deterministic and synchronous for normal payloads. Introduce an injectable tokenizer interface plus an async assembly wrapper that offloads large token-counting batches to a worker thread; default checkout behavior remains the current conservative estimator when no tokenizer package is installed.

**Tech Stack:** Python 3.12, asyncio, optional tokenizer dependency adapter, pytest, pytest-asyncio, existing `ContextAssemblyService` and `RetrievalOrchestrator`.

---

## Scope Check

This is valuable, but it is not a total absence of scaling protection. `ContextAssemblyService` already has a conservative token estimator and a production `_should_offload_tokenization()` helper. The missing production value is wiring: no optional high-speed tokenizer adapter, no async offload path, and no orchestrator path that uses offload for unusually large candidate text.

## File Structure

- Create `backend/src/ragstudio/services/token_counting.py`
  - Own tokenizer protocol, default conservative tokenizer, optional C-backed adapter detection, and offload threshold.
- Modify `backend/pyproject.toml`
  - Add a `tokenizer` optional dependency extra for deployments that want the C-backed tokenizer adapter.
- Modify `backend/src/ragstudio/services/context_assembly_service.py`
  - Accept a tokenizer dependency and add `assemble_async()` for large payload offload.
- Modify `backend/src/ragstudio/services/retrieval_orchestrator.py`
  - Await async context assembly when candidate text volume crosses the offload threshold.
- Create `backend/tests/test_token_counting.py`
  - Cover default estimates, optional adapter fallback, and offload decision.
- Modify `backend/tests/test_context_assembly_service.py`
  - Cover injected tokenizer and async offload path.
- Modify `backend/tests/test_retrieval_orchestrator.py`
  - Cover that large candidate sets use async assembly metadata without changing context contents.
- Modify `docs/architecture/query-retrieval-architecture.md`
  - Document tokenizer-aware context budgeting and fallback behavior.

---

### Task 1: Add Token Counting Service

**Files:**
- Create: `backend/src/ragstudio/services/token_counting.py`
- Modify: `backend/pyproject.toml`
- Test: `backend/tests/test_token_counting.py`

- [ ] **Step 1: Write failing token counting tests**

Create `backend/tests/test_token_counting.py`:

```python
from ragstudio.services import token_counting
from ragstudio.services.token_counting import ConservativeTokenCounter, should_offload_token_counting


def test_conservative_token_counter_preserves_existing_arabic_behavior():
    counter = ConservativeTokenCounter()
    assert counter.count("alpha beta gamma") == 3
    assert counter.count("الحمد لله رب العالمين") >= 4
    assert counter.count("function call() { return 1; }") >= 7


def test_should_offload_token_counting_uses_total_text_volume():
    small = ["word " * 100, "word " * 100]
    large = ["word " * 6000, "word " * 6000]
    assert should_offload_token_counting(small) is False
    assert should_offload_token_counting(large) is True


def test_best_available_token_counter_falls_back_without_optional_tokenizer(monkeypatch):
    class FailingTiktokenTokenCounter:
        def __init__(self, model=None):
            raise RuntimeError("tokenizer unavailable")

    monkeypatch.setattr(token_counting, "TiktokenTokenCounter", FailingTiktokenTokenCounter)

    assert isinstance(token_counting.best_available_token_counter(), ConservativeTokenCounter)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_token_counting.py -q
```

Expected: FAIL because `token_counting.py` does not exist.

- [ ] **Step 3: Implement the token counting service**

Create `backend/src/ragstudio/services/token_counting.py`:

```python
from __future__ import annotations

from typing import Protocol


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class ConservativeTokenCounter:
    def count(self, text: str) -> int:
        stripped = text.strip()
        if not stripped:
            return 1
        word_count = len(stripped.split())
        arabic_chars = sum(1 for char in stripped if "\u0600" <= char <= "\u06FF")
        code_symbols = sum(1 for char in stripped if char in "{}[]()=;:,.<>/\\|")
        char_estimate = max(1, len(stripped) // 4)
        arabic_estimate = max(1, int(arabic_chars * 0.75)) if arabic_chars else 0
        code_estimate = max(1, code_symbols // 2) if code_symbols else 0
        return max(word_count, char_estimate, arabic_estimate, code_estimate, 1)


class TiktokenTokenCounter:
    def __init__(self, model: str | None = None) -> None:
        import tiktoken

        self.encoding = (
            tiktoken.encoding_for_model(model)
            if model
            else tiktoken.get_encoding("cl100k_base")
        )

    def count(self, text: str) -> int:
        return max(1, len(self.encoding.encode(text)))


def best_available_token_counter(model: str | None = None) -> TokenCounter:
    try:
        return TiktokenTokenCounter(model)
    except Exception:
        return ConservativeTokenCounter()


def should_offload_token_counting(texts: list[str], *, word_threshold: int = 10_000) -> bool:
    return sum(len(text.split()) for text in texts) > word_threshold
```

- [ ] **Step 4: Add the optional tokenizer dependency extra**

Modify `backend/pyproject.toml`:

```toml
[project.optional-dependencies]
tokenizer = [
  "tiktoken",
]
dev = [
  "pytest>=9.0.3",
  "pytest-asyncio>=1.3.0",
  "ruff>=0.15.12",
  "pyright>=1.1.409",
]
```

Keep `tiktoken` optional so the default proof path remains dependency-stable and the fallback tests still pass without the extra installed.

- [ ] **Step 5: Run token counting tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_token_counting.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the token service**

```bash
git add backend/src/ragstudio/services/token_counting.py backend/pyproject.toml backend/tests/test_token_counting.py
git commit -m "feat: add token counting service"
```

---

### Task 2: Inject Token Counter Into Context Assembly

**Files:**
- Modify: `backend/src/ragstudio/services/context_assembly_service.py`
- Modify: `backend/tests/test_context_assembly_service.py`

- [ ] **Step 1: Add failing injected-tokenizer test**

Add this import at the top of `backend/tests/test_context_assembly_service.py`:

```python
import pytest
```

Then append this test:

```python
class FixedTokenCounter:
    def count(self, text: str) -> int:
        return 5


def test_context_assembly_uses_injected_token_counter():
    candidate = _candidate("pgvector", "token-counter", "one two three four five six", 1)

    context = ContextAssemblyService(
        max_context_tokens=4,
        token_counter=FixedTokenCounter(),
    ).assemble([candidate])

    assert context.dropped[0].estimated_tokens == 5
    assert context.dropped[0].drop_reason == "token_budget"
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_context_assembly_service.py::test_context_assembly_uses_injected_token_counter -q
```

Expected: FAIL because `ContextAssemblyService` does not accept `token_counter`.

- [ ] **Step 3: Wire the token counter**

Modify `backend/src/ragstudio/services/context_assembly_service.py`:

```python
from ragstudio.services.token_counting import ConservativeTokenCounter, TokenCounter, best_available_token_counter
```

Change the constructor:

```python
    def __init__(
        self,
        *,
        max_context_tokens: int = 2400,
        hard_context_tokens: int | None = None,
        token_counter: TokenCounter | None = None,
    ) -> None:
        self.max_context_tokens = max_context_tokens
        self.hard_context_tokens = hard_context_tokens
        self.token_counter = token_counter or best_available_token_counter()
```

Replace calls to `_estimate_tokens(text)` inside `assemble()` with:

```python
self.token_counter.count(text)
```

Keep `_estimate_tokens()` as a compatibility wrapper:

```python
def _estimate_tokens(text: str) -> int:
    return ConservativeTokenCounter().count(text)
```

- [ ] **Step 4: Run context assembly tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_context_assembly_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit injected token counting**

```bash
git add backend/src/ragstudio/services/context_assembly_service.py backend/tests/test_context_assembly_service.py
git commit -m "feat: inject context token counter"
```

---

### Task 3: Add Async Offload For Large Context Assembly

**Files:**
- Modify: `backend/src/ragstudio/services/context_assembly_service.py`
- Modify: `backend/tests/test_context_assembly_service.py`

- [ ] **Step 1: Add failing async offload test**

Append this test to `backend/tests/test_context_assembly_service.py`:

```python
@pytest.mark.asyncio
async def test_context_assembly_async_matches_sync_result_for_large_payload():
    candidate = _candidate("pgvector", "large-context", "word " * 12_000, 1)
    service = ContextAssemblyService(max_context_tokens=20_000)

    sync_context = service.assemble([candidate])
    async_context = await service.assemble_async([candidate])

    assert async_context.total_estimated_tokens == sync_context.total_estimated_tokens
    assert [item.candidate_id for item in async_context.evidence] == [
        item.candidate_id for item in sync_context.evidence
    ]
```

- [ ] **Step 2: Run the async test and verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_context_assembly_service.py::test_context_assembly_async_matches_sync_result_for_large_payload -q
```

Expected: FAIL because `assemble_async()` does not exist.

- [ ] **Step 3: Implement async offload**

Modify `backend/src/ragstudio/services/context_assembly_service.py`:

```python
import asyncio
from ragstudio.services.token_counting import should_offload_token_counting
```

Add this method to `ContextAssemblyService`:

```python
    async def assemble_async(self, candidates: list[EvidenceCandidate]) -> AssembledContext:
        texts = [candidate.text for candidate in candidates]
        if should_offload_token_counting(texts):
            return await asyncio.to_thread(self.assemble, candidates)
        return self.assemble(candidates)
```

- [ ] **Step 4: Run async and full context tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_context_assembly_service.py backend/tests/test_token_counting.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit async assembly**

```bash
git add backend/src/ragstudio/services/context_assembly_service.py backend/tests/test_context_assembly_service.py
git commit -m "perf: offload large context token counting"
```

---

### Task 4: Use Async Assembly In Retrieval Orchestration

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Add a failing profile override regression**

Add this test to `backend/tests/test_retrieval_orchestrator.py` near the other context assembly tests:

```python
def test_context_assembly_profile_override_preserves_injected_service_config():
    token_counter = object()
    base_service = ContextAssemblyService(
        max_context_tokens=200,
        hard_context_tokens=40,
        token_counter=token_counter,
    )
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        context_assembly_service=base_service,
    )

    service = orchestrator._context_assembly_service(
        type("Profile", (), {"max_context_tokens": 80})()
    )

    assert service.max_context_tokens == 80
    assert service.hard_context_tokens == 40
    assert service.token_counter is token_counter
```

- [ ] **Step 2: Run the profile override test and verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_orchestrator.py::test_context_assembly_profile_override_preserves_injected_service_config -q
```

Expected: FAIL because `_context_assembly_service()` creates a fresh service and drops injected configuration.

- [ ] **Step 3: Preserve injected service configuration under profile budget overrides**

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, replace `_context_assembly_service()` with:

```python
    def _context_assembly_service(self, profile: Any) -> ContextAssemblyService:
        max_context_tokens = getattr(profile, "max_context_tokens", None)
        if isinstance(max_context_tokens, int) and max_context_tokens > 0:
            return ContextAssemblyService(
                max_context_tokens=max_context_tokens,
                hard_context_tokens=self.context_assembly_service.hard_context_tokens,
                token_counter=self.context_assembly_service.token_counter,
            )
        return self.context_assembly_service
```

- [ ] **Step 4: Add a failing async orchestration regression**

Add a fake context assembly service in `backend/tests/test_retrieval_orchestrator.py`:

```python
class AsyncAwareContextAssemblyService(ContextAssemblyService):
    def __init__(self):
        super().__init__(max_context_tokens=20_000)
        self.async_called = False

    async def assemble_async(self, candidates):
        self.async_called = True
        return self.assemble(candidates)
```

Add a focused test using the existing fake chunk service helpers in that file:

```python
@pytest.mark.asyncio
async def test_query_orchestrator_uses_async_context_assembly():
    assembly_service = AsyncAwareContextAssemblyService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
        context_assembly_service=assembly_service,
    )

    result = await orchestrator.query(
        query="context",
        runtime=FakeRuntimeTool(),
        profile=type(
            "Profile",
            (),
            {"enable_rerank": False, "reranker_provider": "disabled"},
        )(),
        document_ids=["doc-1"],
        variant_id="variant-context",
        query_config={
            "response_mode": "fast",
            "limit": 1,
            "vector_baseline_gate": {"passed": True},
        },
    )

    assert result.error is None
    assert assembly_service.async_called is True
```

- [ ] **Step 5: Run the focused orchestrator test and verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_orchestrator.py::test_query_orchestrator_uses_async_context_assembly -q
```

Expected: FAIL because `RetrievalOrchestrator` calls `assemble()` directly.

- [ ] **Step 6: Await async assembly in the orchestrator**

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, replace the current context assembly call near the `context_assembly_ms` timing block:

```python
context_service = self._context_assembly_service(profile)
assembled_context = context_service.assemble(reranked)
```

with:

```python
context_service = self._context_assembly_service(profile)
assembled_context = await context_service.assemble_async(reranked)
```

- [ ] **Step 7: Run retrieval and context tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_orchestrator.py backend/tests/test_context_assembly_service.py backend/tests/test_token_counting.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit orchestration wiring**

```bash
git add backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_retrieval_orchestrator.py
git commit -m "perf: use async context assembly in query orchestration"
```

---

### Task 5: Document Context Budgeting Behavior

**Files:**
- Modify: `docs/architecture/query-retrieval-architecture.md`

- [ ] **Step 1: Add architecture note**

Add this paragraph to the context assembly section:

```markdown
Context assembly estimates token budgets through an injectable token counter. The default counter is conservative and dependency-free; deployments can replace it with a faster tokenizer adapter. When candidate text volume is unusually large, query orchestration uses async context assembly so token counting can run off the request event loop while preserving the same inclusion, drop, and truncation decisions.
```

Also note that the C-backed tokenizer is enabled by installing the backend `tokenizer` extra; default installs keep the conservative fallback.

- [ ] **Step 2: Review the documentation diff**

Run:

```bash
git diff -- docs/architecture/query-retrieval-architecture.md
```

Expected: the note explains fallback behavior and async offload without changing retrieval claims.

- [ ] **Step 3: Commit the docs**

```bash
git add docs/architecture/query-retrieval-architecture.md
git commit -m "docs: document tokenizer-aware context budgeting"
```
