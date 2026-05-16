# Fast Query Results Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a grounded query result in 5-8 seconds by returning retrieval, graph evidence, and an evidence-first answer before the slow 32B LLM answer path can block the user.

**Architecture:** Keep retrieval, graph expansion, hydration, and source tracing in the synchronous `/api/query` path, because those stages already produce the useful proof result. Add a fast answer mode that gives the LLM a small budget and then falls back to a deterministic evidence-first answer while preserving sources, chunk traces, graph traces, and timings. The UI defaults to fast mode and labels evidence-first results clearly; full LLM wording remains available as an explicit slower mode.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async ORM, React, TanStack Query, Vitest, pytest, existing Ragstudio retrieval orchestrator.

**Execution status:** Implemented on branch `codex/fast-query-results`. The live fast Tafseer query returned in about `5.3s` wall time with `status=succeeded`, `source_count=5`, `answer_mode=evidence_first`, `graph_expansion.status=ok`, and `rerank_ms=0.0`. Full mode with a `30000ms` answer budget returned a clean persisted `ReadTimeout` failure at about `34s` when captured with a `45s` curl cap.

---

## File Structure

- Modify `backend/src/ragstudio/schemas/query.py`
  - Add `response_mode`, `answer_budget_ms`, and `response_budget_ms` to the query request contract.
- Modify `backend/src/ragstudio/services/query_understanding.py`
  - Detect query-aware hybrid strategy: reference-first, semantic-hybrid, graph-context, and count/metadata-heavy.
- Modify `backend/src/ragstudio/services/retrieval_evidence.py`
  - Carry the selected hybrid strategy into retrieval planning and scoring.
  - Add domain-aware scoring so Tafseer, hadith, legal, research, and generic documents do not use the same ranking assumptions.
- Modify `backend/src/ragstudio/services/hybrid_chunk_search.py`
  - Keep the metadata lane domain-aware through existing `domain_metadata`, `reference_metadata`, `ReferenceSemantics`, and `quality_action_policy` signals.
- Create `backend/src/ragstudio/services/evidence_first_answer_service.py`
  - Build a deterministic answer from final evidence when the LLM exceeds the fast budget.
- Modify `backend/src/ragstudio/services/retrieval_orchestrator.py`
  - Preserve evidence when answer generation times out.
  - Use evidence-first fallback only in fast mode.
  - Keep full mode behavior for users who explicitly request the slow path.
- Modify `backend/src/ragstudio/services/query_service.py`
  - Put `response_mode`, `answer_budget_ms`, and `response_budget_ms` into `query_config`.
  - In fast mode, disable rerank and cap native query time so the first visible result stays inside 5-8 seconds.
  - Mark runs failed when `error_type` is set even if `error` is an empty string.
- Modify `backend/src/ragstudio/services/metadata_retrieval_service.py`
  - Preserve metadata as the first usable fast-mode lane instead of letting native runtime delay it.
- Modify `backend/src/ragstudio/services/chunk_lexical_search_repository.py`
  - Add DB-first reference prefiltering for queries like `1:5`.
- Modify `backend/src/ragstudio/db/models.py`
  - Add a scoped `preview_ref` index so reference lookup does not scan every Tafseer chunk.
- Modify `backend/src/ragstudio/db/engine.py`
  - Ensure the `preview_ref` index exists for existing local databases.
- Modify `backend/tests/test_retrieval_orchestrator.py`
  - Add failing coverage for answer timeout fallback with preserved sources.
- Modify `backend/tests/test_query_understanding.py`
  - Add coverage for reference + surrounding-context strategy detection.
- Modify `backend/tests/test_runtime_query_service.py`
  - Add coverage for fast-mode query config and error-type-only failed runs.
- Modify `frontend/src/api/generated.ts`
  - Regenerate or update generated API types after backend schema changes.
- Modify `frontend/src/features/query/query-page.tsx`
  - Default the Query page to fast mode.
  - Add a compact mode control.
  - Show evidence-first answer status outside raw JSON.
- Modify `frontend/tests/query-page.test.tsx`
  - Assert fast mode is sent by default and evidence-first status is visible.

## Target Behavior

- Fast mode returns a useful result in 5-8 seconds for the live Tafseer graph query.
- Fast mode response includes:
  - non-empty `answer`
  - non-empty `sources`
  - preserved `chunk_traces`
  - `graph_expansion` trace with `status: "ok"` when graph is available
  - `token_metadata.answer_mode: "evidence_first"` if the LLM missed the fast budget
  - no top-level `ReadTimeout` failure
- Full mode can still wait for the configured provider timeout and can return a normal LLM answer.
- A run with `error_type="ReadTimeout"` and empty `error` must be stored as `failed`, not `succeeded`.

---

## Speed Strategy Matrix

The root cause is not basic LLM connectivity. The live provider answered a tiny prompt in about `219ms`, but the real Tafseer prompt was about `15,841` characters / `4,459` prompt tokens and needed about `19.8s` on `QuantTrio/Qwen3-VL-32B-Instruct-AWQ`. A 5-8 second UX must combine several speed strategies instead of simply raising `llm_timeout_ms`.

`gsd-debugger` review added one important constraint: evidence-first fallback alone is not enough if native retrieval, metadata scanning, or graph expansion burns the budget before answer generation starts. Therefore the first implementation must include metadata-first fast retrieval, a total response deadline, and DB-first reference prefiltering. Background full-answer completion, caching, and provider/model routing remain follow-up strategies after the first fast path is proven.

The codebase already stores domain signals on chunks through `domain_metadata`, `reference_metadata`, and `quality_action_policy`. The fast hybrid strategy should use those signals directly so a Tafseer query gets scripture/reference behavior, while a research paper or policy document keeps a more generic semantic/metadata strategy.

| Strategy | What It Speeds Up | Implementation In This Plan | Code Touchpoints | Test Signal |
| --- | --- | --- | --- | --- |
| Evidence-first response | User sees a useful grounded result before slow generation finishes | Primary strategy in Tasks 1-4 | `retrieval_orchestrator.py`, `evidence_first_answer_service.py`, `query_service.py` | Fast Tafseer query returns non-empty answer and sources under 8s |
| Query-aware hybrid routing | Chooses the right first lane per query instead of always treating every query as generic semantic search | Task 3A adds strategy detection and scoring | `query_understanding.py`, `retrieval_evidence.py`, `retrieval_orchestrator.py` | Reference queries start metadata-first; semantic queries keep vector/native; context queries boost graph neighbors |
| Domain-aware hybrid routing | Prevents scripture-specific or hadith-specific boosts from being applied to unrelated PDFs, and lets Tafseer reference metadata outrank generic semantic matches | Task 3B adds domain family detection and domain-safe scoring | `retrieval_evidence.py`, `hybrid_chunk_search.py`, `test_retrieval_orchestrator.py` | Tafseer `1:5` keeps exact reference first; research/policy chunks do not receive Tafseer boosts |
| Multi-document scoped fusion | Keeps selected documents in scope without letting one document drown out all others | Task 3C adds document diversity and comparison-aware ranking | `retrieval_evidence.py`, `retrieval_orchestrator.py`, `test_retrieval_orchestrator.py` | Multiple selected Tafseer docs return grouped evidence; comparison queries include more than one document when available |
| Metadata-first fast retrieval | Prevents slow native retrieval from delaying metadata/graph evidence | Task 4A races native behind metadata and degrades native if it misses the fast cap | `retrieval_orchestrator.py`, `query_service.py` | Slow native + useful metadata returns sources with `native_degraded=true` |
| Total fast deadline | Keeps all stages inside one 5-8s envelope | Task 4A propagates `response_budget_ms` and per-stage remaining budget | `retrieval_orchestrator.py`, `query_service.py` | Slow graph/answer traces degrade while evidence still returns |
| DB-first reference prefilter | Avoids scoring every chunk for exact Tafseer-style references | Task 4B adds indexed `preview_ref` lookup before Python scoring, gated by reference-shaped queries/domain signals | `chunk_lexical_search_repository.py`, `chunk_service.py`, `db/models.py`, `db/engine.py` | Query `1:5` finds exact chunk without full-scan behavior |
| Disable rerank in fast mode | Removes the observed `~2.6s` reranker cost from first response | Task 4C sets `enable_rerank=False` for fast mode | `query_service.py` | `run.query_config["enable_rerank"] is False`; timings show `rerank_ms=0` |
| Cap native retrieval time | Prevents native runtime from consuming the full budget before metadata/graph can answer | Task 4C caps `native_query_timeout_ms` at `2500` in fast mode | `query_service.py`, `retrieval_orchestrator.py` | Native timeouts degrade to metadata/graph without failing the run |
| Keep graph, but bound graph inputs | Preserves graph usefulness while limiting graph expansion fanout | Use `limit=5` for fast-mode UI default and pass only top seeds to graph | `query-page.tsx`, `retrieval_orchestrator.py`, `graph_expansion_service.py` | Graph trace shows `seed_count <= 5` and `expanded_candidates > 0` |
| Prompt compaction | Reduces the answer call from thousands of tokens to concise evidence snippets | Evidence-first answer uses compact snippets; full LLM mode remains available | `evidence_first_answer_service.py`, `runtime_answer_service.py` in follow-up | Evidence-first answer is readable and short; full mode still cites sources |
| Generation caps | Prevents answer generation from drifting into long completions | Add in follow-up if full mode still misses UX target: pass `max_tokens` for fast LLM attempts | `runtime_answer_service.py`, tests for request payload | Captured LLM payload includes `max_tokens`, answer latency drops |
| Progressive full answer | Shows fast evidence now and lets the polished LLM answer arrive later | Follow-up strategy after fast evidence mode is stable | New `/api/runs/{id}/answer` or background job route | UI first paints evidence, later updates answer without blocking initial result |
| Result cache | Repeated demo queries return immediately | Follow-up strategy for exact same query/document/variant/profile shape | `QueryService`, `Run` lookup, cache key helper | Second identical query returns cached run/evidence under 1s |
| Provider/model routing | Uses a smaller/faster model for fast mode and keeps 32B for full mode | Follow-up strategy if infrastructure has a smaller chat endpoint | Settings profile or variant parameter | Fast mode token metadata records fast model; full mode records 32B model |

