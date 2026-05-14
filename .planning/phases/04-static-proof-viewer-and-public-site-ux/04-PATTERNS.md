---
phase: 04
slug: static-proof-viewer-and-public-site-ux
status: complete
created: 2026-05-14
---

# Phase 04 Pattern Map

## Scope

Map Phase 4 implementation targets to current code patterns in
`/Users/meet/Documents/ragstudio-site` and upstream proof packet artifacts.

## Planned Files And Closest Analogs

| Planned File | Role | Closest Existing Analog | Pattern To Preserve |
|--------------|------|-------------------------|---------------------|
| `/Users/meet/Documents/ragstudio-site/src/App.tsx` | Static proof viewer shell and route/anchor composition | Current `src/App.tsx` scaffold | Import static JSON at module top, render without network setup, keep accessible sections |
| `/Users/meet/Documents/ragstudio-site/src/styles.css` | Global layout, typography, responsive proof-viewer styling | Current `src/styles.css` scaffold | Plain CSS, root tokens, responsive media queries, stable grids |
| `/Users/meet/Documents/ragstudio-site/tests/app.test.tsx` | UI behavior tests | Current scaffold smoke test | Testing Library render assertions with no backend mocks |
| `/Users/meet/Documents/ragstudio-site/src/data/proof-packet.generated.json` | Imported summary data | Generated Phase 3 data | Treat as static source; do not hand-edit unless importer changes |
| `/Users/meet/Documents/ragstudio-site/src/data/proof-validation.generated.json` | Imported validation data | Generated Phase 3 data | Use validation status/id/timestamp for proof summary and feedback |
| `/Users/meet/Documents/ragstudio-site/public/proof/ragstudio-oss-proof-v1/claims/claims.registry.json` | Rich claim details | Source claims registry | Use for evidence, source paths, disabled/roadmap details if needed |
| `/Users/meet/Documents/ragstudio-site/scripts/check-static-boundary.mjs` | Static-only guard | Phase 3 guard script | Continue running after each UI slice |

## Data Flow Pattern

1. Static generated JSON imports provide safe summary and validation data.
2. Claim ids connect summary data to richer static registry details.
3. Rendered links point to `/proof/ragstudio-oss-proof-v1/...` paths.
4. Missing files produce visible fallback copy rather than network lookups.
5. Feedback URLs encode proof context and leave the site as a normal link.

## Styling Pattern

- Keep CSS centralized unless component complexity clearly demands modules.
- Use page bands, rules, and dense but readable proof metadata instead of nested
  decorative cards.
- Reserve accent colors for status, focus, links, and validation states.
- Use `overflow-wrap: anywhere` for commits, claim ids, artifact paths, and URLs.

## Testing Pattern

- Prefer Testing Library assertions for visible copy, landmarks, links, and
  section labels.
- Add source-like assertions through rendered output: exact CTA, all three
  status groups, detail evidence headings, feedback URL query content, fallback
  text.
- Keep tests backend-free and network-free.

## Landmines

- Do not import from `/Users/meet/Documents/Ragstudio/frontend`.
- Do not add live `/api`, auth, upload, provider env vars, or fetch calls.
- Do not imply roadmap/disabled claims are proven.
- Do not render unapproved screenshots.
- Do not rely on Cloudflare/domain/GitHub repository setup in Phase 4.
