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

The backend serves the API and, after frontend build, can serve the static frontend so users can run Studio from one local command.

The adapter exposes capability-oriented methods such as:

- `get_capabilities`
- `validate_variant`
- `index_document`
- `query`
- `inspect_content`
- `get_graph`
- `run_variant`

Everything outside the adapter depends on Studio-owned schemas rather than upstream internals.

## Core Concepts

### Project

A local Studio workspace containing documents, settings, variants, evaluation sets, experiments, runs, scores, and cached artifacts.

### Document

An uploaded source file plus metadata, content hashes, parse/index state, extracted content references, and media artifacts.

### Variant

A saved RAG strategy. A variant captures provider settings, enabled RAG-Anything features, parser options, chunking, retrieval mode, reranking, fusion, graph usage, multimodal toggles, prompt/generation settings, storage/index settings, concurrency, cache policy, and optimizer hints.

### Evaluation Case

A single query plus expected output information. It can include answer text, structured fields, source expectations, media expectations, required terms, forbidden terms, rubric notes, objective preferences, and variant hints.

### Evaluation Set

A collection of evaluation cases used for comparison and optimization.

### Experiment

A comparison plan combining documents, an evaluation set, candidate variants, and objectives.

### Run

Execution result for one variant on one query or evaluation case. It stores answer text, retrieved sources, media evidence, graph evidence, timing, errors, token or cost metadata when available, and raw trace metadata.

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
- Pipeline Builder: visual flow, presets, advanced stage parameters, and save-as-variant.
- Query: run one variant or compare variants for an ad hoc query.
- Evaluation Sets: import, validate, inspect, and edit expected-output cases.
- Experiments: select documents, evaluation set, variants, objectives, and run strategy.
- Comparison: side-by-side answers, sources, media evidence, graph traces, latency, scores, and errors.
- Knowledge Graph: graph view for a document, variant, or run when available.
- Diagnostics and API: health, adapter capabilities, dependency status, logs, and endpoint status.

## Parameter Modes

Studio supports three parameter modes.

### Presets

Users choose optimization goals such as fast, balanced, high recall, multimodal-heavy, graph-heavy, low cost, and high precision. Presets populate a variant configuration and show which parameters changed.

### Advanced Overrides

Every preset can be opened into detailed controls. Initial override categories are parser strategy, OCR/VLM behavior, chunking, embedding model and dimension, retrieval mode, top-k, similarity thresholds, reranking, fusion, graph expansion depth, multimodal evidence inclusion, generation prompt and model, storage backend, concurrency, and cache policy.

### Guided Optimizer

Users define an objective such as best source grounding, fastest acceptable answer, best multimodal evidence, or highest structured-output match. Studio generates candidate variants, runs experiments, scores outputs against expected results, ranks methods, and recommends a best variant with explanation.

The guided optimizer is designed now but implemented in phases.

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
5. User imports evaluation files. Studio validates and normalizes them into evaluation cases.
6. User creates an experiment from documents, an evaluation set, candidate variants, and an objective.
7. Studio runs variants against cases and stores run outputs.
8. Studio scores outputs against expected results.
9. Studio ranks variants and recommends the best method with explanation.
10. Later optimizer phases generate new variants based on score gaps and rerun selected cases.

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
- scoring helpers
- job state transitions
- adapter capability handling
- API behavior for health, settings, documents, variants, evaluation sets, experiments, runs, and query

Integration tests:

- mocked adapter happy path for upload, index, query, and compare
- unsupported capability path
- import validation failures
- FastAPI starts and serves built frontend assets

Frontend tests are added where state complexity justifies them, especially Pipeline Builder, Evaluation Set import, and Comparison views.

## Phasing

### Phase 1: Production Foundation

Create the repo scaffold, backend contracts, typed schemas, local persistence, settings, documents, jobs, variants, evaluation import schema, and a basic React shell with navigation.

### Phase 2: Real RAG Execution

Integrate the RAG-Anything adapter for single-variant upload, index, query, traces, readiness, graph inspection, and content inspection where available.

### Phase 3: Comparison Workspace

Implement experiments, multi-variant runs, side-by-side comparison, deterministic scoring against expected outputs, and reportable run history.

### Phase 4: Guided Optimizer

Generate candidate variants from objectives, run and rank them, recommend the best method, and explain why it won.

### Phase 5: Advanced Optimization

Add iterative parameter search, richer metrics, optional LLM-as-judge scoring, cost and token tracking, exportable reports, and advanced optimizer controls.

## Open Implementation Choices For Planning

The implementation plan should choose concrete tooling for:

- Python package management and project layout.
- Local persistence backend: SQLite is preferred if it fits the final stack; JSON files are acceptable only for low-risk metadata.
- Background job execution model.
- Frontend component and styling approach.
- How to package and serve frontend assets from FastAPI.
- The exact subset of RAG-Anything APIs available through the adapter in Phase 2.

These are planning choices, not product ambiguities.
