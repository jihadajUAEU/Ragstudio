# Query Retrieval Architecture

Date: 2026-05-21

Status: architecture plan

Scope: full end-to-end `RetrievalRoutePlanner` architecture for chunk search,
query retrieval, fusion, rerank, context assembly, trace UI, and public proof.

## Goal

Make `RetrievalRoutePlanner` the durable control plane for Ragstudio retrieval.
The planner should decide which retrieval lanes are allowed, skipped, degraded,
or required before any lane runs. The orchestrator should execute the plan, not
reimplement routing decisions with scattered conditionals.

The target is robust enough to keep long-term:

- canonical Postgres evidence remains source of truth
- layout and domain metadata influence retrieval without bypassing evidence
- quality and materialization policy are hard gates
- every lane decision is traceable
- ranking changes are eval-gated
- public claims stay replayable from proof packets

## Benefit Scorecard

These are acceptance targets, not already-proven claims. The first implementation
must capture the baseline and then report current-versus-target metrics before
we claim the architecture improved the product.

| Metric | Current baseline | Target after route-planner authority | Why this matters |
| --- | --- | --- | --- |
| Route planning overhead P95 | TBD from `Run.timings` | <= 5 ms | The planner should be a cheap control plane, not another slow retrieval stage. |
| Primary retrieval P95 for metadata/reference-only queries | TBD; native lane can currently wait up to the configured native timeout, default 15s | 15-35% lower P95 when native/graph/reranker lanes are skipped by plan | Reference-heavy queries should not pay for broad semantic/runtime traversal when exact evidence is enough. |
| Graph traversal cost on stale/disabled graph | Can still reach graph fallback path unless disabled earlier | Skip stale/unavailable graph before expansion; save up to the current graph fallback window, currently about 1.2s per affected query | Stale graph should be visible but not slow down answers or pollute ranking. |
| Candidate count before reranker/context assembly | TBD | 20-40% fewer low-value candidates for direct/reference/layout queries | Smaller candidate sets reduce reranker cost, context dilution, and answer latency. |
| Direct-evidence hit rate | TBD golden set | 95-100% for exact reference and Arabic exact-token cases | Hadith, Quran, legal, and policy queries must rank direct evidence ahead of broad semantic matches. |
| MRR@10 / NDCG@10 | TBD golden set | No regression for planner/fusion work; 5-20% improvement target only after eval-gated vector/FTS | Ranking rewrites must prove they help before becoming default. |
| Recall@10 | TBD golden set | No regression for known relevant chunks | Speed improvements must not hide necessary evidence. |
| Document-scope agreement | Partially tested | 100% selected-document preservation across metadata, native, graph, fusion, rerank, and context assembly | User-selected documents must not silently widen to the corpus. |
| Lane trace coverage | Partial ad hoc traces | 100% planned/skipped/degraded lane result traces | Operators should see why a lane ran, skipped, degraded, or timed out. |
| Context drop explainability | Mostly token-budget drops | 100% dropped candidates carry reason codes | Missing evidence must be debuggable from traces, not guessed from final answers. |

Do not use percentages such as "accuracy increased by X%" in public or product
claims until the Phase 6 retrieval-quality baseline exists. Until then, the
honest expected benefit is: faster skipped-lane paths, stricter scope/policy
correctness, and measurable traceability.

## Review Refinements Added

The architecture review adds seven rules that should be treated as part of the
implementation contract, not optional polish:

1. **Hybrid score normalization.** Lexical, vector, metadata, graph, and runtime
   lanes must not add raw scores from incompatible scales. Fusion uses rank-based
   RRF by default and may add per-lane min-max normalization only inside a lane
   before rank/boost logic.
2. **Graph seed quality.** Graph expansion consumes only high-confidence seed
   chunks from completed canonical, lexical, and metadata lanes. Default seed
   count is 5. Runtime-only or low-confidence candidates are not graph seeds
   unless explicitly bridged to canonical chunks.
3. **Strict scope semantics.** Empty `document_ids` means "all documents in the
   active runtime profile" only when the profile allows broad search. A strict
   profile must reject empty scope with `ScopeAccessViolationError`.
4. **Partial timeout recovery.** If a lane reaches `timeout_ms` after collecting
   candidates, it returns those candidates as `degraded` with warning flags. It
   returns an error only when the lane is marked critical.
5. **Physical context safety.** Required direct evidence can be protected over
   the soft budget, but it must never exceed the model's hard context window.
   Over-limit evidence is truncated at a logical boundary and marked
   `context_truncated`.
6. **Request-local domain classification cache.** `DomainClassifier` should cache
   per-document classification for the current request so multi-document routes
   do not repeatedly parse the same metadata.
