---
name: rag-pipeline-auditor
description: >-
  Audit, debug, and improve Ragstudio's end-to-end RAG evidence pipeline across
  parsing, canonical chunking, quality gates, indexing, retrieval, reranking,
  graph projection, proof packets, and trace UI. Use when a task involves RAG
  correctness, retrieval quality, document evidence, public claims, or pipeline
  regressions in this repository.
---

# Ragstudio Pipeline Auditor

## Purpose

Use this skill to make Ragstudio changes evidence-first. Ragstudio is not a
generic chat-over-documents app: it is a local RAG data-quality workbench whose
main promise is that failures before retrieval are visible, traceable, and
gateable before bad evidence reaches answers.

Your job when using this skill is to trace behavior from user-visible symptom to
source code, persisted state, raw artifact, public-safe proof evidence, and a
focused fix or recommendation. Do not treat final answer quality as the only
signal. In Ragstudio, parser warnings, canonical chunk assembly, layout repair
diagnostics, quality action policy, graph projection state, retrieval route
plans, reranker traces, and proof packet validity are first-class evidence.

## Use This Skill When

- Debugging upload, parsing, indexing, chunk, graph, query, reranker, or runtime
  behavior.
- Reviewing a proposed RAG architecture change.
- Improving retrieval quality, query traces, graph projection, or materialization
  gates.
- Adding or changing proof packet exports, public claim evidence, screenshots, or
  replay validation.
- Investigating whether a missing chunk, failed graph edge, or poor answer is a
  real bug, an intentional quality gate, stale projection, unavailable runtime, or
  unsafe evidence.
- Making frontend changes that display pipeline status, parser warnings,
  document evidence, retrieval traces, or public proof results.

## Non-Negotiable Rules

- Ground every conclusion in repository files, tests, runtime records, or public
  proof artifacts. If evidence is missing, say exactly what is missing.
- Preserve the source-of-truth boundary: Ragstudio exports proof packets; the
  public site imports and renders them.
- Do not claim launch readiness from a passing UI alone. Public claims require a
  valid proof packet, redaction pass, claim registry entry, source paths, raw
  artifacts, and limitations.
- Do not leak or normalize private evidence. Public artifacts must not contain API
  keys, access tokens, private hosts, LAN IPs, local absolute paths, unpublished
  model hosts, private document content, or unapproved screenshots.
- Do not bypass quality gates to make retrieval look better. If a gate blocks
  vector indexing or graph projection, inspect the warning and policy first.
- Do not assume standard RAG behavior. Ragstudio uses MinerU strict parsing,
  layout-aware chunking, metadata policies, pgvector, lexical search, optional
  native RAG-Anything, optional reranking, and Neo4j as a rebuildable projection.
- Treat RAG-Anything as a runtime/retrieval lane, not the canonical source of
  truth. Canonical Ragstudio evidence in Postgres must remain the bridge for
  fusion, context assembly, graph projection, proof export, and public claims.
- Keep fixes scoped. Pipeline behavior often spans schemas, services, routes,
  tests, and frontend traces; update the full contract only where the task needs
  it.
- If a change touches an API schema, update backend schemas, route/client
  behavior, generated frontend bindings, and focused tests together. Do not let
  frontend query parameters drift from backend request-body contracts.

## First Pass Checklist

Before changing code or making a recommendation, collect the smallest useful
context:

1. Symptom: document id, job id, chunk id, query/run id, claim id, screenshot, or
   exact UI behavior.
2. Stage: upload, parse, layout normalization, domain resolution, canonical
   evidence, repair/quality, materialization policy, persistence, vector
   materialization, graph projection, query planning, retrieval, fusion, rerank,
   context assembly, proof export, or frontend display.
3. Evidence: relevant DB row fields, job logs/result payload, chunk metadata,
   run traces, graph projection record, proof packet file, or failing test.
4. Boundary: live runtime issue, static fixture proof issue, UI display issue, or
   public launch/claim issue.
5. Safety: whether any artifact, screenshot, log, or endpoint is public-safe.

## Architecture Map

Use these repository paths as the starting map. Verify current names with file
search when in doubt.

### Ten-Layer Evidence Pipeline Contract

