---
phase: 04
slug: static-proof-viewer-and-public-site-ux
status: approved
shadcn_initialized: false
preset: none
created: 2026-05-14
---

# Phase 04 — UI Design Contract

> Visual and interaction contract for the static public proof viewer. Generated
> by the Phase 4 UI workflow and verified inline against the six UI quality
> dimensions.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none |
| Preset | not applicable |
| Component library | none |
| Icon library | none for Phase 4 unless installed deliberately during planning |
| Font | Inter fallback stack: `Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif` |

Use plain React components and CSS in `/Users/meet/Documents/ragstudio-site`.
Do not add a UI kit unless planning proves it reduces implementation risk.

---

## Product Shape

The page is a static Technical Field Guide, not a SaaS dashboard and not a
marketing landing page. The first viewport introduces the proof system and moves
visitors to the evidence instrument. The proof viewer then behaves like a
structured dossier browser.

### Required Flow

1. First viewport with proof-first story and primary CTA.
2. Static proof summary showing packet id, validation status, claim counts, and
   source commit.
3. Status-grouped claim list with `Proven`, `Roadmap`, and `Disabled` sections.
4. Claim dossier route/section for each claim.
5. Evidence panels grouped by evidence type.
6. Feedback link with pre-filled GitHub issue context.
7. Approved screenshot rendering plus fallback text for missing static files.

---

## Layout Contract

| Surface | Layout |
|---------|--------|
| Page shell | Full-width page with constrained inner content, max width 1120px |
| First viewport | Unframed editorial layout, no nested cards, next section partially visible on common desktop/mobile heights |
| Proof summary | Compact metric row or responsive grid, separated by rules rather than decorative cards |
| Claim list | Status-grouped sections; each claim row/card has stable spacing and does not change height on hover |
| Claim detail | Dossier layout with sticky or top summary on desktop; single column on mobile |
| Evidence panels | Sectioned by evidence type with stable headings, artifact link rows, and fallback states |
| Feedback | Inline action near claim detail metadata and raw artifact rows |

Do not create a separate marketing hero with stock imagery, gradient blobs, or
decorative illustration. Visual interest should come from typography, rules,
status language, structured proof metadata, and approved screenshots.

---

## Spacing Scale

Declared values are multiples of 4:

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | Inline icon/text gaps, compact metadata separators |
| sm | 8px | Label-to-value spacing, status badge padding |
| md | 16px | Default component gaps and mobile padding |
| lg | 24px | Claim row padding, evidence panel padding |
| xl | 32px | Section gaps, desktop component gutters |
| 2xl | 48px | First viewport content breaks, major section breaks |
| 3xl | 64px | Desktop page bands and proof-viewer region breaks |

Exceptions: none.

---

## Typography

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Body | 16px | 400 | 1.6 |
| Label | 13px | 700 | 1.3 |
| Small metadata | 13px | 500 | 1.45 |
| Heading | 28px | 750 | 1.15 |
| Section heading | 20px | 750 | 1.25 |
| Display | clamp(44px, 8vw, 88px) | 800 | 0.98 |

Letter spacing must remain `0`. Do not scale body or label text with viewport
width. Long claim ids, commits, artifact paths, and URLs must use
`overflow-wrap: anywhere`.

---

## Color

The palette should feel like a public technical field guide: warm neutral paper,
ink, muted green/teal proof signals, amber caution, and red disabled/error
signals. Avoid one-note purple, beige-only, dark neon, terminal, or card-heavy
SaaS palettes.

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `#f6f7f4` | Page background |
| Primary ink | `#182026` | Main text |
| Secondary ink | `#45545c` | Body copy and summaries |
| Rule | `#c9d2ca` | Dividers, table borders, panel boundaries |
| Secondary surface (30%) | `#ffffff` | Dossier panels and claim rows only |
| Proven accent | `#1f7a5f` | Proven status, validation passed state |
| Roadmap accent | `#9a6a16` | Roadmap status and missing evidence |
| Disabled accent | `#8f3d3d` | Disabled status and unavailable features |
| Link accent | `#125d7c` | Text links, raw artifact links, feedback links |
| Focus ring | `#0d6b8a` | Keyboard focus outline |
| Destructive | `#a03232` | Error and invalid static-build states only |

Accent reserved for: status badges, primary CTA, text links, focus rings, and
validation states. Do not use accent color as a generic decorative wash.

---

## Copywriting Contract