7. **Non-blocking token estimation.** Context token estimation should use a fast
   tokenizer when available, fall back to conservative heuristics, and offload
   unusually large text payloads so it does not block the async request path.

## Non-Negotiable Invariants

1. **Canonical evidence first.** Every answer source must trace back to a
   canonical Ragstudio chunk or be explicitly marked as degraded runtime-only
   evidence.
2. **No silent scope widening.** Selected `document_ids` must propagate through
   metadata, lexical, native runtime, graph, hydration, fusion, rerank, and
   context assembly.
3. **Policy beats ranking.** `quality_action_policy` and materialization policy
   decide lane eligibility before scoring, reranking, or graph expansion.
4. **Runtime and graph are lanes, not authority.** RAG-Anything and Neo4j can
   add candidates, but they cannot replace canonical Postgres evidence.
5. **Fallbacks are bounded and honest.** Bounded candidate sets must be reported
   as bounded. Do not imply a full corpus was ranked when it was not.
6. **Every skipped lane has a reason.** Disabled, blocked, stale, unavailable,
   timed out, unsupported, or out-of-budget states must be visible in traces.
7. **Fusion is explainable.** Final rank must preserve lane membership,
   per-lane rank, score basis, direct-match boosts, and reranker changes.
8. **Public proof is stricter than runtime success.** Launch claims require
   valid proof packets, static fixtures, redaction, claim registry entries, and
   limitations.

## Pipeline Ownership

`RetrievalRoutePlanner` owns layers 6-8 and consumes signals from layers 1-5:

```text
Parse
 -> Layout Normalization
 -> Domain Resolver
 -> Canonical Evidence
 -> Repair / Quality
 -> Materialization Policy
 -> RetrievalRoutePlanner
 -> Lane Executors
 -> Fusion / Rerank
 -> Context Assembly
 -> Proof Trace
```

The planner does not parse documents, repair layout, or score final answers. It
does decide whether those upstream outputs allow each retrieval lane to run.

## Lessons From Chunking Work

The previous context-aware, layout-aware, and domain-aware chunking work changed
what retrieval should optimize. Retrieval should no longer treat all chunks as
anonymous text spans. It should use the chunk assembly metadata as routing,
ranking, and context signals.

| Chunking lesson | Retrieval use | Expected performance effect | Metric to watch |
| --- | --- | --- | --- |
| Canonical reference units are better than parser fragments. | Search answerable canonical units first; keep header-only/provenance-only chunks out of answer evidence unless explicitly requested. | Higher direct-evidence precision and fewer irrelevant chunks in reranker/context. | Direct-evidence hit rate, MRR@10, provenance-only drop count. |
| Domain-aware assembly identifies reference-heavy corpora such as Quran, tafseer, hadith, legal, and policy docs. | `DomainClassifier` maps those documents to `reference_heavy`; planner runs `lexical_reference` and metadata before vector/runtime lanes. | Faster exact-reference traversal and better rank for direct evidence. | Reference lane latency, direct hit rate, native lane skip rate. |
| Layout-aware assembly preserves block type, page, bbox, reading order, and layout roles. | Planner routes table/figure/equation queries through layout-aware canonical evidence and runtime bridge only when materialization allows it. | Fewer failed semantic matches for layout questions and fewer unnecessary graph traversals. | Layout-query MRR@10, runtime bridge missing rate, graph skip/degrade count. |
| Semantic page-boundary stitching creates chunks that preserve multi-page evidence. | Context assembly can include stitched chunks directly instead of searching adjacent pages or graph neighbors. | Less follow-up traversal for page-boundary answers and better context compactness. | Context token use, adjacent-expansion count, answer evidence recall. |
| Quality gates distinguish answerable, warning, repaired, quarantined, blocked, and provenance-only material. | Route planner uses `quality_action_policy` and materialization policy before ranking. | Unsafe chunks do not enter vector/graph/runtime lanes; precision improves without hiding the reason. | Policy-blocked lane count, unsafe candidate count, trace reason coverage. |
| Parallel text and script coverage matter in Arabic/reference corpora. | Ranking boosts direct Arabic/reference evidence and avoids penalizing commentary where Arabic is optional by policy. | Better Arabic exact-token retrieval and fewer false missing-script penalties. | Arabic direct hit rate, missing-script warning agreement, MRR@10 for Arabic queries. |
| Parser recovery warnings can be accepted or blocking depending on document policy. | Retrieval traces must carry parser warning and source quality metadata so operators know whether evidence is repaired but usable. | Better operator trust and less over-filtering of useful repaired text. | Warning-bearing candidate inclusion rate, quality trace coverage. |
| Chunk metadata is the durable bridge between ingestion and retrieval. | Route input should consume `reference_metadata`, `domain_metadata`, `layout_hint`, `quality_action_policy`, and `materialization_policy`. | Smaller candidate pools and better lane choices before expensive traversal. | Candidate count before rerank, lane skip rate, route-plan correctness. |

