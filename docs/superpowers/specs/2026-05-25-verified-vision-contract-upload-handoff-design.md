# Verified Vision Contract Upload Handoff Design

Date: 2026-05-25
Status: Ready for user review before implementation planning

## Problem

Ragstudio now has the core pieces for execution-based reference contracts:

- The vision autosuggest path samples pages and can execute generated reference
  contract candidates against those pages.
- Verified execution can produce `reference_contract_execution`,
  `reference_contract_validation`, `reference_resolution.enabled=true`, and
  `reference_resolution.build_canonical_units=true`.
- Upload and reindex compile and validate whichever metadata they receive before
  creating an indexing job.

The missing piece is the handoff. The Documents page treats "Analyze with
vision" and "Upload and index" as related UI actions, but the product contract is
not explicit enough: the verified vision contract package must become the exact
metadata package used by upload/reindex. When that handoff is incomplete,
Ragstudio can correctly block with:

`Reference-unit chunking requires custom_json.reference_resolution.enabled=true and build_canonical_units=true before indexing.`

That warning means indexing received metadata that requested reference-unit
chunking, but did not receive the verified canonical-unit authorization required
to create enforceable reference chunks.

## Decision

Use the verified vision result automatically for upload and indexing, while
showing a compact review panel before upload.

If the vision result contains a verified executable reference contract, upload
uses that compiled metadata by default. If the result is `metadata_only` or
`unverified`, upload can proceed only after the upload-ready metadata has removed
enforceable reference-unit chunking requests. If Ragstudio cannot safely demote
the metadata, upload is blocked before job creation with a contract-state error.
The UI must explain that Ragstudio is preserving the model's observation as a
hint instead of enforcing it as a canonical-unit contract.

The model proposes. Ragstudio executes and verifies. Only the verified compiled
contract becomes enforceable indexing policy.

## Contract State Rules

The upload-ready metadata has three states:

| UI state | Backend state | Canonical units | Upload behavior |
| --- | --- | --- | --- |
| `verified` | `compiled_reference_contract` with `reference_contract.verified=true` and `canonical_units=true` | Enabled | Upload and index with reference-unit chunking. |
| `metadata-only` | `metadata_only` or reference hints with `verified=false` | Disabled | Upload as metadata hints only; no enforceable `custom_json.chunking.unit`. |
| `generic` | `generic` or no reference contract | Disabled | Upload as normal generic/domain metadata. |

`unverified` is an analysis outcome, not an enforceable upload state. Before
upload, unverified reference observations must become `metadata-only` by
stripping or disabling enforceable reference-unit chunking. If the payload still
contains `custom_json.chunking.unit` without canonical-unit authorization, upload
must fail with a contract handoff error instead of creating an indexing job.

## Target Flow

1. User selects a file.
2. User clicks `Analyze with vision`.
3. Backend samples representative pages.
4. Vision model proposes domain metadata and executable reference contract
   candidates.
5. Ragstudio executes candidate extractors on sampled page text.
6. Ragstudio selects the best passing candidate, marks it verified, compiles the
   metadata, and returns a complete upload-ready contract package.
7. Backend binds the analysis result to the selected file using a stable
   fingerprint.
8. UI stores the analysis only if the fingerprint still matches the selected
   file.
9. UI shows the contract review panel:
   - domain and document type
   - contract state: verified, metadata-only, or unverified
   - canonical units: on or off
   - matched units and sampled pages
   - selected strategy and identity fields
   - any reason reference-unit chunking will not be enforced
10. User clicks `Upload and index`.
11. Frontend submits the exact compiled metadata returned by analysis and its
    matching file fingerprint.
12. Backend recompiles and validates the metadata as a defense-in-depth check.
13. Worker indexes with canonical reference-unit chunking only when the verified
    contract and `reference_resolution` flags are present.

## Backend Contract

The `/api/domain-profiles/suggest` response should be treated as an upload-ready
metadata package, not only a display suggestion. The returned
`domain_metadata.custom_json` must contain the complete compiled state needed for
the upload path:

- `reference_schema` with identity fields and `canonical_ref_template` when a
  reference contract exists.
- `reference_contract_execution` with selected status, matched units, matched
  pages, and execution reports.
- `reference_contract_validation` with selected strategy and selected regexes
  when validation is available.
- `domain_structure` anchors marked `verified=true` only for the selected
  executable contract.
- `reference_resolution.enabled=true` and
  `reference_resolution.build_canonical_units=true` only when the selected
  contract is executable and verified.
