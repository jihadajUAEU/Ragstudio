---
name: chunk-query-retrieval-auditor
description: Audit and improve Ragstudio chunk search, metadata retrieval, query planning, candidate ranking, fusion, reranking, graph expansion, and retrieval trace explainability. Use when work touches ChunkService.search, ChunkLexicalSearchRepository, HybridChunkSearch, MetadataRetrievalService, RetrievalOrchestrator, RetrievalRoutePlanner, RetrievalFusion, query runs, Run.sources, chunk traces, reranker traces, graph expansion, quality_action_policy effects on retrieval, bounded search fallback, or architecture decisions across pipeline layers 6-8.
---

# Chunk Query Retrieval Auditor

## Overview

Use this skill for focused retrieval/search/ranking work in Ragstudio. Keep every recommendation tied to canonical Postgres evidence, materialization policy, retrieval traces, and tests; do not turn Ragstudio into a generic vector-only RAG app.

This skill complements `rag-pipeline-auditor`: use that broad skill for parse-to-proof investigations, and this skill when the main question is "which chunks were searched, ranked, fused, reranked, shown, or omitted, and why?"

## Architecture To Preserve

Ragstudio retrieval must follow this architecture unless the user explicitly asks for a redesign and the change has eval coverage:

1. **Canonical evidence first.** Start from persisted Ragstudio chunks in Postgres. Every candidate must be traceable to `document_id`, `chunk_id`, `runtime_source_id` when available, source location, provenance blocks, reference metadata, and quality/materialization policy.

2. **Layer 6 gates retrieval.** `quality_action_policy`, parser warnings, provenance-only status, vector indexing policy, graph projection policy, and materialization policy decide which lanes a chunk may enter. Do not bypass these policies to make answers look better.

3. **Layer 7 plans routes before ranking.** Retrieval route planning must choose deterministic lanes from query intent, document filters, domain/reference semantics, runtime health, graph projection readiness, and quality policy. It must not silently drop document filters.

4. **Layer 8 fuses explainable lanes.** Lexical, metadata/reference, vector, graph, runtime RAG-Anything, and reranker lanes may be combined, but final ranking must preserve lane scores, source ids, route decisions, and reranker changes in traces.

5. **Runtime lanes are not source of truth.** Native RAG-Anything and graph stores are retrieval/projection lanes. They must bridge back to canonical Postgres chunks and cannot become the only evidence path.

6. **Fallbacks must be bounded and honest.** A fallback search can return partial candidates, but must not full-scan large corpora in request memory or report misleading totals. `ChunkSearchOut.has_more` should reflect the ranked candidate set actually considered, or the response/trace must say the result is bounded.

7. **Public proof requires replayable evidence.** Retrieval claims need static fixtures, valid proof packet artifacts, claim registry entries, redaction status, source paths, limitations, and screenshot signoff when screenshots are used.

Current implementation status:

- Domain-aware routing is implemented through domain classification, executable
  profiles, lexical adapters, route input, materialization hints, and lane
  planner decisions.
- Layout-aware retrieval is implemented through canonical source location,
  layout group, layout role, reading order, block index, native bridge metadata,
  and `LayoutNeighborService`.
- Context-aware retrieval is implemented through parent/previous/next metadata,
  reading-order windows, graph-seeded hydration, `ContextWindowService`, and
  `ContextAssemblyService`.
- Static proof for this architecture lives under
  `docs/benchmarks/ragstudio-oss-proof-v1/` as
  `RAGSTUDIO-RETRIEVAL-ARCHITECTURE`. Treat production corpus quality as a
  separate eval question, not as proven by the static packet.

## Three-Pillar Retrieval Architecture

Use these pillars as the preferred architecture for chunk search, query
planning, candidate generation, fusion, reranking, graph expansion, and context
assembly. Treat them as review criteria when deciding whether a retrieval change
is good enough.

### 1. Domain-Aware Ingestion And Retrieval

Target behavior:

- Domain metadata resolves to an executable retrieval contract: profile id,
  reference schema, expected scripts/languages, query expansion adapter,
  tokenizer/normalizer, quality policy, and materialization policy.
- Query expansion is profile-driven and traceable. Arabic religious expansion is
  one adapter; other domains should be able to supply legal/policy references,
  technical synonyms, financial terms, medical aliases, code identifiers, or
  multilingual/code-mixed mappings without editing core orchestration.
- Exact reference and exact script retrieval stay canonical-first. Lexical,
  vector, graph, runtime, and reranker lanes may help, but blocked or
  provenance-only chunks must not re-enter through secondary lanes.
- Candidate traces should answer: which domain/profile was resolved, which
  expansion rules ran, which lanes were allowed or skipped, which policy allowed
  this chunk, and which quality flags affected ranking or assembly.

Audit prompts:

- Is this retrieval path using a hardcoded domain family where a profile or
  contract should decide?
- Does every candidate preserve `domain_metadata`, `reference_metadata`,
  canonical chunk identity, retrieval pass, and `quality_action_policy`?