Practical rule:

```text
Better chunks reduce retrieval work.
Canonical units decide what can be searched.
Domain/layout metadata decides which lane should search it.
Quality/materialization policy decides whether the lane is allowed.
Route traces explain the decision.
```

This is why the route planner should sit after chunk quality/materialization and
before lane execution. It turns the earlier chunking intelligence into runtime
retrieval decisions instead of leaving it as passive metadata.

## Current State

Already present:

- `pipeline_architecture.py` defines the ten-layer evidence model, but it is
  currently a conceptual/test contract rather than runtime enforcement.
- `domain_profile_registry.py` defines general, reference-heavy, and multimodal
  domain profiles.
- `evidence_unit_contract.py` defines quality and materialization policies, but
  runtime retrieval still mostly carries those policies as chunk metadata on
  `EvidenceCandidate`.
- `retrieval_route_planner.py` exists and can produce route decisions.
- `RetrievalOrchestrator` now emits a `retrieval_route_plan` trace, but it does
  not yet execute lane plans.
- `MetadataRetrievalService` provides bounded metadata/chunk retrieval passes.
- `RetrievalFusion` performs reciprocal-rank style fusion, but today it is fed a
  collapsed already-fused list instead of independent lane result lists.

Main gap:

`RetrievalRoutePlanner` is visible in traces, but it is not yet the single
authority that gates lane execution. Existing orchestrator gates still live in
ad hoc conditionals such as metadata-only mode, fast-mode deadline handling, and
graph expansion flags.

## Gap Findings Folded Into This Plan

The 2026-05-21 query-retrieval gap analysis identified 14 findings. All are
relevant to the architecture, but several are partial or stale relative to the
current working tree. The plan treats them as follows:

| Gap | Decision | Architecture update |
| --- | --- | --- |
| GAP-01 route plan trace-only | Relevant | Make planner advisory-only status explicit; Phase 3 replaces ad hoc orchestrator gates with lane-plan execution. |
| GAP-02 double fusion | Relevant | Phase 5 now requires one fusion pass over per-lane candidate lists. |
| GAP-03 `EvidenceUnit` disconnected | Relevant with nuance | Runtime may either merge policy fields into `EvidenceCandidate` or construct `EvidenceUnit` wrappers before fusion/context assembly. |
| GAP-04 `pipeline_architecture.py` unreferenced | Relevant with nuance | Treat it as conceptual/test-only until layer transitions are enforced by runtime contracts. |
| GAP-05 graph readiness missing | Relevant | Add explicit graph readiness states and planner-visible degraded reasons. |
| GAP-06 budgets missing | Relevant | Rename future route count budget to `candidate_limit`; add per-lane time budgets and response budget policy. |
| GAP-07 lane result traces missing | Relevant | Add `RetrievalLaneResult` as the stable trace/proof contract. |
| GAP-08 context drop reasons incomplete | Relevant | Phase 5 requires full drop reason taxonomy and direct-evidence budget behavior. |
| GAP-09 domain logic scattered | Relevant | Add a shared `DomainClassifier` route-input component. |
| GAP-10 token estimation weak | Relevant | Add tokenizer-aware estimation as context assembly work. |
| GAP-11 reranker scores not propagated | Relevant | Reranker lane must write score/rank deltas back into final evidence traces. |
| GAP-12 no query-time vector search | Relevant, not immediate | Add as eval-gated accuracy lane after baseline metrics exist. |
| GAP-13 no Postgres FTS | Relevant, not immediate | Add as eval-gated prerequisite for DB-level hybrid retrieval. |
| GAP-14 no retrieval eval baseline | Relevant and blocking | Add quality baseline before vector/FTS/RRF ranking rewrites. |

Findings not adopted:

- None are rejected outright.
- GAP-01 is worded as advisory-only rather than "decorative" because the route
  trace already exists and is useful for migration.
- GAP-03 is not treated as a mandatory type replacement; the architecture allows
  either a first-class `EvidenceUnit` pipeline or an enriched `EvidenceCandidate`
  that carries the same policy fields.
- GAP-04 is corrected to "no runtime enforcement" rather than "zero references"
  because tests can reference the model even when services do not.
- GAP-12 and GAP-13 are intentionally not moved ahead of GAP-14. Vector/FTS work
  changes ranking behavior and must be validated against a retrieval-quality
  baseline first.