- Contract: `backend/src/ragstudio/services/pipeline_architecture.py`
- Domain profiles: `backend/src/ragstudio/services/domain_profile_registry.py`
- Evidence units: `backend/src/ragstudio/services/evidence_unit_contract.py`
- Retrieval route planner:
  `backend/src/ragstudio/services/retrieval_route_planner.py`
- Tests: `backend/tests/test_pipeline_architecture.py`,
  `backend/tests/test_domain_profile_registry.py`,
  `backend/tests/test_evidence_unit_contract.py`,
  `backend/tests/test_retrieval_route_planner.py`

Audit focus:

- Map every architecture change to one of the ten layers: parse, layout
  normalization, domain resolver, canonical evidence, repair and quality,
  materialization policy, retrieval planner, fusion and rerank, context
  assembly, proof trace.
- Distinguish shipped runtime behavior from architecture scaffolding. A contract
  module with tests is useful, but do not claim live domain-aware retrieval until
  the planner/profile/evidence contract is wired into the production query or
  indexing path being discussed.
- Preserve the bridge identity for every RAG-Anything lane handoff:
  `document_id`, canonical `chunk_id` when available, `runtime_source_id`,
  evidence unit type, canonical reference, page/block provenance, quality action
  policy, and materialization policy.

### Three-Pillar RAG Architecture Target

Use this model when auditing or improving Ragstudio's evidence pipeline. The
goal is not "more vectors"; the goal is to preserve domain, layout, and context
semantics from ingestion through retrieval, reranking, context assembly, and
proof export.

Current implementation status:

- Domain-aware ingestion and retrieval is implemented through
  `DomainClassifier`, `DomainProfileRegistry`, `DomainLexicalRegistry`,
  `retrieval_route_input.py`, `retrieval_route_planner.py`, quality action
  policy, materialization policy, and route/lane traces.
- Layout-aware ingestion and retrieval is implemented through canonical
  `source_location`, layout metadata, native bridge metadata,
  `LayoutNeighborService`, layout-neighbor traces, and context-visible layout
  summaries.
- Context-aware ingestion and retrieval is implemented through evidence
  breadcrumbs, parent/previous/next metadata, `ContextWindowService`,
  graph-seeded canonical hydration, `ContextAssemblyService`, direct-evidence
  preservation, and dropped/truncated evidence reasons.
- Public proof status is backed by
  `RAGSTUDIO-RETRIEVAL-ARCHITECTURE` in
  `docs/benchmarks/ragstudio-oss-proof-v1/`, validated with static synthetic
  fixtures. It proves trace propagation, not production retrieval quality over
  customer corpora.

#### 1. Domain-Aware Ingestion And Retrieval

Target contract:

- Domain profiles should be executable contracts, not labels. A profile should
  define reference schemas, expected scripts/languages, canonical unit rules,
  parser normalization rules, quality policy, retrieval preferences, graph
  projection hints, and public-proof limitations.
- Domain query expansion should be pluggable by domain/profile. Arabic
  religious expansion is one adapter, not the architecture. Legal, policy,
  medical, financial, code, tabular, and multilingual domains need their own
  lexical adapters, synonym maps, reference parsers, tokenizers, and
  cross-lingual/code-mixed rules when supported.
- Domain metadata must compile before durable indexing. Raw AI/vision metadata
  is descriptive until `domain_metadata_contract_compiler.py` turns it into a
  validated contract with named regex groups and materialization policy.
- Quality gates must travel with every evidence unit. `quality_action_policy`
  decides exact search, vector materialization, graph projection, runtime lane
  eligibility, and context assembly inclusion.
- Retrieval should expose domain decisions in traces: resolved domain profile,
  query expansion adapter, reference parser, blocked lanes, exact-match policy,
  and whether a result came from canonical, lexical, vector, graph, or runtime
  evidence.

Audit checks:

- Is the domain family hardcoded in the path being changed, or resolved through a
  profile/registry/contract?
- Does the change preserve `domain_metadata`, `reference_metadata`,
  `canonical_reference_unit`, and `quality_action_policy` in persisted chunks
  and response traces?
- Are query expansions language/domain-specific and traceable, or silent
  heuristic rewrites?
