# RAG-Anything Studio Design

Date: 2026-05-07

## Context

This project starts from an empty workspace and will build a clean, standalone Studio for RAG-Anything. The reference product direction comes from HKUDS/RAG-Anything pull request #270, but this repo will not be a direct fork. Studio should depend on `raganything` as an external package and isolate all package-specific calls behind an adapter.

The goal is a production-quality foundation for exploring, operating, comparing, and optimizing RAG-Anything workflows. Studio should make the RAG flow visible, configurable, and measurable.

## Product Goals

- Provide a local-first web Studio for RAG-Anything.
- Show the actual RAG flow as an inspectable pipeline.
- Let users choose presets, manually tune parameters, and later run guided optimization.
- Support saved variants for different RAG methods and settings.
- Compare RAG-Anything features across variants, documents, queries, and expected outputs.
- Allow users to upload evaluation files that describe expected results in formats understood by Studio.
- Use expected outputs to evaluate, select, and eventually iteratively optimize RAG execution methods.
- Keep the implementation modular enough to survive changes in the upstream RAG-Anything package.

## Non-Goals

- Do not fork or vendor the full RAG-Anything repository into this project.
- Do not silently inject expected answers into generation prompts unless the user explicitly enables a reference-guided generation mode.
- Do not build every optimizer capability in the first implementation phase.
- Do not treat unsupported upstream features as successful no-ops. Unsupported capabilities must be visible.

## Architecture

Studio will be a standalone full-stack app.

- `backend/`: FastAPI backend for health, settings, documents, jobs, variants, experiments, runs, graph data, and diagnostics.
- `backend/services/raganything_adapter.py`: the only backend layer that imports or calls `raganything`.
- `backend/stores/`: local persistence for settings, documents, jobs, variants, experiments, runs, scores, optimization sessions, and cached artifacts.
- `frontend/`: React, TypeScript, and Vite single-page app.
- `tests/`: backend unit and API tests first, with adapter behavior mocked where needed.

The backend language is Python. It should use Python typing throughout and Pydantic schemas for API contracts, validation, and persisted records where appropriate.

The frontend language is TypeScript. React components, API clients, UI state, forms, pipeline schemas, and evaluation import models should be typed. Shared contracts should be generated from or kept consistent with the backend schemas during planning and implementation.

The backend serves the API and, after frontend build, can serve the static frontend so users can run Studio from one local command.

## Implementation Technology Stack

Use the latest stable versions available at implementation time. The versions below were checked against package metadata on 2026-05-07 and should be treated as the current baseline, not permanent pins.

### Runtime And Package Management

- Backend runtime: Python `>=3.12,<3.15`. Python 3.12 is the compatibility floor; newer versions are allowed if RAG-Anything and transitive dependencies support them.
- Backend package manager: `uv` for Python dependency management, lockfiles, virtual environments, and scripts. Current package metadata shows `uv` `0.11.11`.
- Frontend runtime: Node.js LTS, `>=22`. Avoid depending on non-LTS-only Node behavior.
- Frontend package manager: `npm`, because it is bundled with Node and avoids extra package-manager bootstrap issues. Current local metadata shows Node `25.9.0` and npm `11.13.0`, but implementation should target Node LTS compatibility.
- Upstream RAG package: `raganything`, isolated behind the Studio adapter. Current package metadata shows `raganything` `1.3.0`.

### Backend Stack

- API framework: FastAPI. Current package metadata shows `fastapi` `0.136.1`.
- ASGI server: Uvicorn. Current package metadata shows `uvicorn` `0.46.0`.
- Schema and validation: Pydantic v2. Current package metadata shows `pydantic` `2.13.4`.
- Persistence: SQLite for the local-first Studio database.
- ORM/database toolkit: SQLAlchemy 2.x. Current package metadata shows `sqlalchemy` `2.0.49`.
- Migrations: Alembic. Current package metadata shows `alembic` `1.18.4`.
- Async SQLite driver: `aiosqlite`. Current package metadata shows `aiosqlite` `0.22.1`.
- Upload handling: `python-multipart`. Current package metadata shows `python-multipart` `0.0.27`.
- HTTP client and API tests: HTTPX. Current package metadata shows `httpx` `0.28.1`.
- YAML import support: PyYAML. Current package metadata shows `pyyaml` `6.0.3`.
- JSON performance: `orjson`. Current package metadata shows `orjson` `3.11.9`.
- Structured logging: `structlog`. Current package metadata shows `structlog` `25.5.0`.
- Async foundation: AnyIO where direct async primitives are needed. Current package metadata shows `anyio` `4.13.0`.