## Target Contracts

### RetrievalRouteRequest

The request should be built once per query run after query understanding,
domain expansion, runtime readiness, index readiness, graph readiness, and
document quality summaries are known.

Required fields:

- `query`
- `document_ids`
- `scope_policy`
- `runtime_profile_id`
- `variant_id`
- `query_intent`
- `retrieval_strategy`
- `direct_evidence_required`
- `graph_context_required`
- `target_references`
- `target_phrases`
- `expanded_terms`
- `domain_profile_id`
- `layout_hint`
- `materialization_hint`
- `quality_action_policy_summary`
- `materialization_policy_summary`
- `runtime_readiness`
- `graph_readiness`
- `reranker_readiness`
- `limit`
- `candidate_limit`
- `response_budget_ms`
- `lane_time_budget_ms`

The request should not include raw secrets, private endpoints, or full document
content.

Scope behavior:

- `scope_policy="allow_profile_wide"` means empty `document_ids` is interpreted
  as all documents associated with `runtime_profile_id`.
- `scope_policy="strict_document_scope"` means empty `document_ids` raises
  `ScopeAccessViolationError` before any lane executes.
- Every lane result must echo the effective document scope it used.

Readiness fields should use explicit state objects, not booleans:

- `state`: `ready`, `disabled`, `stale`, `unavailable`, `degraded`, or
  `unknown`
- `reason`
- `checked_at`
- `scope`: document ids, runtime profile id, graph projection id, or reranker
  provider id when applicable
- `safe_to_run`: boolean used by the planner

Graph readiness needs special care because `stale` and `unavailable` are
different operator states. Stale graph projection can be reported and skipped;
unavailable graph infrastructure can be degraded with a different reason.

### RetrievalRoutePlan

The plan is immutable for one query run and should serialize into
`Run.chunk_traces`.

Required fields:

- `route_plan_version`
- `route_id`
- `source_of_truth`
- `document_ids`
- `domain_profile_id`
- `layout_hint`
- `query_intent`
- `retrieval_strategy`
- `direct_evidence_required`
- `graph_context_required`
- `candidate_limit`
- `response_budget_ms`
- `lane_time_budget_ms`
- `lanes`
- `skipped_lanes`
- `degraded_lanes`
- `readiness`
- `reasons`

### RetrievalLanePlan

Each lane plan should be explicit:

- `lane`: `postgres_canonical`, `lexical_reference`, `metadata`, `vector`,
  `graph`, `raganything_runtime`, `reranker`
- `status`: `planned`, `required`, `skipped`, or `degraded`
- `executor`: service method or adapter path that will execute it
- `candidate_limit`
- `timeout_ms`
- `document_ids`
- `lane_score_policy`
- `requires_runtime_ready`
- `requires_graph_ready`
- `requires_index_vector`
- `requires_project_graph`
- `requires_runtime_materialization`
- `hydrate_to_canonical`
- `critical`
- `reasons`

No lane executor should run unless its lane plan status is `planned` or
`required`.

### RetrievalLaneResult

Every executor returns or emits a result trace:

- `lane`
- `status`: `ran`, `skipped`, `degraded`, `failed`, or `timed_out`
- `reason`
- `candidate_count`
- `candidate_ids`
- `canonical_chunk_ids`
- `document_ids`
- `candidates`
- `score_basis`
- `per_candidate_scores`
- `latency_ms`
- `timed_out`
- `partial`
- `warning_flags`
- `error_type`

This becomes the stable UI/proof diagnostic surface.

Lane results should be the only input shape accepted by fusion once the
migration completes. Ad hoc trace dicts can remain as compatibility fields until
the frontend and proof packet readers have moved to this contract.

Timeout behavior:

- A non-critical lane that times out after collecting candidates returns
  `status="degraded"`, `partial=true`, and `warning_flags=["lane_timeout"]`.
- A critical lane that times out raises a lane failure and marks the run failed
  or answer-degraded according to the route policy.
- Partial candidates must still hydrate to canonical chunks before fusion unless
  the route plan explicitly permits degraded runtime-only evidence.

## End-To-End Flow

### 1. QueryService Builds Runtime Context

`QueryService` remains responsible for:

- validating selected variants and documents
- loading the active runtime profile
- checking runtime readiness
- checking index compatibility
- checking graph readiness/degradation
- recording `Run` state

It should pass a runtime context object into `RetrievalOrchestrator`, not make
lane decisions itself except for hard preflight failures.

### 2. RetrievalOrchestrator Builds Route Input

`RetrievalOrchestrator` remains responsible for:

- query hypothesis
- domain query expansion
- `QueryUnderstanding`
- domain metadata lookup
- document quality summary lookup
- converting all signals into `RetrievalRouteRequest`