- unverified or metadata-only reference observations must not leave an
  enforceable `custom_json.chunking.unit` request in the upload-ready metadata
  unless canonical-unit creation is also enabled.
- quality, layout, parser, and preprocessing policies compiled from evidence,
  not guessed from document filename.

Upload and reindex keep their current compiler/validator checks. They should not
trust the UI blindly. Their job is to reject malformed or partially copied
metadata before a durable indexing job is created.

Both verification paths must emit the same normalized upload-ready package:

- Generated contract execution is the preferred path. When it verifies, it
  writes the selected `reference_schema`, `domain_structure`,
  `reference_contract_execution`, `reference_contract_validation`, and
  `reference_resolution` together.
- Legacy candidate validation may enable canonical units only if it can produce
  the same normalized package: identity fields, canonical template, verified
  anchors, validation payload, and reference resolution flags.
- Any path that cannot produce the normalized package must return metadata-only
  hints and must not leave enforceable reference-unit chunking enabled.
- The normalizer belongs on the backend. The frontend must not patch missing
  contract fields.

## Response Shape

The backend can keep the existing `DomainMetadataSuggestOut` shape, but the
payload must be internally complete enough for both display and upload. The
frontend should derive the review panel from:

- `domain_metadata`
- `custom_json.reference_contract_execution`
- `custom_json.reference_contract_validation`
- `custom_json.reference_resolution`
- `custom_json.reference_schema`
- `evidence_pages`
- `confidence`
- `warnings`
- `analysis_binding`, including filename, size, and content hash or equivalent
  stable fingerprint

If a future schema change adds a dedicated `contract_summary`, it should be a
read-only summary of those fields, not a second source of truth.

The response should also expose a normalized `contract_state` summary if adding
one is cheaper than repeatedly deriving the state in the frontend. That summary
must be derived from the fields above and treated as display-only.

## Frontend Behavior

The Documents page keeps a single vision-first upload path:

- File selection clears the previous vision result.
- Each analyze request records the selected file fingerprint. Late responses are
  ignored unless they match the currently selected file.
- Upload is disabled until analysis has run for the selected file.
- The upload payload uses `visionSuggestion.domain_metadata` exactly as returned.
- The upload payload includes the matching file fingerprint so the backend can
  reject stale or mismatched analysis.
- The UI does not reconstruct or patch `custom_json.reference_resolution` on the
  client.
- If contract state is verified, the primary upload action reads as normal.
- If contract state is metadata-only or unverified, the panel explains that
  reference-unit chunking will not be enforced, while independently evidenced
  script/table/layout gates may still apply.

The review panel is for operator trust and diagnosis, not for manual metadata
editing in the normal path.

## Reindex Behavior

Reindex does not silently run a new vision analysis. Reindex has two supported
paths:

- Reindex with stored/latest index options: reuse the previously compiled
  metadata and let backend validation reject stale or malformed contracts.
- Reanalyze then reindex: run the vision contract flow again for the document
  artifact, produce a new upload-ready contract package, then submit that exact
  compiled metadata to the reindex endpoint.

If a document was originally indexed with metadata-only hints, reindex must not
upgrade it to canonical reference units unless a fresh verified contract package
is supplied.

## Document Flow UI

The document flow page should expose this handoff as explicit stages:

- `vision_sampled`: sampled pages selected.
- `contract_proposed`: model returned candidate contract metadata.
- `contract_executed`: Ragstudio ran candidates on sampled pages.
- `contract_verified`: executable contract selected, or metadata-only reason
  recorded.
- `upload_contract_applied`: upload used the analyzed metadata payload.
- `canonical_units_enabled`: indexing is allowed to build reference units.

These stages must be data-driven from backend metadata and job result fields.
The UI should not hardcode a fixed stage list that breaks when new stages are
added; unknown stage ids should render as normal event rows with their
backend-provided labels.

The first implementation should map stages to explicit source fields:

| Stage | Source fields |
| --- | --- |
| `vision_sampled` | `evidence_pages`, `analysis_binding`, sampler warnings |
| `contract_proposed` | `reference_contract_candidates`, `reference_schema`, `domain_structure` |
| `contract_executed` | `reference_contract_execution.status`, `matched_units`, `matched_pages`, `reports` |
| `contract_verified` | `reference_contract_validation.status`, selected strategy, selected regex fields |
| `upload_contract_applied` | document `latest_index_options.domain_metadata.custom_json` and matching analysis binding |
| `canonical_units_enabled` | document contract `reference_contract.verified` and `reference_contract.canonical_units` |

