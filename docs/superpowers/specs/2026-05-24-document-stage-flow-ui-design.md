# Document Stage Flow UI Design

Date: 2026-05-24
Status: Approved for implementation planning

## Problem

Ragstudio records document indexing progress, MinerU state, contract decisions,
chunk persistence, parser warnings, and quality-gate outcomes, but the UI does
not yet show the actual path a document traveled through the pipeline in one
place. During the Quran Arabic-English upload, the user had to ask for repeated
manual monitoring to understand that the file was uploaded, vision metadata was
suggested, the executable reference contract stayed unverified, MinerU validated
the parse artifacts, chunks were being persisted, and warnings were coming from
script/layout quality gates rather than unresolved reference enforcement.

The UI should make that channel visible directly on the document evidence
surface.

## Decision

Use the approved A+C visual direction:

- A compact stage rail summarizes the current document path at a glance.
- A flow map shows the ordered stages the document actually passed through.
- A selected-stage inspector explains the active or selected stage using the
  persisted evidence, contract state, and warning summary.
- A stage event ledger keeps the chronological audit trail available without
  making it the primary visual surface.

The compact rail belongs in document list/detail contexts. The full flow map,
ledger, and inspector belong in the document evidence view.

## User Experience

On the Documents page or document header, each active/recent document shows a
compact rail with stage status. The baseline flow is:

1. Upload
2. Vision
3. Contract
4. Parser
5. Chunks
6. Quality gates
7. Materialization
8. Proof/readiness

These baseline stages are product vocabulary, not a frontend hardcoded list.
The backend stage contract owns the ordered stages for each document. If a
future pipeline adds, removes, renames, or skips a stage, the backend returns
the revised ordered list and the UI renders it generically. The frontend may
have optional icon/color mappings for known stage ids, but unknown stage ids
must still render with a neutral fallback label, status, and detail panel.

Each returned stage has a visible state such as `pending`, `running`,
`complete`, `warning`, `blocked`, `skipped`, or `metadata_only`. The rail must
also show the current stage label and a short progress detail, for example
`Persisted 4500 of 17699 canonical chunks`.

In the document evidence view, the user sees:

- Left: actual flow map with the same stages, ordered by what happened for the
  selected document.
- Center: stage event ledger with persisted timestamps/logs, contract decisions,
  warning counts, and chunk counts.
- Right: selected-stage inspector with the evidence for the currently selected
  stage.

The default selected stage is the active stage while a job is running. For a
completed job, default to the most severe stage state: blocked first, then
warning, then metadata-only/unverified, then complete.

## Stage Inspector Content

The inspector should explain each stage using concrete persisted fields, not
derived frontend guesses.

Upload:

- Document id, filename, content type, upload status, artifact path, and backend
  file existence when available.

Vision:

- Domain, document type, language, confidence, evidence pages, sample pages, and
  metadata source such as `ai_vision`.

Contract:

- `contract_status`, `reference_contract.verified`,
  `reference_contract.canonical_units`, schema type, repair status, validation
  status, matched units, selected strategy, and rejection reasons.
- If a contract is unverified, explicitly say it is kept as retrieval/display
  hint and is not used for enforcement.

Parser:

- Parser mode, MinerU job status, parse method, artifact references, page/chunk
  counts, and parse validation messages.

Chunks:

- Canonical chunk target count, persisted count, current progress, and latest
  job log.

Quality gates:

- Warning groups by code, severity/action, expected script, chunk count, and
  examples.
- Distinguish verified-contract enforcement warnings from independent script,
  table, layout, OCR, and equation warnings.

Materialization:

- Vector/native/runtime/graph eligibility and any blocked lanes, when those
  fields are available.

Proof/readiness:

- Whether the document has enough completed evidence for later proof export or
  query inspection. This is a local readiness signal, not a public launch claim.

## Data Flow

The UI should consume existing live data first:

- `GET /api/documents?limit=5&offset=0`
- `GET /api/jobs?limit=5&offset=0`
- `GET /api/documents/{document_id}/parse-evidence`