The first implementation should use an in-process async job worker backed by persisted SQLite job records. This keeps local setup simple while preserving durable job state, progress, logs, and retries. Do not add Redis, Celery, or a distributed queue in the initial implementation. Revisit that only if multi-process or remote execution becomes a real requirement.

Uploaded files and derived artifacts should live in a local app data directory managed by Studio. SQLite stores metadata and references; the filesystem stores original uploads, extracted media, generated artifacts, and larger trace payloads when appropriate.

### Frontend Stack

- App framework: React with TypeScript and Vite.
- Component system: shadcn/ui plus Radix UI primitives.
- Styling: Tailwind CSS, shadcn/ui theme tokens, and CSS variables. Tailwind is the only general-purpose CSS framework.
- Data fetching and server state: TanStack Query.
- Tables and dense grids: TanStack Table.
- Pipeline builder and stage trace canvas: React Flow package `@xyflow/react`.
- Advanced editors: Monaco Editor.
- Forms and validation: React Hook Form plus Zod.
- Local UI/workspace state: Zustand.
- Icons: Lucide React.
- Charts: Recharts.
- Large knowledge graph visualization: Cytoscape.js with React Cytoscape.js when React Flow is too constrained.

Current npm metadata checked on 2026-05-07:

- TypeScript `6.0.3`
- React `19.2.6`
- React DOM `19.2.6`
- Vite `8.0.11`
- `@vitejs/plugin-react` `6.0.1`
- Tailwind CSS `4.2.4`
- shadcn CLI `4.7.0`
- Radix dialog package `@radix-ui/react-dialog` `1.1.15`
- TanStack Query `5.100.9`
- TanStack Table `8.21.3`
- React Flow package `@xyflow/react` `12.10.2`
- Monaco Editor `0.55.1`
- Zod `4.4.3`
- React Hook Form `7.75.0`
- Zustand `5.0.13`
- Lucide React `1.14.0`
- Recharts `3.8.1`
- Cytoscape `3.33.3`
- React Cytoscape.js `2.0.0`

### API Contracts

FastAPI OpenAPI output is the source of truth for HTTP contracts. Generate TypeScript API types from OpenAPI rather than hand-copying backend models. Use `openapi-typescript` or `@hey-api/openapi-ts`; current npm metadata shows `openapi-typescript` `7.13.0` and `@hey-api/openapi-ts` `0.97.1`.

### Testing And Quality Tools

- Backend tests: pytest and pytest-asyncio. Current package metadata shows `pytest` `9.0.3` and `pytest-asyncio` `1.3.0`.
- Backend lint and formatting: Ruff. Current package metadata shows `ruff` `0.15.12`.
- Backend type checking: Pyright. Current package metadata shows `pyright` `1.1.409`.
- Frontend unit/component tests: Vitest and Testing Library React. Current npm metadata shows `vitest` `4.1.5` and `@testing-library/react` `16.3.2`.
- Frontend browser/E2E tests: Playwright for critical flows once the UI shell exists. Current npm metadata shows `playwright` `1.59.1`.
- Frontend lint/format: ESLint and Prettier. Current npm metadata shows `eslint` `10.3.0`, `@eslint/js` `10.0.1`, and `prettier` `3.8.3`.

### Deliberately Excluded For Initial Implementation

- No Bootstrap, Bulma, Foundation, or second broad CSS framework.
- No Redux unless Zustand proves insufficient.
- No Celery, Redis, RabbitMQ, or external queue in the local-first foundation.
- No separate Next.js/SSR framework; Studio is an app shell served by FastAPI after build.
- No direct RAG-Anything imports outside the adapter.

The adapter exposes capability-oriented methods such as:

- `get_capabilities`
- `validate_variant`
- `index_document`
- `query`
- `search_chunks`
- `get_chunk`
- `inspect_content`
- `get_graph`
- `run_variant`

