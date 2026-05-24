# Live Database Hybrid Retrieval Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an out-of-the-box PostgreSQL FTS retrieval baseline, with an explicit pgvector extension point, that can be measured with live database-backed evaluation cases before production ranking changes are enabled.

**Architecture:** Preserve canonical Postgres chunks as the source of truth. Add a database baseline repository that runs FTS out of the box and can later fuse pgvector rows when a canonical embedding table is configured. Keep the baseline trace-only for query orchestration until product ranking is deliberately switched over and covered by live eval gates.

**Tech Stack:** Python 3.12, SQLAlchemy async, PostgreSQL, PostgreSQL full-text search, pgvector extension readiness, pytest, existing retrieval metrics.

---

## Scope Check

This is valuable, but the missing piece is narrower than "no baseline exists." The repo already has synthetic gates in `backend/tests/test_retrieval_quality_eval.py`, metric helpers in `backend/src/ragstudio/services/retrieval_metrics.py`, `pg_trgm`/`vector` extension setup in `backend/src/ragstudio/db/engine.py`, and a trigram text index on `chunks.text`.

The real gap is live, database-level quality measurement. `VectorCandidateRepository` currently uses bounded `ILIKE` term matching and synthetic scores, so it is not a live PostgreSQL FTS/pgvector quality baseline. The current `Chunk` model does not have a canonical embedding column; pgvector must remain an explicit extension point or bridge to an approved vector table rather than an invented column.

## File Structure

- Modify `backend/src/ragstudio/db/models.py`
  - Add a `to_tsvector('simple', text)` expression GIN index declaration for chunk FTS.
- Modify `backend/src/ragstudio/db/engine.py`
  - Add runtime repair for the same FTS expression index.
- Modify `backend/tests/test_chunk_lexical_search_repository.py`
  - Prove `init_db()` creates the FTS expression index.
- Create `backend/src/ragstudio/services/db_hybrid_retrieval_repository.py`
  - Own bounded FTS candidate SQL over canonical chunks and expose an empty pgvector extension point until an embedding table contract exists.
- Create `backend/tests/test_db_hybrid_retrieval_repository.py`
  - Prove FTS ranking, document filters, quality policy filtering, and bounded row counts.
- Create `backend/src/ragstudio/services/live_retrieval_baseline_service.py`
  - Run approved cases through the DB baseline, convert rows to `EvidenceCandidate`, and use existing retrieval metrics.
- Create `backend/tests/test_live_retrieval_baseline_service.py`
  - Prove MRR/NDCG/precision output over live DB chunks using `calculate_retrieval_metrics(candidates, relevant_references=..., k=...)`.
- Create `backend/src/ragstudio/services/live_retrieval_baseline_cli.py`
  - Provide an operator-runnable module that loads approved JSON cases, connects to the configured PostgreSQL database, and prints per-case plus aggregate metrics.
- Create `backend/tests/test_live_retrieval_baseline_cli.py`
  - Prove the CLI parses cases, rejects invalid input, and emits the expected metric JSON without requiring ad hoc Python.
- Modify `backend/src/ragstudio/services/retrieval_orchestrator.py`
  - Add optional trace-only `live_db_baseline` lane diagnostics gated by `query_config["live_db_baseline"]`.
- Modify `backend/tests/test_retrieval_orchestrator.py`
  - Prove the optional baseline trace does not replace production ranking.
- Modify `docs/benchmarks/ragstudio-oss-proof-v1/retrieval-quality-baseline.md`
  - Separate static proof gates from optional live DB baseline gates.
- Create `docs/benchmarks/ragstudio-oss-proof-v1/live-db-baseline-cases.sample.json`
  - Provide the JSON case shape consumed by the live baseline CLI without requiring private corpus data.

---

### Task 1: Add FTS Index Contract

**Files:**
- Modify: `backend/src/ragstudio/db/models.py`
- Modify: `backend/src/ragstudio/db/engine.py`
- Test: `backend/tests/test_chunk_lexical_search_repository.py`

- [ ] **Step 1: Write the failing FTS index regression**

Add this test to `backend/tests/test_chunk_lexical_search_repository.py` near the other runtime index tests:

```python
@pytest.mark.asyncio
async def test_init_db_creates_simple_fts_expression_index(database_url):
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
                  AND indexname = 'ix_chunks_text_fts_simple'
                """
            )
        )

    assert indexdef is not None
    assert "USING gin" in indexdef
    assert "to_tsvector('simple'::regconfig, text)" in indexdef
    await engine.dispose()
```