| Element | Copy |
|---------|------|
| Primary CTA | `Inspect the proof trail` |
| First viewport label | `Ragstudio proof system` |
| First viewport headline | `Inspect RAG evidence before retrieval failures become answers.` |
| First viewport body | `A static proof viewer for parser warnings, chunk evidence, retrieval traces, graph and reranker states, screenshots, source commit, and known limitations.` |
| Proven section heading | `Proven claims` |
| Roadmap section heading | `Roadmap claims` |
| Disabled section heading | `Disabled claims` |
| Claim detail heading pattern | `{claim title}` |
| Missing raw artifact fallback | `Not available in this static build.` |
| Missing screenshot fallback | `Screenshot is listed in the proof packet but is not available in this static build.` |
| Empty state heading | `No claims in this status yet` |
| Empty state body | `The imported proof packet has no claims for this section.` |
| Error state | `The imported proof data could not be rendered. Re-run npm run import:proof and npm run build.` |
| Feedback link | `Open feedback issue` |
| Destructive confirmation | Not applicable — Phase 4 has no destructive actions |

Do not include visible instructional text about how to use the UI. Copy should
explain the proof content, not the interface mechanics.

---

## Interaction Contract

### Navigation

- The primary CTA scrolls or routes to the proof viewer region.
- Claim rows link to deep-linkable claim dossiers.
- Deep links must work through static hosting. A hash route such as
  `#claim-RAGSTUDIO-PARSER-GATE` is acceptable and preferred if it keeps the
  build simple.

### Claim List

- Group by exact status values: `proven`, `roadmap`, `disabled`.
- Preserve the visibility of all statuses even when a group has zero items.
- Roadmap and disabled claims must use distinct color/copy so they cannot be
  mistaken for proven claims.

### Claim Detail

- Use the evidence dossier structure:
  - Summary
  - Status and validation context
  - Limitations or disabled reason
  - Evidence panels by type
  - Source commit and code path context when present
  - Raw artifact links and fallback text
  - Feedback link
- If imported summary data lacks detailed evidence fields, read from the static
  claims registry copy in `public/proof/.../claims/claims.registry.json` at
  build/runtime only as a static asset or extend import output during execution.

### Feedback

- Use a pre-filled GitHub issue URL.
- Include claim id, artifact path when available, packet id, validation id or
  packet hash context when available, source commit, and viewer URL.
- The link must be usable without JavaScript network calls to the Ragstudio
  backend.

---

## Accessibility Contract

| Area | Requirement |
|------|-------------|
| Landmarks | Use `main`, `section`, and heading hierarchy in document order |
| Keyboard | Every link/button must be keyboard reachable with visible focus |
| Focus | Use a 2px or stronger focus outline using `#0d6b8a`; do not rely on color fill alone |
| Contrast | Body text, status labels, CTA, and links must meet WCAG 2.2 AA contrast |
| Status | Status meaning must be conveyed by text plus color, never color alone |
| Responsive | No horizontal scrolling at 320px viewport width except intentional code/path wrapping |
| Motion | No required animation; any hover/focus transition must be under 180ms and non-essential |
| Screenshots | Every rendered screenshot needs meaningful alt text based on signoff notes |

Phase 5 owns automated axe/Playwright launch gates, but Phase 4 implementation
must be designed so those checks can pass without reworking the UI.

---

## Screenshot Contract

- Render only screenshots listed in
  `docs/benchmarks/ragstudio-oss-proof-v1/screenshots/signoff.json` or imported
  static equivalents.
- Do not capture new screenshots in Phase 4.
- Each screenshot display must show:
  - Screenshot id
  - Affected claim ids
  - Human reviewer
  - Reviewed timestamp
  - Safe-to-publish state
  - Alt text or caption derived from signoff notes
- If the static image file is not copied into `public/proof/...`, show the
  missing screenshot fallback copy instead of a broken image.

---

## Raw Artifact Contract

- Static links should use `/proof/ragstudio-oss-proof-v1/<artifact_path>`.
- Existing copied files may be linked directly.
- Artifact paths referenced by claims but not present under `public/proof/` must
  show `Not available in this static build.`
- Do not inline large JSON previews in Phase 4 unless planning explicitly adds a
  bounded preview task and tests text overflow.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | none | not required |
| third-party registry | none | not allowed in Phase 4 without explicit planning task and review |

No remote design registry blocks are approved for this phase.

---

## Verification Expectations

The Phase 4 plan should include verification through:

- `cd /Users/meet/Documents/ragstudio-site && npm run check:static`
- `cd /Users/meet/Documents/ragstudio-site && npm run lint`
- `cd /Users/meet/Documents/ragstudio-site && npm test`
- `cd /Users/meet/Documents/ragstudio-site && npm run build`
- Browser or screenshot review during execution for desktop and mobile layout
  once the UI exists

---

## Checker Sign-Off

- [x] Dimension 1 Copywriting: PASS
- [x] Dimension 2 Visuals: PASS
- [x] Dimension 3 Color: PASS
- [x] Dimension 4 Typography: PASS
- [x] Dimension 5 Spacing: PASS
- [x] Dimension 6 Registry Safety: PASS

**Approval:** approved 2026-05-14