This conversion should move into a small helper/service when it grows:

- proposed file: `backend/src/ragstudio/services/retrieval_route_input.py`
- tests: `backend/tests/test_retrieval_route_input.py`

Domain classification should be centralized while building this input:

- proposed helper: `DomainClassifier`
- consumes: domain metadata, document type, tags, parser/domain hints, query
  intent, and layout signals
- produces: stable `domain_profile_id`, `domain_family`, `layout_hint`, and
  reference-heavy flags
- used by: route planning, scoring boosts, metadata expansion, and proof traces
- request-local cache key: `document_id` plus metadata version/fingerprint

This replaces the current scattered domain-family helpers so a Quran, tafseer,
hadith, legal, research, table-heavy, or generic document is classified once and
then reused consistently.

### 3. RetrievalRoutePlanner Produces The Plan

The planner applies rules in this order:

1. set source of truth to canonical Postgres evidence
2. resolve domain profile
3. resolve layout hint
4. apply query intent and direct evidence requirements
5. apply quality action policy
6. apply materialization policy
7. apply runtime/graph/reranker readiness
8. allocate lane budgets
9. emit planned/skipped/degraded lane reasons

Planner output is appended to traces before retrieval starts.

### 4. Lane Executor Registry Runs The Plan

`RetrievalOrchestrator` should call lane executors through a simple registry:

- `postgres_canonical` -> canonical metadata/chunk lookup
- `lexical_reference` -> exact reference / preview-ref / language-aware lexical
- `metadata` -> `MetadataRetrievalService`
- `raganything_runtime` -> native runtime scoped query
- `graph` -> graph expansion only after seed candidates and readiness checks
- `reranker` -> reranker service after final bounded fusion

The first implementation can keep methods inside `RetrievalOrchestrator`; the
important change is that each method receives a `RetrievalLanePlan` and emits a
`RetrievalLaneResult`.

Graph seed rule:

- default maximum graph seeds: 5
- seed sources: completed `postgres_canonical`, `lexical_reference`, and
  `metadata` lane results
- seed eligibility: canonical chunk id present, document scope matches, not
  blocked by quality policy, and above the lane's minimum confidence/rank cutoff
- excluded by default: runtime-only candidates, unhydrated graph candidates,
  provenance-only chunks, and candidates with missing canonical bridge
- graph expansion must emit `graph_no_eligible_seeds` instead of running when no
  seed passes the rule

### 5. Fusion Uses Lane Results

Fusion input should be a list of lane result candidate lists, not loose
candidate arrays. Fusion must preserve:

- lane membership
- lane rank
- lane status
- direct evidence features
- canonical reference
- materialization/quality risk flags
- runtime bridge status

Target shape:

1. Lane executors return independent ordered lists.
2. Fusion deduplicates by canonical chunk id.
3. Fusion calculates one final score from lane ranks, boosts, and penalties.
4. Compatibility fields can expose the old `final_fusion` and
   `retrieval_fusion` stages until the UI migrates.

The final architecture must not run an already-fused list through a second RRF
pass as a single input list. That adds trace noise without true multi-lane
fusion.

Default fusion formula:

```text
RRF_score(candidate) = sum(1 / (k + lane_rank(candidate))) for each active lane
```

Use `k=60` unless the retrieval-quality baseline proves another value improves
MRR@10, NDCG@10, Recall@10, and direct-evidence hit rate. Raw vector cosine,
Postgres `ts_rank`, metadata confidence, graph distance, and runtime scores must
remain lane-local features unless normalized inside their own lane before rank
fusion.

### 6. Reranker Runs As A Planned Lane

Reranker should be represented as a lane plan:

- skipped when disabled
- degraded when primary reranker fails and fallback runs
- failed only if reranker is required and no fallback is allowed

Reranker traces must include before/after rank and provider/model without
leaking secrets.

Reranker output must also propagate back into final evidence:

- `pre_rerank_rank`
- `post_rerank_rank`
- `pre_rerank_score`
- `reranker_relevance_score`
- `reranker_model`
- `reranker_status`
- `reranker_reason`

This lets operators compare the fusion score journey and reranker score journey
without joining separate trace arrays by hand.

### 7. Context Assembly Consumes Canonical Evidence

Context assembly should reject or downgrade candidates with missing canonical
bridges unless the route plan explicitly allowed degraded runtime-only evidence.

Dropped candidates should expose reason codes:

- `token_budget`
- `duplicate_evidence`
- `quality_policy_block`
- `runtime_bridge_missing`
- `graph_projection_stale`
- `reranker_degraded`