- [ ] **Step 2: Run the index test and verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_chunk_lexical_search_repository.py::test_init_db_creates_simple_fts_expression_index -q
```

Expected: FAIL because `ix_chunks_text_fts_simple` is not created yet.

- [ ] **Step 3: Add model-level FTS expression index**

In `backend/src/ragstudio/db/models.py`, add this `Index` inside `Chunk.__table_args__` after `ix_chunks_text_trgm`:

```python
        Index(
            "ix_chunks_text_fts_simple",
            text("to_tsvector('simple', text)"),
            postgresql_using="gin",
        ),
```

No new import is needed because `backend/src/ragstudio/db/models.py` already imports `text` from SQLAlchemy.

- [ ] **Step 4: Add runtime schema repair index**

In `_ensure_chunk_search_indexes()` in `backend/src/ragstudio/db/engine.py`, add this block after `ix_chunks_text_trgm`:

```python
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_chunks_text_fts_simple
            ON chunks USING gin (to_tsvector('simple', text))
            """
        )
    )
```

- [ ] **Step 5: Run the index test and verify it passes**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_chunk_lexical_search_repository.py::test_init_db_creates_simple_fts_expression_index -q
```

Expected: PASS.

- [ ] **Step 6: Commit the index contract**

```bash
git add backend/src/ragstudio/db/models.py backend/src/ragstudio/db/engine.py backend/tests/test_chunk_lexical_search_repository.py
git commit -m "feat: add chunk fts baseline index"
```

---

### Task 2: Add Database FTS Retrieval Repository

**Files:**
- Create: `backend/src/ragstudio/services/db_hybrid_retrieval_repository.py`
- Test: `backend/tests/test_db_hybrid_retrieval_repository.py`

- [ ] **Step 1: Write failing FTS repository tests**

Create `backend/tests/test_db_hybrid_retrieval_repository.py`:

```python
import pytest

from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.services.db_hybrid_retrieval_repository import DbHybridRetrievalRepository


@pytest.mark.asyncio
async def test_db_hybrid_repository_ranks_fts_matches(database_url, tmp_path):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)
    async with factory() as session:
        session.add(
            Document(
                id="doc-live",
                filename="live.pdf",
                content_type="application/pdf",
                sha256="live-sha",
                artifact_path=str(tmp_path / "live.pdf"),
                status="succeeded",
            )
        )
        session.add_all(
            [
                Chunk(
                    id="chunk-top",
                    document_id="doc-live",
                    text="Alpha retrieval baseline evidence with exact operational term.",
                    source_location={"page": 1, "reference": "top-ref"},
                    metadata_json={
                        "reference_metadata": {"references": ["top-ref"]},
                        "quality_action_policy": {"index_vector": True},
                    },
                ),
                Chunk(
                    id="chunk-low",
                    document_id="doc-live",
                    text="General alpha evidence background without the operational phrase.",
                    source_location={"page": 2, "reference": "low-ref"},
                    metadata_json={
                        "reference_metadata": {"references": ["low-ref"]},
                        "quality_action_policy": {"index_vector": True},
                    },
                ),
            ]
        )
        await session.commit()

        rows = await DbHybridRetrievalRepository(session).search(
            query="operational evidence",
            document_ids=["doc-live"],
            limit=5,
            mode="fts",
        )

    assert [row["chunk_id"] for row in rows][:2] == ["chunk-top", "chunk-low"]
    assert rows[0]["retrieval_pass"] == "fts_db"
    assert rows[0]["score"] > rows[1]["score"]
    await engine.dispose()
```

Add a second test in the same file:

```python
@pytest.mark.asyncio
async def test_db_hybrid_repository_filters_quality_blocked_chunks(database_url, tmp_path):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)
    async with factory() as session:
        session.add(
            Document(
                id="doc-quality",
                filename="quality.pdf",
                content_type="application/pdf",
                sha256="quality-sha",
                artifact_path=str(tmp_path / "quality.pdf"),
                status="succeeded",
            )
        )
        session.add_all(
            [
                Chunk(
                    id="chunk-allowed",
                    document_id="doc-quality",
                    text="Needle evidence allowed",
                    source_location={"page": 1, "reference": "allowed-ref"},
                    metadata_json={
                        "reference_metadata": {"references": ["allowed-ref"]},
                        "quality_action_policy": {"index_vector": True},
                    },
                ),
                Chunk(
                    id="chunk-blocked",
                    document_id="doc-quality",
                    text="Needle evidence blocked",
                    source_location={"page": 2, "reference": "blocked-ref"},
                    metadata_json={
                        "reference_metadata": {"references": ["blocked-ref"]},
                        "quality_action_policy": {"index_vector": False},
                    },
                ),
            ]
        )
        await session.commit()

        rows = await DbHybridRetrievalRepository(session).search(
            query="needle evidence",
            document_ids=["doc-quality"],
            limit=10,
            mode="fts",
        )

    assert [row["chunk_id"] for row in rows] == ["chunk-allowed"]
    await engine.dispose()
```

Add a third test in the same file:

```python
@pytest.mark.asyncio
async def test_db_hybrid_repository_applies_document_scope_and_limit(database_url, tmp_path):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)
    async with factory() as session:
        session.add_all(
            [
                Document(
                    id="doc-scope-a",
                    filename="scope-a.pdf",
                    content_type="application/pdf",
                    sha256="scope-a-sha",
                    artifact_path=str(tmp_path / "scope-a.pdf"),
                    status="succeeded",
                ),
                Document(
                    id="doc-scope-b",
                    filename="scope-b.pdf",
                    content_type="application/pdf",
                    sha256="scope-b-sha",
                    artifact_path=str(tmp_path / "scope-b.pdf"),
                    status="succeeded",
                ),
            ]
        )
        for index in range(3):
            session.add(
                Chunk(
                    id=f"chunk-scope-a-{index}",
                    document_id="doc-scope-a",
                    text=f"Scoped needle evidence {index}",
                    source_location={"page": index + 1, "reference": f"scope-a-{index}"},
                    metadata_json={
                        "reference_metadata": {"references": [f"scope-a-{index}"]},
                        "quality_action_policy": {"index_vector": True},
                    },
                )
            )
        session.add(
            Chunk(
                id="chunk-scope-b",
                document_id="doc-scope-b",
                text="Scoped needle evidence outside requested document",
                source_location={"page": 1, "reference": "scope-b"},
                metadata_json={
                    "reference_metadata": {"references": ["scope-b"]},
                    "quality_action_policy": {"index_vector": True},
                },
            )
        )
        await session.commit()

        rows = await DbHybridRetrievalRepository(session).search(
            query="scoped needle evidence",
            document_ids=["doc-scope-a"],
            limit=1,
            mode="fts",
        )

    assert len(rows) == 1
    assert rows[0]["document_id"] == "doc-scope-a"
    assert rows[0]["chunk_id"].startswith("chunk-scope-a-")
    await engine.dispose()
```

Add a fourth test in the same file to prevent blocked rows from consuming the SQL limit before quality filtering:

```python
@pytest.mark.asyncio
async def test_db_hybrid_repository_filters_quality_before_limit(database_url, tmp_path):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)
    async with factory() as session:
        session.add(
            Document(
                id="doc-limit-quality",
                filename="limit-quality.pdf",
                content_type="application/pdf",
                sha256="limit-quality-sha",
                artifact_path=str(tmp_path / "limit-quality.pdf"),
                status="succeeded",
            )
        )
        session.add_all(
            [
                Chunk(
                    id="chunk-blocked-limit",
                    document_id="doc-limit-quality",
                    text="Dominant needle evidence exact phrase",
                    source_location={"page": 1, "reference": "blocked-limit-ref"},
                    metadata_json={
                        "reference_metadata": {"references": ["blocked-limit-ref"]},
                        "quality_action_policy": {"index_vector": False},
                    },
                ),
                Chunk(
                    id="chunk-action-blocked-limit",
                    document_id="doc-limit-quality",
                    text="Dominant needle evidence exact phrase with action block",
                    source_location={"page": 2, "reference": "action-blocked-limit-ref"},
                    metadata_json={
                        "reference_metadata": {"references": ["action-blocked-limit-ref"]},
                        "quality_action_policy": {"action": "block", "index_vector": True},
                    },
                ),
                Chunk(
                    id="chunk-allowed-limit",
                    document_id="doc-limit-quality",
                    text="Needle evidence",
                    source_location={"page": 3, "reference": "allowed-limit-ref"},
                    metadata_json={
                        "reference_metadata": {"references": ["allowed-limit-ref"]},
                        "quality_action_policy": {"index_vector": True},
                    },
                ),
            ]
        )
        await session.commit()

        rows = await DbHybridRetrievalRepository(session).search(
            query="needle evidence",
            document_ids=["doc-limit-quality"],
            limit=1,
            mode="fts",
        )

    assert [row["chunk_id"] for row in rows] == ["chunk-allowed-limit"]
    await engine.dispose()
```

Add a fifth test in the same file for malformed or empty FTS input:

```python
@pytest.mark.asyncio
async def test_db_hybrid_repository_returns_no_rows_for_blank_query(database_url):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)
    async with factory() as session:
        rows = await DbHybridRetrievalRepository(session).search(
            query="   ",
            document_ids=[],
            limit=5,
            mode="fts",
        )

    assert rows == []
    await engine.dispose()
```

- [ ] **Step 2: Run the repository tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_db_hybrid_retrieval_repository.py -q
```

Expected: FAIL because the repository does not exist.

- [ ] **Step 3: Implement FTS search**

Create `backend/src/ragstudio/services/db_hybrid_retrieval_repository.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from ragstudio.db.models import Chunk
from ragstudio.services.evidence_context import evidence_context_from_metadata
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

SearchMode = Literal["fts", "vector", "hybrid"]


class DbHybridRetrievalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self,
        *,
        query: str,
        document_ids: list[str],
        limit: int,
        mode: SearchMode = "hybrid",
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(limit, 100))
        if mode == "vector" and query_embedding:
            return await self._vector_search(query_embedding, document_ids, bounded_limit)
        if mode == "hybrid" and query_embedding:
            return await self._hybrid_search(query, query_embedding, document_ids, bounded_limit)
        return await self._fts_search(query, document_ids, bounded_limit)

    async def _fts_search(
        self,
        query: str,
        document_ids: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        tsquery = func.websearch_to_tsquery("simple", query)
        vector = func.to_tsvector("simple", Chunk.text)
        rank = func.ts_rank_cd(vector, tsquery)
        statement = select(Chunk, rank.label("score")).where(vector.op("@@")(tsquery))
        if document_ids:
            statement = statement.where(Chunk.document_id.in_(document_ids))
        statement = statement.where(
            Chunk.metadata_json["quality_action_policy"]["index_vector"].as_boolean().is_not(False),
            Chunk.metadata_json["quality_action_policy"]["action"].as_string().is_distinct_from("block"),
        )
        statement = statement.order_by(text("score DESC"), Chunk.created_at.asc(), Chunk.id.asc()).limit(limit)
        result = await self.session.execute(statement)
        return [
            _row(chunk, score=float(score or 0.0), rank=index, retrieval_pass="fts_db")
            for index, (chunk, score) in enumerate(result.all(), start=1)
        ]

    async def _vector_search(
        self,
        query_embedding: list[float],
        document_ids: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        # Pgvector requires a canonical embedding table contract. Returning no
        # rows keeps hybrid mode honest until that table is explicitly wired.
        return []

    async def _hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        document_ids: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        fts_rows = await self._fts_search(query, document_ids, limit)
        vector_rows = await self._vector_search(query_embedding, document_ids, limit)
        return _rrf(fts_rows, vector_rows)[:limit]


def _row(chunk: Chunk, *, score: float, rank: int, retrieval_pass: str) -> dict[str, Any]:
    metadata = dict(chunk.metadata_json) if isinstance(chunk.metadata_json, dict) else {}
    evidence_context = evidence_context_from_metadata(
        metadata,
        source_location=chunk.source_location,
        content_type=chunk.content_type,
    )
    if evidence_context:
        metadata["evidence_context"] = evidence_context
    return {
        "candidate_id": f"{retrieval_pass}:{chunk.id}",
        "chunk_id": chunk.id,
        "document_id": chunk.document_id,
        "text": chunk.text,
        "source_location": chunk.source_location,
        "metadata": metadata,
        "score": score,
        "rank": rank,
        "retrieval_pass": retrieval_pass,
    }


def _rrf(*ranked_lists: list[dict[str, Any]], k: int = 60) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for ranked in ranked_lists:
        for rank, row in enumerate(ranked, start=1):
            chunk_id = str(row["chunk_id"])
            existing = merged.setdefault(chunk_id, {**row, "score": 0.0, "retrieval_passes": []})
            existing["score"] += 1.0 / (k + rank)
            existing["retrieval_passes"].append(row.get("retrieval_pass", "unknown"))
    return sorted(merged.values(), key=lambda item: (-float(item["score"]), str(item["chunk_id"])))
```

- [ ] **Step 4: Run the repository tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_db_hybrid_retrieval_repository.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the repository**

```bash
git add backend/src/ragstudio/services/db_hybrid_retrieval_repository.py backend/tests/test_db_hybrid_retrieval_repository.py
git commit -m "feat: add database fts retrieval baseline"
```

---

### Task 3: Add Live Baseline Evaluation Service

**Files:**
- Create: `backend/src/ragstudio/services/live_retrieval_baseline_service.py`
- Test: `backend/tests/test_live_retrieval_baseline_service.py`

- [ ] **Step 1: Write the failing live metric test**

Create `backend/tests/test_live_retrieval_baseline_service.py`:

```python
import pytest

from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.services.live_retrieval_baseline_service import LiveRetrievalBaselineService


@pytest.mark.asyncio
async def test_live_baseline_service_returns_retrieval_metrics(database_url, tmp_path):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)
    async with factory() as session:
        session.add(
            Document(
                id="doc-eval",
                filename="eval.pdf",
                content_type="application/pdf",
                sha256="eval-sha",
                artifact_path=str(tmp_path / "eval.pdf"),
                status="succeeded",
            )
        )
        session.add(
            Chunk(
                id="chunk-answer",
                document_id="doc-eval",
                text="The live baseline answer is alpha evidence.",
                source_location={"page": 1, "reference": "answer-ref"},
                metadata_json={
                    "reference_metadata": {"references": ["answer-ref"]},
                    "quality_action_policy": {"index_vector": True},
                },
            )
        )
        await session.commit()

        metrics = await LiveRetrievalBaselineService(session).evaluate_case(
            case={
                "query": "alpha evidence",
                "relevant_references": ["answer-ref"],
            },
            document_ids=["doc-eval"],
            k=5,
        )

    assert metrics.precision_at_k == 0.2
    assert metrics.recall_at_k == 1.0
    assert metrics.hit_rate == 1.0
    assert metrics.mrr == 1.0
    assert metrics.ndcg_at_k == 1.0
    await engine.dispose()
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_live_retrieval_baseline_service.py -q
```

Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement the service**

Create `backend/src/ragstudio/services/live_retrieval_baseline_service.py`:

```python
from __future__ import annotations

from typing import Any

from ragstudio.services.db_hybrid_retrieval_repository import DbHybridRetrievalRepository
from ragstudio.services.retrieval_evidence import EvidenceCandidate
from ragstudio.services.retrieval_metrics import calculate_retrieval_metrics
from sqlalchemy.ext.asyncio import AsyncSession


class LiveRetrievalBaselineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def evaluate_case(
        self,
        *,
        case: dict[str, Any],
        document_ids: list[str],
        k: int = 5,
    ):
        repository = DbHybridRetrievalRepository(self.session)
        query = str(case["query"])
        relevant_references = {str(item) for item in case.get("relevant_references", [])}
        rows = await repository.search(query=query, document_ids=document_ids, limit=k, mode="fts")
        candidates = [_candidate_from_row(row) for row in rows]
        return calculate_retrieval_metrics(candidates, relevant_references=relevant_references, k=k)


def _candidate_from_row(row: dict[str, Any]) -> EvidenceCandidate:
    return EvidenceCandidate(
        candidate_id=str(row["candidate_id"]),
        text=str(row["text"]),
        document_id=str(row["document_id"]),
        chunk_id=str(row["chunk_id"]),
        source_location=dict(row.get("source_location") or {}),
        metadata=dict(row.get("metadata") or {}),
        tool="fts_db",
        tool_rank=int(row.get("rank") or 1),
        base_score=float(row.get("score") or 0.0),
        final_score=float(row.get("score") or 0.0),
    )
```

- [ ] **Step 4: Run live baseline tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_live_retrieval_baseline_service.py backend/tests/test_retrieval_metrics.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the evaluation service**

```bash
git add backend/src/ragstudio/services/live_retrieval_baseline_service.py backend/tests/test_live_retrieval_baseline_service.py
git commit -m "feat: measure live database retrieval baseline"
```

---

### Task 4: Add Operator-Runnable Live Baseline CLI

**Files:**
- Create: `backend/src/ragstudio/services/live_retrieval_baseline_cli.py`
- Test: `backend/tests/test_live_retrieval_baseline_cli.py`

- [ ] **Step 1: Write the failing CLI tests**

Create `backend/tests/test_live_retrieval_baseline_cli.py`:

```python
import json

import pytest

from ragstudio.services import live_retrieval_baseline_cli


def test_load_cases_rejects_invalid_case_file(tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([{"query": ""}]), encoding="utf-8")

    with pytest.raises(ValueError, match="query"):
        live_retrieval_baseline_cli.load_cases(cases_path)


def test_summarize_results_emits_per_case_and_aggregate_metrics():
    payload = live_retrieval_baseline_cli.summarize_results(
        [
            {
                "case_id": "case-1",
                "metrics": {
                    "precision_at_k": 0.2,
                    "recall_at_k": 1.0,
                    "hit_rate": 1.0,
                    "mrr": 1.0,
                    "ndcg_at_k": 1.0,
                },
            },
            {
                "case_id": "case-2",
                "metrics": {
                    "precision_at_k": 0.0,
                    "recall_at_k": 0.0,
                    "hit_rate": 0.0,
                    "mrr": 0.0,
                    "ndcg_at_k": 0.0,
                },
            },
        ]
    )

    assert payload["case_count"] == 2
    assert payload["aggregate"]["mrr"] == 0.5
    assert payload["cases"][0]["case_id"] == "case-1"
```

- [ ] **Step 2: Run the CLI tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_live_retrieval_baseline_cli.py -q
```

Expected: FAIL because `live_retrieval_baseline_cli.py` does not exist.

- [ ] **Step 3: Implement the CLI module**

Create `backend/src/ragstudio/services/live_retrieval_baseline_cli.py`:

```python
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ragstudio.db.engine import make_engine, make_session_factory
from ragstudio.services.live_retrieval_baseline_service import LiveRetrievalBaselineService


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("case file must contain a JSON array")
    cases: list[dict[str, Any]] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"case {index} must be an object")
        query = item.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"case {index} must include a non-empty query")
        refs = item.get("relevant_references")
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"case {index} must include relevant_references")
        cases.append(item)
    return cases


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = ["precision_at_k", "recall_at_k", "hit_rate", "mrr", "ndcg_at_k"]
    aggregate = {
        name: round(
            sum(float(result["metrics"][name]) for result in results) / len(results),
            6,
        )
        if results
        else 0.0
        for name in metric_names
    }
    return {"case_count": len(results), "aggregate": aggregate, "cases": results}


async def run(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_cases(Path(args.cases))
    engine = make_engine(args.database_url)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            service = LiveRetrievalBaselineService(session)
            results = []
            for index, case in enumerate(cases, start=1):
                metrics = await service.evaluate_case(
                    case=case,
                    document_ids=args.document_ids,
                    k=args.k,
                )
                results.append(
                    {
                        "case_id": str(case.get("id") or f"case-{index}"),
                        "query": case["query"],
                        "metrics": asdict(metrics),
                    }
                )
            return summarize_results(results)
    finally:
        await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate live DB retrieval baseline cases.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--document-id", action="append", dest="document_ids", default=[])
    parser.add_argument("--k", type=int, default=5)
    return parser


def main() -> None:
    payload = asyncio.run(run(build_parser().parse_args()))
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the CLI tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_live_retrieval_baseline_cli.py backend/tests/test_live_retrieval_baseline_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Verify the operator command shape**

Run against a live Ragstudio PostgreSQL database with approved cases:

```powershell
$env:PYTHONPATH='backend/src'; python -m ragstudio.services.live_retrieval_baseline_cli --database-url $env:RAGSTUDIO_DATABASE_URL --cases <approved-cases.json> --document-id <document-id> --k 5
```

Expected: JSON with `case_count`, aggregate `precision_at_k`/`recall_at_k`/`mrr`/`ndcg_at_k`, and per-case metrics.

- [ ] **Step 6: Commit the CLI**

```bash
git add backend/src/ragstudio/services/live_retrieval_baseline_cli.py backend/tests/test_live_retrieval_baseline_cli.py
git commit -m "feat: add live retrieval baseline cli"
```

---

### Task 5: Add Optional Query Trace For Live DB Baseline

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Write the failing trace test**

Add this focused orchestrator test near the existing `FakeChunkSearchService` tests in `backend/tests/test_retrieval_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_orchestrator_records_live_db_baseline_trace_without_replacing_ranking():
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        query="alpha evidence",
        runtime=FakeRuntimeTool(),
        profile=type(
            "Profile",
            (),
            {"enable_rerank": False, "reranker_provider": "disabled"},
        )(),
        document_ids=["doc-live"],
        variant_id="variant-live",
        query_config={
            "response_mode": "fast",
            "limit": 3,
            "live_db_baseline": True,
            "vector_baseline_gate": {"passed": True},
        },
    )

    assert result.sources[0]["chunk_id"] == "metadata-1"
    assert any(
        trace.get("stage") == "retrieval_lane_result"
        and trace.get("lane") == "live_db_baseline"
        for trace in result.chunk_traces
    )
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_orchestrator.py::test_orchestrator_records_live_db_baseline_trace_without_replacing_ranking -q
```

Expected: FAIL because no live DB baseline trace exists.

- [ ] **Step 3: Add trace-only baseline diagnostics**

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, after route planning and before final fusion, add a guarded branch:

```python
if query_config.get("live_db_baseline") is True:
    traces.append(
        _lane_result_trace(
            lane="live_db_baseline",
            status="skipped",
            reason="live_db_baseline_requires_database_session_service",
            candidates=[],
            latency_ms=0,
        )
    )
```

Keep this trace-only until `QueryService` wires a real session-backed baseline service. Do not merge FTS rows into production `sources`.

- [ ] **Step 4: Run focused retrieval baseline tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_orchestrator.py::test_orchestrator_records_live_db_baseline_trace_without_replacing_ranking backend/tests/test_db_hybrid_retrieval_repository.py backend/tests/test_live_retrieval_baseline_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the trace gate**

```bash
git add backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: trace live database baseline lane"
```

---

### Task 6: Document Static Versus Live Gates

**Files:**
- Modify: `docs/benchmarks/ragstudio-oss-proof-v1/retrieval-quality-baseline.md`
- Create: `docs/benchmarks/ragstudio-oss-proof-v1/live-db-baseline-cases.sample.json`

- [ ] **Step 1: Add live baseline documentation**

Add this section after "Focused Validation":

````markdown
## Live Database Baseline

The static proof gate validates deterministic architecture behavior without private data or provider dependencies. Production deployments should also run the live database baseline against approved evaluation cases in their own PostgreSQL database. The live baseline uses canonical chunks, document filters, quality policy, and PostgreSQL FTS out of the box. Pgvector is an explicit extension point and should remain disabled until a canonical embedding table contract is configured. The live baseline reports the same precision, recall, MRR, and NDCG metric contract as the static gate.

Run the live baseline with:

```powershell
$env:PYTHONPATH='backend/src'; python -m ragstudio.services.live_retrieval_baseline_cli --database-url $env:RAGSTUDIO_DATABASE_URL --cases docs/benchmarks/ragstudio-oss-proof-v1/live-db-baseline-cases.sample.json --document-id <document-id> --k 5
```

Use reviewed local case files for production measurement; the sample case file documents the JSON shape only.
````

- [ ] **Step 2: Add a sample case file**

Create `docs/benchmarks/ragstudio-oss-proof-v1/live-db-baseline-cases.sample.json`:

```json
[
  {
    "id": "sample-live-case-1",
    "query": "alpha evidence",
    "relevant_references": ["answer-ref"]
  }
]
```

This file documents the approved case format only; production users should replace it with their own reviewed evaluation cases and document IDs.

- [ ] **Step 3: Review the documentation diff**

Run:

```bash
git diff -- docs/benchmarks/ragstudio-oss-proof-v1/retrieval-quality-baseline.md docs/benchmarks/ragstudio-oss-proof-v1/live-db-baseline-cases.sample.json
```

Expected: the document clearly separates public static proof from production live DB measurement.

- [ ] **Step 4: Commit the docs**

```bash
git add docs/benchmarks/ragstudio-oss-proof-v1/retrieval-quality-baseline.md docs/benchmarks/ragstudio-oss-proof-v1/live-db-baseline-cases.sample.json
git commit -m "docs: document live database retrieval baseline"
```