Everything outside the adapter depends on Studio-owned schemas rather than upstream internals.

## Core Concepts

### Project

A local Studio workspace containing documents, settings, variants, evaluation sets, experiments, runs, scores, and cached artifacts.

### Document

An uploaded source file plus metadata, content hashes, parse/index state, extracted content references, and media artifacts.

### Chunk

A retrievable content unit produced by parsing, chunking, or multimodal extraction. A chunk stores source document, location metadata, text or media preview references, chunking strategy, embedding/index status, and retrieval metadata when returned by a run.

### Variant

A saved RAG strategy. A variant captures provider settings, enabled RAG-Anything features, parser options, chunking, retrieval mode, reranking, fusion, graph usage, multimodal toggles, prompt/generation settings, storage/index settings, concurrency, cache policy, and optimizer hints.

### Evaluation Case

A single query plus expected output information. It can include answer text, structured fields, source expectations, media expectations, required terms, forbidden terms, rubric notes, objective preferences, and variant hints.

### Evaluation Set

A collection of evaluation cases used for comparison and optimization.

### Experiment

A comparison plan combining documents, an evaluation set, candidate variants, and objectives.

### Run

Execution result for one variant on one query or evaluation case. It stores answer text, retrieved sources, retrieved chunks, prompt-included chunks, media evidence, graph evidence, timing, errors, token or cost metadata when available, and raw trace metadata.

### Score

Evaluation of a run against expected output. Early scoring should include deterministic checks such as required terms, forbidden terms, source coverage, structured-field match, latency, and error state. Later phases can add LLM-as-judge scoring and user ratings.

### Optimization Session

A tracked automatic method-selection workflow. It records objectives, generated candidate variants, runs, scores, selected best variant, and a plain explanation of why the method was recommended.

## User Experience

The main experience is an interactive RAG pipeline view:

Upload or Select Documents -> Parse -> Chunk or Segment -> Embed -> Store or Index -> Retrieve -> Rerank or Fuse -> Graph or Multimodal Expansion -> Generate -> Evaluate and Compare

Each stage shows:

- status: not configured, ready, running, succeeded, failed, or unsupported
- editable parameters
- output preview where possible
- diagnostics such as latency, item counts, warnings, and errors
- variant differences when comparing methods

Primary screens:

- Dashboard: readiness, recent documents, recent experiments, and quick pipeline status.
- Settings: provider, model, storage, and connection tests.
- Documents: upload, parse/index jobs, content inspection, and media inspection.
- Chunk Inspector: search indexed chunks, ask a retrieval-only question, inspect ranked chunk contents, and compare chunk selection across variants.
- Pipeline Builder: visual flow, presets, advanced stage parameters, and save-as-variant.
- Query: run one variant or compare variants for an ad hoc query.
- Evaluation Sets: import, validate, inspect, and edit expected-output cases.
- Experiments: select documents, evaluation set, variants, objectives, and run strategy.
- Comparison: side-by-side answers, sources, media evidence, graph traces, latency, scores, and errors.
- Knowledge Graph: graph view for a document, variant, or run when available.
- Diagnostics and API: health, adapter capabilities, dependency status, logs, and endpoint status.

## Frontend Component Stack

The finalized frontend stack is React, TypeScript, Vite, shadcn/ui, TanStack, React Flow, and Monaco. Version baselines are recorded in the Implementation Technology Stack section.

Use shadcn/ui and Radix UI for accessible, composable primitives such as dialogs, sheets, tabs, popovers, tooltips, dropdowns, accordions, command menus, forms, and toasts. Use Tailwind CSS for styling and design tokens.

Tailwind CSS is the locked CSS framework. Styling should use Tailwind utilities, shadcn/ui theme tokens, and CSS variables for app-specific tokens such as pipeline stage status, score bands, graph colors, run states, and evidence/source highlights. Do not add a second general-purpose CSS framework such as Bootstrap, Bulma, or Foundation.

Use TanStack Query for API fetching, mutation state, job polling, run polling, cache invalidation, retries, and optimistic UI where appropriate. Use TanStack Table for dense data views such as documents, chunks, variants, runs, scores, and evaluation cases.

