# RAG Search Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce metadata and lexical retrieval latency by adding the missing English text trigram index, making metadata retrieval passes session-safe and concurrent, and removing repeated regex compilation work from hot scoring paths.

**Architecture:** Keep `ChunkService.search()` as the single chunk-ranking API, but let `MetadataRetrievalService` use an optional session-safe parallel search callable so production metadata passes do not share one SQLAlchemy `AsyncSession`. Keep database compatibility in both the SQLAlchemy model definition and `init_db()` runtime schema repair path. Move hot regexes in `HybridChunkSearch` to module-level compiled patterns and an LRU-cached dynamic Arabic phrase-boundary pattern.

**Tech Stack:** Python 3.12, FastAPI services, SQLAlchemy async, PostgreSQL `pg_trgm`, pytest, pytest-asyncio, Ruff.

---

## Verification Notes

Confirmed by code inspection on 2026-05-19:

- `backend/src/ragstudio/services/chunk_lexical_search_repository.py:124-126` builds `Chunk.text.ilike("%term%")` predicates for English lexical prefiltering.
- `backend/src/ragstudio/db/models.py:116-126` defines trigram/GIN indexes for `text_search_ar` and `tokens_ar`, but no trigram index for `Chunk.text`.
- `backend/src/ragstudio/db/engine.py:359-385` creates runtime indexes for `text_search_ar`, `tokens_ar`, and `(document_id, preview_ref)`, but no runtime repair index for `chunks.text`.
- `backend/src/ragstudio/services/metadata_retrieval_service.py:38-74` executes metadata passes sequentially and stops after a direct evidence pass.
- `backend/src/ragstudio/services/chunk_service.py:129-163` uses one injected `AsyncSession` for each `search()` call. This means `asyncio.gather()` must not be used against the same `ChunkService` instance in production.
- `backend/src/ragstudio/services/hybrid_chunk_search.py:272-377` repeatedly calls regex helpers in scorer hot paths, including Arabic boundary search, count-query detection, number detection, guidance phrase detection, answer-bearing phrase extraction, term tokenization, and Arabic detection.

The user suggestion is directionally correct, with one important correction: concurrent metadata retrieval must use independent sessions or an injected parallel-safe search callable. Sharing the current `ChunkService` session concurrently would be unsafe.

## File Structure

- Modify `backend/src/ragstudio/db/models.py`: add SQLAlchemy model declaration for `ix_chunks_text_trgm` on `Chunk.text`.
- Modify `backend/src/ragstudio/db/engine.py`: add runtime `CREATE INDEX IF NOT EXISTS ix_chunks_text_trgm ON chunks USING gin (text gin_trgm_ops)` inside `_ensure_chunk_search_indexes()`.
- Modify `backend/tests/test_chunk_lexical_search_repository.py`: add a PostgreSQL regression that `init_db()` creates the English text trigram index.
- Modify `backend/src/ragstudio/services/metadata_retrieval_service.py`: add session-safe parallel metadata pass execution with deterministic replay of results in retrieval-pass order.
- Modify `backend/src/ragstudio/services/query_service.py`: accept an optional `session_factory`, build a parallel-safe metadata search callable, and pass it into `MetadataRetrievalService`.
- Modify `backend/src/ragstudio/api/routes/query.py`: pass `request.app.state.session_factory` into `QueryService`.
- Modify `backend/tests/test_metadata_retrieval_service.py`: add tests for concurrent dispatch, deterministic candidate ordering, early-stop replay semantics, and sequential fallback.
- Modify `backend/src/ragstudio/services/hybrid_chunk_search.py`: precompile static regex patterns and LRU-cache dynamic Arabic phrase-boundary patterns.
- Modify `backend/tests/test_hybrid_chunk_search_arabic.py`: add regression tests proving scorer behavior stays the same and dynamic Arabic boundary regexes are cached.

---

### Task 1: Add English Trigram Index for Lexical Search

**Files:**
- Modify: `backend/src/ragstudio/db/models.py:116-126`
- Modify: `backend/src/ragstudio/db/engine.py:359-385`
- Test: `backend/tests/test_chunk_lexical_search_repository.py`

- [ ] **Step 1: Write the failing index regression**

Add this import near the top of `backend/tests/test_chunk_lexical_search_repository.py`:

```python
from sqlalchemy import text
```

Add this test below `test_repository_prefilters_arabic_token_with_postgres_columns`:

```python
@pytest.mark.asyncio
async def test_init_db_creates_english_text_trigram_index(database_url):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        indexdef = await session.scalar(
            text(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename = 'chunks'
                  AND indexname = 'ix_chunks_text_trgm'
                """
            )
        )

    assert indexdef is not None
    assert "USING gin" in indexdef
    assert "text gin_trgm_ops" in indexdef
    await engine.dispose()
```

- [ ] **Step 2: Run the focused index test and verify it fails**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_chunk_lexical_search_repository.py::test_init_db_creates_english_text_trigram_index -q
```

Expected: fails because `ix_chunks_text_trgm` does not exist.

- [ ] **Step 3: Add the model-level trigram index**

In `backend/src/ragstudio/db/models.py`, add this `Index` entry inside `Chunk.__table_args__`, after `ix_chunks_document_preview_ref` and before `ix_chunks_text_search_ar_trgm`:

```python
        Index(
            "ix_chunks_text_trgm",
            "text",
            postgresql_using="gin",
            postgresql_ops={"text": "gin_trgm_ops"},
        ),
```

- [ ] **Step 4: Add the runtime schema repair index**

In `backend/src/ragstudio/db/engine.py`, add this block at the start of `_ensure_chunk_search_indexes()` after the PostgreSQL dialect guard:

```python
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_chunks_text_trgm
            ON chunks USING gin (text gin_trgm_ops)
            """
        )
    )
```

- [ ] **Step 5: Run the focused index test and verify it passes**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_chunk_lexical_search_repository.py::test_init_db_creates_english_text_trigram_index -q
```

Expected: passes.

- [ ] **Step 6: Run lexical repository tests**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_chunk_lexical_search_repository.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit the index fix**

```bash
git add backend/src/ragstudio/db/models.py backend/src/ragstudio/db/engine.py backend/tests/test_chunk_lexical_search_repository.py
git commit -m "perf: add trigram index for chunk text search"
```

---

### Task 2: Make Metadata Retrieval Passes Concurrent Without Sharing Sessions

**Files:**
- Modify: `backend/src/ragstudio/services/metadata_retrieval_service.py:1-76`
- Modify: `backend/src/ragstudio/services/query_service.py:1-76`
- Modify: `backend/src/ragstudio/services/query_service.py:301-307`
- Modify: `backend/src/ragstudio/api/routes/query.py:18-22`
- Test: `backend/tests/test_metadata_retrieval_service.py`

- [ ] **Step 1: Write a failing concurrent dispatch test**

Add these imports near the top of `backend/tests/test_metadata_retrieval_service.py`:

```python
import asyncio
from time import perf_counter
```

Add this fake service near the other fake chunk services:

```python
class SlowMetadataPassChunkService:
    def __init__(self):
        self.started: list[str] = []
        self.finished: list[str] = []

    async def search(self, search_in):
        self.started.append(search_in.query)
        await asyncio.sleep(0.05)
        self.finished.append(search_in.query)
        return type(
            "SearchResult",
            (),
            {
                "items": [
                    ChunkOut(
                        id=f"chunk-{search_in.query}",
                        document_id="doc-1",
                        text=f"Result for {search_in.query}",
                        source_location={},
                        metadata={"score": 10.0},
                    )
                ],
                "total": 1,
            },
        )()
```

Add this test:

```python
@pytest.mark.asyncio
async def test_metadata_service_runs_non_blocking_passes_concurrently():
    chunk_service = SlowMetadataPassChunkService()
    understanding = QueryUnderstanding(
        query="query",
        intent="mixed",
        answer_type="text",
        retrieval_passes=[
            RetrievalPass("phrase_exact", "phrase"),
            RetrievalPass("semantic_metadata", "semantic"),
        ],
    )

    started = perf_counter()
    candidates, trace = await MetadataRetrievalService(
        chunk_service,
        parallel_search=chunk_service.search,
    ).retrieve(
        "query",
        understanding=understanding,
        document_ids=["doc-1"],
        variant_id="variant-1",
        limit=5,
    )
    elapsed = perf_counter() - started

    assert elapsed < 0.09
    assert chunk_service.started == ["phrase", "semantic"]
    assert sorted(chunk_service.finished) == ["phrase", "semantic"]
    assert [candidate.chunk_id for candidate in candidates] == ["chunk-phrase", "chunk-semantic"]
    assert [item["name"] for item in trace["passes"]] == ["phrase_exact", "semantic_metadata"]
```

- [ ] **Step 2: Write a failing sequential fallback test**

Add this test below the concurrent test:

```python
@pytest.mark.asyncio
async def test_metadata_service_uses_sequential_search_without_parallel_callable():
    chunk_service = SlowMetadataPassChunkService()
    understanding = QueryUnderstanding(
        query="query",
        intent="mixed",
        answer_type="text",
        retrieval_passes=[
            RetrievalPass("phrase_exact", "phrase"),
            RetrievalPass("semantic_metadata", "semantic"),
        ],
    )

    started = perf_counter()
    candidates, trace = await MetadataRetrievalService(chunk_service).retrieve(
        "query",
        understanding=understanding,
        document_ids=["doc-1"],
        variant_id="variant-1",
        limit=5,
    )
    elapsed = perf_counter() - started

    assert elapsed >= 0.09
    assert [candidate.chunk_id for candidate in candidates] == ["chunk-phrase", "chunk-semantic"]
    assert [item["name"] for item in trace["passes"]] == ["phrase_exact", "semantic_metadata"]
```

- [ ] **Step 3: Write a failing early-stop replay test**

Add this fake service:

```python
class DirectEvidenceParallelChunkService:
    def __init__(self):
        self.calls: list[str] = []

    async def search(self, search_in):
        self.calls.append(search_in.query)
        if search_in.query == "direct":
            items = [
                ChunkOut(
                    id="direct",
                    document_id="doc-1",
                    text="Direct evidence",
                    source_location={},
                    metadata={"score": 100.0},
                )
            ]
        else:
            items = [
                ChunkOut(
                    id="later",
                    document_id="doc-1",
                    text="Later evidence",
                    source_location={},
                    metadata={"score": 50.0},
                )
            ]
        return type("SearchResult", (), {"items": items, "total": len(items)})()
```

Add this test:

```python
@pytest.mark.asyncio
async def test_metadata_service_replays_parallel_results_in_pass_order_and_stops_trace():
    chunk_service = DirectEvidenceParallelChunkService()
    understanding = QueryUnderstanding(
        query="query",
        intent="mixed",
        answer_type="text",
        retrieval_passes=[
            RetrievalPass("phrase_exact", "direct", direct_evidence=True),
            RetrievalPass("semantic_metadata", "later"),
        ],
    )

    candidates, trace = await MetadataRetrievalService(
        chunk_service,
        parallel_search=chunk_service.search,
    ).retrieve(
        "query",
        understanding=understanding,
        document_ids=["doc-1"],
        variant_id="variant-1",
        limit=5,
    )

    assert sorted(chunk_service.calls) == ["direct", "later"]
    assert [candidate.chunk_id for candidate in candidates] == ["direct"]
    assert [item["name"] for item in trace["passes"]] == ["phrase_exact"]
```

- [ ] **Step 4: Run metadata tests and verify failure**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_metadata_retrieval_service.py::test_metadata_service_runs_non_blocking_passes_concurrently backend/tests/test_metadata_retrieval_service.py::test_metadata_service_uses_sequential_search_without_parallel_callable backend/tests/test_metadata_retrieval_service.py::test_metadata_service_replays_parallel_results_in_pass_order_and_stops_trace -q
```

Expected: concurrent test fails because current implementation always runs passes sequentially and does not accept `parallel_search`.

- [ ] **Step 5: Add parallel-search support to `MetadataRetrievalService`**

In `backend/src/ragstudio/services/metadata_retrieval_service.py`, add imports:

```python
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
```

Add this type and dataclass above `MetadataRetrievalService`:

```python
MetadataSearch = Callable[[ChunkSearchIn], Awaitable[Any]]


@dataclass(frozen=True)
class MetadataPassResult:
    retrieval_pass: RetrievalPass
    pass_query: str
    started_at: float
    search: Any
```

Change the constructor to:

```python
    def __init__(
        self,
        chunk_service: Any,
        *,
        parallel_search: MetadataSearch | None = None,
        max_parallel_passes: int = 4,
    ):
        self.chunk_service = chunk_service
        self.parallel_search = parallel_search
        self.max_parallel_passes = max(1, max_parallel_passes)
```

Replace the loop in `retrieve()` with:

```python
        pass_results = await self._run_metadata_passes(
            query,
            understanding=understanding,
            document_ids=document_ids,
            variant_id=variant_id,
            limit=limit,
        )
        for pass_result in pass_results:
            retrieval_pass = pass_result.retrieval_pass
            pass_candidates: list[EvidenceCandidate] = []
            for index, chunk in enumerate(pass_result.search.items, start=1):
                chunk_id = _chunk_id(chunk)
                if chunk_id in seen_chunk_ids:
                    continue
                candidate = self._candidate_from_chunk(chunk, index, retrieval_pass)
                if candidate.retrieval_pass != "reference_hypothesis":
                    seen_chunk_ids.add(chunk_id)
                pass_candidates.append(candidate)

            candidates.extend(pass_candidates)
            pass_traces.append(
                {
                    "name": retrieval_pass.name,
                    "query": pass_result.pass_query,
                    "candidate_count": len(pass_candidates),
                    "latency_ms": _elapsed_ms(pass_result.started_at),
                    "top_candidate_ids": [
                        candidate.candidate_id for candidate in pass_candidates[:5]
                    ],
                }
            )
            if _has_direct_evidence_candidates(retrieval_pass, pass_candidates):
                break
```

Add these methods inside `MetadataRetrievalService`:

```python
    async def _run_metadata_passes(
        self,
        query: str,
        *,
        understanding: QueryUnderstanding,
        document_ids: list[str],
        variant_id: str,
        limit: int,
    ) -> list[MetadataPassResult]:
        retrieval_passes = self._metadata_passes(understanding)
        if self.parallel_search is None or len(retrieval_passes) <= 1:
            results: list[MetadataPassResult] = []
            for retrieval_pass in retrieval_passes:
                results.append(
                    await self._run_one_pass(
                        query,
                        retrieval_pass=retrieval_pass,
                        document_ids=document_ids,
                        variant_id=variant_id,
                        limit=limit,
                        search=self.chunk_service.search,
                    )
                )
            return results

        semaphore = asyncio.Semaphore(self.max_parallel_passes)

        async def run_limited(retrieval_pass: RetrievalPass) -> MetadataPassResult:
            async with semaphore:
                return await self._run_one_pass(
                    query,
                    retrieval_pass=retrieval_pass,
                    document_ids=document_ids,
                    variant_id=variant_id,
                    limit=limit,
                    search=self.parallel_search,
                )

        return list(await asyncio.gather(*(run_limited(item) for item in retrieval_passes)))

    async def _run_one_pass(
        self,
        query: str,
        *,
        retrieval_pass: RetrievalPass,
        document_ids: list[str],
        variant_id: str,
        limit: int,
        search: MetadataSearch,
    ) -> MetadataPassResult:
        pass_started = perf_counter()
        pass_query = retrieval_pass.query or query
        result = await search(
            ChunkSearchIn(
                query=pass_query,
                document_ids=document_ids,
                variant_id=variant_id,
                limit=max(limit * retrieval_pass.limit_multiplier, limit),
                explain=True,
                include_neighbors=True,
            )
        )
        return MetadataPassResult(
            retrieval_pass=retrieval_pass,
            pass_query=pass_query,
            started_at=pass_started,
            search=result,
        )
```

- [ ] **Step 6: Wire a session-safe production parallel search callable**

In `backend/src/ragstudio/services/query_service.py`, add this import:

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
```

Change the constructor signature to include:

```python
        session_factory: async_sessionmaker[AsyncSession] | None = None,
```

Set it in the constructor:

```python
        self.session_factory = session_factory
```

Add this helper method to `QueryService`:

```python
    def _parallel_metadata_search(self):
        if self.session_factory is None:
            return None

        async def search(search_in):
            async with self.session_factory() as session:
                return await ChunkService(session, self.data_dir, self.adapter).search(search_in)

        return search
```

Change `_retrieval_orchestrator()` to:

```python
        chunk_service = ChunkService(self.session, self.data_dir, self.adapter)
        return RetrievalOrchestrator(
            chunk_service=chunk_service,
            reranker_service=self.reranker_service,
            metadata_retrieval_service=MetadataRetrievalService(
                chunk_service,
                parallel_search=self._parallel_metadata_search(),
            ),
        )
```

In `backend/src/ragstudio/api/routes/query.py`, pass the app session factory:

```python
        return await QueryService(
            session,
            request.app.state.settings.data_dir,
            settings=request.app.state.settings,
            session_factory=request.app.state.session_factory,
        ).run_query(payload)
```

- [ ] **Step 7: Run metadata tests and verify pass**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_metadata_retrieval_service.py -q
```

Expected: all metadata retrieval tests pass.

- [ ] **Step 8: Run query service smoke tests**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_query_service.py backend/tests/test_metadata_retrieval_service.py -q
```

Expected: all selected tests pass. If `backend/tests/test_query_service.py` is not present, run only the metadata retrieval test file and note that query-service coverage is absent.

- [ ] **Step 9: Commit the concurrent retrieval fix**

```bash
git add backend/src/ragstudio/services/metadata_retrieval_service.py backend/src/ragstudio/services/query_service.py backend/src/ragstudio/api/routes/query.py backend/tests/test_metadata_retrieval_service.py
git commit -m "perf: run metadata retrieval passes concurrently"
```

---

### Task 3: Precompile Hot Regexes in Hybrid Chunk Scoring

**Files:**
- Modify: `backend/src/ragstudio/services/hybrid_chunk_search.py:1-377`
- Test: `backend/tests/test_hybrid_chunk_search_arabic.py`

- [ ] **Step 1: Write a failing cached Arabic boundary pattern test**

Add this import to `backend/tests/test_hybrid_chunk_search_arabic.py`:

```python
from ragstudio.services.hybrid_chunk_search import _arabic_phrase_boundary_pattern
```

Add this test:

```python
def test_arabic_phrase_boundary_pattern_is_cached():
    first = _arabic_phrase_boundary_pattern("وحنانا")
    second = _arabic_phrase_boundary_pattern("وحنانا")

    assert first is second
```

- [ ] **Step 2: Write a behavior-preservation test for answer-bearing phrases**

Add this test:

```python
def test_compiled_answer_bearing_phrase_patterns_preserve_phrase_boost():
    chunk = Chunk(
        id="chunk-phrase",
        document_id="doc-1",
        text="This section is translated as guide us to the straight path.",
        source_location={"page": 1},
        metadata_json={},
    )

    score = HybridChunkSearch().score(
        'Which verse is translated as "guide us to the straight path"?',
        chunk,
    )

    assert score.breakdown["exact_phrase"] >= 24.0
```

- [ ] **Step 3: Run the focused regex tests and verify failure**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_hybrid_chunk_search_arabic.py::test_arabic_phrase_boundary_pattern_is_cached backend/tests/test_hybrid_chunk_search_arabic.py::test_compiled_answer_bearing_phrase_patterns_preserve_phrase_boost -q
```

Expected: import fails because `_arabic_phrase_boundary_pattern` does not exist.

- [ ] **Step 4: Add compiled regex constants and cached dynamic pattern helper**

In `backend/src/ragstudio/services/hybrid_chunk_search.py`, add this import:

```python
from functools import lru_cache
```

Add these constants below `_ENGLISH_STOPWORDS`:

```python
_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
_COUNT_QUERY_RE = re.compile(r"\b(how many|count|number of|total)\b")
_NUMBER_RE = re.compile(r"\b\d{2,}\b")
_GUIDE_US_RE = re.compile(r"\bguide\s+us\b")
_QUOTED_PHRASE_RE = re.compile(r'"([^"]{8,160})"')
_ANSWER_BEARING_PATTERNS = (
    re.compile(r"\b(?:that|which)\s+says?\s+(.+?)(?:[.?!]|$)"),
    re.compile(r"\bsays?\s+(.+?)(?:[.?!]|$)"),
    re.compile(r"\btranslated\s+as\s+(.+?)(?:[.?!]|$)"),
)
_LEADING_PHRASE_NOISE_RE = re.compile(r"^(?:that|which|the verse)\s+")
_SPACE_RE = re.compile(r"\s+")
_TERM_RE = re.compile(r"[\w\u0600-\u06FF]+", flags=re.UNICODE)
```

Add this helper near `_contains_arabic()`:

```python
@lru_cache(maxsize=2048)
def _arabic_phrase_boundary_pattern(variant: str) -> re.Pattern[str]:
    escaped = re.escape(variant)
    return re.compile(rf"(?<![\u0600-\u06FF]){escaped}(?![\u0600-\u06FF])")
```

- [ ] **Step 5: Replace hot `re.*` calls with compiled patterns**

Make these replacements in `HybridChunkSearch`:

```python
    def _has_arabic_phrase_boundary(self, searchable: str, variant: str) -> bool:
        return _arabic_phrase_boundary_pattern(variant).search(searchable) is not None
```

```python
        if not _COUNT_QUERY_RE.search(query_text):
            return 0.0
```

```python
        if not _NUMBER_RE.search(combined):
            return 0.0
```

```python
        if _GUIDE_US_RE.search(chunk_text):
            return 40.0
```

```python
        for match in _QUOTED_PHRASE_RE.finditer(query_text):
            phrases.append(match.group(1).strip())

        for pattern in _ANSWER_BEARING_PATTERNS:
            for match in pattern.finditer(query_text):
                phrase = match.group(1).strip()
                phrase = _LEADING_PHRASE_NOISE_RE.sub("", phrase)
                if phrase:
                    phrases.append(phrase)
```

```python
            phrase = _SPACE_RE.sub(" ", phrase).strip().casefold()
```

```python
        for match in _TERM_RE.finditer(value):
```

```python
def _contains_arabic(value: str) -> bool:
    return _ARABIC_RE.search(value) is not None
```

- [ ] **Step 6: Run focused scorer tests and verify pass**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_hybrid_chunk_search_arabic.py -q
```

Expected: all hybrid scorer tests pass.

- [ ] **Step 7: Commit the regex optimization**

```bash
git add backend/src/ragstudio/services/hybrid_chunk_search.py backend/tests/test_hybrid_chunk_search_arabic.py
git commit -m "perf: cache regexes in hybrid chunk scoring"
```

---

### Task 4: Final Retrieval Performance Verification

**Files:**
- Verify only unless earlier tasks expose missing coverage.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_chunk_lexical_search_repository.py backend/tests/test_metadata_retrieval_service.py backend/tests/test_hybrid_chunk_search_arabic.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run lint on touched files**

Run:

```bash
ruff check backend/src/ragstudio/db/models.py backend/src/ragstudio/db/engine.py backend/src/ragstudio/services/chunk_lexical_search_repository.py backend/src/ragstudio/services/metadata_retrieval_service.py backend/src/ragstudio/services/query_service.py backend/src/ragstudio/api/routes/query.py backend/src/ragstudio/services/hybrid_chunk_search.py backend/tests/test_chunk_lexical_search_repository.py backend/tests/test_metadata_retrieval_service.py backend/tests/test_hybrid_chunk_search_arabic.py
```

Expected: `All checks passed!`

- [ ] **Step 3: Verify the query route still constructs successfully**

Run:

```bash
PYTHONPATH=backend/src python -m pytest backend/tests/test_query_service.py backend/tests/test_documents.py -q
```

Expected: all selected tests pass. If either file is absent or requires unavailable services, record the exact blocker in the final implementation notes and keep the focused retrieval tests as the required gate.

- [ ] **Step 4: Commit verification-only cleanup if needed**

If final verification required small test or lint cleanup, commit it:

```bash
git add backend/src/ragstudio backend/tests
git commit -m "test: verify retrieval performance optimizations"
```

If no cleanup was needed, do not create an empty commit.

---

## Self-Review

- Spec coverage: The plan covers all three reported bottlenecks: missing English trigram index, sequential metadata retrieval, and regex overhead in hybrid scoring.
- Corrected assumption: Parallel metadata retrieval is not implemented as a direct `asyncio.gather()` over the current `ChunkService` instance because that would concurrently use one SQLAlchemy `AsyncSession`. The plan adds a production-safe `parallel_search` callable backed by fresh sessions.
- Placeholder scan: No placeholder markers or unspecified test instructions remain.
- Type consistency: `MetadataRetrievalService` keeps `ChunkSearchIn`, `QueryUnderstanding`, `RetrievalPass`, and `EvidenceCandidate`; `QueryService` receives `async_sessionmaker[AsyncSession]`; regex helper returns `re.Pattern[str]`.