If a field is missing, the stage should render as unavailable or metadata-only,
not as failed unless the backend recorded a failed state.

## Error Handling

If analysis fails, upload is blocked and the error is shown in the upload panel.

If analysis succeeds but the contract is unverified, upload can proceed only as a
metadata-only or generic indexing path. Reference-unit chunking must not be
silently enabled.

If analysis succeeds after the selected file changed, the frontend ignores the
late result. If a stale or mismatched analysis reaches the backend, upload fails
with a file/analysis mismatch error before reading parser or runtime state.

If upload receives stale or incomplete metadata and reference-unit chunking is
requested without canonical-unit authorization, the existing `422` validation
error remains correct. The UI should render it as a contract handoff failure,
not as a parser or MinerU failure.

If the selected file changes after analysis, upload is blocked until analysis is
rerun for that file.

## Non-Goals

- Do not add a second vision pass inside the worker.
- Do not hardcode Quran, policy, hadith, chapter, verse, article, or clause
  rules in the upload handoff.
- Do not let the frontend invent `verified=true`.
- Do not bypass the backend compiler or validator.
- Do not force canonical units for metadata-only contracts.
- Do not make raw model metadata enforceable without successful execution on
  sampled pages.

## Acceptance Criteria

- A verified generated contract from `Analyze with vision` uploads without the
  `reference_resolution.enabled=true` / `build_canonical_units=true` validation
  error.
- The uploaded document's latest index options preserve
  `reference_contract_execution.status="verified"`,
  `reference_contract_validation.status="verified"`,
  `reference_resolution.enabled=true`, and
  `reference_resolution.build_canonical_units=true`.
- An unverified generated contract uploads as metadata-only or is blocked from
  reference-unit chunking without producing `reference_unit_unresolved` solely
  because `reference_schema` exists.
- Unverified analysis output does not leave `custom_json.chunking.unit` enabled
  unless canonical units are also enabled.
- Generated execution and legacy candidate validation both pass through the same
  upload-ready contract normalizer.
- A late vision response for file A cannot be applied to file B.
- Reindex cannot silently upgrade metadata-only hints to canonical units without
  a fresh verified contract package.
- The UI shows whether canonical units are enabled before upload.
- The document flow UI shows proposal, execution, verification, and upload
  contract application stages.
- Backend tests cover verified and unverified handoff payloads.
- Frontend tests cover upload disabled state, verified contract display, and
  metadata-only explanation.

## Testing Strategy

Backend:

- Extend `backend/tests/test_domain_metadata_ai_suggester.py` to assert the
  returned metadata is upload-ready when execution verifies a generated contract.
- Add autosuggest tests proving unverified execution demotes reference-unit
  chunking to metadata-only instead of returning an enforceable chunking request.
- Extend `backend/tests/test_documents.py` to upload with a verified autosuggest
  payload and confirm the document stores the compiled index options.
- Extend `backend/tests/test_domain_metadata_contract_compiler.py` to confirm
  incomplete copied payloads still fail before job creation.
- Add upload/reindex tests for analysis/file fingerprint mismatch and for
  metadata-only reindex not upgrading to canonical units.

Frontend:

- Extend `frontend/tests/documents-page.test.tsx` to verify the upload mutation
  receives the exact `visionSuggestion.domain_metadata` object.
- Add a contract review rendering test for verified and metadata-only states.
- Add a file-change test confirming stale analysis is cleared and upload is
  disabled.
- Add a late-response test confirming a completed analysis for a previous file
  is ignored.

Pipeline/observability:

- Extend timeline tests so contract proposal, execution, verification, and
  upload application are visible when the relevant metadata exists.
- Add timeline tests for missing fields rendering as unavailable or
  metadata-only instead of failed.

## Implementation Handoff

This design should become an implementation plan with small, reviewable tasks:

1. Lock backend autosuggest output as an upload-ready contract package.
2. Add a backend upload-ready contract normalizer shared by generated execution
   and legacy validation paths.
3. Add file/analysis fingerprint binding to autosuggest and upload.
4. Add document upload/reindex regression tests for verified, metadata-only,
   stale, and incomplete handoff payloads.
5. Add frontend contract review panel, exact-payload tests, and stale-response
   guards.
6. Add document flow stages for the vision-to-upload contract handoff.
7. Run focused backend, frontend, and live upload validation.