- Can a quality-blocked chunk still enter vector, graph, native runtime, rerank,
  or final context through a bypass?
- Are specialized tokenization needs explicit for the domain, especially Arabic,
  references, tables, legal citations, code, and numeric/financial content?

#### 2. Layout-Aware Ingestion And Retrieval

Target contract:

- Parsing should preserve page/block provenance: page number, block id/type,
  reading order, bbox, source artifact reference, preview/crop reference, and
  parser warning codes.
- Chunking should assemble canonical units from visual order and semantic
  structure. Reading order, columns, tables, captions, figures, equations,
  headers/footers, and reference headers must be distinguished instead of
  flattened blindly.
- Layout repair should be deterministic and local first. It may downgrade noise
  to provenance-only, recover same-unit text, or request targeted vision
  recovery, but it must not fabricate missing content or provenance.
- Vector and runtime materialization should either carry layout metadata into
  retrievable rows or explicitly bridge retrieved rows back to canonical
  Postgres chunks before fusion.
- Query-time retrieval should support layout-aware expansion when metadata is
  present: same page, same reference unit, table/caption neighborhood, figure
  text, bbox proximity, and graph relationships. If this is not implemented, the
  trace should make the limitation visible.

Audit checks:

- Does the path preserve `source_location`, `preview_ref`, `content_type`,
  `provenance.blocks`, bbox, page range, and parser warning metadata?
- Are hardcoded layout thresholds appropriate for the domain, or should they be
  profile-configured and covered by reading-order tests?
- Are textless page artifacts treated as provenance/noise while text-bearing
  disallowed blocks remain recoverable or blocked according to policy?
- Does native RAG-Anything receive only flat text/page ids? If so, is there a
  canonical hydration step before fusion and context assembly?
- Can query-time retrieval pull neighboring layout evidence when a caption,
  table cell, figure block, or reference header is retrieved?

#### 3. Context-Aware Ingestion And Retrieval

Target contract:

- Every answerable chunk should know its parent context: document title when
  public-safe, section/header chain, canonical reference, page range, sibling
  links, previous/next unit relationships, and graph relationships.
- Embedding text should include enough safe parent context to make standalone
  chunks semantically meaningful, or the system should use late-chunking or an
  equivalent parent-window embedding strategy when available.
- Retrieval should be seedable across channels. Direct canonical/metadata hits
  can seed graph expansion; vector hits should be able to seed canonical
  hydration and graph/context neighborhood expansion when bridge ids exist.
- Fusion should dedupe by canonical identity, preserve lane scores and reasons,
  and keep diversity across documents/sections when the query asks for
  comparison, coverage, or synthesis.
- Context assembly should not be a blind text join. It should inject concise
  breadcrumbs, preserve direct evidence, include needed neighbors within budget,
  mark dropped/truncated evidence, and keep quality/reranker degradation visible.

Audit checks:

- Does the candidate carry enough parent context for the LLM to understand what
  the chunk refers to?
- Are breadcrumbs or section/reference labels injected at context assembly or
  answer-prompt time?
- Are duplicate chunks merged while preserving all retrieval passes and parser
  warning metadata?
- Can vector/runtime candidates hydrate to canonical chunks before graph
  expansion, reranking, and final context?
- Does reranking improve relevance without hiding redundancy, timeout, fallback,
  degraded status, or provider/model details?

### Ingestion And Jobs

- Routes: `backend/src/ragstudio/api/routes/documents.py`,
  `backend/src/ragstudio/api/routes/chunks.py`,
  `backend/src/ragstudio/api/routes/jobs.py`
- Job execution: `backend/src/ragstudio/workers/index_worker.py`,
  `backend/src/ragstudio/services/index_job_runner.py`,
  `backend/src/ragstudio/services/job_queue_service.py`
- Job progress: `backend/src/ragstudio/services/index_progress.py`
- Durable indexing: `docs/architecture/durable-rag-indexing.md`
- Core tests: `backend/tests/test_documents.py`,
  `backend/tests/test_index_lifecycle_service.py`,
  `backend/tests/test_index_worker_recovery.py`,
  `backend/tests/test_index_progress.py`,
  `backend/tests/test_jobs.py`