Use React Flow for the visual RAG pipeline builder and pipeline-stage traces. Use Cytoscape.js for larger knowledge-graph inspection if React Flow becomes too constrained for graph exploration. Use Monaco Editor for JSON, YAML, prompt, and advanced variant configuration editing. Use React Hook Form with Zod for settings, variant forms, evaluation import validation, and optimizer objective forms.

The UI should feel like a modern technical workbench: dense, responsive, inspectable, keyboard-friendly, and professional. It should avoid a marketing-page feel. Tables, inspectors, split panes, drawers, command menus, tabs, resizable panels, and canvas-based flow views are preferred over decorative cards.

## Parameter Modes

Studio supports three parameter modes.

### Presets

Users choose optimization goals such as fast, balanced, high recall, multimodal-heavy, graph-heavy, low cost, and high precision. Presets populate a variant configuration and show which parameters changed.

### Advanced Overrides

Every preset can be opened into detailed controls. Initial override categories are parser strategy, OCR/VLM behavior, chunking, embedding model and dimension, retrieval mode, top-k, similarity thresholds, reranking, fusion, graph expansion depth, multimodal evidence inclusion, generation prompt and model, storage backend, concurrency, and cache policy.

### Guided Optimizer

Users define an objective such as best source grounding, fastest acceptable answer, best multimodal evidence, or highest structured-output match. Studio generates candidate variants, runs experiments, scores outputs against expected results, ranks methods, and recommends a best variant with explanation.

The guided optimizer is designed now but implemented in phases.

## Chunk Inspection

Studio must let users ask specific questions to inspect chunk contents without forcing answer generation. Chunk inspection supports two related workflows.

Direct chunk search:

1. User selects documents, a variant, and a retrieval mode.
2. User asks a retrieval-only question or enters a keyword/vector search query.
3. Studio returns ranked chunks without generating an answer.
4. User inspects chunk text, source document, page or section, media preview, retrieval score, and rerank score when available.

Run-level chunk trace:

1. User runs a query or experiment.
2. Studio records candidate chunks returned by retrieval.
3. Studio records reranked chunks and final prompt-included chunks when available.
4. The result view shows which chunks supported the answer, which chunks were ignored, and which answer sentences cite or depend on each chunk when citation data is available.

Chunk Inspector should expose:

- chunk text or media preview
- source document, page, section, bounding box, or time range when available
- chunk ID and parent document ID
- chunking strategy and variant that produced it
- retrieval score, similarity score, and rerank score when available
- inclusion status: candidate, reranked, prompt-included, answer-cited, or ignored
- neighboring chunks before and after the selected chunk
- filters for document, source type, score range, variant, and run

This makes retrieval debuggable. Users can verify whether the right evidence was indexed, retrieved, reranked, and used before judging the final answer.

## Evaluation File Formats

Studio supports CSV, JSON, YAML, and JSONL imports. Internally, every import normalizes to canonical Evaluation Case JSONL. JSONL is the canonical export and repeatable experiment format.

Canonical fields:

```json
{
  "id": "case-001",
  "query": "What warranty terms apply to product X?",
  "documents": ["policy.pdf"],
  "expected_answer": "Product X has a two-year warranty...",
  "expected_sources": ["policy.pdf#page=4"],
  "must_include": ["two-year warranty", "proof of purchase"],
  "must_avoid": ["lifetime warranty"],
  "expected_media": [],
  "expected_structure": {
    "warranty_period": "2 years",
    "conditions": ["proof of purchase"]
  },
  "rubric": {
    "grounding": "Answer must cite the warranty clause.",
    "completeness": "Must include warranty period and conditions."
  },
  "objective": {
    "primary": "grounded_correctness",
    "secondary": ["latency", "source_precision"]
  },
  "variant_hints": {
    "prefer": ["high_recall", "rerank", "graph"],
    "avoid": ["low_context"]
  }
}
```

CSV imports map simple columns into this structure. JSON and YAML support nested fields. Validation reports file, row or line, field, and reason.

Required fields for a valid evaluation case are `id`, `query`, and at least one expected-output signal: `expected_answer`, `expected_sources`, `must_include`, `expected_structure`, `rubric`, or `expected_media`.