Context assembly should also replace word-count token estimation with a
tokenizer-aware estimator. If the exact production tokenizer is unavailable, use
a conservative fallback calibrated for Arabic, code, and reference-heavy text.
For unusually large payloads, tokenizer work should use a fast C-backed library
or be offloaded so the async request path is not blocked.

Direct evidence should have explicit budget behavior:

- keep required direct evidence when it fits
- trim surrounding context before dropping direct evidence
- emit `direct_evidence_preserved_over_budget` if the route policy intentionally
  protects it
- emit `direct_evidence_budget_conflict` if the system cannot include required
  evidence within the answer budget
- emit `context_truncated` if evidence exceeds the model's physical context
  limit after soft-budget handling
- truncate at paragraph, verse, table row, or block boundary before calling the
  LLM when the hard model limit would otherwise be exceeded

## Domain And Layout Routing Rules

### Generic Documents

Default profile:

1. `postgres_canonical`
2. `metadata`
3. `vector` if allowed and ready
4. `raganything_runtime` if allowed and useful
5. `graph` only when graph context is requested or projection is explicitly ready

### Reference-Heavy Documents

Examples: Quran, tafseer, hadith, legal/policy documents.

Profile:

1. `postgres_canonical`
2. `lexical_reference`
3. `metadata`
4. `graph` when projection is ready and policy allows
5. `vector` only after direct/reference lanes
6. `raganything_runtime` only as supporting lane

Direct evidence queries must not be answered from broad semantic matches when
exact reference or lexical evidence is missing.

### Layout-Heavy Documents

Examples: tables, figures, equations, parallel text, mixed page layouts.

Profile:

1. `postgres_canonical`
2. `metadata`
3. `raganything_runtime` when materialization allows and bridge ids exist
4. `vector`
5. `graph` only when ready and policy allows

Layout diagnostics can influence skipped/degraded reasons, but they must not
invent coordinates, text, or provenance.

## Implementation Phases

### Phase 1: Strengthen Planner Contract

Files:

- `backend/src/ragstudio/services/retrieval_route_planner.py`
- `backend/tests/test_retrieval_route_planner.py`

Tasks:

1. Add `RetrievalLanePlan`.
2. Add `SkippedLane` or represent skipped lanes as lane plans with
   `status="skipped"`.
3. Add request fields for intent, direct evidence, graph context, readiness,
   document ids, and budgets.
4. Add plan serialization with `route_plan_version`.
5. Test generic, reference-heavy, layout-heavy, blocked-quality, graph-stale,
   runtime-unavailable, and reranker-disabled cases.

Exit criteria:

- Planner tests explain every lane allowed or skipped.
- Canonical Postgres is always first.

### Phase 2: Build Route Input From Runtime State

Files:

- `backend/src/ragstudio/services/retrieval_route_input.py`
- `backend/src/ragstudio/services/domain_classifier.py`
- `backend/src/ragstudio/services/retrieval_orchestrator.py`
- `backend/tests/test_retrieval_route_input.py`
- `backend/tests/test_domain_classifier.py`
- `backend/tests/test_retrieval_orchestrator.py`

Tasks:

1. Convert domain metadata and query understanding into route input.
2. Include runtime, graph, and reranker readiness from query config/profile.
3. Include materialization and quality summaries when available.
4. Preserve selected document ids.
5. Move scattered domain-family logic into `DomainClassifier`.
6. Add explicit graph readiness states: `ready`, `stale`, `unavailable`,
   `disabled`, and `unknown`.
7. Add scope policy handling:
   - `allow_profile_wide` permits empty `document_ids`
   - `strict_document_scope` rejects empty `document_ids`
8. Add request-local domain classification cache for multi-document queries.

Exit criteria:

- Orchestrator route traces show all planner inputs needed to debug lane
  decisions.
- Domain classification is identical for route planning, scoring, and query
  expansion.
- Empty document scope behavior is explicit and tested.

### Phase 3: Execute Primary Retrieval From Lane Plans

Files:

- `backend/src/ragstudio/services/retrieval_orchestrator.py`
- `backend/src/ragstudio/services/metadata_retrieval_service.py`
- `backend/tests/test_retrieval_orchestrator.py`
- `backend/tests/test_metadata_retrieval_service.py`

Tasks:

1. Replace scattered metadata/native retrieval conditionals with lane-plan
   execution for primary retrieval.
2. Preserve existing behavior while adding lane result traces.
3. Ensure metadata-only mode becomes a planner decision.
4. Ensure native runtime is skipped/degraded by plan when not allowed.
5. Replace the current orchestrator gates with plan checks:
   - metadata-only mode becomes a lane status decision
   - fast-mode deadline handling becomes route and lane budgets
   - graph expansion flags become graph readiness plus graph lane status
