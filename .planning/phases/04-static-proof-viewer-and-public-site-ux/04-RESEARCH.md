---
phase: 04
slug: static-proof-viewer-and-public-site-ux
status: complete
created: 2026-05-14
---

# Phase 04 Research: Static Proof Viewer and Public Site UX

## Research Question

What does the planner need to know to implement the Phase 4 proof viewer well?

## Phase Boundary

Phase 4 is a static UI implementation in `/Users/meet/Documents/ragstudio-site`.
It replaces the current scaffold with a proof-first Technical Field Guide and
claim evidence viewer. It must keep the Phase 3 static-only boundary: no live
Ragstudio backend calls, no auth, no upload, no provider env vars, and no
Cloudflare/domain launch work.

## Inputs Available

- `src/data/proof-packet.generated.json` provides packet id, packet version,
  source commit, claim counts, claim summaries, evidence counts, limitations,
  and artifact paths.
- `src/data/proof-validation.generated.json` provides validation id/status,
  validator version, validation timestamp, and artifact validation results.
- `public/proof/ragstudio-oss-proof-v1/manifest.json` and
  `public/proof/ragstudio-oss-proof-v1/claims/claims.registry.json` provide
  public static packet metadata and full claim details.
- The source proof packet includes screenshot signoff at
  `docs/benchmarks/ragstudio-oss-proof-v1/screenshots/signoff.json`, with one
  approved screenshot.

## Implementation Findings

### Static Routing

Hash-based claim anchors are the lowest-risk routing approach for this phase.
They work on static hosting without server rewrites and satisfy deep-linking for
claim dossiers. A route such as `#claim-RAGSTUDIO-PARSER-GATE` is enough for
Phase 4.

### Data Shape

The generated packet summary is enough for the first viewport, proof summary,
and grouped claim list. Claim detail needs richer fields that currently live in
the static claims registry copy: evidence items, source code paths, disabled
reason, missing evidence, planned proof path, and screenshot ids. The plan should
either import/copy that registry into source data or add a local data module that
merges summary and registry fields without network calls.

### Raw Artifact Links

Only manifest and claims registry are currently copied into
`public/proof/ragstudio-oss-proof-v1/`. Artifact paths referenced by claims may
not exist in the static site yet. Phase 4 should render raw links with explicit
fallback states rather than broken assumptions. Copying all artifacts can be a
bounded task if planner wants full link availability, but the UI contract allows
fallback text.

### Screenshots

Screenshots are approved in the source proof packet, but the static site does
not currently contain the image file or signoff JSON. Phase 4 should import or
copy only the approved signoff metadata and approved image if available. It must
not capture new screenshots.

### Accessibility And Responsive Risk

The content contains long claim ids, commits, artifact paths, and issue URLs.
The implementation must use `overflow-wrap: anywhere`, stable layout tracks,
visible focus states, text-based status labels, and mobile single-column
dossiers to avoid overflow and WCAG regressions.

## Validation Architecture

The phase should validate both source contracts and built behavior.

### Automated Commands

- `cd /Users/meet/Documents/ragstudio-site && npm run check:static`
- `cd /Users/meet/Documents/ragstudio-site && npm run lint`
- `cd /Users/meet/Documents/ragstudio-site && npm test`
- `cd /Users/meet/Documents/ragstudio-site && npm run build`

### Test Coverage Targets

- App renders first viewport headline and exact CTA `Inspect the proof trail`.
- Claim groups render `Proven claims`, `Roadmap claims`, and `Disabled claims`.
- Claim detail exposes evidence dossier sections and non-proven claim language.
- Feedback link includes claim id, packet id, validation/source context, and
  viewer URL.
- Missing raw artifacts and screenshots show fallback copy instead of broken
  assumptions.

### Manual/Screenshot Checks

During execution, the implementer should run the site locally and inspect at
least one desktop and one mobile viewport. Phase 5 owns formal axe/Playwright
launch gates, but Phase 4 must avoid obvious overlap, horizontal overflow, or
missing focus states.

## Planning Implications

- Plan 04-01 should establish shared data/types, first viewport, proof summary,
  status grouping, and hash anchors.
- Plan 04-02 should build the claim dossier and evidence panels, including
  feedback links and raw artifact fallback behavior.
- Plan 04-03 should add approved screenshot rendering, responsive polish,
  fixture-loading fallbacks, and final verification coverage.

## Open Risks

- GitHub issue target may not be configured yet. Use a configurable constant or
  clear placeholder that does not block static build; Phase 5 can replace it
  with the final public repository URL.
- The static site currently lacks copied raw artifacts and screenshot images.
  The UI must fail gracefully unless execution adds a bounded copy step.
