---
phase: fast-query-results
reviewed: 2026-05-16T06:43:45Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - backend/src/ragstudio/db/engine.py
  - backend/src/ragstudio/db/models.py
  - backend/src/ragstudio/schemas/query.py
  - backend/src/ragstudio/services/chunk_lexical_search_repository.py
  - backend/src/ragstudio/services/chunk_service.py
  - backend/src/ragstudio/services/evidence_first_answer_service.py
  - backend/src/ragstudio/services/query_service.py
  - backend/src/ragstudio/services/query_understanding.py
  - backend/src/ragstudio/services/retrieval_evidence.py
  - backend/src/ragstudio/services/retrieval_orchestrator.py
  - backend/tests/test_metadata_retrieval_service.py
  - backend/tests/test_query_understanding.py
  - backend/tests/test_retrieval_orchestrator.py
  - backend/tests/test_runtime_query_service.py
  - docs/superpowers/plans/2026-05-16-fast-query-results.md
  - frontend/src/api/generated.ts
  - frontend/src/features/query/query-page.tsx
  - frontend/tests/query-page.test.tsx
findings:
  critical: 3
  warning: 3
  info: 0
  total: 6
status: issues_found
---

# Phase fast-query-results: Code Review Report

**Reviewed:** 2026-05-16T06:43:45Z
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

The implementation adds the requested fast/full query contract, evidence-first answer builder, query-aware planning, rerank skipping, graph hydration, and UI controls. The main architecture is directionally aligned with the plan, but the current code has correctness gaps in the fast timeout path, exact-reference labeling, and total response budget enforcement.

I did not edit source files. I only added this review artifact.

## Critical Issues

### CR-01: [BLOCKER] Fast fallback misses provider-side answer timeouts

**File:** `backend/src/ragstudio/services/retrieval_orchestrator.py:345`

**Issue:** `_answer_with_budget()` only falls back for `TimeoutError` from `asyncio.wait_for()`. The actual answer service uses `httpx.AsyncClient(timeout=timeout)` and can raise `httpx.ReadTimeout` / `httpx.TimeoutException` before `wait_for()` raises. Those exceptions skip the evidence-first fallback and are caught by the outer orchestrator failure handler, so a fast-mode query with good evidence can persist as failed instead of returning the required evidence-first answer.

**Fix:**
```python
import httpx

...
        except (TimeoutError, httpx.TimeoutException) as exc:
            if response_mode != "fast":
                raise
            timings["answer_ms"] = _elapsed_ms(answer_started)
            timings["answer_timeout_ms"] = timeout_ms
            timings["answer_fallback"] = True
            answer, token_metadata = self.evidence_first_answer_service.answer(
                query,
                evidence,
                reason="llm_timeout",
                llm_timeout_ms=timeout_ms,
            )
            return answer, {
                **token_metadata,
                "llm_answer_status": "timeout",
                "llm_error_type": exc.__class__.__name__,
            }
```

Add a regression where the answer service raises `httpx.ReadTimeout` in fast mode and assert the run still returns `answer_mode=evidence_first`.

### CR-02: [BLOCKER] Reference-first retrieval can label the wrong chunk as an exact reference

**File:** `backend/src/ragstudio/services/metadata_retrieval_service.py:55`

**Issue:** Every chunk returned by the first metadata pass for a reference query is converted with `retrieval_pass="reference_exact"`, and `_match_features()` marks it as `{"reference_exact": True}` without checking whether the chunk actually contains the requested reference. `RetrievalFusion` then gives that candidate an exact-reference boost. A non-exact result from `ChunkService.search()` can therefore be promoted as exact and shown in an evidence-first answer for a different reference.

**Fix:** Pass the requested normalized reference into candidate construction and only set `reference_exact` when `source_location.reference`, `preview_ref`, or `reference_metadata.references` contains that exact value. Otherwise keep the candidate as semantic metadata with no direct exact-reference feature.

```python
if retrieval_pass.name == "reference_exact" and _chunk_has_reference(chunk, requested_ref):
    return {"reference_exact": True, "reference": requested_ref}
return {}
```

Add a negative regression where query `Explain 1:5` returns a chunk with reference `2:2`; assert it is not marked `reference_exact` and does not receive `exact_reference_match`.

### CR-03: [BLOCKER] Fast response budget is not enforced across retrieval

**File:** `backend/src/ragstudio/services/retrieval_orchestrator.py:534`

**Issue:** Fast mode computes a `response_budget_ms` deadline, but `_fast_parallel_retrieval()` awaits metadata retrieval with no deadline and then waits up to `native_query_timeout_ms` after metadata returns. If metadata search or DB access takes most of the budget, native can still add another 2.5 seconds, and later stages start after the claimed total budget is already gone. The budget is only applied to graph and answer stages.

**Fix:** Apply the same deadline to metadata and native retrieval. Start both tasks, use `_remaining_timeout_seconds(deadline_at, ...)` for each await, and degrade a lane that misses the remaining budget instead of waiting the fixed cap after another lane has already consumed time.

```python
metadata_result = await asyncio.wait_for(
    self._timed_metadata_candidates(...),
    timeout=_remaining_timeout_seconds(deadline_at, fallback_ms=2500),
)
native_result = await asyncio.wait_for(
    native_task,
    timeout=_remaining_timeout_seconds(deadline_at, fallback_ms=timeout_ms),
)
```

Add a fast-mode regression with slow metadata plus slow native and assert total retrieval degrades inside `response_budget_ms`.

## Warnings

### WR-01: [WARNING] Reference prefilter still loads and scores the full selected chunk set

**File:** `backend/src/ragstudio/services/chunk_service.py:116`

**Issue:** `ChunkService.search()` selects all chunks for the selected documents before calling the indexed `reference_prefilter()`, then scores the full list anyway. That means the new `ix_chunks_document_preview_ref` lookup improves ordering, but it does not deliver the planned DB-first fast path for large selected Tafseer documents.

**Fix:** For reference-shaped queries, run `reference_prefilter()` before the full chunk scan and return/score that bounded set when it satisfies the request. Only fall back to the full scan when the indexed lookup returns no supported candidates.

### WR-02: [WARNING] Multi-document comparison/diversity ordering is lost after final fusion

**File:** `backend/src/ragstudio/services/retrieval_orchestrator.py:215`

**Issue:** `fuse_candidates()` applies the new multi-document ordering, but the orchestrator immediately passes that list through `RetrievalFusion.fuse()`, which sorts by direct priority and score again. In the implemented comparison case, the lower-scored best candidate from doc B can be pushed behind another doc A candidate, so the orchestrator path does not preserve the multi-document behavior that the helper tests assert.

**Fix:** Apply `_apply_multi_document_ordering()` after final fusion, or teach `RetrievalFusion` to preserve comparison/diversity rank from the incoming list. Add an orchestrator-level regression, not only a `fuse_candidates()` unit test.

### WR-03: [WARNING] Answer mode control does not expose selected state to assistive tech

**File:** `frontend/src/features/query/query-page.tsx:148`

**Issue:** The fast/full segmented control is rendered as plain buttons in a `role="group"` without `aria-pressed`, `aria-checked`, or radio semantics. Sighted users can infer selected state from styling, but screen reader users do not get the current mode.

**Fix:** Use a radio group (`role="radiogroup"` with `role="radio"` and `aria-checked`) or add `aria-pressed={responseMode === mode}` to each button and cover it in the query page test.

---

_Reviewed: 2026-05-16T06:43:45Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