Audit focus:

- Upload and reindex should create durable jobs, not long blocking request work.
- Worker leases, heartbeats, attempts, and recovery actions must explain stalled
  or resumed indexing.
- Failed jobs should preserve actionable user-visible logs, not only backend
  exceptions.
- Real-time progress uses the jobs SSE endpoint. The backend event contract is
  `job_stage` for stage updates and `job_status` for terminal status; frontend
  subscribers must listen for those names and keep polling as a fallback when
  EventSource is unavailable.

### Parsing And Evidence

- Parser: `backend/src/ragstudio/services/document_parser_service.py`
- Parse evidence: `backend/src/ragstudio/services/document_parse_evidence_service.py`,
  `backend/src/ragstudio/services/document_parse_evidence_exporter.py`
- Schemas/UI: `backend/src/ragstudio/schemas/document_parse_evidence.py`,
  `frontend/src/features/document-evidence/`
- Tests: `backend/tests/test_document_parser_service.py`,
  `backend/tests/test_document_parse_evidence.py`,
  `frontend/tests/document-evidence-page.test.tsx`,
  `frontend/tests/document-evidence-inspector.test.tsx`

Audit focus:

- Confirm parser mode, artifact references, page/block provenance, parser warning
  codes, and document evidence summary.
- Treat missing evidence as a first-order bug when the UI or proof claim depends
  on it.
- For public proof, raw parser artifacts must be synthetic or approved and
  redacted.

### Canonical Chunking

- Chunk splitter: `backend/src/ragstudio/services/chunk_splitter.py`
- Canonical assembly: `backend/src/ragstudio/services/canonical_assembly.py`
- Layout repair: `backend/src/ragstudio/services/layout_auto_repair.py`
- Evidence graph helper: `backend/src/ragstudio/services/evidence_graph.py`
- Persistence: `backend/src/ragstudio/services/chunk_persistence_service.py`
- Search surfaces: `backend/src/ragstudio/services/chunk_service.py`,
  `backend/src/ragstudio/services/hybrid_chunk_search.py`,
  `backend/src/ragstudio/services/chunk_lexical_search_repository.py`
- Tests: `backend/tests/test_chunk_splitter.py`,
  `backend/tests/test_canonical_assembly.py`,
  `backend/tests/test_chunk_persistence_service.py`,
  `backend/tests/test_chunks.py`,
  `backend/tests/test_chunk_service_arabic_search.py`,
  `backend/tests/test_layout_auto_repair.py`

Audit focus:

- Check whether chunks are canonical reference units, parser fragments,
  warning-only/provenance-only records, or regular text chunks.
- Inspect `source_location`, `metadata_json`, `reference_metadata`,
  `canonical_reference_unit`, `parser_warnings`, and `provenance.blocks`.
- Visual reading order and block coordinates matter. Do not rely only on raw
  text order when investigating fragmented or multilingual documents.
- Layout auto-repair is deterministic and local. It may normalize page range
  metadata and attach before/after diagnostics, but it must not invent missing
  text or fabricate provenance.
- If chunk boundaries changed, preserve metadata needed for exact reference
  retrieval and graph projection.
- Chunk search pagination belongs in the `ChunkSearchIn` JSON body (`limit` and
  `offset`), not as query parameters. `ChunkSearchOut.has_more` should reflect
  the ranked candidate total.

### Quality Gates And Materialization

- Metadata contract compiler:
  `backend/src/ragstudio/services/domain_metadata_contract_compiler.py`
- Domain gate: `backend/src/ragstudio/services/domain_metadata_quality_gate.py`
- Chunk gate: `backend/src/ragstudio/services/chunk_quality_gate.py`
- Index gate: `backend/src/ragstudio/services/index_quality_gate.py`
- Vector policy: `backend/src/ragstudio/services/vector_index_policy.py`
- Warning surfacing: `backend/src/ragstudio/services/job_quality_warning_service.py`
- Tests: `backend/tests/test_domain_metadata_quality_gate.py`,
  `backend/tests/test_chunk_quality_gate.py`,
  `backend/tests/test_index_quality_gate.py`,
  `backend/tests/test_vector_index_policy.py`,
  `backend/tests/test_domain_metadata_contract_compiler.py`,
  `backend/tests/test_job_quality_warnings.py`,
  `backend/tests/test_ingestion_retrieval_quality_gate.py`