## Fast Budget Allocation

The first implementation should target this budget on the current Tafseer query:

| Stage | Target | Strategy |
| --- | ---: | --- |
| Metadata retrieval | `<= 2500ms` | Run metadata first, use DB-first reference prefilter, avoid waiting on native first |
| Native retrieval | `<= 2500ms` | Race in fast mode; degrade if it misses the cap |
| Graph expansion + hydration | `<= 1200ms` | Keep graph enabled with top seeds only and remaining-budget timeout |
| Rerank | `0ms` | Disable rerank in fast mode |
| Context assembly | `<= 100ms` | Use existing context assembly |
| LLM fast attempt | `<= 1000ms` | Try LLM briefly, then fallback to evidence-first answer |
| Total user-visible result | `<= 8000ms` | Return evidence-first result if polished LLM wording misses budget |

This gives the user a useful answer with sources and graph proof quickly. It does not remove the slower full-answer path; it makes that path explicit instead of blocking the first visible result.

## Domain-Aware Query Hybrid Strategy

The Query page should not use one fixed retrieval order for every question. It should use the query shape to decide which lane gets priority, then use indexed document domain signals to decide which reference semantics and ranking boosts are valid.

| Query Shape | Example | First Lane | Parallel/Fallback Lane | Graph Role | Ranking Rule |
| --- | --- | --- | --- | --- | --- |
| Exact reference | `Explain 1:5` | Metadata/reference prefilter | Vector/native semantic search | Expand after exact seed | Exact reference remains first |
| Reference + context | `Explain 1:5 and surrounding connected verses` | Metadata/reference prefilter | Vector/native semantic search | Expand after exact seed and boost graph neighbors | Exact seed first, graph neighbors next |
| Semantic | `What does Ibn Kathir say about guidance?` | Vector/native + semantic metadata in parallel | Reference/phrase metadata if extracted | Expand from best semantic seeds | Best semantic evidence first, graph supports context |
| Arabic exact token | `حنانا` | Arabic/token metadata | Vector/native semantic search | Expand only if context words are present | Exact Arabic matches first |
| Phrase lookup | `quote guidance mentioned in the Surah` | Phrase metadata | Vector/native semantic search | Expand only if context words are present | Phrase matches first |
| Count/title | `how many hadith in bukhari` | Metadata/count/title evidence | Native/vector only if useful | Usually skipped unless context words are present | Count-bearing/title chunks first |

Graph remains an expansion lane, not the first lane, because it needs a seed node. The strategy is hybrid because metadata/reference and vector/native can both run, but query intent decides priority and ranking.

Domain awareness makes that hybrid strategy safer and more useful:

| Domain Family | Signals | Retrieval Behavior | Graph Behavior | Ranking Rule |
| --- | --- | --- | --- | --- |
| Tafseer/Quran commentary | `domain_metadata.domain` like `quran_tafseer`, Quran tags, Arabic script, `reference_metadata` verse ranges | Prefer reference and Arabic/token metadata for verse-shaped queries; keep vector/native for commentary questions | Expand verse neighbors, cross-references, and commentary relationships after seed evidence | Exact verse/reference evidence stays first; graph neighbors boost only when query asks for context |
| Hadith | `domain_metadata.domain=hadith`, book/chapter/hadith reference metadata | Prefer book/chapter/hadith metadata for reference or count queries | Expand collection/book/chapter/hadith relationships after seed evidence | Exact hadith/book hits outrank generic semantic hits |
| Legal/policy | legal/policy domain, article/section/citation style | Prefer section/article/citation metadata for exact references; keep semantic for policy meaning | Expand citations and related sections when present | Section/article exactness wins; no scripture verse boosts |
| Research/report | paper/report domain, title/section/page metadata | Prefer vector/native plus title/section metadata; reference prefilter only for page/section-shaped queries | Usually secondary, used for citations/figures/tables if projected | Semantic relevance and section title matches win; no Tafseer/hadith boosts |
| Unknown/generic | missing or weak `domain_metadata` | Use semantic hybrid with metadata as supporting evidence | Expand only from strong seeds and within budget | Conservative scoring; avoid domain-specific boosts |

For Tafseer, this means domain awareness directly helps search: the system can treat `1:5`, Arabic terms, verse ranges, and surrounding-verse requests as structured evidence instead of only as words inside a PDF.

When multiple documents are selected, the strategy is still one query plan, but scoring is applied per document and then fused across the selected scope:

| Multi-Document Case | Retrieval Behavior | Graph Behavior | Fusion Rule |
| --- | --- | --- | --- |
| Same-domain Tafseer docs | Run the same reference/Arabic/semantic lanes across all selected Tafseer documents | Expand graph from top seeds in each selected document, within budget | Keep exact reference evidence from each relevant document when available, then rank by score |
| Mixed-domain docs | Apply each candidate's own `domain_metadata`; Tafseer boosts only affect Tafseer chunks, research boosts only affect research chunks | Expand from strong seeds; avoid cross-domain graph expansion unless relationships are explicit | Domain-safe exact matches win, but unrelated documents do not inherit another document's boosts |
| Comparison query | Search all selected documents and keep per-document evidence groups | Graph expansion can support cross-document relationships if projected | Require evidence from at least two selected documents when possible |
| Single-answer query over many docs | Search all selected documents but do not force every document into the answer | Graph expansion follows only the best seeds | Return the strongest evidence, with light document diversity so one document does not dominate all sources |

The key rule is: selected documents define the scope, query intent defines the first lane, and each candidate's domain metadata defines which ranking boosts are allowed.

---

### Task 1: Add a Failing Orchestrator Test for Fast Evidence Fallback

**Files:**
- Modify: `backend/tests/test_retrieval_orchestrator.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Add a slow answer service test double**

Add this class below the existing `FakeAnswerService` in `backend/tests/test_retrieval_orchestrator.py`:

```python
class SlowAnswerService:
    def __init__(self):
        self.called = False

    async def answer(self, query, evidence, profile):
        self.called = True
        await asyncio.sleep(0.05)
        return "This slow LLM answer should not be returned in fast mode.", {
            "prompt_tokens": 4000,
        }
```

- [ ] **Step 2: Add the failing fast-mode test**

Append this test near the other orchestrator graph tests in `backend/tests/test_retrieval_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_orchestrator_returns_evidence_first_answer_when_fast_llm_budget_expires():
    answer_service = SlowAnswerService()
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
        query_config={
            "limit": 8,
            "response_mode": "fast",
            "answer_budget_ms": 1,
        },
    )

    assert answer_service.called is True
    assert result.error is None
    assert result.error_type is None
    assert result.sources
    assert any(source["metadata"]["retrieval_tool"] == "graph" for source in result.sources)
    assert result.answer.startswith("Evidence-first result")
    assert "Sahih al-Bukhari" in result.answer
    assert result.token_metadata["answer_mode"] == "evidence_first"
    assert result.token_metadata["generated_without_llm"] is True
    assert result.token_metadata["llm_answer_status"] == "timeout"
    assert result.token_metadata["llm_timeout_ms"] == 1
    assert result.timings["answer_fallback"] is True
    assert result.timings["answer_timeout_ms"] == 1
```

- [ ] **Step 3: Run the failing test**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_retrieval_orchestrator.py::test_orchestrator_returns_evidence_first_answer_when_fast_llm_budget_expires -q
```

Expected: FAIL because `response_mode`, `answer_budget_ms`, and response budgeting are ignored and the slow answer text is returned.

- [ ] **Step 4: Commit the failing test**

```bash
git add backend/tests/test_retrieval_orchestrator.py
git commit -m "test: capture fast answer fallback requirement"
```

---

### Task 2: Add Evidence-First Answer Builder

**Files:**
- Create: `backend/src/ragstudio/services/evidence_first_answer_service.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Create the evidence-first answer service**

Create `backend/src/ragstudio/services/evidence_first_answer_service.py` with this content:

```python
from __future__ import annotations

from typing import Any

from ragstudio.services.retrieval_evidence import EvidenceCandidate


class EvidenceFirstAnswerService:
    def answer(
        self,
        query: str,
        evidence: list[EvidenceCandidate],
        *,
        reason: str,
        llm_timeout_ms: int | None,
    ) -> tuple[str, dict[str, Any]]:
        if not evidence:
            return (
                "Evidence-first result\n\nNo grounded evidence was available for this query.",
                {
                    "answer_mode": "evidence_first",
                    "generated_without_llm": True,
                    "source_count": 0,
                    "fallback_reason": reason,
                    "llm_timeout_ms": llm_timeout_ms,
                },
            )

        lines = [
            "Evidence-first result",
            "",
            f"Question: {query.strip()}",
            "",
            "Grounded evidence:",
        ]
        for index, candidate in enumerate(evidence[:5], start=1):
            label = f"S{index}"
            reference = _reference_label(candidate)
            relationship = _relationship_label(candidate.metadata)
            snippet = _compact_text(candidate.text, limit=520)
            header_parts = [f"[{label}]", reference]
            if relationship:
                header_parts.append(relationship)
            lines.append(f"{' '.join(part for part in header_parts if part)}\n{snippet}")

        lines.extend(
            [
                "",
                "The LLM wording did not finish within the fast response budget, "
                "so this result is assembled directly from the retrieved evidence.",
            ]
        )
        return (
            "\n\n".join(lines),
            {
                "answer_mode": "evidence_first",
                "generated_without_llm": True,
                "source_count": len(evidence),
                "fallback_reason": reason,
                "llm_timeout_ms": llm_timeout_ms,
            },
        )


def _reference_label(candidate: EvidenceCandidate) -> str:
    reference = candidate.canonical_reference
    if not reference:
        raw_reference = candidate.source_location.get("reference")
        reference = raw_reference if isinstance(raw_reference, str) else None
    if reference:
        return f"reference={reference}"
    if candidate.chunk_id:
        return f"chunk={candidate.chunk_id}"
    return "chunk=unknown"


