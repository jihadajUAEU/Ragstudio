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
`unverified`, upload still may proceed, but reference-unit chunking is disabled
or blocked according to the returned contract state. The UI must explain that
Ragstudio is preserving the model's observation as a hint instead of enforcing it
as a canonical-unit contract.

The model proposes. Ragstudio executes and verifies. Only the verified compiled
contract becomes enforceable indexing policy.

## Target Flow

1. User selects a file.
2. User clicks `Analyze with vision`.
3. Backend samples representative pages.
4. Vision model proposes domain metadata and executable reference contract
   candidates.
5. Ragstudio executes candidate extractors on sampled page text.
6. Ragstudio selects the best passing candidate, marks it verified, compiles the
   metadata, and returns a complete upload-ready contract package.
7. UI shows the contract review panel:
   - domain and document type
   - contract state: verified, metadata-only, or unverified
   - canonical units: on or off
   - matched units and sampled pages
   - selected strategy and identity fields
   - any reason reference-unit chunking will not be enforced
8. User clicks `Upload and index`.
9. Frontend submits the exact compiled metadata returned by analysis.
10. Backend recompiles and validates the metadata as a defense-in-depth check.
11. Worker indexes with canonical reference-unit chunking only when the verified
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

If a future schema change adds a dedicated `contract_summary`, it should be a
read-only summary of those fields, not a second source of truth.

## Frontend Behavior

The Documents page keeps a single vision-first upload path:

- File selection clears the previous vision result.
- Upload is disabled until analysis has run for the selected file.
- The upload payload uses `visionSuggestion.domain_metadata` exactly as returned.
- The UI does not reconstruct or patch `custom_json.reference_resolution` on the
  client.
- If contract state is verified, the primary upload action reads as normal.
- If contract state is metadata-only or unverified, the panel explains that
  reference-unit chunking will not be enforced, while independently evidenced
  script/table/layout gates may still apply.

The review panel is for operator trust and diagnosis, not for manual metadata
editing in the normal path.

## Document Flow UI

The document flow page should expose this handoff as explicit stages:

- `vision_sampled`: sampled pages selected.
- `contract_proposed`: model returned candidate contract metadata.
- `contract_executed`: Ragstudio ran candidates on sampled pages.
- `contract_verified`: executable contract selected, or metadata-only reason
  recorded.
- `upload_contract_applied`: upload used the analyzed metadata payload.
- `canonical_units_enabled`: indexing is allowed to build reference units.

These stages should be data-driven from existing metadata and job result fields
where possible. The UI should not hardcode a fixed stage list that breaks when
new stages are added; unknown stage ids should render as normal event rows with
their backend-provided labels.

## Error Handling

If analysis fails, upload is blocked and the error is shown in the upload panel.

If analysis succeeds but the contract is unverified, upload can proceed only as a
metadata-only or generic indexing path. Reference-unit chunking must not be
silently enabled.

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
- Extend `backend/tests/test_documents.py` to upload with a verified autosuggest
  payload and confirm the document stores the compiled index options.
- Extend `backend/tests/test_domain_metadata_contract_compiler.py` to confirm
  incomplete copied payloads still fail before job creation.

Frontend:

- Extend `frontend/tests/documents-page.test.tsx` to verify the upload mutation
  receives the exact `visionSuggestion.domain_metadata` object.
- Add a contract review rendering test for verified and metadata-only states.
- Add a file-change test confirming stale analysis is cleared and upload is
  disabled.

Pipeline/observability:

- Extend timeline tests so contract proposal, execution, verification, and
  upload application are visible when the relevant metadata exists.

## Implementation Handoff

This design should become an implementation plan with small, reviewable tasks:

1. Lock backend autosuggest output as an upload-ready contract package.
2. Add document upload/reindex regression tests for verified and incomplete
   handoff payloads.
3. Add frontend contract review panel and exact-payload tests.
4. Add document flow stages for the vision-to-upload contract handoff.
5. Run focused backend, frontend, and live upload validation.