Audit focus:

- Treat vision/LLM metadata as descriptive until it has been compiled into an
  executable reference contract. Reference-aware chunking must have normalized
  `reference_schema.type`, `domain_structure.primary_anchor.regex` with required
  named groups, and `reference_resolution.build_canonical_units=true` before
  upload or reindex can proceed.
- The compiler belongs before durable job creation; the quality gate belongs in
  upload/reindex validation. Do not let raw vision metadata such as
  `surah:verse` without a regex reach the worker as an indexing contract.
- A missing retrieval candidate may be correct if `quality_action_policy` blocks
  `index_vector`, exact search, graph projection, or materialization.
- Inspect `index_quality_report`, parser warning severity, expected script checks,
  reference completeness, `quality_repair_report`, and document-specific policy.
- Quality is an architecture layer, not a late cleanup step. The repair pass must
  run after canonical evidence assembly and before final materialization policy:
  first attempt local recovery from same-unit provenance, then mark unrepaired
  reference units for targeted vision recovery.
- Do not count pure layout noise as a content failure. Textless headers, footers,
  page numbers, and similar parser artifacts should be downgraded to
  provenance-only/info, while text-bearing disallowed blocks remain recoverable
  or warn/block according to policy.
- Preserve the distinction between answerable chunks, provenance-only chunks, and
  blocked unsafe chunks.
- A fix that hides a warning without repairing the evidence path is not a real
  fix.

### Runtime, Retrieval, Fusion, And Answering

- Query route/schema: `backend/src/ragstudio/api/routes/query.py`,
  `backend/src/ragstudio/schemas/query.py`
