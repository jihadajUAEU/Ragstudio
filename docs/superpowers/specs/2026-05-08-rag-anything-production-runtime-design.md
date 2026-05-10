# RAG-Anything Production Runtime Design

## Purpose

Ragstudio should operate the real RAG-Anything runtime end to end instead of only exposing a Studio shell around fallback indexing and query behavior. The target architecture uses RAG-Anything and LightRAG in-process behind the existing adapter boundary, with production storage, model endpoints, reranking, health checks, and trace inspection wired into the existing Studio workflows.

This design intentionally chooses the heavier production path:

- Postgres replaces SQLite as the Studio application database.
- PGVector in Postgres stores vector retrieval data.
- Neo4j stores graph retrieval data.
- RAG-Anything and LightRAG execute indexing and query flows.
- Studio keeps mirrored chunk snapshots for inspection, not as the retrieval source of truth.
- Local fallback behavior remains available only as an explicit parser mode for local chunk creation and inspection.

## Current State

Ragstudio already has the shape of this system:

- Settings store LLM, embedding, MinerU, and storage values.
- `RAGAnythingAdapter` isolates upstream RAG-Anything imports.
- Documents, chunks, variants, experiments, runs, scores, diagnostics, and optimizer screens exist.
- MinerU sidecar parsing and artifact import exist.
- Query, chunk inspection, and graph flows are wired through runtime-first services with Studio-managed mirrored chunks for inspection.

The remaining work is operational hardening around production RAG-Anything dependencies, storage readiness, and benchmark coverage. Runtime profiles are the source of query execution; local fallback is parser-only and is not a query/runtime substitute.

## Goals

- Make Studio operate RAG-Anything + LightRAG for indexing and querying.
- Replace SQLite with Postgres as the application metadata store.
- Use PGVector and Neo4j for production retrieval and graph state.
- Preserve the current Studio UX for Documents, Chunks, Query, Variants, Experiments, Optimizer, and Diagnostics.
- Add runtime profiles that describe the complete execution environment.
- Add health checks that identify dependency failures before indexing or query work starts.
- Store normalized traces, timings, errors, sources, and mirrored chunk snapshots for inspection.
- Keep destructive per-document reindexing simple and explicit for the first implementation.

## Non-Goals

- Do not build a multi-tenant authorization system in this phase.
- Do not add managed cloud deployment automation beyond local docker-compose services.
- Do not support silent fallback from production runtime to local fallback query behavior.
- Do not support versioned per-document indexes in the first implementation.
- Do not replace Neo4j with a Postgres graph model.
- Do not implement every possible RAG-Anything storage backend. The first production target is Postgres/PGVector plus Neo4j.

## Architecture

Studio keeps `RAGAnythingAdapter` as the only backend layer that directly imports or calls upstream RAG-Anything and LightRAG APIs. The adapter becomes a thin boundary around a runtime subsystem instead of holding every responsibility itself.

Backend components:

- `RuntimeProfileService`: validates, saves, and loads complete runtime profiles.
- `RuntimeHealthService`: checks package import, LLM, vision, embedding, reranker, Postgres/PGVector, Neo4j, parser, and index readiness.
- `RAGAnythingRuntimeFactory`: builds the configured RAG-Anything and LightRAG instances from a runtime profile.
- `IndexLifecycleService`: owns destructive per-document reindexing and mirrored chunk cleanup.
- `TraceNormalizer`: converts RAG-Anything and LightRAG outputs into Studio sources, chunk traces, timings, and diagnostic metadata.
- `RerankerClient`: supports a generic reranker configuration with a Cohere-compatible implementation first.

Studio screens continue calling the existing API concepts. The backend changes the execution path under those APIs from fallback SQLite chunk search to runtime-backed indexing and query execution.

## Runtime Profile

A runtime profile describes the complete execution environment:

- LLM provider, model, base URL, API key presence, timeout, max async calls, and capabilities.
- Vision model settings, defaulting to the LLM endpoint when the configured model supports vision.
- Embedding provider, model, base URL, dimensions, batch size, timeout, TLS verification, and max async calls.
- Reranker provider type, model, base URL, API key presence, timeout, enable flag, and provider-specific options.
- Parser settings: parser type, parse method, image/table/equation processing, context window, context mode, max context tokens, headers, and captions.
- Storage settings: Postgres URL, PGVector schema/table prefix, Neo4j URL/database/auth, and working directory.
- Query defaults: mode, top-k, chunk top-k, rerank enabled, similarity threshold, max total tokens, entity token budget, and relation token budget.
- Cache and concurrency settings: LLM cache, entity-extraction cache, embedding batch count, max parallel insert, and runtime timeout.

Changing fields that affect index shape requires reindexing affected documents. These include embedding model, embedding dimensions, parser mode, chunking, vector storage, graph storage, and graph mode.

## Storage Design

Postgres becomes the primary application database and the PGVector host.

Postgres owns:

- settings and runtime profiles
- documents
- jobs
- variants
- experiments
- runs
- scores
- mirrored chunk snapshots
- RAG-Anything index metadata
- vector tables through PGVector

Neo4j owns:

- graph nodes and edges produced by RAG-Anything/LightRAG
- graph retrieval state
- relationship traversal support

Artifact storage owns:

- uploaded source files
- extracted MinerU/RAG-Anything artifacts
- media previews
- raw parser outputs when useful for debugging

The repository should provide docker-compose services for local Postgres with PGVector and Neo4j. The app should point to those services by default in local development, while production deployments can provide managed service URLs through environment/configuration.

SQLite is not part of the target runtime architecture. If a migration bridge is needed during implementation, it should be temporary and clearly scoped.

## Indexing Flow

Upload still creates a Studio `Document` record and stores the artifact.

When a user indexes a document, `IndexLifecycleService` performs a destructive per-document rebuild:

1. Load and validate the active runtime profile.
2. Run health checks for Postgres/PGVector, Neo4j, LLM, vision, embeddings, reranker when enabled, parser, and RAG-Anything package availability.
3. Mark the document `indexing`.
4. Remove prior runtime index entries and mirrored chunks for that document.
5. Build or load the RAG-Anything runtime from the active profile.
6. Parse and index the document through RAG-Anything/LightRAG into PGVector and Neo4j.
7. Normalize indexed content into mirrored Studio chunk snapshots.
8. Store index metadata tying the document to the runtime profile and index timestamp.
9. Mark the document `succeeded`.

If the rebuild fails after deletion, the document becomes `failed`, the error is stored, and Studio shows that the document has no active runtime index. The first implementation does not keep a previous active index after a destructive rebuild starts.

## Query Flow

The Query page keeps its current shape: question, selected documents, selected variants, and chunk/result limits.

For each selected variant:

1. Load the active runtime profile.
2. Validate runtime health and selected document index readiness.
3. Compile variant parameters into RAG-Anything/LightRAG query parameters.
4. Execute the query against the runtime index.
5. Normalize the answer, sources, chunk traces, reranker traces, timings, token metadata, and errors.
6. Store a Studio run for experiments, comparison, and optimizer workflows.

Production runtime profiles must not silently fall back to local query behavior. If runtime dependencies are unhealthy, the run fails with a clear dependency error. Explicit local fallback remains parser-only for local chunk creation and inspection.

## Mirrored Chunks And Inspection

The `chunks` concept remains, but mirrored chunks are inspection snapshots rather than the retrieval source of truth.

Each mirrored chunk stores:

- runtime profile id
- document id
- parser/backend metadata
- source location
- content type
- text or preview reference
- source artifact reference
- chunk/index timestamp
- retrieval metadata when available
- index shape metadata such as parser mode, chunking settings, embedding model, and embedding dimensions

Chunks are deleted and recreated during destructive document reindexing. UI copy and diagnostics should make clear that these rows mirror the runtime index for inspection.

## Variants

Variants continue to store JSON parameters, but the backend validates and compiles those parameters into RAG-Anything/LightRAG settings.