def _relationship_label(metadata: dict[str, Any]) -> str:
    relationship = metadata.get("graph_relationship")
    if not isinstance(relationship, dict):
        return ""
    relationship_type = relationship.get("type")
    path = relationship.get("path")
    parts = []
    if isinstance(relationship_type, str) and relationship_type:
        parts.append(f"graph={relationship_type}")
    if isinstance(path, str) and path:
        parts.append(f"path={path}")
    return " ".join(parts)


def _compact_text(text: str, *, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}..."
```

- [ ] **Step 2: Run the failing orchestrator test again**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_retrieval_orchestrator.py::test_orchestrator_returns_evidence_first_answer_when_fast_llm_budget_expires -q
```

Expected: still FAIL because `RetrievalOrchestrator` has not used the new service yet.

- [ ] **Step 3: Commit the service**

```bash
git add backend/src/ragstudio/services/evidence_first_answer_service.py
git commit -m "feat: add evidence-first answer builder"
```

---

### Task 3: Use Answer Budgets in RetrievalOrchestrator

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Import the evidence-first service**

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, add this import with the other service imports:

```python
from ragstudio.services.evidence_first_answer_service import EvidenceFirstAnswerService
```

- [ ] **Step 2: Add the service dependency to the constructor**

Change the constructor signature from:

```python
        grounding_validator: GroundingValidator | None = None,
    ):
```

to:

```python
        grounding_validator: GroundingValidator | None = None,
        evidence_first_answer_service: EvidenceFirstAnswerService | None = None,
    ):
```

Then add this assignment after `self.grounding_validator = ...`:

```python
        self.evidence_first_answer_service = (
            evidence_first_answer_service or EvidenceFirstAnswerService()
        )
```

- [ ] **Step 3: Replace the direct answer call**

Replace this block in `RetrievalOrchestrator.query`:

```python
            answer_started = perf_counter()
            answer, token_metadata = await self.answer_service.answer(
                query,
                final_evidence,
                profile,
            )
            timings["answer_ms"] = _elapsed_ms(answer_started)
```

with:

```python
            answer, token_metadata = await self._answer_with_budget(
                query,
                final_evidence,
                profile,
                query_config=query_config,
                timings=timings,
            )
```

- [ ] **Step 4: Add the answer budget helper methods**

Add these methods inside `RetrievalOrchestrator`, just above `_quality_diagnostics_trace`:

```python
    async def _answer_with_budget(
        self,
        query: str,
        evidence: list[EvidenceCandidate],
        profile: Any,
        *,
        query_config: dict[str, Any],
        timings: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        answer_started = perf_counter()
        response_mode = _response_mode(query_config)
        timeout_ms = _answer_budget_ms(query_config)
        try:
            if response_mode == "fast":
                answer, token_metadata = await asyncio.wait_for(
                    self.answer_service.answer(query, evidence, profile),
                    timeout=max(timeout_ms, 1) / 1000,
                )
            else:
                answer, token_metadata = await self.answer_service.answer(
                    query,
                    evidence,
                    profile,
                )
            timings["answer_ms"] = _elapsed_ms(answer_started)
            return answer, {
                **token_metadata,
                "answer_mode": response_mode,
                "generated_without_llm": False,
            }
        except TimeoutError as exc:
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

- [ ] **Step 5: Add module-level helpers**

Add these functions near `_metadata_only` in `backend/src/ragstudio/services/retrieval_orchestrator.py`:

```python
def _response_mode(query_config: dict[str, Any]) -> str:
    mode = str(query_config.get("response_mode") or "full").casefold()
    return mode if mode in {"fast", "full"} else "full"


def _answer_budget_ms(query_config: dict[str, Any]) -> int:
    value = query_config.get("answer_budget_ms")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 1000
    return min(max(parsed, 500), 8000)
```

- [ ] **Step 6: Run the orchestrator test**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_retrieval_orchestrator.py::test_orchestrator_returns_evidence_first_answer_when_fast_llm_budget_expires -q
```

Expected: PASS.

- [ ] **Step 7: Run the full orchestrator test file**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_retrieval_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit the orchestrator change**

```bash
git add backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: return evidence-first answer on fast timeout"
```

---

### Task 3A: Add Query-Aware Hybrid Retrieval Planning

**Files:**
- Modify: `backend/src/ragstudio/services/query_understanding.py`
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`
- Modify: `backend/tests/test_query_understanding.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Add query strategy types to query understanding**

In `backend/src/ragstudio/services/query_understanding.py`, after `QueryUnderstandingIntent`, add:

```python
QueryRetrievalStrategy = Literal[
    "reference_first_hybrid",
    "graph_context_hybrid",
    "semantic_hybrid",
    "count_metadata_hybrid",
]
```

In the `QueryUnderstanding` dataclass, add these fields after `answer_type`:

```python
    retrieval_strategy: QueryRetrievalStrategy = "semantic_hybrid"
    graph_context_required: bool = False
```

- [ ] **Step 2: Add graph-context detection**

In `backend/src/ragstudio/services/query_understanding.py`, add this regex near the other regex constants:

```python
_GRAPH_CONTEXT_RE = re.compile(
    r"\b(?:surrounding|connected|related|nearby|neighboring|previous|next|before|after|context|around)\b",
    re.IGNORECASE,
)
```

Add this helper below `_reference_hints`:

```python
def _needs_graph_context(query: str) -> bool:
    return bool(_GRAPH_CONTEXT_RE.search(query))
```

- [ ] **Step 3: Set retrieval strategy in `understand_query`**

At the top of `understand_query`, after `reference_hints = _reference_hints(query)`, add:

```python
    graph_context_required = _needs_graph_context(query)
```

In the `reference_hints` return block, add:

```python
            retrieval_strategy=(
                "graph_context_hybrid"
                if graph_context_required
                else "reference_first_hybrid"
            ),
            graph_context_required=graph_context_required,
```

In the compact Arabic return block, add:

```python
            retrieval_strategy=(
                "graph_context_hybrid" if graph_context_required else "reference_first_hybrid"
            ),
            graph_context_required=graph_context_required,
```

In the phrase lookup return block, add:

```python
            retrieval_strategy=(
                "graph_context_hybrid" if graph_context_required else "reference_first_hybrid"
            ),
            graph_context_required=graph_context_required,
```

In the count return block, add:

```python
            retrieval_strategy="count_metadata_hybrid",
            graph_context_required=graph_context_required,
```

In the summary return block, add:

```python
            retrieval_strategy=(
                "graph_context_hybrid" if graph_context_required else "semantic_hybrid"
            ),
            graph_context_required=graph_context_required,
```

In the final semantic return block, add:

```python
        retrieval_strategy=(
            "graph_context_hybrid" if graph_context_required else "semantic_hybrid"
        ),
        graph_context_required=graph_context_required,
```

- [ ] **Step 4: Add query understanding tests**

Add this test to `backend/tests/test_query_understanding.py`:

```python
def test_reference_query_with_context_uses_graph_context_hybrid_strategy():
    understanding = understand_query("Explain 1:5 and show the surrounding connected verses")

    assert understanding.intent == "reference"
    assert understanding.reference_hints == ["1:5"]
    assert understanding.retrieval_strategy == "graph_context_hybrid"
    assert understanding.graph_context_required is True
    assert understanding.direct_evidence_required is True
```

Add this test to the same file:

```python
def test_semantic_query_uses_semantic_hybrid_strategy():
    understanding = understand_query("What does Ibn Kathir say about guidance?")

    assert understanding.intent == "semantic"
    assert understanding.retrieval_strategy == "semantic_hybrid"
    assert understanding.graph_context_required is False
```

- [ ] **Step 5: Run the query understanding tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_query_understanding.py -q
```

Expected: PASS.

- [ ] **Step 6: Carry strategy into `RetrievalPlan`**

In `backend/src/ragstudio/services/retrieval_evidence.py`, extend the `RetrievalPlan` dataclass with:

```python
    retrieval_strategy: str = "semantic_hybrid"
    graph_context_required: bool = False
```

In `plan_for_query`, add these fields to the `RetrievalPlan(...)` return:

```python
        retrieval_strategy=understanding.retrieval_strategy,
        graph_context_required=understanding.graph_context_required,
```

- [ ] **Step 7: Add strategy-aware scoring**

In `_score_candidate` in `backend/src/ragstudio/services/retrieval_evidence.py`, after the `if plan.intent == "count": ...` block and before the tool boost block, add:

```python
    if (
        plan.retrieval_strategy in {"reference_first_hybrid", "graph_context_hybrid"}
        and candidate.retrieval_pass == "reference_exact"
    ):
        boost += 12.0
        reasons.append("reference_first_hybrid")

    if plan.graph_context_required and candidate.tool == "graph":
        boost += 8.0
        reasons.append("query_requested_graph_context")

    if plan.retrieval_strategy == "count_metadata_hybrid" and candidate.tool == "metadata":
        boost += 6.0
        reasons.append("count_metadata_hybrid")
```

- [ ] **Step 8: Add plan/scoring tests**

Add this test to `backend/tests/test_retrieval_orchestrator.py` near the existing `plan_for_query` tests:

```python
def test_plan_for_reference_context_query_sets_graph_context_strategy():
    plan = plan_for_query(
        "Explain 1:5 and show the surrounding connected verses",
        document_ids=["doc-tafseer"],
        limit=5,
    )

    assert plan.intent == "reference"
    assert plan.retrieval_strategy == "graph_context_hybrid"
    assert plan.graph_context_required is True
