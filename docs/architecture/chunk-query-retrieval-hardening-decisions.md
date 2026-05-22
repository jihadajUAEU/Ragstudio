# Chunk Query Retrieval Hardening Decisions

Date: 2026-05-20

Scope: Tasks 3-8 from `docs/superpowers/plans/2026-05-20-chunk-query-retrieval-hardening-8-items.md`.

This record covers architecture decisions only. It does not change runtime code. The decisions preserve Ragstudio's pipeline contract: canonical Postgres chunks remain the source of truth, quality and materialization policy gate retrieval, native RAG-Anything stays a retrieval lane, and public claims require replayable proof evidence.

## Task 3: Layout Diagnostics

Decision: add a future diagnostics-only pass before expanding layout repair.

Recommended first diagnostic set:

- `missing_coordinates`: a text-bearing block has no coordinate metadata where the parser artifact should provide coordinates.
- `invalid_coordinate_shape`: coordinate metadata is present but not a supported list/object shape or contains non-numeric values.
- `impossible_page_span`: page range metadata is missing, non-positive, or spans backward after the current local repair rules run.
- `overlapping_blocks`: blocks on the same page overlap enough to make reading order ambiguous.
- `reading_order_gap`: adjacent parser blocks have a suspicious page/block/order discontinuity that may explain fragmented evidence.

Guardrail: the first pass must be diagnostics-only. It must not fabricate coordinates, missing blocks, missing text, or provenance. If a later repair pass is added, it must be separately gated by tests proving the repaired value came from same-unit parser provenance or another approved public-safe artifact.

Evidence:

- `backend/src/ragstudio/services/layout_auto_repair.py` currently repairs only page metadata: single page to page range, missing page start/end fill, inverted page range reorder, and redundant page removal.
- `backend/tests/test_layout_auto_repair.py` asserts repaired chunks preserve existing text, runtime source id, preview ref, and metadata while only changing supported source-location fields.
- `backend/tests/test_proof_packet_contract.py` requires public packet fixtures and artifacts to expose parser warning, quality action policy, chunk trace, reranker trace, graph projection state, and redaction status shapes.
- `backend/tests/test_proof_packet_validator.py` enforces strict packet validation, redaction leak detection, path traversal rejection, screenshot signoff, and stale source commit checks.

Rationale: layout diagnostics are useful for explaining chunk fragmentation and retrieval misses, but the current implementation deliberately avoids inventing content or provenance. A diagnostic layer can improve operator visibility without changing evidence semantics.

Validation gate for future work:

- `python -m pytest backend/tests/test_layout_auto_repair.py backend/tests/test_proof_packet_contract.py backend/tests/test_proof_packet_validator.py -q`

## Task 4: Native Storage Env Mutation

Decision: keep `scoped_native_storage_env()` as intentional containment until a direct third-party storage configuration path is verified against the installed RAG-Anything and LightRAG stack.

Current boundary:

- `derive_native_storage_config()` derives Postgres, workspace, and Neo4j values from Ragstudio settings and runtime profile.
- `scoped_native_storage_env()` applies only the required third-party environment variables inside an async context, serializes access with `NATIVE_STORAGE_ENV_LOCK`, and restores previous values afterward.
- `NativeRAGAnythingAdapter` confines indexing, preparsed insertion, scoped retrieval preflight, native query, delete, and storage initialization behind `_storage_env()`.

Future replacement condition: replace environment mutation only when direct constructor/configuration arguments are verified for the concrete RAG-Anything/LightRAG storage classes used by Ragstudio, including Postgres KV, pgvector, Neo4j, doc-status storage, and workspace selection. The replacement must preserve scoped document filtering, cache disabling for scoped native queries, leak detection, and test coverage for restore/containment behavior.

Evidence:

- `backend/src/ragstudio/services/native_storage_config.py` contains the derivation, lock, scoped environment updates, and restoration behavior.
- `backend/src/ragstudio/services/native_raganything_adapter.py` passes LightRAG storage names through `lightrag_kwargs` but still wraps third-party calls in `_storage_env()`, indicating env mutation is the current storage handoff boundary.
- `backend/src/ragstudio/services/native_raganything_adapter.py` also has scoped storage verification through `ScopedVectorStorageProxy`, direct `query_by_full_doc_ids` support when available, pgvector fallback, and native scope leak checks.
- `backend/tests/test_native_storage_config.py` proves derived database values are decoded correctly, values are visible from a worker thread while scoped, the lock is held, empty Neo4j values are removed, and previous environment values are restored.

Rationale: global environment mutation is not ideal, but it is currently contained, serialized, and tested. Replacing it without verifying all third-party storage entry points risks breaking native runtime indexing and scoped retrieval.

Validation gate for future work:

- `python -m pytest backend/tests/test_native_storage_config.py backend/tests/test_runtime_query_service.py -q`

## Task 5: Full DB-Level Hybrid RRF

Decision: defer a full SQL vector plus FTS plus RRF implementation until retrieval eval coverage exists.

Required eval gate before implementation:

- exact reference lookup
- conversational query terms
- Arabic text and normalized Arabic tokens
- selected document filters
- quality-blocked and provenance-only chunks
- reranker before/after rank changes
- graph projection degraded or unavailable
- native runtime lane degraded or unavailable

Evidence:

- `backend/src/ragstudio/services/retrieval_fusion.py` already implements explainable reciprocal-rank style fusion over bounded ranked candidate lists and preserves retrieval passes in candidate metadata.
- `backend/tests/test_rag_retrieval_fusion.py` covers exact Arabic and exact reference priority over broad semantic matches.
- `backend/tests/test_retrieval_orchestrator.py` covers domain-aware fusion, graph neighbor behavior, metadata/lexical boosts, multi-document ordering, duplicate merging, native parser warning hydration, and final fusion trace emission.
- `backend/src/ragstudio/services/chunk_lexical_search_repository.py` already provides indexed reference, Arabic token, and English lexical prefilters used before broad fallback.

Rationale: moving fusion into a single DB-level hybrid query would change ranking semantics, trace detail, and lane explainability. The current system has targeted fusion behavior and trace tests; a broader SQL rewrite needs side-by-side evals before it can replace or subsume those contracts.

Validation gate for future work:

- `python -m pytest backend/tests/test_retrieval_orchestrator.py backend/tests/test_rag_retrieval_fusion.py backend/tests/test_retrieval_route_planner.py backend/tests/test_retrieval_metrics.py -q`

## Task 6: Chunk Self-Links

Decision: defer `previous_chunk_id` and `next_chunk_id` columns until a concrete graph, query, or UI traversal requires stable persisted adjacency.

2026-05-22 update: query-time context awareness now consumes logical adjacency
from chunk metadata when available. `ContextWindowService` can use
`parent_chunk_id`, `previous_chunk_id`, `next_chunk_id`, `reading_order`, and
`block_index` carried in `metadata_json` to recover bounded neighbors during
retrieval. This does not change the physical-column decision below: durable DB
columns are still deferred until a consumer needs migration-backed adjacency
state instead of metadata-derived or order-derived context.

Future acceptance criteria:

- schema migration and startup compatibility plan for existing chunks
- deterministic backfill rules across document order, page ranges, reference units, and provenance-only chunks
- persistence tests proving links are created, updated, and removed correctly during reindex
- graph tests proving adjacency is consumed only when projection state and materialization policy allow it
- query or UI consumer evidence showing why dynamic ordering by document/source location is insufficient

Evidence:

- `backend/src/ragstudio/db/models.py` defines `Chunk` without adjacency columns and already indexes document id, preview ref, English trigram text, Arabic trigram text, and Arabic tokens.
- `backend/src/ragstudio/services/graph_projection_runner.py` and `backend/src/ragstudio/services/graph_materialization_service.py` read `quality_action_policy` before graph projection/materialization, so adjacency must not bypass graph policy.
- `backend/src/ragstudio/services/retrieval_evidence.py` and `backend/src/ragstudio/services/context_assembly_service.py` assemble retrieval evidence from canonical chunk fields and metadata rather than persisted neighbor columns.

Rationale: self-links add migration and reindex complexity. Without an identified consumer, they risk becoming stale denormalized state. Adjacency should be added only when the consuming path needs stable links and can prove they respect materialization policy.

Validation gate for future work:

- `python -m pytest backend/tests/test_chunk_persistence_service.py backend/tests/test_graph_materialization_service.py backend/tests/test_graph_expansion_service.py backend/tests/test_retrieval_orchestrator.py -q`

## Task 7: Active Job Unique Index

Decision: mark mostly handled. Startup dedupes active index jobs before creating or ensuring `uq_active_index_document_job`.

Reopen only if one of these appears:

- a real startup failure while creating `uq_active_index_document_job`
- duplicate active `index_document` rows remain after startup schema compatibility runs
- regression coverage no longer proves dedupe-before-index behavior

Evidence:

- `backend/src/ragstudio/db/engine.py` calls `_dedupe_active_index_document_jobs()` before creating `uq_active_index_document_job`.
- `_dedupe_active_index_document_jobs()` ranks active jobs per `target_id`, keeps the best active row, marks duplicates failed, clears lease fields, appends a user-visible log, and records the superseded error in `result`.
- `backend/src/ragstudio/db/models.py` defines `uq_active_index_document_job` as a partial unique index for active `index_document` jobs with non-null `target_id`.
- `backend/tests/test_db_engine.py` creates duplicate active index jobs in a legacy table, runs `init_db()`, asserts only the preferred job remains active, asserts the duplicate is failed with the expected error, and asserts the unique index definition includes the active-job predicate.

Rationale: the migration concern is valid in general, but the current startup path already handles duplicate active rows before enforcing the partial unique index.

Validation gate:

- `python -m pytest backend/tests/test_db_engine.py backend/tests/test_documents.py backend/tests/test_job_quality_warnings.py -q`

## Task 8: `pg_trgm` And `ILIKE`

Decision: mark the missing `pg_trgm` concern stale. Keep `ILIKE` query-shape changes as future benchmark work only.

Benchmark gate before changing query shape:

- capture `EXPLAIN (ANALYZE, BUFFERS)` for representative English lexical queries, Arabic lexical queries, selected-document filters, and worst-case no-hit terms
- compare current trigram-backed `ILIKE` behavior against any proposed operator/query rewrite
- preserve exact reference and Arabic token prefilter behavior
- prove improved latency or lower buffer usage without reducing recall or trace explainability

Evidence:

- `backend/src/ragstudio/db/engine.py` creates `pg_trgm` during Postgres startup initialization.
- `backend/src/ragstudio/db/models.py` declares GIN trigram indexes for `chunks.text` and `chunks.text_search_ar`.
- `backend/src/ragstudio/db/engine.py` also creates `ix_chunks_text_trgm` and `ix_chunks_text_search_ar_trgm` in the runtime compatibility path.
- `backend/src/ragstudio/services/chunk_lexical_search_repository.py` uses escaped `ILIKE` term filters for English lexical prefiltering, Arabic token containment for Arabic prefiltering, and document filters when provided.
- `backend/tests/test_chunk_lexical_search_repository.py` verifies `init_db()` creates the English text trigram index with `text gin_trgm_ops`.

Rationale: the index-extension concern is already addressed. Query-shape changes may still be worthwhile, but they should be performance work backed by database plans, not an architecture fix based on a stale missing-index premise.

Validation gate:

- `python -m pytest backend/tests/test_chunk_lexical_search_repository.py backend/tests/test_chunks.py backend/tests/test_chunk_service_arabic_search.py -q`
