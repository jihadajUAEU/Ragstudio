# Phase 1: Proof Contract and Baseline Packet - Patterns

**Mapped:** 2026-05-14
**Purpose:** Point executors at existing repository patterns before creating proof packet docs, schemas, fixtures, and public evidence artifacts.

## Files To Create

| New Path | Role | Closest Existing Analogs | Notes |
|----------|------|--------------------------|-------|
| `docs/benchmarks/ragstudio-oss-proof-v1/manifest.json` | Packet provenance manifest | `.planning/research/ARCHITECTURE.md`, `backend/src/ragstudio/services/trace_normalizer.py` | Should connect artifacts, source commit/tag, hashes, claim counts, and redaction status. |
| `docs/benchmarks/ragstudio-oss-proof-v1/schemas/*.schema.json` | Public JSON contracts | `backend/src/ragstudio/services/metadata_json_schema.py` | Existing code validates nested metadata with explicit allowed values and precise errors; schemas should be equally explicit. |
| `docs/benchmarks/ragstudio-oss-proof-v1/fixtures/*.json` | Synthetic corpus and proof fixtures | `backend/src/ragstudio/services/metadata_json_schema.py`, `docs/superpowers/plans/2026-05-12-canonical-reference-units.md` | Existing examples model Arabic/English reference units and provenance-rich metadata. |
| `docs/benchmarks/ragstudio-oss-proof-v1/artifacts/*.json` | Redacted exported evidence artifacts | `backend/src/ragstudio/services/domain_metadata_quality_gate.py`, `backend/src/ragstudio/services/trace_normalizer.py` | Exported artifacts should mirror real parser warning/chunk/query trace shapes without private runtime data. |
| `docs/benchmarks/ragstudio-oss-proof-v1/screenshots/signoff.json` | Screenshot safety record | `.planning/ui-reviews/*/*.png`, `.planning/ui-reviews/*UI-REVIEW.md` | Existing UI review artifacts show screenshot capture practice; Phase 1 needs publishability signoff metadata. |
| `docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.registry.json` | Machine-readable claim source of truth | `.planning/REQUIREMENTS.md`, `.planning/PROJECT.md` | Use explicit IDs/status/evidence/limitations to prevent overclaiming. |
| `docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.matrix.md` | Human claim audit table | `docs/superpowers/reviews/*.md` | Review docs use tables for evidence and issue tracking; claims matrix should be similarly scan-friendly. |
| `docs/benchmarks/ragstudio-oss-proof-v1/docs/*.md` | Human packet docs | `docs/architecture/durable-rag-indexing.md`, `docs/superpowers/plans/*.md` | Existing docs use direct goal/scope/architecture sections; proof docs should be compact and reviewer-first. |

## Relevant Existing Patterns

### Explicit Metadata Validation

`backend/src/ragstudio/services/metadata_json_schema.py` validates custom metadata through small functions with:
- allowlisted enum values,
- path-specific errors,
- strict type checks,
- safe regex constraints.

Apply the same spirit in public schemas: prefer constrained `enum`, `required`, `additionalProperties: false`, and named object shapes over loose freeform blobs.

### Quality Evidence Shape

`backend/src/ragstudio/services/domain_metadata_quality_gate.py` produces parser-quality warnings with stable codes such as `reference_unit_missing_expected_script` and applies `quality_action_policy` for materialization decisions. Phase 1 artifacts should include representative warning codes and policy metadata so later proof tooling can demonstrate the real Ragstudio value proposition.

### Trace Artifact Shape

`backend/src/ragstudio/services/trace_normalizer.py` normalizes query results into `answer`, `sources`, `chunk_traces`, `reranker_traces`, `timings`, `token_metadata`, `error`, and `error_type`. Retrieval proof artifacts should reuse these field names where possible instead of inventing a separate trace vocabulary.

### Documentation Style

`docs/architecture/durable-rag-indexing.md` uses short sections, diagrams, and concrete operational behavior. `docs/superpowers/plans/*.md` uses scope/out-of-scope and evidence-heavy tables. The packet docs should use the same direct style, with limitations near claims.

## Implementation Guidance For Planner

- Keep Phase 1 artifact-only. Do not create `backend/src/ragstudio/proof_packet/`, `scripts/proof.sh`, `ragstudio-site`, or validator code in this phase.
- Split plans by proof packet slice, not by technical layer:
  - packet shell + synthetic evidence,
  - schemas + claims registry,
  - docs + safety/signoff.
- Include source assertions that can be verified with `test -f`, `find`, `rg`, and JSON parsing commands.
- Treat screenshot signoff and redaction metadata as required packet data, not prose-only caveats.