6. Enforce `candidate_limit`, `response_budget_ms`, and per-lane `timeout_ms`
   for every lane, not only native runtime.

Exit criteria:

- No primary retrieval lane runs unless present as planned/required.
- Slow lanes return `timed_out` or `degraded` lane results rather than blocking
  the whole response indefinitely.
- Existing orchestrator tests pass.

### Phase 4: Execute Graph And Reranker From Lane Plans

Files:

- `backend/src/ragstudio/services/retrieval_orchestrator.py`
- `backend/src/ragstudio/services/graph_expansion_service.py`
- `backend/src/ragstudio/services/reranker_service.py`
- `backend/tests/test_retrieval_orchestrator.py`
- `backend/tests/test_graph_expansion_service.py`
- `backend/tests/test_reranker_service.py`

Tasks:

1. Graph expansion runs only from graph lane plan.
2. Graph skipped/degraded reasons include stale projection, disabled flag,
   quality policy block, and missing seeds.
3. Reranker runs only from reranker lane plan.
4. Reranker skipped/degraded reasons include disabled profile, disabled query
   config, provider failure, timeout, and fallback use.
5. Graph expansion consumes at most 5 eligible seeds from completed canonical,
   lexical/reference, and metadata lanes.
6. Graph lane returns `graph_no_eligible_seeds` when seed quality is too low
   rather than expanding from noisy candidates.

Exit criteria:

- Graph/reranker traces are lane results, not ad hoc trace fragments.
- Graph expansion never uses unbridged runtime-only evidence as a seed.

### Phase 5: Fusion And Context Assembly Consume Lane Results

Files:

- `backend/src/ragstudio/services/retrieval_fusion.py`
- `backend/src/ragstudio/services/retrieval_evidence.py`
- `backend/src/ragstudio/services/context_assembly_service.py`
- `backend/tests/test_rag_retrieval_fusion.py`
- `backend/tests/test_retrieval_orchestrator.py`

Tasks:

1. Preserve lane result metadata through fusion.
2. Add risk flags for quality/materialization and runtime bridge state.
3. Add context-drop reasons for blocked or degraded evidence.
4. Ensure final source traces answer why the chosen chunks won.
5. Collapse double fusion into a single pass over per-lane candidate lists.
6. Bridge policy contracts by either:
   - enriching `EvidenceCandidate` with `QualityActionPolicy` and
     `MaterializationPolicy` fields, or
   - constructing `EvidenceUnit` wrappers before fusion/context assembly.
7. Replace word-count token estimation with a tokenizer-aware estimator.
8. Define direct-evidence behavior when required evidence conflicts with the
   answer token budget.
9. Make RRF the default cross-lane scale bridge and keep raw vector/FTS/runtime
   scores as lane-local features unless normalized inside the lane.
10. Add hard model context limit handling with logical-boundary truncation and
   `context_truncated` trace metadata.
11. Ensure token estimation does not block the async request path for large
   payloads.

Exit criteria:

- A final answer source can be traced to route plan, lane result, fusion, rerank,
  context assembly, and validation.
- One fusion stage receives lane result lists; no single-list RRF pass remains
  except as a temporary compatibility trace.
- Fusion never adds raw lexical, vector, metadata, graph, and runtime scores
  without a documented normalization or rank-fusion rule.

### Phase 6: Retrieval Quality Baseline

Files:

- `backend/tests/test_retrieval_quality_eval.py`
- `backend/tests/test_rag_retrieval_fusion.py`
- `backend/tests/test_retrieval_orchestrator.py`
- `docs/benchmarks/ragstudio-oss-proof-v1/`

Tasks:

1. Add golden retrieval eval cases before SQL/vector/FTS/RRF changes:
   - exact reference lookup
   - conversational query terms
   - Arabic text and normalized Arabic tokens
   - selected document filters
   - quality-blocked chunks
   - provenance-only chunks
   - reranker before/after changes
   - graph degradation
   - native runtime degradation
   - layout/table evidence
   - runtime-only candidate with missing canonical bridge
2. Measure:
   - MRR@k for single-answer queries
   - NDCG@k for ranked-list quality
   - Recall@k for known relevant chunks
   - direct-evidence hit rate for exact/reference queries
   - per-lane latency P50/P95/P99
   - degraded-lane correctness
3. Store baseline fixtures and expected metrics with the proof benchmark docs.

Exit criteria:

- Ranking behavior has a baseline that can detect regressions.
- DB-level hybrid/RRF work does not start until this baseline exists.

### Phase 7: Eval-Gated Vector And FTS Retrieval

Files:

- `backend/src/ragstudio/services/vector_retrieval_service.py`
- `backend/src/ragstudio/services/chunk_lexical_search_repository.py`
- `backend/src/ragstudio/services/retrieval_orchestrator.py`
- `backend/tests/test_vector_retrieval_service.py`
- `backend/tests/test_chunk_lexical_search_repository.py`
- `backend/tests/test_retrieval_quality_eval.py`

Tasks:

1. Add direct query-time PGVector retrieval over canonical chunks that are
   allowed by materialization and quality policy.
2. Add Postgres FTS as the indexed lexical lane for supported languages, while
   retaining Arabic-specific normalization and exact reference handling.
3. Fuse vector, FTS/lexical, metadata/reference, graph, and runtime lanes through
   the same lane-result contract.
4. Compare ranking metrics against the Phase 6 baseline before enabling by
   default.
5. Keep native RAG-Anything as an explainable lane that bridges back to
   canonical chunks, not as the hidden source of truth.
6. Normalize lane-local scores before exposing them to fusion diagnostics; use
   RRF for default cross-lane ordering.

Exit criteria:

- Vector/FTS improves or preserves MRR@k, NDCG@k, Recall@k, direct-evidence hit
  rate, and latency budgets on the baseline suite.
- Regressions are documented and blocked unless explicitly accepted.

## Migration Strategy

Use a compatibility-first rollout:

1. Add route plan and lane result traces without changing candidate results.
2. Replace the three current ad hoc gates with planner-owned decisions:
   metadata-only mode, fast-mode deadlines, and graph expansion flags.
3. Gate one lane at a time through the planner.
4. Keep old trace names until frontend/tests have migrated.
5. Add strict tests after each lane moves under planner control.
6. Remove old ad hoc routing only when all lanes are planner-driven.
7. Add retrieval-quality baseline metrics before enabling new ranking lanes.

## Test Matrix

Planner tests:

- generic semantic query
- reference-heavy exact reference
- Arabic compact token
- phrase lookup
- table/layout-heavy query
- graph context requested
- graph stale
- runtime unavailable
- vector blocked by quality policy
- graph blocked by quality policy
- runtime blocked by materialization policy
- reranker disabled

Orchestrator tests:

- route plan emitted before retrieval
- metadata-only route skips native runtime
- selected document ids preserved across lanes
- no lane runs unless its plan status is `planned` or `required`
- graph lane skipped when not planned
- graph lane degraded when stale
- reranker lane skipped/degraded/ran states
- reranker scores and before/after ranks propagate to final traces
- final fusion keeps lane result metadata
- context assembly records dropped candidate reasons
- direct evidence budget conflicts are explicit

Quality eval tests:

- MRR@k baseline is stable for single-answer queries
- NDCG@k baseline is stable for ranked-list queries
- Recall@k baseline covers known relevant chunks
- direct-evidence hit rate protects exact reference queries
- per-lane latency P50/P95/P99 stays within route budget
- vector/FTS changes cannot enable by default without baseline comparison

Proof/public tests:

- proof packet includes route plan or documented limitation
- redaction check sees no private endpoints or paths
- static fixture replay validates retrieval traces

## Non-Goals

- Do not replace canonical Postgres evidence with native runtime retrieval.
- Do not add chunk self-link columns until there is a concrete consumer.
- Do not rewrite `ILIKE` query shape or enable FTS/vector ranking by default
  without EXPLAIN evidence and retrieval-quality baseline comparison.
- Do not make graph projection authoritative.
- Do not claim public launch readiness from runtime traces alone.

## Validation

Run focused suites as phases land:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_route_planner.py backend/tests/test_retrieval_orchestrator.py -q
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_metadata_retrieval_service.py backend/tests/test_rag_retrieval_fusion.py backend/tests/test_retrieval_metrics.py -q
```

For public proof changes:

```powershell
./scripts/proof.sh --strict --json
```

## Implementation Compliance Status

Ragstudio's retrieval architecture is implemented against the three-pillar
contract:

- Domain-aware ingestion and retrieval is implemented through domain
  classification, executable profiles, domain lexical adapters, route input,
  quality policy, materialization policy, and public lane traces.
- Layout-aware ingestion and retrieval is implemented through canonical source
  location, provenance, layout group expansion, bbox proximity, native bridge
  metadata, and context-visible layout summaries.
- Context-aware ingestion and retrieval is implemented through evidence context,
  adjacent context-window expansion, graph-seeded canonical hydration, context
  assembly, direct-evidence preservation, and dropped/truncated evidence reasons.

The public proof packet validates this with deterministic synthetic fixtures.
Production retrieval quality over customer corpora remains measured by separate
retrieval quality baselines.