```

Add this test near the fusion scoring tests:

```python
def test_fusion_keeps_exact_reference_first_and_boosts_graph_context_neighbors():
    plan = plan_for_query(
        "Explain 1:5 and show the surrounding connected verses",
        document_ids=["doc-tafseer"],
        limit=5,
    )
    exact = EvidenceCandidate(
        candidate_id="metadata:1-5",
        text="Verse 1:5 Guide us to the straight path.",
        document_id="doc-tafseer",
        chunk_id="chunk-1-5",
        source_location={"reference": "1:5"},
        metadata={},
        tool="metadata",
        tool_rank=1,
        base_score=10.0,
        retrieval_pass="reference_exact",
    )
    neighbor = EvidenceCandidate(
        candidate_id="graph:1-4",
        text="Verse 1:4 It is You we worship and You we ask for help.",
        document_id="doc-tafseer",
        chunk_id="chunk-1-4",
        source_location={"reference": "1:4"},
        metadata={"graph_relationship": {"type": "REFERENCES", "path": "reference_hop"}},
        tool="graph",
        tool_rank=1,
        base_score=10.0,
    )

    fused = fuse_candidates(plan, [neighbor, exact])

    assert fused[0].chunk_id == "chunk-1-5"
    assert fused[1].chunk_id == "chunk-1-4"
    assert "reference_first_hybrid" in fused[0].reasons
    assert "query_requested_graph_context" in fused[1].reasons
```

- [ ] **Step 9: Run the new plan/scoring tests**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_retrieval_orchestrator.py::test_plan_for_reference_context_query_sets_graph_context_strategy \
  backend/tests/test_retrieval_orchestrator.py::test_fusion_keeps_exact_reference_first_and_boosts_graph_context_neighbors \
  -q
```

Expected: PASS.

- [ ] **Step 10: Run all query planning tests**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_query_understanding.py \
  backend/tests/test_retrieval_orchestrator.py \
  -q
```

Expected: PASS.

- [ ] **Step 11: Commit query-aware hybrid planning**

```bash
git add \
  backend/src/ragstudio/services/query_understanding.py \
  backend/src/ragstudio/services/retrieval_evidence.py \
  backend/tests/test_query_understanding.py \
  backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: add query-aware hybrid retrieval strategy"
```

---

### Task 3B: Add Domain-Aware Hybrid Routing

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`
- Modify: `backend/src/ragstudio/services/hybrid_chunk_search.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Add domain-family helpers to fusion scoring**

In `backend/src/ragstudio/services/retrieval_evidence.py`, add these helpers near the other private helpers:

```python
def _domain_family(metadata: dict[str, Any]) -> str:
    domain_metadata = metadata.get("domain_metadata")
    if not isinstance(domain_metadata, dict):
        return "generic"

    raw_tags = domain_metadata.get("tags")
    tags = (
        {str(tag).casefold() for tag in raw_tags if isinstance(tag, str)}
        if isinstance(raw_tags, list)
        else set()
    )
    tokens = {
        str(domain_metadata.get("domain") or "").casefold(),
        str(domain_metadata.get("document_type") or "").casefold(),
        str(domain_metadata.get("collection") or "").casefold(),
        str(domain_metadata.get("content_role") or "").casefold(),
        str(domain_metadata.get("citation_style") or "").casefold(),
        *tags,
    }

    if {"quran_tafseer", "tafseer", "quran"} & tokens:
        return "tafseer_reference"
    if "hadith" in tokens:
        return "hadith_reference"
    if {"legal", "law", "statute", "policy"} & tokens:
        return "legal_reference"
    if {"research", "paper", "report", "scientific"} & tokens:
        return "research_semantic"
    return "generic"


def _quality_allows_domain_reference_boost(metadata: dict[str, Any]) -> bool:
    policy = metadata.get("quality_action_policy")
    if not isinstance(policy, dict):
        return True
    return (
        bool(policy.get("index_exact_arabic", True))
        and policy.get("graph_confidence") != "blocked"
    )
```

- [ ] **Step 2: Add domain-aware boost rules**

In `_score_candidate`, after the query-aware boost block from Task 3A and before the generic tool boost block, add:

```python
    domain_family = _domain_family(candidate.metadata)
    domain_reference_allowed = _quality_allows_domain_reference_boost(candidate.metadata)

    if (
        domain_reference_allowed
        and domain_family in {"tafseer_reference", "hadith_reference", "legal_reference"}
        and candidate.retrieval_pass == "reference_exact"
    ):
        boost += 10.0
        reasons.append(f"{domain_family}_exact")

    if domain_family == "tafseer_reference" and plan.graph_context_required and candidate.tool == "graph":
        boost += 5.0
        reasons.append("tafseer_graph_context")

    if domain_family == "research_semantic" and candidate.tool == "native":
        boost += 2.0
        reasons.append("research_semantic_native")
```

This keeps Tafseer and hadith reference boosts explicit, while preventing those boosts from leaking into research/report documents.

- [ ] **Step 3: Keep metadata-lane scoring aligned with domain semantics**

Review `backend/src/ragstudio/services/hybrid_chunk_search.py`. It already uses:

- `domain_metadata`
- `ReferenceSemantics.from_metadata(...)`
- `reference_metadata`
- `quality_action_policy`

Keep those as the metadata lane's domain-aware scoring source. If the implementation changes this file, preserve the existing quality gates:

```python
quality_allows_reference_boost = self._quality_allows_reference_boost(metadata)
```

and do not apply Arabic/reference boosts when `quality_action_policy` blocks them.

- [ ] **Step 4: Add Tafseer domain-aware fusion coverage**

Add this test to `backend/tests/test_retrieval_orchestrator.py` near the fusion scoring tests:

```python
def test_domain_aware_fusion_boosts_tafseer_exact_reference():
    plan = plan_for_query("Explain 1:5", document_ids=["doc-tafseer"], limit=5)
    tafseer_exact = EvidenceCandidate(
        candidate_id="metadata:tafseer-1-5",
        text="Verse 1:5 Guide us to the straight path.",
        document_id="doc-tafseer",
        chunk_id="chunk-tafseer-1-5",
        source_location={"reference": "1:5"},
        metadata={
            "domain_metadata": {
                "domain": "quran_tafseer",
                "tags": ["quran"],
                "script": "arabic",
            },
            "reference_metadata": {"references": ["1:5"]},
            "quality_action_policy": {
                "index_exact_arabic": True,
                "graph_confidence": "trusted",
            },
        },
        tool="metadata",
        tool_rank=1,
        base_score=10.0,
        retrieval_pass="reference_exact",
    )
    generic_native = EvidenceCandidate(
        candidate_id="native:generic",
        text="A generic discussion of guidance.",
        document_id="doc-tafseer",
        chunk_id="chunk-generic",
        source_location={},
        metadata={"domain_metadata": {"domain": "generic"}},
        tool="native",
        tool_rank=1,
        base_score=20.0,
    )

    fused = fuse_candidates(plan, [generic_native, tafseer_exact])

    assert fused[0].chunk_id == "chunk-tafseer-1-5"
    assert "tafseer_reference_exact" in fused[0].reasons
```

- [ ] **Step 5: Add negative coverage for research documents**

Add this test to the same file:

```python
def test_domain_aware_fusion_does_not_apply_tafseer_boost_to_research_paper():
    plan = plan_for_query("Explain 1:5", document_ids=["doc-paper"], limit=5)
    paper_candidate = EvidenceCandidate(
        candidate_id="metadata:paper-section",
        text="Section 1.5 describes retrieval methodology.",
        document_id="doc-paper",
        chunk_id="chunk-paper-1-5",
        source_location={"section": "1.5"},
        metadata={
            "domain_metadata": {
                "domain": "research",
                "document_type": "paper",
            },
        },
        tool="metadata",
        tool_rank=1,
        base_score=10.0,
        retrieval_pass="reference_exact",
    )

    fused = fuse_candidates(plan, [paper_candidate])

    assert "tafseer_reference_exact" not in fused[0].reasons
    assert "hadith_reference_exact" not in fused[0].reasons
```

- [ ] **Step 6: Run the domain-aware fusion tests**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_retrieval_orchestrator.py::test_domain_aware_fusion_boosts_tafseer_exact_reference \
  backend/tests/test_retrieval_orchestrator.py::test_domain_aware_fusion_does_not_apply_tafseer_boost_to_research_paper \
  -q
```

Expected: PASS.

- [ ] **Step 7: Commit domain-aware hybrid scoring**

```bash
git add \
  backend/src/ragstudio/services/retrieval_evidence.py \
  backend/src/ragstudio/services/hybrid_chunk_search.py \
  backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: add domain-aware hybrid retrieval scoring"
```

---

### Task 3C: Add Multi-Document Hybrid Fusion

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Add multi-document fusion helpers**

In `backend/src/ragstudio/services/retrieval_evidence.py`, add helpers near the other private fusion helpers:

```python
def _selected_document_count(plan: RetrievalPlan) -> int:
    return len({document_id for document_id in plan.document_ids if document_id})


def _best_candidate_by_document(candidates: list[EvidenceCandidate]) -> dict[str, EvidenceCandidate]:
    best: dict[str, EvidenceCandidate] = {}
    for candidate in candidates:
        if not candidate.document_id:
            continue
        existing = best.get(candidate.document_id)
        if existing is None or candidate.final_score > existing.final_score:
            best[candidate.document_id] = candidate
    return best
```

- [ ] **Step 2: Add a post-score multi-document ordering pass**

In `fuse_candidates`, replace the direct `return sorted(...)` with:

```python
    ranked = sorted(
        scored,
        key=lambda candidate: (candidate.final_score, -candidate.tool_rank),
        reverse=True,
    )
    return _apply_multi_document_ordering(plan, ranked)
```

Then add:

```python
def _apply_multi_document_ordering(
    plan: RetrievalPlan,
    ranked: list[EvidenceCandidate],
) -> list[EvidenceCandidate]:
    if _selected_document_count(plan) <= 1:
        return ranked

    best_by_document = _best_candidate_by_document(ranked)
    if len(best_by_document) <= 1:
        return ranked

    if plan.intent == "comparison":
        comparison_head = sorted(
            best_by_document.values(),
            key=lambda candidate: (candidate.final_score, -candidate.tool_rank),
            reverse=True,
        )
        comparison_ids = {candidate.candidate_id for candidate in comparison_head}
        return [
            *comparison_head,
            *[candidate for candidate in ranked if candidate.candidate_id not in comparison_ids],
        ]

    top_window = ranked[: max(plan.limit, 1)]
    top_documents = {candidate.document_id for candidate in top_window if candidate.document_id}
    if len(top_documents) > 1:
        return ranked

    top_score = ranked[0].final_score if ranked else 0.0
    diversity_candidates = [
        candidate
        for candidate in best_by_document.values()
        if candidate.document_id not in top_documents and candidate.final_score >= top_score * 0.65
    ]
    if not diversity_candidates:
        return ranked

    diversity_candidate = sorted(
        diversity_candidates,
        key=lambda candidate: (candidate.final_score, -candidate.tool_rank),
        reverse=True,
    )[0]
    return [
        ranked[0],
        diversity_candidate,
        *[
            candidate
            for candidate in ranked[1:]
            if candidate.candidate_id != diversity_candidate.candidate_id
        ],
    ]
```