- Are language/token rules domain-specific enough for the query and corpus?
- Can a chunk with `index_vector=false`, `project_graph=false`, or blocked exact
  retrieval still leak into final evidence?

### 2. Layout-Aware Ingestion And Retrieval

Target behavior:

- Retrieved chunks should retain layout semantics from canonical evidence:
  `content_type`, page/page range, bbox when available, block type, reading
  order, table/figure/caption relationships, preview refs, and
  `provenance.blocks`.
- Vector and native runtime lanes must hydrate back to canonical chunks before
  fusion whenever possible. If a native lane only returns flat text and page id,
  traces should mark the limitation and avoid treating that snippet as the sole
  source of truth.
- Query-time retrieval should be able to expand from a layout hit to nearby
  evidence: same canonical reference, same page, same table/caption, same figure,
  nearby bbox, previous/next visual block, or graph relationship.
- Layout boosts should be explicit and measurable. Static boosts are acceptable
  only when their inputs and score contribution are in the trace.

Audit prompts:

- Does this query path use `source_location`, `content_type`, preview/crop refs,
  and `provenance.blocks`, or only raw text?
- Are layout candidates flattened before reranking/context assembly without
  breadcrumbs or neighborhood recovery?
- Does graph expansion or metadata retrieval include spatial/layout neighbors
  when they are necessary to understand the answer?
- Are layout thresholds or boost constants covered by focused tests for
  multi-column, RTL, tables, captions, and page-boundary cases?

### 3. Context-Aware Ingestion And Retrieval

Target behavior:

- Each candidate should carry enough parent context to be meaningful:
  document/title when safe, section/header chain, canonical reference, page
  range, sibling/previous/next relationships, and graph path when available.
- Embedding and vector retrieval should avoid isolated leaf chunks. Prefer safe
  pre-embedding context, parent-window retrieval, late-chunking, or canonical
  hydration plus context-window expansion.
- Fusion should dedupe by canonical identity, preserve all retrieval passes, keep
  parser warnings and quality flags, and add diversity for comparison or broad
  coverage queries.
- Reranking should operate on a bounded, canonical candidate set and record
  before/after ranks, scores, provider/model, timeout/fallback, and degraded
  status. If redundancy is high, prefer MMR/diversity selection or explicit
  duplicate suppression before final context.
- Context assembly should inject concise breadcrumbs, preserve direct evidence,
  include necessary neighbors within budget, and record dropped/truncated
  candidates with reasons.

Audit prompts:

- Would this chunk still make sense if read alone by the answer model?
- Are parent headers, canonical references, or graph paths available in the
  prompt or only hidden in metadata?
- Are vector/runtime hits able to seed graph or context neighborhood expansion
  after canonical hydration?
- Does final context explain why evidence was included, dropped, truncated,
  reranked, or blocked?

## Starting Map

Read only the paths needed for the current task:

- Chunk API/schema: `backend/src/ragstudio/api/routes/chunks.py`, `backend/src/ragstudio/schemas/chunks.py`
- Chunk search: `backend/src/ragstudio/services/chunk_service.py`, `backend/src/ragstudio/services/chunk_lexical_search_repository.py`, `backend/src/ragstudio/services/hybrid_chunk_search.py`
- Metadata/reference retrieval: `backend/src/ragstudio/services/metadata_retrieval_service.py`, `backend/src/ragstudio/services/reference_metadata.py`
- Query orchestration: `backend/src/ragstudio/services/query_service.py`, `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Route planning and contracts: `backend/src/ragstudio/services/retrieval_route_planner.py`, `backend/src/ragstudio/services/pipeline_architecture.py`, `backend/src/ragstudio/services/evidence_unit_contract.py`
- Fusion/traces: `backend/src/ragstudio/services/retrieval_fusion.py`, `backend/src/ragstudio/services/retrieval_evidence.py`, `backend/src/ragstudio/services/retrieval_observability.py`, `backend/src/ragstudio/services/retrieval_metrics.py`
- Reranking: `backend/src/ragstudio/services/reranker_service.py`, `backend/src/ragstudio/services/llm_reranker_service.py`
- Runtime lane: `backend/src/ragstudio/services/native_raganything_adapter.py`, `backend/src/ragstudio/services/native_storage_config.py`, `backend/src/ragstudio/services/runtime_factory.py`
- Graph lane: `backend/src/ragstudio/services/graph_expansion_service.py`, `backend/src/ragstudio/services/graph_projection_runner.py`, `backend/src/ragstudio/services/graph_materialization_service.py`
- Query UI traces: `frontend/src/features/query/query-page.tsx`, `frontend/src/features/query/query-pathway-viewer.tsx`
- Chunk UI: `frontend/src/features/chunks/chunk-inspector.tsx`

## Audit Workflow

1. **Classify the request.** Use one stage: materialization policy, retrieval planner, candidate generation, fusion/rerank, context assembly, graph expansion, runtime lane, or trace/UI display.

2. **Collect evidence before recommending changes.** Prefer one of: API response body, `Run.sources`, `Run.chunk_traces`, `Run.reranker_traces`, `Run.timings`, `Run.query_config`, graph projection state, chunk metadata, `quality_action_policy`, or a focused test.

3. **Trace why a candidate appeared or disappeared.** Check document filters, route decision, lexical/reference prefilter, vector/materialization policy, graph readiness, runtime availability, reranker status, and final trace serialization.

4. **Label the failure class.** Use: `bug`, `intentional-gate`, `observability-gap`, `stale-state`, `configuration-gap`, `public-proof-gap`, or `test-gap`.

5. **Choose the smallest defensible change.** Prefer service-level tests and trace-preserving changes before broad ranking rewrites.

## Decision Rules

- If chunk search falls back to request-memory full scans, bound it first. Do not jump straight to a full vector/FTS redesign.
- If a result is missing, inspect `quality_action_policy` before relaxing search/ranking logic.
- If ranking changes, assert final order and trace details together.
- If RRF or hybrid DB ranking is proposed, require eval cases covering exact reference lookup, conversational query terms, Arabic text, document filters, quality-blocked chunks, reranker changes, and graph/runtime degradation.
- If a graph candidate is missing, verify projection readiness and staleness before changing graph expansion.
- If native runtime results differ from canonical retrieval, preserve bridge ids and report the discrepancy in traces.
- If a UI trace looks wrong, confirm the backend trace payload first; do not paper over missing backend evidence with frontend copy.
- If public launch claims depend on retrieval behavior, validate `scripts/proof.sh --strict --json` and update proof packet limitations honestly.

## Preferred Architecture For Search And Query

Use this target model for new work and reviews:

1. Query request enters with explicit document/profile filters and body-level pagination for chunk search.
2. Route planner derives allowed lanes from query intent, domain/reference semantics, runtime health, graph readiness, and materialization policy.
3. Candidate generation uses bounded, indexed queries:
   - exact reference and preview refs first,
   - metadata/reference filters next,
   - language-aware lexical search with trigram/token support,
   - vector lane only for chunks allowed by policy,
   - graph lane only from ready, scoped projections,
   - native runtime lane only as an explainable bridge back to canonical chunks.
4. Candidate fusion deduplicates by canonical chunk id, keeps per-lane ranks/scores, and records why each lane was allowed or skipped.
5. Reranker receives only a bounded candidate set and records before/after rank, provider/model, timeout/fallback, and failure reason.
6. Context assembly uses canonical evidence units, not raw runtime snippets, unless the runtime snippet is explicitly bridged and marked.
7. Response traces expose enough data for an operator to answer: why this chunk, why this rank, why this lane, and why not the others.

## Validation Guide

Select the narrowest useful command:

- Chunk search: `docker compose run --rm backend python -m pytest backend/tests/test_chunks.py backend/tests/test_chunk_lexical_search_repository.py backend/tests/test_chunk_service_arabic_search.py -q`
- Query/retrieval: `docker compose run --rm backend python -m pytest backend/tests/test_retrieval_orchestrator.py backend/tests/test_runtime_query_service.py backend/tests/test_query_runs.py -q`
- Route/fusion metrics: `docker compose run --rm backend python -m pytest backend/tests/test_retrieval_route_planner.py backend/tests/test_rag_retrieval_fusion.py backend/tests/test_retrieval_metrics.py -q`
- Three-pillar architecture: `uv run pytest backend/tests/test_domain_classifier.py backend/tests/test_domain_query_expansion_service.py backend/tests/test_domain_profile_registry.py backend/tests/test_retrieval_route_input.py backend/tests/test_retrieval_route_planner.py backend/tests/test_layout_neighbor_service.py backend/tests/test_context_window_service.py backend/tests/test_context_assembly_service.py backend/tests/test_retrieval_orchestrator.py backend/tests/test_vector_retrieval_service.py backend/tests/test_vector_candidate_repository.py backend/tests/test_native_raganything_adapter.py -q`
- Reranker: `docker compose run --rm backend python -m pytest backend/tests/test_reranker_service.py backend/tests/test_llm_reranker_service.py -q`
- Graph expansion: `docker compose run --rm backend python -m pytest backend/tests/test_graph_expansion_service.py backend/tests/test_graph_materialization_service.py -q`
- Query/chunk UI: run the focused Vitest file from `frontend/`, then build only if behavior changed.
- Public proof: `./scripts/proof.sh --strict --json`

If Docker, Postgres, Neo4j, npm, or runtime services are unavailable, report the blocked validation and name the exact command that should be run next.

## Audit Response Format

Use this compact format for reviews:

```text
Finding: <one-line status>
Stage: <materialization policy | retrieval planner | candidate generation | fusion/rerank | context assembly | graph expansion | runtime lane | trace/UI>
Class: <bug | intentional-gate | observability-gap | stale-state | configuration-gap | public-proof-gap | test-gap>
Evidence:
- <file, test, payload, trace, artifact, or DB field>
Impact:
- <why this matters for retrieval correctness, operator trust, or public proof>
Recommendation:
- <smallest defensible fix or next check>
Validation:
- <focused command or reason validation is blocked>
```

Order multiple findings by risk to retrieval correctness, public safety, and developer trust.
