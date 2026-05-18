# Document Parse Evidence Inspector Design

## Purpose

Build a shared Evidence Inspector for document-parse evidence. The first evidence
object is a document parse: parser blocks, semantic page-boundary stitching,
normalization decisions, modal extraction, parser and quality warnings, and final
chunk materialization.

The design supports two hosts:

- Local Studio: interactive debugging for uploaded documents and indexing jobs.
- Public proof viewer: sanitized, read-only proof-packet rendering for the
  open-source launch site.

This keeps Ragstudio as the source of truth while letting public claims trace to
replayable evidence, source commit, raw artifact references, and known
limitations.

## Goals

- Make document-parse failures inspectable before bad chunks reach retrieval.
- Show how raw parser blocks become normalized semantic units and final chunks.
- Make page-boundary stitching visible as an explicit decision, not an invisible
  text transformation.
- Reuse the same evidence components in Local Studio and the public proof viewer.
- Keep public output safe: no API keys, private endpoints, private hostnames,
  local absolute paths, unpublished model hosts, or private content.

## Non-Goals

- Do not build a separate marketing feature grid.
- Do not replace the existing Graph page or Comparison page.
- Do not require live provider access for public proof validation.
- Do not infer lineage in React by re-parsing displayed text.
- Do not make query-run trace simulation the first implementation target. Query
  run evidence can reuse this pattern later.

## Architecture

The inspector is a shared presentation layer with host-specific data adapters.

Local Studio host:

- Lives inside the existing app, likely near Documents or Chunks.
- Fetches live document, job, parser warning, chunk, and artifact metadata.
- Enables filters, selection, replay/reindex links, and local debugging actions.

Public proof-viewer host:

- Lives in the future public `ragstudio-site` static proof viewer.
- Imports exported proof-packet JSON.
- Renders the same evidence model in read-only mode.
- Shows raw artifact links only when those artifacts are sanitized and bundled in
  the proof packet.

Shared components:

- `EvidenceInspector`
- `EvidenceRail`
- `BlockDiffPanel`
- `QualityWarningPanel`
- `ChunkMaterializationPanel`
- `ProofMetadataPanel`

These components consume a normalized document-parse evidence contract. They do
not call product APIs directly.

## Evidence Contract

Introduce a normalized evidence object, tentatively named
`DocumentParseEvidence`. The exact API schema can be refined during planning,
but the design intent is stable: the UI renders reviewable decisions and their
lineage.

Core fields:

- `document`: sanitized document id, filename, content type, page count, and
  parser mode.
- `sourceArtifacts`: safe artifact ids, relative proof-packet paths, checksums,
  and capped preview availability.
- `parserBlocks`: ordered raw or normalized blocks with page, block index, type,
  text preview, safe bbox data, modality, and warnings.
- `normalizationDecisions`: decisions such as `page_stitch`, `modal_route`,
  `script_recovery`, and `quality_gate`, each linked to input block ids and
  output chunk ids.
- `chunks`: final materialized chunks with page range, reference metadata,
  modality, quality status, and artifact lineage.
- `warnings`: parser and quality warnings grouped by severity, page, block,
  decision, and affected chunk.
- `proof`: source commit, proof packet id, fixture/static-vs-live mode, replay
  command, limitations, and redaction summary.

Rule: lineage is derived once by backend/export code. React renders the contract
and must not reconstruct lineage by parsing visible text.

## UI Design

Use the Evidence Inspector layout selected during brainstorming.

Left rail:

- Lists reviewable issues and decisions.
- Examples: `Page 1 -> 2 stitch`, `Table extraction`, `Missing script warning`,
  `Chunk blocked by quality gate`.
- Local Studio supports filters by severity, page range, modality, and decision
  type.
- Public proof viewer supports simple read-only filtering and anchors.

Center panel:

- Shows the selected evidence detail.
- `Source blocks`: parser blocks involved in the selected decision.
- `Normalized unit`: the semantic unit Ragstudio produced after stitching,
  routing, or recovery.
- `Chunk output`: final chunk or chunks, quality state, page/reference metadata,
  and materialization status.