This keeps one very strong document in first place, but prevents a selected second document with good evidence from disappearing from the first visible result set.

- [ ] **Step 3: Add same-domain multi-document reference coverage**

Add this test to `backend/tests/test_retrieval_orchestrator.py` near the fusion tests:

```python
def test_multi_document_reference_query_keeps_exact_hits_from_each_tafseer_document():
    plan = plan_for_query("Explain 1:5", document_ids=["doc-a", "doc-b"], limit=2)
    doc_a = EvidenceCandidate(
        candidate_id="metadata:doc-a-1-5",
        text="Doc A verse 1:5 explanation.",
        document_id="doc-a",
        chunk_id="chunk-doc-a-1-5",
        source_location={"reference": "1:5"},
        metadata={"domain_metadata": {"domain": "quran_tafseer"}},
        tool="metadata",
        tool_rank=1,
        base_score=30.0,
        retrieval_pass="reference_exact",
    )
    doc_b = EvidenceCandidate(
        candidate_id="metadata:doc-b-1-5",
        text="Doc B verse 1:5 explanation.",
        document_id="doc-b",
        chunk_id="chunk-doc-b-1-5",
        source_location={"reference": "1:5"},
        metadata={"domain_metadata": {"domain": "quran_tafseer"}},
        tool="metadata",
        tool_rank=2,
        base_score=24.0,
        retrieval_pass="reference_exact",
    )
    doc_a_extra = EvidenceCandidate(
        candidate_id="metadata:doc-a-extra",
        text="Another strong Doc A passage.",
        document_id="doc-a",
        chunk_id="chunk-doc-a-extra",
        source_location={},
        metadata={"domain_metadata": {"domain": "quran_tafseer"}},
        tool="metadata",
        tool_rank=3,
        base_score=25.0,
    )

    fused = fuse_candidates(plan, [doc_a, doc_a_extra, doc_b])

    assert [candidate.document_id for candidate in fused[:2]] == ["doc-a", "doc-b"]
```

- [ ] **Step 4: Add comparison-query coverage**

Add this test to the same file:

```python
def test_multi_document_comparison_query_prioritizes_multiple_documents():
    plan = plan_for_query(
        "Compare guidance in these selected documents",
        document_ids=["doc-a", "doc-b"],
        limit=4,
    )
    doc_a = EvidenceCandidate(
        candidate_id="native:doc-a",
        text="Doc A discusses guidance as a straight path.",
        document_id="doc-a",
        chunk_id="chunk-doc-a",
        source_location={},
        metadata={"domain_metadata": {"domain": "quran_tafseer"}},
        tool="native",
        tool_rank=1,
        base_score=40.0,
    )
    doc_b = EvidenceCandidate(
        candidate_id="native:doc-b",
        text="Doc B discusses guidance as divine direction.",
        document_id="doc-b",
        chunk_id="chunk-doc-b",
        source_location={},
        metadata={"domain_metadata": {"domain": "quran_tafseer"}},
        tool="native",
        tool_rank=2,
        base_score=20.0,
    )
    doc_a_extra = EvidenceCandidate(
        candidate_id="native:doc-a-extra",
        text="Doc A extra evidence.",
        document_id="doc-a",
        chunk_id="chunk-doc-a-extra",
        source_location={},
        metadata={"domain_metadata": {"domain": "quran_tafseer"}},
        tool="native",
        tool_rank=3,
        base_score=35.0,
    )

    fused = fuse_candidates(plan, [doc_a, doc_a_extra, doc_b])

    assert {candidate.document_id for candidate in fused[:2]} == {"doc-a", "doc-b"}
```

- [ ] **Step 5: Run the multi-document fusion tests**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_retrieval_orchestrator.py::test_multi_document_reference_query_keeps_exact_hits_from_each_tafseer_document \
  backend/tests/test_retrieval_orchestrator.py::test_multi_document_comparison_query_prioritizes_multiple_documents \
  -q
```

Expected: PASS.

- [ ] **Step 6: Commit multi-document hybrid fusion**

```bash
git add \
  backend/src/ragstudio/services/retrieval_evidence.py \
  backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: add multi-document hybrid query fusion"
```

---

### Task 4A: Make Fast Retrieval Metadata-First With a Total Deadline

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Add a slow native runtime test double**

Add this class near the existing runtime fakes in `backend/tests/test_retrieval_orchestrator.py`:

```python
class SlowNativeRuntimeTool(FakeRuntimeTool):
    def __init__(self):
        self.query_called = False

    async def query(self, query, *, document_ids, query_config):
        self.query_called = True
        await asyncio.sleep(0.05)
        return RuntimeQueryResult(
            answer="slow native answer",
            sources=[],
            timings={"runtime_query_ms": 50},
        )
```

- [ ] **Step 2: Add the failing metadata-first test**

Add this test near the native degradation tests in `backend/tests/test_retrieval_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_fast_mode_uses_metadata_when_native_misses_fast_budget():
    runtime = SlowNativeRuntimeTool()
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=runtime,
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={
            "limit": 8,
            "response_mode": "fast",
            "response_budget_ms": 200,
            "native_query_timeout_ms": 1,
            "graph_expansion_enabled": False,
        },
    )

    assert runtime.query_called is True
    assert result.error is None
    assert result.sources
    assert result.timings["native_degraded"] is True
    assert result.timings["native_error_type"] == "native_query_timeout"
    assert result.timings["response_budget_ms"] == 200
    assert answer_service.called is True
```

- [ ] **Step 3: Run the failing test**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_retrieval_orchestrator.py::test_fast_mode_uses_metadata_when_native_misses_fast_budget -q
```

Expected: FAIL because the selected-document path currently waits on native before metadata.

- [ ] **Step 4: Add fast-mode helpers**

Add these module-level helpers near `_metadata_only` in `backend/src/ragstudio/services/retrieval_orchestrator.py`:

```python
def _fast_mode(query_config: dict[str, Any]) -> bool:
    return _response_mode(query_config) == "fast"


def _response_budget_ms(query_config: dict[str, Any]) -> int:
    value = query_config.get("response_budget_ms")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 8000
    return min(max(parsed, 1000), 120_000)


def _deadline_at(started: float, query_config: dict[str, Any]) -> float | None:
    if not _fast_mode(query_config):
        return None
    return started + (_response_budget_ms(query_config) / 1000)


def _remaining_timeout_seconds(deadline_at: float | None, *, fallback_ms: int) -> float:
    if deadline_at is None:
        return max(fallback_ms, 1) / 1000
    remaining = deadline_at - perf_counter()
    return max(min(remaining, max(fallback_ms, 1) / 1000), 0.001)
```

- [ ] **Step 5: Compute the deadline at the start of the orchestrator**

In `RetrievalOrchestrator.query`, after:

```python
        timings: dict[str, Any] = {"orchestrated_query": True}
```

add:

```python
        deadline_at = _deadline_at(started, query_config)
        if deadline_at is not None:
            timings["response_budget_ms"] = _response_budget_ms(query_config)
```

- [ ] **Step 6: Route fast selected-document queries through metadata-first retrieval**

In `_parallel_retrieval`, replace the selected-document branch:

```python
        if document_ids:
            if _metadata_only(query_config):
```

with:

```python
        if document_ids:
            if _fast_mode(query_config):
                return await self._fast_parallel_retrieval(
                    query,
                    runtime,
                    document_ids,
                    variant_id,
                    query_config,
                    plan,
                    timings,
                    parallel_started,
                )
            if _metadata_only(query_config):
```

- [ ] **Step 7: Add the metadata-first retrieval method**

Add this method inside `RetrievalOrchestrator`, just above `_metadata_after_native_result`:

```python
    async def _fast_parallel_retrieval(
        self,
        query: str,
        runtime: Any,
        document_ids: list[str],
        variant_id: str,
        query_config: dict[str, Any],
        plan: Any,
        timings: dict[str, Any],
        parallel_started: float,
    ) -> tuple[list[EvidenceCandidate], list[EvidenceCandidate], dict[str, Any]]:
        native_task = asyncio.create_task(
            self._timed_native_candidates(query, runtime, document_ids, query_config)
        )
        metadata_result = await self._timed_metadata_candidates(
            query,
            document_ids,
            variant_id,
            plan.candidate_limit,
            plan,
        )
        timeout_ms = int(query_config.get("native_query_timeout_ms") or 2500)
        try:
            native_result = await asyncio.wait_for(
                native_task,
                timeout=max(timeout_ms, 1) / 1000,
            )
        except TimeoutError as exc:
            native_task.cancel()
            native_result = NativeRuntimeQueryFailed(
                f"Native query timed out after {timeout_ms} ms.",
                "native_query_timeout",
                {"native_stage_ms": _elapsed_ms(parallel_started)},
            )
            native_result.__cause__ = exc
        except Exception as exc:
            native_result = exc
        return self._resolve_retrieval_results(
            native_result=native_result,
            metadata_result=metadata_result,
            plan=plan,
            timings=timings,
            parallel_started=parallel_started,
        )
```

- [ ] **Step 8: Make graph use the remaining fast budget**

Change the `_safe_graph_expansion` call in `RetrievalOrchestrator.query` to include the deadline:

```python
                deadline_at=deadline_at,
```

Then add `deadline_at: float | None,` to `_safe_graph_expansion` parameters and replace:

```python
            graph_candidates, graph_traces = await self.graph_expansion_service.expand(
```

with:

```python
            graph_candidates, graph_traces = await asyncio.wait_for(
                self.graph_expansion_service.expand(
                    query,
                    seeds=seeds,
                    profile=profile,
                    document_ids=document_ids,
                    limit=limit,
                ),
                timeout=_remaining_timeout_seconds(deadline_at, fallback_ms=1200),
            )
```

Keep the existing `except Exception as exc:` branch; `TimeoutError` will be converted to a degraded graph trace through that branch.

- [ ] **Step 9: Make answer fallback use the remaining fast budget**

Change the `_answer_with_budget` call to include the deadline:

```python
                deadline_at=deadline_at,
```

Add `deadline_at: float | None,` to `_answer_with_budget` parameters. Replace:

```python
        timeout_ms = _answer_budget_ms(query_config)
```

with:

```python
        timeout_ms = int(_remaining_timeout_seconds(deadline_at, fallback_ms=_answer_budget_ms(query_config)) * 1000)
```

- [ ] **Step 10: Run the metadata-first test**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_retrieval_orchestrator.py::test_fast_mode_uses_metadata_when_native_misses_fast_budget -q
```

Expected: PASS.

- [ ] **Step 11: Run orchestrator tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_retrieval_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 12: Commit fast retrieval scheduling**

```bash
git add backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: prioritize metadata in fast query mode"
```

---

### Task 4B: Add Domain-Safe DB-First Reference Prefilter for Large Documents

**Files:**
- Modify: `backend/src/ragstudio/db/models.py`
- Modify: `backend/src/ragstudio/db/engine.py`
- Modify: `backend/src/ragstudio/services/chunk_lexical_search_repository.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Test: `backend/tests/test_metadata_retrieval_service.py`

- [ ] **Step 1: Add a scoped preview reference index**

In `backend/src/ragstudio/db/models.py`, add this index to `Chunk.__table_args__` after `Index("ix_chunks_document_id", "document_id"),`:

```python
        Index("ix_chunks_document_preview_ref", "document_id", "preview_ref"),
```

- [ ] **Step 2: Ensure the index for existing databases**

In `backend/src/ragstudio/db/engine.py`, inside `_ensure_chunk_search_columns`, after the existing `ix_chunks_tokens_ar_gin` creation block, add:

```python
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_chunks_document_preview_ref
            ON chunks (document_id, preview_ref)
            """
        )
    )
```

- [ ] **Step 3: Add domain-safe reference prefiltering to the repository**

In `backend/src/ragstudio/services/chunk_lexical_search_repository.py`, add `import re` at the top and add this method inside `ChunkLexicalSearchRepository`:

```python
    async def reference_prefilter(
        self,
        *,
        query: str,
        document_ids: list[str],
        limit: int,
    ) -> list[Chunk]:
        references = _query_references(query)
        if not references or limit <= 0:
            return []

        statement = select(Chunk).where(Chunk.preview_ref.in_(references))
        if document_ids:
            statement = statement.where(Chunk.document_id.in_(document_ids))
        statement = statement.order_by(Chunk.created_at.asc(), Chunk.id.asc()).limit(
            max(limit * 4, limit)
        )

        result = await self.session.execute(statement)
        chunks = list(result.scalars().all())
        supported = [chunk for chunk in chunks if _supports_reference_prefilter(chunk)]
        return supported[:limit]
```

Add this helper at module level:

```python
def _query_references(query: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\b\d{1,3}:\d{1,3}\b", query)))


def _supports_reference_prefilter(chunk: Chunk) -> bool:
    metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
    if isinstance(metadata.get("reference_metadata"), dict):
        return True

    domain_metadata = metadata.get("domain_metadata")
    if not isinstance(domain_metadata, dict):
        return False

    raw_tags = domain_metadata.get("tags")
    tags = (
        {str(tag).casefold() for tag in raw_tags if isinstance(tag, str)}
        if isinstance(raw_tags, list)
        else set()
    )
    tokens = {
        str(domain_metadata.get("domain") or "").casefold(),
        str(domain_metadata.get("document_type") or "").casefold(),
        str(domain_metadata.get("citation_style") or "").casefold(),
        *tags,
    }
    return bool(
        tokens
        & {
            "quran_tafseer",
            "tafseer",
            "quran",
            "hadith",
            "legal",
            "law",
            "statute",
            "policy",
        }
    )
```

This keeps `1:5` fast for Tafseer while avoiding accidental scripture-style reference behavior for unrelated research/report chunks that happen to contain section-like numbers.

- [ ] **Step 4: Use reference prefilter before full Python scoring**

In `backend/src/ragstudio/services/chunk_service.py`, replace:

```python
        prefiltered = await ChunkLexicalSearchRepository(self.session).arabic_prefilter(
            query=search_in.query,
            document_ids=search_in.document_ids,
            limit=max(search_in.limit, 20),
        )
        prefiltered_ids = {chunk.id for chunk in prefiltered}
        chunks = [*prefiltered, *[chunk for chunk in chunks if chunk.id not in prefiltered_ids]]
```

with:

```python
        repository = ChunkLexicalSearchRepository(self.session)
        prefilter_limit = max(search_in.limit, 20)
        reference_prefiltered = await repository.reference_prefilter(
            query=search_in.query,
            document_ids=search_in.document_ids,
            limit=prefilter_limit,
        )
        arabic_prefiltered = await repository.arabic_prefilter(
            query=search_in.query,
            document_ids=search_in.document_ids,
            limit=prefilter_limit,
        )
        prefiltered = [*reference_prefiltered, *arabic_prefiltered]
        prefiltered_ids = {chunk.id for chunk in prefiltered}
        chunks = [*prefiltered, *[chunk for chunk in chunks if chunk.id not in prefiltered_ids]]
```

- [ ] **Step 5: Add a metadata retrieval prefilter test**

Add this test to `backend/tests/test_metadata_retrieval_service.py`:

```python
@pytest.mark.asyncio
async def test_reference_prefilter_returns_exact_preview_ref_before_full_scan(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="tafseer.txt",
            content_type="text/plain",
            sha256="tafseer-ref-prefilter",
            artifact_path=str(app.state.settings.data_dir / "tafseer.txt"),
            status="succeeded",
        )
        session.add(document)
        await session.flush()
        session.add_all(
            [
                Chunk(
                    document_id=document.id,
                    text=f"Filler chunk {index}",
                    preview_ref=None,
                    metadata_json={},
                    source_location={},
                )
                for index in range(100)
            ]
        )
        exact = Chunk(
            document_id=document.id,
            text="Verse 1:5 Guide us to the straight path.",
            preview_ref="1:5",
            metadata_json={"reference_metadata": {"references": ["1:5"]}},
            source_location={"reference": "1:5"},
        )
        session.add(exact)
        await session.commit()

        results = await ChunkLexicalSearchRepository(session).reference_prefilter(
            query="Explain 1:5",
            document_ids=[document.id],
            limit=5,
        )

    assert [chunk.preview_ref for chunk in results] == ["1:5"]
```

Add these imports if missing:

```python
import pytest
from ragstudio.db.models import Chunk, Document
from ragstudio.services.chunk_lexical_search_repository import ChunkLexicalSearchRepository
```

- [ ] **Step 6: Run the reference prefilter test**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_metadata_retrieval_service.py::test_reference_prefilter_returns_exact_preview_ref_before_full_scan -q
```

Expected: PASS.

- [ ] **Step 7: Commit DB-first reference search**

```bash
git add \
  backend/src/ragstudio/db/models.py \
  backend/src/ragstudio/db/engine.py \
  backend/src/ragstudio/services/chunk_lexical_search_repository.py \
  backend/src/ragstudio/services/chunk_service.py \
  backend/tests/test_metadata_retrieval_service.py
git commit -m "feat: add fast reference prefilter"
```

---

### Task 4C: Add Fast Mode to Query Schema and Query Config

**Files:**
- Modify: `backend/src/ragstudio/schemas/query.py`
- Modify: `backend/src/ragstudio/services/query_service.py`
- Modify: `backend/tests/test_runtime_query_service.py`

- [ ] **Step 1: Update the query schema**

Replace `backend/src/ragstudio/schemas/query.py` with:

```python
from typing import Literal

from pydantic import Field

from ragstudio.schemas.common import StudioModel
from ragstudio.schemas.runs import RunOut

QueryResponseMode = Literal["fast", "full"]


class QueryIn(StudioModel):
    query: str
    document_ids: list[str] = Field(default_factory=list)
    variant_ids: list[str]
    limit: int = Field(default=8, ge=0)
    response_mode: QueryResponseMode = "fast"
    answer_budget_ms: int | None = Field(default=None, ge=500, le=120_000)
    response_budget_ms: int | None = Field(default=None, ge=1000, le=120_000)


class QueryOut(StudioModel):
    runs: list[RunOut]
```

- [ ] **Step 2: Change QueryService to pass the full payload**

In `backend/src/ragstudio/services/query_service.py`, replace:

```python
            query_config = self._query_config(profile, variant, payload.limit)
```

with:

```python
            query_config = self._query_config(profile, variant, payload)
```

Then change the `_query_config` signature from:

```python
    def _query_config(self, profile: Any, variant: Variant, limit: int) -> dict[str, Any]:
```

to:

```python
    def _query_config(self, profile: Any, variant: Variant, payload: QueryIn) -> dict[str, Any]:
```

- [ ] **Step 3: Build the fast-mode query config**

Replace the `return { ... }` body of `_query_config` with this structure. Keep every existing key from the current return value and add the fast-mode section at the end:

```python
        query_config = {
            "mode": self._query_mode(parameters.get("mode"), profile.query_mode),
            "parser": self._text_param(parameters.get("parser"), profile.parser),
            "parse_method": self._text_param(parameters.get("parse_method"), profile.parse_method),
            "chunk_token_size": self._int_param(
                parameters.get("chunk_token_size"), profile.chunk_token_size
            ),
            "chunk_overlap_token_size": self._int_param(
                parameters.get("chunk_overlap_token_size"),
                profile.chunk_overlap_token_size,
            ),
            "enable_image_processing": self._bool_param(
                parameters.get("enable_image_processing"),
                profile.enable_image_processing,
            ),
            "enable_table_processing": self._bool_param(
                parameters.get("enable_table_processing"),
                profile.enable_table_processing,
            ),
            "enable_equation_processing": self._bool_param(
                parameters.get("enable_equation_processing"),
                profile.enable_equation_processing,
            ),
            "context_window": self._int_param(
                parameters.get("context_window"), profile.context_window
            ),
            "context_mode": self._text_param(parameters.get("context_mode"), profile.context_mode),
            "max_context_tokens": self._int_param(
                parameters.get("max_context_tokens"), profile.max_context_tokens
            ),
            "include_headers": self._bool_param(
                parameters.get("include_headers"), profile.include_headers
            ),
            "include_captions": self._bool_param(
                parameters.get("include_captions"), profile.include_captions
            ),
            "top_k": self._int_param(parameters.get("top_k"), profile.top_k),
            "chunk_top_k": self._int_param(parameters.get("chunk_top_k"), profile.chunk_top_k),
            "enable_rerank": self._bool_param(
                parameters.get("enable_rerank"), profile.enable_rerank
            ),
            "max_total_tokens": self._int_param(
                parameters.get("max_total_tokens"), profile.max_total_tokens
            ),
            "max_entity_tokens": self._int_param(
                parameters.get("max_entity_tokens"), profile.max_entity_tokens
            ),
            "max_relation_tokens": self._int_param(
                parameters.get("max_relation_tokens"), profile.max_relation_tokens
            ),
            "cosine_better_than_threshold": self._float_param(
                parameters.get("cosine_better_than_threshold"),
                profile.cosine_better_than_threshold,
            ),
            "enable_llm_cache": self._bool_param(
                parameters.get("enable_llm_cache"), profile.enable_llm_cache
            ),
            "enable_llm_cache_for_entity_extract": self._bool_param(
                parameters.get("enable_llm_cache_for_entity_extract"),
                profile.enable_llm_cache_for_entity_extract,
            ),
            "llm_model_max_async": self._int_param(
                parameters.get("llm_model_max_async"), profile.llm_model_max_async
            ),
            "embedding_func_max_async": self._int_param(
                parameters.get("embedding_func_max_async"),
                profile.embedding_func_max_async,
            ),
            "max_parallel_insert": self._int_param(
                parameters.get("max_parallel_insert"), profile.max_parallel_insert
            ),
            "vlm_enhanced": self._bool_param(
                parameters.get("vlm_enhanced"),
                profile.enable_image_processing or "vision" in profile.llm_capabilities,
            ),
            "retrieval_mode": self._text_param(parameters.get("retrieval_mode"), "hybrid"),
            "reference_query_mode": self._text_param(
                parameters.get("reference_query_mode"),
                "hybrid",
            ),
            "native_query_timeout_ms": self._int_param(
                parameters.get("native_query_timeout_ms"),
                15_000,
            ),
            "answer_style": self._text_param(parameters.get("answer_style"), ""),
            "limit": payload.limit,
            "response_mode": payload.response_mode,
            "answer_budget_ms": payload.answer_budget_ms,
            "response_budget_ms": payload.response_budget_ms,
        }
        if payload.response_mode == "fast":
            query_config["enable_rerank"] = False
            query_config["native_query_timeout_ms"] = min(
                int(query_config["native_query_timeout_ms"]),
                2500,
            )
            query_config["answer_budget_ms"] = payload.answer_budget_ms or 1000
            query_config["response_budget_ms"] = payload.response_budget_ms or 8000
        else:
            query_config["answer_budget_ms"] = payload.answer_budget_ms or profile.llm_timeout_ms
            query_config["response_budget_ms"] = payload.response_budget_ms
        return query_config
```

- [ ] **Step 4: Add a QueryService test for fast config**

Append this test to `backend/tests/test_runtime_query_service.py`:

```python
@pytest.mark.asyncio
async def test_query_service_fast_mode_caps_slow_stages(client):
    app = client._transport.app
    runtime = FakeRuntime()
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(
            session,
            app,
            indexed=False,
            settings_overrides={"enable_rerank": True},
        )
        variant.parameters = {
            "enable_rerank": True,
            "native_query_timeout_ms": 15000,
        }
        profile = await RuntimeProfileService(session, app.state.settings).get_active_profile()
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id=profile.id,
                status=StageStatus.SUCCEEDED.value,
                index_shape=profile.index_shape,
                chunk_count=1,
            )
        )
        await session.commit()

        service = QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
            retrieval_orchestrator=_real_retrieval_orchestrator(),
        )
        result = await service.run_query(
            QueryIn(
                query="What happened?",
                document_ids=[document.id],
                variant_ids=[variant.id],
                response_mode="fast",
                answer_budget_ms=1200,
                response_budget_ms=7500,
            )
        )

    run = result.runs[0]
    assert run.status == StageStatus.SUCCEEDED
    assert run.query_config["response_mode"] == "fast"
    assert run.query_config["answer_budget_ms"] == 1200
    assert run.query_config["response_budget_ms"] == 7500
    assert run.query_config["enable_rerank"] is False
    assert run.query_config["native_query_timeout_ms"] == 2500
```

- [ ] **Step 5: Run the QueryService fast config test**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_runtime_query_service.py::test_query_service_fast_mode_caps_slow_stages -q
```

Expected: PASS.

- [ ] **Step 6: Commit schema and config**

```bash
git add backend/src/ragstudio/schemas/query.py backend/src/ragstudio/services/query_service.py backend/tests/test_runtime_query_service.py
git commit -m "feat: add fast query response mode"
```

---

### Task 5: Fix Error-Type-Only Run Status

**Files:**
- Modify: `backend/src/ragstudio/services/query_service.py`
- Modify: `backend/tests/test_runtime_query_service.py`

- [ ] **Step 1: Add a failing test for empty ReadTimeout error text**

Append this test to `backend/tests/test_runtime_query_service.py`:

```python
@pytest.mark.asyncio
async def test_query_service_marks_error_type_only_orchestrated_run_failed(client):
    app = client._transport.app

    class ErrorTypeOnlyOrchestrator:
        async def query(self, *args, **kwargs):
            return type(
                "Answer",
                (),
                {
                    "answer": "",
                    "sources": [],
                    "chunk_traces": [],
                    "reranker_traces": [],
                    "token_metadata": {},
                    "error": "",
                    "error_type": "ReadTimeout",
                    "timings": {"answer_ms": 5000},
                },
            )()

    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(session, app, indexed=False)
        profile = await RuntimeProfileService(session, app.state.settings).get_active_profile()
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id=profile.id,
                status=StageStatus.SUCCEEDED.value,
                index_shape=profile.index_shape,
                chunk_count=1,
            )
        )
        await session.commit()

        service = QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(),
            health_service=FakeHealthService(),
            retrieval_orchestrator=ErrorTypeOnlyOrchestrator(),
        )
        result = await service.run_query(
            QueryIn(query="slow answer", document_ids=[document.id], variant_ids=[variant.id])
        )

    run = result.runs[0]
    assert run.status == StageStatus.FAILED
    assert run.error_type == "ReadTimeout"
    assert run.error == "ReadTimeout"
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_runtime_query_service.py::test_query_service_marks_error_type_only_orchestrated_run_failed -q
```

Expected: FAIL because current status logic checks only `orchestrated.error`.

- [ ] **Step 3: Fix QueryService status assignment**

In `backend/src/ragstudio/services/query_service.py`, replace:

```python
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
```

with:

```python
                has_orchestrated_error = bool(orchestrated.error or orchestrated.error_type)
                run.status = (
                    StageStatus.FAILED.value
                    if has_orchestrated_error
                    else StageStatus.SUCCEEDED.value
                )
                run.answer = orchestrated.answer
                run.sources = orchestrated.sources
                run.chunk_traces = orchestrated.chunk_traces
                run.reranker_traces = orchestrated.reranker_traces
                run.token_metadata = orchestrated.token_metadata
                run.error = orchestrated.error or orchestrated.error_type
                run.error_type = orchestrated.error_type
```

- [ ] **Step 4: Run the error status test**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_runtime_query_service.py::test_query_service_marks_error_type_only_orchestrated_run_failed -q
```

Expected: PASS.

- [ ] **Step 5: Run runtime query service tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_runtime_query_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the status fix**

```bash
git add backend/src/ragstudio/services/query_service.py backend/tests/test_runtime_query_service.py
git commit -m "fix: fail runs with error type only"
```

---

### Task 6: Update the Query Page for Fast Mode

**Files:**
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/features/query/query-page.tsx`
- Modify: `frontend/tests/query-page.test.tsx`

- [ ] **Step 1: Regenerate API types**

Start the backend if it is not already running:

```bash
docker compose up -d backend
```

Then run:

```bash
cd frontend
npm run generate:api
```

Expected: `frontend/src/api/generated.ts` includes:

```ts
export interface QueryIn {
  query: string;
  document_ids: string[];
  variant_ids: string[];
  limit: number;
  response_mode?: "fast" | "full";
  answer_budget_ms?: number | null;
  response_budget_ms?: number | null;
}
```

- [ ] **Step 2: Add answer mode state**

In `frontend/src/features/query/query-page.tsx`, add this type near `queryKeys`:

```ts
type QueryResponseMode = "fast" | "full";
```

Then add this state below the existing `limit` state:

```ts
  const [responseMode, setResponseMode] = useState<QueryResponseMode>("fast");
```

- [ ] **Step 3: Send fast mode in the query payload**

Replace the `runQuery.mutate({ ... })` call in `submit` with:

```ts
    runQuery.mutate({
      query: queryText.trim(),
      document_ids: selectedDocumentIds,
      variant_ids: selectedVariantIds,
      limit,
      response_mode: responseMode,
      answer_budget_ms: responseMode === "fast" ? 1000 : null,
      response_budget_ms: responseMode === "fast" ? 8000 : null,
    });
```