- Query orchestration: `backend/src/ragstudio/services/query_service.py`,
  `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Query understanding: `backend/src/ragstudio/services/query_understanding.py`,
  `backend/src/ragstudio/services/query_hypothesis_service.py`,
  `backend/src/ragstudio/services/query_hypothesis_verifier.py`,
  `backend/src/ragstudio/services/domain_query_expansion_service.py`
- Retrieval engines: `backend/src/ragstudio/services/metadata_retrieval_service.py`,
  `backend/src/ragstudio/services/retrieval_fusion.py`,
  `backend/src/ragstudio/services/retrieval_evidence.py`,
  `backend/src/ragstudio/services/retrieval_observability.py`,
  `backend/src/ragstudio/services/retrieval_metrics.py`
- Runtime adapters/profile: `backend/src/ragstudio/services/runtime_factory.py`,
  `backend/src/ragstudio/services/runtime_profile_service.py`,
  `backend/src/ragstudio/services/runtime_health_service.py`,
  `backend/src/ragstudio/services/runtime_policy.py`,
  `backend/src/ragstudio/services/runtime_types.py`,
  `backend/src/ragstudio/services/native_raganything_adapter.py`,
  `backend/src/ragstudio/services/native_storage_config.py`
- Answering: `backend/src/ragstudio/services/runtime_answer_service.py`
- Tests: `backend/tests/test_query_runs.py`,
  `backend/tests/test_retrieval_orchestrator.py`,
  `backend/tests/test_retrieval_observability.py`,
  `backend/tests/test_retrieval_metrics.py`,
  `backend/tests/test_rag_retrieval_fusion.py`,
  `backend/tests/test_query_understanding.py`,
  `backend/tests/test_query_hypothesis_service.py`,
  `backend/tests/test_query_hypothesis_verifier.py`,
  `backend/tests/test_runtime_query_service.py`

Audit focus:

- Separate failure types: no candidates, wrong candidates, stale graph, runtime
  unavailable, reranker disabled, reranker failed, answer synthesis failed, or UI
  trace display missing.
- Confirm selected document filters are carried through every retrieval stage.
- Confirm retrieval lanes start from canonical Postgres evidence and only then
  add lexical, vector, graph, and RAG-Anything runtime lanes according to domain,
  layout, and materialization policy.
- Inspect `Run.sources`, `Run.chunk_traces`, `Run.reranker_traces`,
  `Run.timings`, `Run.query_config`, `Run.error`, and `Run.error_type`.
- Fusion changes must preserve trace explainability. If RRF or candidate ranking
  changes, tests should assert both final ranking and trace details.
- Native RAG-Anything still requires environment variables for parts of the
  third-party LightRAG stack, but Ragstudio must confine that mutation behind
  `scoped_native_storage_env()` and derive values through
  `derive_native_storage_config()`.

### Reranker And External Calls

- Reranker services: `backend/src/ragstudio/services/reranker_service.py`,
  `backend/src/ragstudio/services/llm_reranker_service.py`,
  `backend/src/ragstudio/services/reranker_connection_service.py`
- Settings: `backend/src/ragstudio/services/settings_service.py`,
  `backend/src/ragstudio/schemas/settings.py`,
  `frontend/src/features/settings/settings-page.tsx`
- Tests: `backend/tests/test_reranker_service.py`,
  `backend/tests/test_llm_reranker_service.py`,
  `backend/tests/test_settings.py`,
  `frontend/tests/settings-page.test.tsx`

Audit focus:

- Respect `RAGSTUDIO_ALLOWED_RERANKER_HOSTS` and saved API-key semantics.
- Do not expose real endpoint URLs or tokens in public artifacts or final reports.
- If rerank is enabled, verify whether the final ranking changed and whether the
  trace records enough detail to explain the change.

### Graph Projection And Expansion

- Projection: `backend/src/ragstudio/services/graph_projection_runner.py`,
  `backend/src/ragstudio/services/graph_materialization_service.py`,
  `backend/src/ragstudio/services/graph_workspace.py`
- Expansion: `backend/src/ragstudio/services/graph_expansion_service.py`
- API/UI: `backend/src/ragstudio/api/routes/graph.py`,
  `frontend/src/features/graph/graph-page.tsx`
- Tests: `backend/tests/test_graph_materialization_service.py`,
  `backend/tests/test_graph_expansion_service.py`,
  `backend/tests/test_graph_workspace.py`,
  `backend/tests/test_graph_service.py`,
  `backend/tests/test_optimizer_graph_diagnostics.py`,
  `frontend/tests/graph-page.test.tsx`

Audit focus:

- Neo4j is a rebuildable projection, not the source of truth.
- Query-time graph expansion should run only when the latest projection is ready
  for the relevant document/profile.
- Stale, failed, skipped, or degraded graph states must be visible in traces and
  user-facing diagnostics.
- Graph UI truncation or empty-state behavior must explain whether data is absent,
  stale, filtered, or only partially displayed.
- Fallback relationship-metadata graph reads should be scoped by `document_id`
  when provided and paginated with `limit`/`offset`. Do not scan every chunk when
  the user is inspecting one document.

### Frontend Trace And Operator UX

- Documents: `frontend/src/features/documents/documents-page.tsx`
- Chunks: `frontend/src/features/chunks/chunk-inspector.tsx`
- Query: `frontend/src/features/query/query-page.tsx`,
  `frontend/src/features/query/query-pathway-viewer.tsx`
- Graph: `frontend/src/features/graph/graph-page.tsx`
- Runtime trust: `frontend/src/components/runtime-trust.tsx`
- API client: `frontend/src/api/client.ts`
- Generated API types: `frontend/src/api/generated.ts`
- Tests: `frontend/tests/documents-page.test.tsx`,
  `frontend/tests/chunk-inspector.test.tsx`,
  `frontend/tests/query-page.test.tsx`,
  `frontend/tests/graph-page.test.tsx`,
  `frontend/tests/api-client.test.ts`

Audit focus:

- UI should show status first, then evidence. Avoid hiding parser warnings,
  blocked materialization, graph degradation, or reranker behavior behind vague
  success states.
- Preserve compact operational UX. Ragstudio is a workbench, not a marketing
  surface.
- Every backend trace or warning field that matters to diagnosis should either be
  displayed, summarized, or intentionally excluded with a reason.
- EventSource is an enhancement, not the only status path. If SSE construction
  fails or is unavailable, existing TanStack Query polling must continue to show
  job state.

### Proof Packet And Public Claims

- CLI/replay: `scripts/proof.sh`, `backend/src/ragstudio/proof_packet/`
- Packet root: `docs/benchmarks/ragstudio-oss-proof-v1/`
- Claim registry: `docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.registry.json`
- Claim matrix: `docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.matrix.md`
- Docs: `docs/benchmarks/ragstudio-oss-proof-v1/docs/CLAIMS.md`,
  `docs/benchmarks/ragstudio-oss-proof-v1/docs/REPLAY.md`,
  `docs/benchmarks/ragstudio-oss-proof-v1/docs/REDACTION.md`,
  `docs/benchmarks/ragstudio-oss-proof-v1/docs/LIMITATIONS.md`
- Tests: `backend/tests/test_proof_packet_contract.py`,
  `backend/tests/test_proof_packet_validator.py`,
  `backend/tests/test_sample_pack_contract.py`

Audit focus:

- `./scripts/proof.sh` is the fresh-checkout trust path. It must validate static
  fixtures without Docker, private providers, Postgres, Neo4j, or live backend.
- A `proven` claim needs registry entry, source commit/tag, source code paths,
  public raw artifact paths, explanation, redaction status, and limitations.
- `roadmap` and `disabled` claims are valid public states; do not inflate them to
  `proven`.
- Screenshot evidence requires signoff metadata.

## Investigation Workflow

### 1. Classify The Symptom

Choose the most likely stage and state it explicitly:

- Parse/evidence: missing blocks, wrong text, warning mismatch, unsafe artifact.
- Chunk/canonicalization: fragmented unit, wrong reference, missing provenance,
  language/script mismatch.
- Gate/materialization: blocked vector index, provenance-only chunk, graph blocked,
  warning hidden from UI.
- Index/runtime: job stuck, lease expired, runtime health failing, adapter refused
  scoped query, stale index record, missing `job_stage`/`job_status` event.
- Retrieval/fusion: candidate absent, low rank, wrong rank, trace mismatch, filter
  dropped.
- Rerank/answer: reranker unavailable, reranker changed order unexpectedly, answer
  ignores source, failed citation grounding.
- Graph: projection stale/failed, graph expansion skipped, Neo4j unavailable, UI
  truncation.
- Proof/public: invalid packet, unsafe artifact, claim lacks evidence, screenshot
  not signed off.

### 2. Trace Backward From The Visible Failure

Use this order unless the task clearly starts elsewhere:

1. Frontend/API response or proof validator output.
2. Persisted model fields and trace payloads.
3. Service that produced the trace or state.
4. Tests covering the service contract.
5. Raw/static artifact that should support the claim.

Avoid jumping directly to model or prompt changes before proving the evidence
path is intact.

### 3. Decide The Failure Class

Label the finding as one of:

- `bug`: behavior violates the intended contract.
- `intentional-gate`: system correctly blocked unsafe or low-quality evidence.
- `observability-gap`: behavior may be correct but evidence is hidden or unclear.
- `stale-state`: persisted job/index/graph state is old, superseded, or pending.
- `configuration-gap`: runtime/provider/storage settings are missing or invalid.
- `public-proof-gap`: private/live evidence exists, but public replayable evidence
  is missing or unsafe.
- `test-gap`: behavior exists but is not protected by focused regression coverage.

### 4. Make The Smallest Defensible Improvement

Prefer fixes that improve traceability and correctness together:

- Preserve warnings and blocked policies in payloads.
- Add or repair a focused service-level test before broad UI work.
- Add UI copy only when it exposes actual state, not when it masks ambiguity.
- Use static fixtures for public proof changes.
- Update schemas, generated/types expectations, API client behavior, and tests
  together when a contract changes.
- If backend adds JSON-body fields such as chunk `offset`, verify route tests and
  generated frontend types before adding client helpers.

## Improvement Heuristics

- Prefer more explicit pipeline states over generic success/failure labels.
- Prefer deterministic synthetic fixtures for public proofs unless a real public
  corpus has an explicit publishability review.
- Prefer pure validation logic and static replay for first-time contributor trust.
- Prefer stored trace fields over parsing logs when a user-visible diagnostic must
  be stable.
- Prefer narrowing retrieval candidates by document/profile filters before adding
  heavier reranking.
- Prefer making quality gates explain themselves before relaxing thresholds.
- Prefer service tests for backend contracts and frontend tests for visible trace
  regressions.
- Prefer `scripts/proof.sh --strict --json` for proof packet automation checks.

## Validation Guide

Select validation based on changed surface:

- Parser/chunk/gate changes:
  `docker compose run --rm backend python -m pytest backend/tests/test_document_parser_service.py backend/tests/test_chunk_splitter.py backend/tests/test_domain_metadata_quality_gate.py -q`
- Indexing/job changes:
  `docker compose run --rm backend python -m pytest backend/tests/test_index_lifecycle_service.py backend/tests/test_index_worker_recovery.py backend/tests/test_job_quality_warnings.py -q`
- Retrieval/query changes:
  `docker compose run --rm backend python -m pytest backend/tests/test_retrieval_orchestrator.py backend/tests/test_runtime_query_service.py backend/tests/test_query_runs.py -q`
- Three-pillar architecture changes:
  `uv run pytest backend/tests/test_domain_classifier.py backend/tests/test_domain_query_expansion_service.py backend/tests/test_domain_profile_registry.py backend/tests/test_retrieval_route_input.py backend/tests/test_retrieval_route_planner.py backend/tests/test_layout_neighbor_service.py backend/tests/test_context_window_service.py backend/tests/test_context_assembly_service.py backend/tests/test_retrieval_orchestrator.py backend/tests/test_vector_retrieval_service.py backend/tests/test_vector_candidate_repository.py backend/tests/test_native_raganything_adapter.py -q`
- Reranker/settings changes:
  `docker compose run --rm backend python -m pytest backend/tests/test_reranker_service.py backend/tests/test_llm_reranker_service.py backend/tests/test_settings.py -q`
- Graph changes:
  `docker compose run --rm backend python -m pytest backend/tests/test_graph_materialization_service.py backend/tests/test_graph_expansion_service.py -q`
- Proof packet changes:
  `./scripts/proof.sh --strict --json`
  and relevant proof tests.
- Frontend trace/UI changes:
  run the focused Vitest file from `frontend/`, then build if behavior changed.
- Cross-cutting changes:
  use `./scripts/test-all.sh` when Docker and time are available.

If Docker, Postgres, Neo4j, npm, or the runtime stack is unavailable, report the
blocked validation clearly and include the focused tests that should be run next.

## Response Format For Audits

When returning an audit or recommendation, use this compact structure:

```text
Finding: <one-line issue or status>
Stage: <pipeline stage>
Class: <bug | intentional-gate | observability-gap | stale-state | configuration-gap | public-proof-gap | test-gap>
Evidence:
- <file/path, row field, test, artifact, or trace>
Impact:
- <why it matters for RAG correctness or public proof>
Recommendation:
- <smallest defensible fix or next check>
Validation:
- <focused command or reason validation is blocked>
```

For multiple findings, order them by risk to RAG correctness, public safety, and
developer trust.

## Common Mistakes To Avoid

- Treating an empty answer as only an LLM issue when retrieval candidates, quality
  gates, or graph state may be the real cause.
- Assuming a chunk was lost before checking `quality_action_policy`.
- Treating Neo4j as authoritative when canonical chunks in Postgres are the
  source of truth.
- Adding public claims from local screenshots, private logs, or live-only data.
- Fixing frontend display without preserving backend trace semantics.
- Adding generic RAG advice that conflicts with Ragstudio's local-first,
  proof-packet, quality-gated architecture.
- Running frontend commands from the repo root; frontend commands belong in
  `frontend/`.
- Forgetting that generated API bindings may need regeneration after schema
  changes.

## Escalation

Stop and ask for missing inputs only when the next step cannot be inferred from
repo state:

- No document/job/query/run/claim identifier is available and multiple unrelated
  paths could be affected.
- Required live DB/runtime evidence is inaccessible and static tests cannot answer
  the question.
- The requested public artifact may contain private or unapproved content.

When blocked, return the partial trace, the exact missing evidence, and the next
command or UI action that would unblock the audit.
