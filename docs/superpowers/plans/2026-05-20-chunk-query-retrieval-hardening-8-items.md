# Chunk Query Retrieval Hardening 8 Items Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Handle the eight reviewed architecture suggestions as two code fixes, two scoped investigations, and four evidence-backed decision records.

**Architecture:** Preserve Ragstudio's evidence-first pipeline. Canonical Postgres chunks stay the source of truth, quality/materialization policy gates retrieval, route planning remains explicit, fusion/rerank traces stay explainable, and public claims require replayable proof evidence.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async ORM, pytest, Ragstudio chunk/query services, local `.codex` skills.

---

## Required Skills

- Use `.codex/skills/rag-pipeline-auditor/SKILL.md` for end-to-end evidence, quality gates, runtime, jobs, layout, and proof safety.
- Use `.codex/skills/chunk-query-retrieval-auditor/SKILL.md` for chunk search, query planning, candidate generation, fusion/rerank, and layers 6-8 architecture.

## Scope Check

Implement now:

- Bounded chunk search fallback.
- CPU offload for remaining synchronous indexing steps.

Investigate and record:

- Layout diagnostics architecture.
- Native storage env mutation / direct config feasibility.

Decision-record only:

- Full DB-level hybrid vector + FTS / RRF.
- `previous_chunk_id` / `next_chunk_id` self-links.
- Active job unique-index migration concern.
- `pg_trgm` / `ILIKE` concern.

## File Structure

- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Modify: `backend/tests/test_chunks.py`
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
- Modify: `backend/tests/test_index_lifecycle_service.py`
- Create: `docs/architecture/chunk-query-retrieval-hardening-decisions.md`
- Preserve: `.codex/skills/chunk-query-retrieval-auditor/SKILL.md`

---

### Task 1: Bound Chunk Search Fallback

**Files:**
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Modify: `backend/tests/test_chunks.py`

- [x] **Step 1: Add a regression proving fallback is bounded**

Add a focused test to `backend/tests/test_chunks.py` that creates more chunks than the fallback window, searches with a query that has no lexical/reference prefilter hits, and asserts the response only reports the bounded candidate set rather than treating the whole table as ranked.

- [x] **Step 2: Implement bounded fallback candidates**

In `ChunkService.search`, when reference, English, and Arabic prefilters return no rows, select only a bounded fallback window using deterministic ordering, `limit`, and `offset` context. Do not load all matching chunks into request memory.

- [x] **Step 3: Keep response semantics honest**

Ensure `total` and `has_more` describe the ranked candidate set actually considered. Do not imply that all chunks in a large corpus were ranked when the fallback was bounded.

- [x] **Step 4: Run focused chunk tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_chunks.py backend/tests/test_chunk_lexical_search_repository.py backend/tests/test_chunk_service_arabic_search.py -q
```

---

### Task 2: Offload Remaining CPU-Heavy Indexing Steps

**Files:**
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
- Modify: `backend/tests/test_index_lifecycle_service.py`

- [x] **Step 1: Add/adjust a regression for CPU helper usage**

Add a focused test showing layout repair and quality validation run through the lifecycle service's CPU-bound helper rather than inline on the event loop.

- [x] **Step 2: Offload layout repair**

Wrap `self.layout_auto_repair.repair(adapter_chunks)` with the existing CPU-bound helper pattern.

- [x] **Step 3: Offload quality validation**

Wrap `self.quality_gate.validate_adapter_chunks(...)` with the existing CPU-bound helper pattern while preserving the same report payload.

- [x] **Step 4: Run focused indexing tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_index_lifecycle_service.py backend/tests/test_job_quality_warnings.py -q
```

---

### Task 3: Layout Diagnostics Investigation

**Files:**
- Create/modify: `docs/architecture/chunk-query-retrieval-hardening-decisions.md`

- [x] **Step 1: Inspect layout repair and proof expectations**

Review `layout_auto_repair.py`, `test_layout_auto_repair.py`, proof packet tests, and current chunk metadata shape.

- [x] **Step 2: Record recommended first diagnostic set**

Document the first safe diagnostics to add later: missing coordinates, invalid coordinate shape, impossible page spans, overlapping blocks, and suspicious reading order gaps.

- [x] **Step 3: State non-negotiable guardrail**

Record that the first pass must be diagnostics-only and must not fabricate repaired coordinates or missing provenance.

---

### Task 4: Native Storage Env Mutation Investigation

**Files:**
- Create/modify: `docs/architecture/chunk-query-retrieval-hardening-decisions.md`

- [x] **Step 1: Inspect native runtime storage boundary**

Review `native_storage_config.py`, `native_raganything_adapter.py`, and `test_native_storage_config.py`.

- [x] **Step 2: Record feasibility decision**

If direct third-party storage config is not verified in this pass, record the current `scoped_native_storage_env()` boundary as intentional containment and list the future replacement condition.

- [x] **Step 3: Record validation path**

Name the focused tests that protect the current containment boundary.

---

### Task 5: Full DB-Level Hybrid RRF Decision

**Files:**
- Create/modify: `docs/architecture/chunk-query-retrieval-hardening-decisions.md`

- [x] **Step 1: Record deferred status**

Explain why full SQL vector + FTS + RRF is deferred until eval coverage exists.

- [x] **Step 2: Define the eval gate**

Require exact reference lookup, conversational terms, Arabic text, document filters, quality-blocked chunks, reranker changes, graph degradation, and runtime degradation cases before implementation.

---

### Task 6: Chunk Self-Link Decision

**Files:**
- Create/modify: `docs/architecture/chunk-query-retrieval-hardening-decisions.md`

- [x] **Step 1: Record deferred status**

Explain why `previous_chunk_id` and `next_chunk_id` are deferred until a concrete graph/query/UI traversal requires stable adjacency.

- [x] **Step 2: Define the future acceptance criteria**

Require schema migration/backfill plan, persistence tests, graph tests, and UI/query consumer evidence before adding the columns.

---

### Task 7: Active Job Unique-Index Decision

**Files:**
- Create/modify: `docs/architecture/chunk-query-retrieval-hardening-decisions.md`

- [x] **Step 1: Record mostly-handled status**

Document that startup dedupes active index jobs before creating `uq_active_index_document_job`.

- [x] **Step 2: Define when to reopen**

Reopen only if real startup failures, duplicate active job rows, or missing regression coverage are found.

---

### Task 8: `pg_trgm` / `ILIKE` Decision

**Files:**
- Create/modify: `docs/architecture/chunk-query-retrieval-hardening-decisions.md`

- [x] **Step 1: Record stale finding**

Document that `pg_trgm` and trigram indexes already exist, so the missing-index claim is stale.

- [x] **Step 2: Define benchmark gate**

Keep `ILIKE` query-shape changes as future benchmark work only after EXPLAIN/perf evidence shows current trigram-backed queries are insufficient.

---

## Final Validation

Run the focused suites from Tasks 1 and 2. If available, run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_chunks.py backend/tests/test_chunk_lexical_search_repository.py backend/tests/test_chunk_service_arabic_search.py backend/tests/test_index_lifecycle_service.py backend/tests/test_job_quality_warnings.py -q
```

Report any blocked validation clearly.