Initial supported variant/runtime parameters:

- `mode`
- `top_k`
- `chunk_top_k`
- `enable_rerank`
- `max_total_tokens`
- `max_context_tokens`
- `cosine_better_than_threshold`
- `parser`
- `parse_method`
- `chunk_token_size`
- `chunk_overlap_token_size`
- `include_headers`
- `include_captions`
- `vlm_enhanced`

Invalid parameters fail before calling RAG-Anything and should produce actionable error messages.

## Runtime Health And Diagnostics

Diagnostics should report:

- app database connectivity
- PGVector extension availability
- Neo4j connectivity and selected database
- RAG-Anything package availability and version
- LightRAG package availability and version when detectable
- LLM endpoint status
- vision capability status
- embedding endpoint status and dimension match
- reranker endpoint status when enabled
- parser/MinerU readiness
- active runtime profile id
- indexed document readiness
- current mode: `runtime`, `degraded`, or `fallback`

Health checks should distinguish configuration errors, network errors, dependency import errors, schema/index errors, and model capability mismatches.

## Error Handling

Indexing cannot start if Postgres/PGVector is unavailable. Production indexing also fails if Neo4j is unavailable because graph state would be incomplete.

LLM, vision, embedding, and enabled reranker failures should block indexing before partial work starts. Query failures should create failed runs with dependency-specific errors.

Data consistency rules:

- Every run stores runtime profile id, variant id, document ids, query config, timings, traces, and errors.
- Mirrored chunks are never treated as production retrieval truth.
- Destructive reindex deletes and recreates mirrored chunks for the document.
- Index-shape changes require reindexing affected documents.

## Local Development

The first implementation should add docker-compose services for:

- Postgres with PGVector enabled.
- Neo4j.

Local configuration should make it easy to start the runtime stores and run Studio against them. Model, embedding, vision, reranker, and parser endpoints can still be external services configured in Settings or environment variables.

## Testing Strategy

Testing moves in layers:

- Unit tests for runtime profile validation.
- Unit tests for variant parameter compilation.
- Unit tests for reranker request building and response normalization.
- Unit tests for trace normalization and failure classification.
- Repository/integration tests against Postgres with PGVector enabled.
- Neo4j health and graph-store tests with docker-compose service readiness.
- Adapter tests that mock RAG-Anything at the boundary to avoid expensive model/parser calls in normal test runs.
- One opt-in end-to-end smoke test requiring real LLM, vision, embedding, reranker, Postgres/PGVector, Neo4j, and parser services.
- Frontend tests for Settings, Diagnostics, Documents, Query, and Chunks state changes.

## Rollout Plan

1. Add docker-compose services and Postgres application database support.
2. Move Studio metadata persistence from SQLite assumptions to Postgres.
3. Add runtime profile schema, API, validation, and Settings support.
4. Add runtime health checks and diagnostics.
5. Add RAG-Anything runtime factory.
6. Add destructive document reindexing through the runtime.
7. Add query execution through the runtime.
8. Add mirrored chunk/source/trace inspection.
9. Keep local fallback available only as explicit parser behavior for development inspection.

## Success Criteria

- Studio runs with Postgres/PGVector and Neo4j in local docker-compose.
- SQLite is no longer required by the target app runtime.
- A document can be uploaded, indexed through RAG-Anything, and inspected through mirrored chunks.
- A query can be executed through RAG-Anything/LightRAG with selected variants.
- Runs store answer, sources, traces, timings, runtime profile id, variant id, and errors.
- Diagnostics clearly identify missing or unhealthy runtime dependencies.
- Production runtime profiles do not silently fall back to local fallback behavior.
- Tests cover runtime profile validation, health checks, config compilation, destructive reindex behavior, and query failure handling.

## Runtime-First Cleanup Update

Production runtime profiles no longer use local fallback query behavior or local graph placeholders. Unsupported scoped native query filtering is a runtime error, not a metadata fallback. Local fallback remains only as a parser mode for explicit local chunk creation.