## Backend API Surface

Initial API groups:

- `/api/health`: service health and readiness.
- `/api/settings`: provider, model, storage, and default configuration.
- `/api/documents`: upload, list, inspect, and document state.
- `/api/chunks`: search chunks, fetch chunk details, inspect neighboring chunks, and fetch chunk traces by run.
- `/api/jobs`: async job lifecycle, progress, and logs.
- `/api/variants`: create, update, list, validate, and duplicate saved variants.
- `/api/evaluation-sets`: import, validate, list, edit, and export evaluation cases.
- `/api/experiments`: define comparison plans and start runs.
- `/api/runs`: fetch run outputs, traces, scores, timings, and errors.
- `/api/query`: single-query execution for one or more variants.
- `/api/graph`: graph visualization data by document, variant, or run.
- `/api/diagnostics`: adapter capabilities, dependency status, and logs.

## Backend Flow

1. User configures settings and runs connection tests.
2. User uploads documents. Studio registers files with hashes and metadata.
3. User builds variants through presets, advanced overrides, optimizer hints, or imported evaluation objectives.
4. User indexes documents through async jobs.
5. User can inspect indexed chunks directly by asking retrieval-only questions.
6. User imports evaluation files. Studio validates and normalizes them into evaluation cases.
7. User creates an experiment from documents, an evaluation set, candidate variants, and an objective.
8. Studio runs variants against cases and stores run outputs plus chunk traces.
9. Studio scores outputs against expected results.
10. Studio ranks variants and recommends the best method with explanation.
11. Later optimizer phases generate new variants based on score gaps and rerun selected cases.

## Error Handling

- Every pipeline stage exposes one of: not configured, ready, running, succeeded, failed, or unsupported.
- Adapter capabilities are queried and shown before users run unsupported features.
- Unsupported features return structured errors with capability names and suggested alternatives.
- Job failures store a short user-facing summary and detailed diagnostic logs.
- Import validation errors include file, row or line, field, and reason.
- Experiment and optimizer results preserve failed runs so comparisons remain auditable.
- Optimizer recommendations show supporting evidence: scores, settings, timings, errors, and tradeoffs.

## Testing Strategy

Backend tests:

- settings validation
- variant schema validation
- evaluation file import and normalization for CSV, JSON, YAML, and JSONL
- chunk search and chunk trace schema validation
- scoring helpers
- job state transitions
- adapter capability handling
- API behavior for health, settings, documents, variants, evaluation sets, experiments, runs, and query
- API behavior for chunk search, chunk detail, neighboring chunks, and run chunk traces

Integration tests:

- mocked adapter happy path for upload, index, query, and compare
- mocked adapter happy path for retrieval-only chunk search
- unsupported capability path
- import validation failures
- FastAPI starts and serves built frontend assets

Frontend tests are added where state complexity justifies them, especially Pipeline Builder, Evaluation Set import, and Comparison views.

## Phasing

### Phase 1: Production Foundation

Create the repo scaffold, backend contracts, typed schemas, local persistence, settings, documents, chunks, jobs, variants, evaluation import schema, and a basic React shell with navigation.

### Phase 2: Real RAG Execution

Integrate the RAG-Anything adapter for single-variant upload, index, query, retrieval-only chunk search, chunk traces, readiness, graph inspection, and content inspection where available.

### Phase 3: Comparison Workspace

Implement experiments, multi-variant runs, side-by-side comparison, chunk-selection comparison, deterministic scoring against expected outputs, and reportable run history.

### Phase 4: Guided Optimizer

Generate candidate variants from objectives, run and rank them, recommend the best method, and explain why it won.

### Phase 5: Advanced Optimization

Add iterative parameter search, richer metrics, optional LLM-as-judge scoring, cost and token tracking, exportable reports, and advanced optimizer controls.

## Open Implementation Choices For Planning

The implementation plan should choose concrete tooling for:

- Python package management and project layout.
- Local persistence backend: SQLite is preferred if it fits the final stack; JSON files are acceptable only for low-risk metadata.
- Background job execution model.
- How to package and serve frontend assets from FastAPI.
- The exact subset of RAG-Anything APIs available through the adapter in Phase 2.

These are planning choices, not product ambiguities.
