# Phase 4: Static Proof Viewer and Public Site UX - Context

**Gathered:** 2026-05-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 4 turns the imported static proof fixtures in
`/Users/meet/Documents/ragstudio-site` into the public proof-viewer experience.
A skeptical visitor should land on a proof-first Technical Field Guide, follow
the `Inspect the proof trail` CTA, scan honest claim statuses, open a claim
dossier, inspect evidence grouped by type, follow raw static artifact links, and
send feedback with enough context to reproduce what they saw.

This phase owns the first viewport, navigation, static routing, claim list,
claim detail views, evidence panels, feedback deep links, approved screenshot
rendering, responsive polish, and static raw-artifact fallback behavior. It does
not configure Cloudflare Pages, connect the public domain, add public CI launch
gates, or make a live backend/upload/auth/provider surface; those remain Phase 5
or v2 work.

</domain>

<decisions>
## Implementation Decisions

### First Viewport And Story
- **D-01:** The first viewport should use a proof-first Technical Field Guide
  direction, not a generic SaaS landing page or evidence dashboard first. Lead
  with the idea that Ragstudio makes RAG evidence inspectable before retrieval
  failures become answers.
- **D-02:** The primary CTA text remains exactly `Inspect the proof trail`.
  The CTA should move the visitor from the short public story into the static
  proof viewer.
- **D-03:** The first viewport should preserve the approved project direction:
  short product story first, proof trail as the trust moment, no dark/neon/
  terminal aesthetic, and no hidden upload/auth/live demo promises.

### Claim List
- **D-04:** Claims should be grouped by status, with separate visible sections
  for `Proven`, `Roadmap`, and `Disabled`. Honesty about non-proven claims is a
  core part of the UX.
- **D-05:** Claim cards/rows should expose claim title, status, summary,
  evidence count when available, limitations/missing-evidence cues, and a route
  to the claim dossier.
- **D-06:** Roadmap and disabled claims must remain visible. The UI must not
  make roadmap or disabled claims look proven.

### Claim Detail
- **D-07:** Claim detail views should use an evidence-dossier structure with
  clear sections for summary, proof status, limitations, evidence artifacts, raw
  links, and source commit context.
- **D-08:** Evidence inside a claim detail should be grouped by evidence type:
  parser warning/unit, chunk/source, retrieval trace, graph/reranker, screenshot,
  and raw artifact.
- **D-09:** The detail view should support both proven claims and non-proven
  claims. For roadmap claims, show missing evidence and planned proof path; for
  disabled claims, show disabled reason and requirements to prove.

### Feedback And Deep Links
- **D-10:** Feedback links should be pre-filled GitHub issue URLs rather than
  mailto or copy-only buttons in Phase 4.
- **D-11:** Feedback links must include enough static proof context to be useful:
  claim id, artifact path when applicable, packet id/hash or validation context,
  source commit, and viewer URL.
- **D-12:** Claim URLs should be deep-linkable so a visitor can share or return
  directly to a claim dossier.

### Screenshots And Raw Artifacts
- **D-13:** Phase 4 should render only screenshots that are already approved in
  the proof packet/signoff records. Do not capture or introduce new unapproved
  local app screenshots in this phase.
- **D-14:** Raw artifact links should point to static paths under the imported
  proof packet, such as `/proof/<packet>/...`.
- **D-15:** When a raw artifact or screenshot is not present in the static site
  build, the viewer should show clear fallback text such as `not available in
  this static build` rather than broken or misleading links.

### the agent's Discretion
- The agent may choose exact React component boundaries, route library or
  hash-routing approach, local type definitions, CSS structure, and test naming
  after researching the existing `ragstudio-site` scaffold.
- The agent may choose the exact visual layout within the Technical Field Guide
  direction as long as the result is static, accessible, responsive, proof-first,
  and avoids inflated claims.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Scope
- `.planning/PROJECT.md` - Public launch definition, Technical Field Guide
  direction, static proof viewer constraint, first-viewport CTA, and launch
  boundaries.
- `.planning/REQUIREMENTS.md` - Phase 4 requirement IDs `VIEW-01` through
  `VIEW-07`, including static viewer, claim scan, claim detail, feedback links,
  screenshots, and signoff requirements.
- `.planning/ROADMAP.md` - Phase 4 goal, success criteria, dependency on Phase
  3, and three planned slices.
- `.planning/STATE.md` - Current project status and Phase 4 readiness.

### Prior Phase Handoff
- `.planning/phases/01-proof-contract-and-baseline-packet/01-CONTEXT.md` -
  Proof packet structure, claim honesty rules, synthetic corpus, and public
  safety decisions.
- `.planning/phases/01-proof-contract-and-baseline-packet/01-VERIFICATION.md` -
  Evidence that the proof packet, claims, screenshots, and signoff records exist.
- `.planning/phases/02-replay-and-export-tooling/02-VERIFICATION.md` -
  Evidence that proof validation and strict JSON replay are complete.
- `.planning/phases/03-ragstudio-site-scaffold-and-import-pipeline/03-CONTEXT.md`
  - Site boundary, import gate, and static-only decisions that Phase 4 must
  preserve.