- [ ] **Step 4: Add a compact mode control**

Add this block between the chunk limit input and the submit button area:

```tsx
        <div className="mt-4">
          <span className="mb-1.5 block text-sm font-medium text-[#3a4a53]">Answer mode</span>
          <div
            className="grid grid-cols-2 rounded-md border border-[#cfd8dd] bg-[#f8fafb] p-1"
            role="group"
            aria-label="Answer mode"
          >
            {(["fast", "full"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                className={`rounded px-3 py-2 text-sm font-medium ${
                  responseMode === mode
                    ? "bg-white text-[#174657] shadow-sm"
                    : "text-[#62717a] hover:text-[#174657]"
                }`}
                onClick={() => setResponseMode(mode)}
                disabled={runQuery.isPending}
              >
                {mode === "fast" ? "Fast evidence" : "Full answer"}
              </button>
            ))}
          </div>
        </div>
```

- [ ] **Step 5: Update pending copy**

Replace:

```tsx
          <EmptyState icon={Loader2} title="Running query" description="Searching chunks and generating answers." />
```

with:

```tsx
          <EmptyState
            icon={Loader2}
            title="Running query"
            description={
              responseMode === "fast"
                ? "Preparing grounded evidence."
                : "Searching chunks and generating answers."
            }
          />
```

- [ ] **Step 6: Show evidence-first status outside JSON**

In `RunResult`, add these constants at the top of the function:

```tsx
  const answerMode = textValue(run.token_metadata.answer_mode);
  const llmAnswerStatus = textValue(run.token_metadata.llm_answer_status);
```

Then add this JSX after `<RerankerSummary traces={run.reranker_traces} />`:

```tsx
      {answerMode === "evidence_first" ? (
        <div className="mt-3 rounded-md border border-[#cfe3ea] bg-[#f5fafb] p-3 text-sm text-[#3a4a53]">
          <p className="font-semibold text-[#1f2933]">Evidence-first result</p>
          {llmAnswerStatus === "timeout" ? (
            <p className="mt-1 text-xs text-[#62717a]">LLM wording exceeded the fast budget.</p>
          ) : null}
        </div>
      ) : null}
```

- [ ] **Step 7: Add frontend tests**

Add this test to `frontend/tests/query-page.test.tsx`:

```ts
  it("runs fast evidence mode by default", async () => {
    renderQueryPage();

    fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
      target: { value: "alpha" },
    });
    fireEvent.click(await screen.findByText("source.txt"));
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(apiClient.query).toHaveBeenCalled());
    expect(apiClient.query).toHaveBeenCalledWith(
      expect.objectContaining({
        response_mode: "fast",
        answer_budget_ms: 1000,
        response_budget_ms: 8000,
      }),
    );
  });
```

Add this test to the same file:

```ts
  it("labels evidence-first fallback results", async () => {
    vi.mocked(apiClient.query).mockResolvedValue({
      runs: [
        {
          id: "run-1",
          variant_id: "variant-1",
          experiment_id: null,
          query: "alpha",
          status: "succeeded",
          answer: "Evidence-first result\n\nGrounded evidence:\n[S1] alpha",
          sources: [],
          chunk_traces: [],
          timings: {},
          error: null,
          runtime_profile_id: null,
          document_ids: ["doc-1"],
          query_config: { response_mode: "fast" },
          reranker_traces: [],
          token_metadata: {
            answer_mode: "evidence_first",
            llm_answer_status: "timeout",
          },
          error_type: null,
        },
      ],
    });
    renderQueryPage();

    fireEvent.change(await screen.findByPlaceholderText("Ask a focused question against selected documents."), {
      target: { value: "alpha" },
    });
    fireEvent.click(await screen.findByText("source.txt"));
    fireEvent.click((await screen.findAllByText("Balanced"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    expect(await screen.findByText("Evidence-first result")).toBeVisible();
    expect(screen.getByText("LLM wording exceeded the fast budget.")).toBeVisible();
  });
```

- [ ] **Step 8: Run frontend tests**

Run:

```bash
cd frontend
npm test -- query-page.test.tsx --run
```

Expected: PASS.

- [ ] **Step 9: Commit frontend changes**

```bash
git add frontend/src/api/generated.ts frontend/src/features/query/query-page.tsx frontend/tests/query-page.test.tsx
git commit -m "feat: default query page to fast evidence results"
```

---

### Task 7: Run Full Verification

**Files:**
- Verify: backend tests
- Verify: frontend tests
- Verify: live local stack

- [ ] **Step 1: Run backend focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_query_understanding.py \
  backend/tests/test_retrieval_orchestrator.py \
  backend/tests/test_metadata_retrieval_service.py \
  backend/tests/test_runtime_query_service.py \
  backend/tests/test_query_runs.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run Ruff**

Run:

```bash
.venv/bin/python -m ruff check \
  backend/src/ragstudio/schemas/query.py \
  backend/src/ragstudio/services/query_understanding.py \
  backend/src/ragstudio/services/retrieval_evidence.py \
  backend/src/ragstudio/services/evidence_first_answer_service.py \
  backend/src/ragstudio/services/retrieval_orchestrator.py \
  backend/src/ragstudio/services/query_service.py \
  backend/src/ragstudio/services/chunk_lexical_search_repository.py \
  backend/src/ragstudio/services/chunk_service.py \
  backend/src/ragstudio/db/models.py \
  backend/src/ragstudio/db/engine.py \
  backend/tests/test_query_understanding.py \
  backend/tests/test_retrieval_orchestrator.py \
  backend/tests/test_metadata_retrieval_service.py \
  backend/tests/test_runtime_query_service.py
```

Expected: PASS.

- [ ] **Step 3: Run frontend checks**

Run:

```bash
cd frontend
npm test -- query-page.test.tsx --run
npm run build
```

Expected: PASS.

- [ ] **Step 4: Restart the local stack**

Run:

```bash
docker compose restart backend frontend
curl -sS http://127.0.0.1:8000/api/health
```

Expected:

```json
{"status":"ok","service":"rag-anything-studio"}
```

- [ ] **Step 5: Run the live fast Tafseer proof query**

Run:

```bash
time curl -sS --max-time 12 \
  -X POST http://127.0.0.1:8000/api/query \
  -H 'Content-Type: application/json' \
  --data '{
    "query":"In Tafseer Ibn Kathir, explain verse 1:5 about seeking help and show the surrounding connected verses.",
    "document_ids":["1e2e700b-bbb1-4972-bc07-0c5bf040a8fc"],
    "variant_ids":["1bc23c48-c1f2-4362-bf76-84126e04c921"],
    "limit":5,
    "response_mode":"fast",
    "answer_budget_ms":1000,
    "response_budget_ms":8000
  }' | jq '.runs[0] | {
    id,
    status,
    error_type,
    answer_preview: (.answer[0:220]),
    source_count: (.sources | length),
    answer_mode: .token_metadata.answer_mode,
    llm_answer_status: .token_metadata.llm_answer_status,
    timings: {
      total_ms: .timings.total_ms,
      metadata_ms: .timings.metadata_ms,
      graph_ms: .timings.graph_ms,
      graph_hydration_ms: .timings.graph_hydration_ms,
      rerank_ms: .timings.rerank_ms,
      answer_ms: .timings.answer_ms,
      answer_fallback: .timings.answer_fallback
    },
    graph_trace: [.chunk_traces[] | select(.stage == "graph_expansion")][0]
  }'
```

Expected:

```json
{
  "status": "succeeded",
  "error_type": null,
  "source_count": 5,
  "answer_mode": "evidence_first",
  "llm_answer_status": "timeout",
  "timings": {
    "total_ms": 8000,
    "answer_fallback": true
  },
  "graph_trace": {
    "stage": "graph_expansion",
    "status": "ok"
  }
}
```

The exact `total_ms` may be lower than `8000`; it must stay under the 12-second curl cap and should be between 5000 and 8000 on the current Tafseer data.

- [ ] **Step 6: Run full mode comparison once**

Run:

```bash
time curl -sS --max-time 35 \
  -X POST http://127.0.0.1:8000/api/query \
  -H 'Content-Type: application/json' \
  --data '{
    "query":"In Tafseer Ibn Kathir, explain verse 1:5 about seeking help and show the surrounding connected verses.",
    "document_ids":["1e2e700b-bbb1-4972-bc07-0c5bf040a8fc"],
    "variant_ids":["1bc23c48-c1f2-4362-bf76-84126e04c921"],
    "limit":5,
    "response_mode":"full",
    "answer_budget_ms":30000,
    "response_budget_ms":null
  }' | jq '.runs[0] | {
    status,
    error_type,
    answer_chars: (.answer | length),
    answer_mode: .token_metadata.answer_mode,
    usage: .token_metadata,
    total_ms: .timings.total_ms,
    answer_ms: .timings.answer_ms
  }'
```

Expected: The run either succeeds with a full LLM answer around the previously measured 20 seconds, or fails cleanly as `status: "failed"` if the provider is slower than the explicit full-mode budget.

- [ ] **Step 7: Commit verification-only generated changes if needed**

If OpenAPI generation changed only `frontend/src/api/generated.ts` and it was not committed in Task 6, commit it:

```bash
git add frontend/src/api/generated.ts
git commit -m "chore: refresh query API types"
```

---

## Self-Review

**Spec coverage:** This plan addresses the user requirement to show a query result in 5-8 seconds without requiring a 30-second wait. It also keeps graph usefulness visible because sources and graph traces remain in the fast response.

**Placeholder scan:** The plan contains concrete file paths, code snippets, commands, and expected results. It does not rely on unspecified helper functions or future design work.

**Type consistency:** `response_mode`, `answer_budget_ms`, and `response_budget_ms` are defined in backend schema, propagated through `query_config`, regenerated into frontend types, and sent by the Query page. `answer_budget_ms` is capped in `RetrievalOrchestrator` for answer fallback, while `response_budget_ms` controls the total fast deadline.

**Execution choice:** Use subagent-driven execution if splitting is available. Otherwise execute inline in the task order above, committing after each task.