If these endpoints do not already expose a normalized document stage contract,
add a backend assembler that returns one. The assembler should derive stage
state from persisted document rows, job result fields, job logs, index contract,
chunk counts, parser evidence, and warning summaries. React should render the
stage contract and must not re-parse raw logs or metadata JSON to reconstruct
pipeline semantics.

The stage contract should include:

- Document identity and status.
- Current job identity, progress, latest log, and stage.
- Ordered stage summaries with stable `id`, display `label`, state, optional
  order, and fallback display metadata.
- Ordered stage events.
- Per-stage detail payloads.
- Warning summary with stable warning codes.
- Contract summary with verification and repair/validation fields.
- Missing-data markers for unavailable sections.

Stage contract compatibility rules:

- Adding a stage: backend emits the new stage in the ordered list; existing UI
  renders it with generic fallback if no custom renderer exists.
- Removing or skipping a stage: backend omits it or returns it as `skipped`;
  frontend does not assume every baseline stage exists.
- Renaming a stage: keep the stable `id` and change only the display `label`
  unless the semantics changed.
- Changing semantics: introduce a new `id` or contract version so historical
  documents remain interpretable.
- Historical documents: render the stage list persisted or reconstructed for
  that document/job, not the latest global pipeline definition.

## Error Handling

- If the backend/API is unavailable, show the last known document status if
  present and mark live stage data unavailable.
- If a stage section is missing, show `Evidence unavailable` for that section
  and name the missing source, such as job result, parse evidence, or chunk
  warning summary.
- If the contract is metadata-only, do not show it as a failed verified
  contract. Show it as an unverified hint.
- If warning counts are still changing while chunks persist, label them as
  partial.
- If job progress and persisted chunk count disagree, show both values and
  avoid hiding the mismatch.

## Non-Goals

- Do not implement a generic marketing pipeline diagram.
- Do not make the frontend infer domain-specific contract rules from raw
  metadata.
- Do not change quality-gate enforcement as part of this UI work.
- Do not claim proof-packet/public readiness from a running local job.
- Do not expose raw private document content in the stage inspector beyond the
  existing local evidence-preview limits.

## Acceptance Criteria

- A running upload shows a compact rail with the current stage and progress.
- The document evidence view shows the actual ordered stage flow for the
  selected document.
- Adding, omitting, or skipping a stage in the backend stage contract does not
  require React component changes unless a custom stage-specific renderer is
  desired.
- The contract stage clearly distinguishes verified executable contracts from
  metadata-only hints.
- The warning section shows grouped warning counts and keeps
  `reference_unit_unresolved` separate from script/layout/equation warnings.
- The UI can show the Quran upload shape: metadata-only `chapter_verse`,
  `verified=false`, `canonical_units=false`, repair/validation unverified,
  matched units `0`, chunk persistence progress, and warning counts.
- Missing or unavailable evidence is explicit and does not collapse into an
  empty success state.
- The UI remains usable on desktop and mobile without overlapping text or
  horizontally overflowing controls.

## Testing

Backend tests:

- Stage assembler maps document/job/index-contract fields into stable stage
  states.
- Metadata-only unverified contracts produce a contract stage warning/hint, not
  a verified-contract failure.
- Warning summaries keep `reference_unit_unresolved` separate from independent
  script/layout/equation warnings.
- Running jobs mark warning counts and chunk counts as partial.

Frontend tests:

- Documents page renders the compact rail for running and completed documents.
- Document evidence page renders flow map, ledger, and selected-stage inspector.
- Selecting a stage changes the inspector content.
- Contract inspector shows verified/unverified states accurately.
- Missing stage details render explicit unavailable states.

Browser checks:

- Desktop evidence view: stage rail, flow map, ledger, and inspector are visible
  without overlap.
- Mobile evidence view: rail wraps or scrolls predictably, and inspector content
  remains readable.

## Implementation Planning Notes

The implementation plan should start by checking the existing parse-evidence
response and job `indexing_stage_events` payload. If those are sufficient, keep
the backend change small and add a typed frontend adapter. If they are not
sufficient, add a normalized backend stage assembler first so the UI renders a
stable contract instead of coupling directly to raw job logs and JSON metadata.