- `.planning/phases/03-ragstudio-site-scaffold-and-import-pipeline/03-VERIFICATION.md`
  - Evidence that `ragstudio-site` imports static proof data and passes
  static-boundary checks.

### Site Source
- `/Users/meet/Documents/ragstudio-site/package.json` - Site scripts and
  dependency surface.
- `/Users/meet/Documents/ragstudio-site/src/App.tsx` - Current static scaffold
  entrypoint to replace or extend.
- `/Users/meet/Documents/ragstudio-site/src/styles.css` - Current global style
  baseline.
- `/Users/meet/Documents/ragstudio-site/src/data/proof-packet.generated.json` -
  Imported claim summaries and artifact paths currently available to the site.
- `/Users/meet/Documents/ragstudio-site/src/data/proof-validation.generated.json`
  - Imported validation result with packet status and artifact validation state.
- `/Users/meet/Documents/ragstudio-site/public/proof/ragstudio-oss-proof-v1/manifest.json`
  - Public static manifest copy available to viewer links.
- `/Users/meet/Documents/ragstudio-site/public/proof/ragstudio-oss-proof-v1/claims/claims.registry.json`
  - Public static claims registry copy available to viewer links.
- `/Users/meet/Documents/ragstudio-site/scripts/check-static-boundary.mjs` -
  Guardrail that Phase 4 must continue to pass.

### Proof Packet Source
- `docs/benchmarks/ragstudio-oss-proof-v1/manifest.json` - Source manifest with
  approved screenshot counts, artifact hashes, and packet metadata.
- `docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.registry.json` - Source
  claim registry with proven, roadmap, and disabled claim details.
- `docs/benchmarks/ragstudio-oss-proof-v1/screenshots/signoff.json` -
  Screenshot signoff record that defines which screenshots may appear publicly.

### Codebase Map
- `.planning/codebase/STACK.md` - React/Vite/TypeScript stack and test tooling.
- `.planning/codebase/STRUCTURE.md` - Existing repo and static/public asset
  conventions.
- `.planning/codebase/CONVENTIONS.md` - TypeScript, naming, and frontend
  testing conventions.
- `.planning/codebase/TESTING.md` - Existing frontend/unit/e2e testing patterns
  useful for Phase 4 verification.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `/Users/meet/Documents/ragstudio-site/src/data/proof-packet.generated.json`
  already contains packet id, packet version, source commit, claim counts, claim
  summaries, evidence counts, limitations, and artifact paths.
- `/Users/meet/Documents/ragstudio-site/src/data/proof-validation.generated.json`
  already contains the validation id/status, validator version, artifact
  validation results, and validation timestamp.
- `/Users/meet/Documents/ragstudio-site/public/proof/ragstudio-oss-proof-v1/`
  currently contains manifest and claims registry copies. Phase 4 can link to
  these static files now, while showing fallbacks for artifacts not copied yet.
- `scripts/check-static-boundary.mjs` protects the static-only boundary and
  should remain part of Phase 4 verification.

### Established Patterns
- The sibling site is a Vite React TypeScript app with Vitest, Testing Library,
  ESLint, static JSON imports, and a simple global CSS file.
- The site is intentionally separate from the Ragstudio app frontend; it should
  not import `../Ragstudio/frontend`, generated API clients, upload/auth routes,
  provider env vars, or live backend calls.
- Existing proof vocabulary is stable: proof packet, proof viewer, proof trail,
  proof replay, proof errors, claim id, artifact path, source commit,
  limitation.

### Integration Points
- Main implementation path: `/Users/meet/Documents/ragstudio-site`.
- Static fixture imports: `src/data/proof-packet.generated.json` and
  `src/data/proof-validation.generated.json`.
- Static public proof paths: `/proof/ragstudio-oss-proof-v1/manifest.json` and
  `/proof/ragstudio-oss-proof-v1/claims/claims.registry.json`.
- Verification commands should include `npm run check:static`, `npm run lint`,
  `npm test`, and `npm run build` from `/Users/meet/Documents/ragstudio-site`.

</code_context>

<specifics>
## Specific Ideas

- Use `Inspect the proof trail` as the exact primary CTA text.
- Present claims in separate `Proven`, `Roadmap`, and `Disabled` sections.
- Use dossier-like claim detail pages rather than a raw JSON-first explorer.
- Group evidence panels by evidence type: parser warning/unit, chunk/source,
  retrieval trace, graph/reranker, screenshot, and raw artifact.
- Use pre-filled GitHub issue links for feedback, carrying proof context.
- Use only screenshots already approved by the packet/signoff records.
- Show explicit fallback text when static raw artifacts or screenshots are not
  available in the current build.

</specifics>

<deferred>
## Deferred Ideas

- Cloudflare Pages, GitHub deployment wiring, public domain connection, public
  CI launch gates, and README/profile links remain Phase 5.
- Public upload, authentication, hosted read-only API demo, and live provider
  demo remain out of scope for v1.
- New screenshot capture from the local app is deferred unless a later phase adds
  explicit screenshot capture and manual signoff work.

</deferred>

---

*Phase: 4-Static Proof Viewer and Public Site UX*
*Context gathered: 2026-05-14*