Right panel:

- Shows proof metadata.
- Includes artifact references, source commit, replay command, limitations, and
  redaction status.

The Diff Viewer is embedded inside the selected evidence detail. It is not a
separate page. Each diff stays tied to one decision and its proof metadata.

## Backend And Export Flow

Add a backend/export layer that produces `DocumentParseEvidence` after parsing
or indexing.

Local API:

- Add an endpoint such as `GET /api/documents/{id}/parse-evidence`.
- Assemble evidence from document rows, jobs, chunks, parser warnings,
  parser metadata, graph projection records where relevant, and artifact
  metadata.
- Return missing sections explicitly so the UI can show clear incomplete-state
  messages.

Public proof export:

- Write a sanitized JSON artifact into the proof packet, for example
  `artifacts/document-parse-evidence.export.json`.
- Strip or rewrite unsafe values: local absolute paths, private hostnames,
  provider URLs, API keys, raw private content beyond allowed fixture previews,
  and unpublished model hosts.
- Include a redaction summary so reviewers can distinguish absent evidence from
  intentionally redacted evidence.

Static validation:

- Validate that exported proof packets contain no unsafe path, host, or key
  patterns.
- Validate that every displayed public claim links to at least one evidence
  object or limitation.
- Validate that static fixtures are enough to render the proof viewer without
  private providers.

## Error Handling

- If evidence is incomplete, show `Evidence unavailable` and name the missing
  contract section.
- If artifact previews are capped, show hidden counts and a raw artifact link.
- If public export redacts content, show a redaction note rather than silently
  omitting it.
- If lineage is ambiguous, mark the decision `unresolved` and link it to the
  relevant limitation.
- If a local API call fails, preserve the selected rail state and show a retry
  action in the affected panel only.

## Accessibility

- The evidence rail is keyboard-navigable.
- Use `aria-current` for the selected decision.
- Each center-panel section is a labelled region.
- Diff rows do not rely on color alone. Use labels such as `Removed`, `Added`,
  `Unchanged`, and `Blocked`.
- Public/mobile proof viewer touch targets are at least 44px high.
- Tables and JSON previews scroll inside bounded regions.
- Raw artifact links, source commit links, and replay instructions remain
  reachable by keyboard.

## Testing

Backend tests:

- Contract assembly for page-stitch lineage.
- Contract assembly for modal extraction lineage.
- Warning grouping by severity, page, block, decision, and chunk.
- Redaction and unsafe-value stripping for proof export.
- Missing-section output for incomplete evidence.

Frontend tests:

- Rail selection renders the matching source blocks, normalized unit, chunk
  output, and proof metadata.
- Diff rendering handles added, removed, unchanged, blocked, and capped rows.
- Missing evidence states are explicit.
- Public read-only mode hides local actions while preserving raw artifact and
  replay links.

Proof-packet tests:

- No unsafe paths, private hosts, provider URLs, or secret-shaped values leak.
- Static fixture validation renders without live providers.
- Every public claim rendered by the proof viewer links to evidence or a
  limitation.

Accessibility checks:

- Testing Library coverage for labelled regions and selected rail state.
- At least one Playwright keyboard-navigation pass through the inspector.

## Implementation Slices

1. Define `DocumentParseEvidence` backend schema and TypeScript generated
   contract.
2. Add local API assembly for one document parse with parser blocks, warnings,
   chunks, and page-stitch decisions.
3. Build shared read-only `EvidenceInspector` components against fixture data.
4. Mount the inspector in Local Studio with filters and local actions.
5. Add proof-packet export and redaction validation.
6. Mount the same inspector in the public proof viewer in read-only mode.

## Self-Review

- Completeness scan: all sections have concrete requirements and no open-ended
  requirement markers remain.
- Consistency check: the architecture, UI, backend export, and tests all depend
  on the same normalized evidence contract.
- Scope check: the design is focused on document-parse evidence only. Query-run
  trace simulation remains a later evidence object.
- Ambiguity check: the public proof viewer is read-only and static; Local Studio
  is interactive and live.
