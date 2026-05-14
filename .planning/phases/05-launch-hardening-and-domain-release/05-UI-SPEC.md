---
phase: 05
slug: launch-hardening-and-domain-release
status: approved
shadcn_initialized: false
preset: none
created: 2026-05-14
---

# Phase 05 — UI Design Contract

> Visual and interaction contract for launch hardening, accessibility checks, release gates, and public-domain amplifier links.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none |
| Preset | not applicable |
| Component library | none |
| Icon library | none required for Phase 05 |
| Font | Current static site font stack is acceptable for Phase 05; future visual polish should move toward DESIGN.md: Literata display, Source Sans 3 body, IBM Plex Mono data |

Phase 05 must not redesign the proof viewer. It hardens and verifies the existing
Phase 04 Technical Field Guide surface for public release on `https://ragstudio.dev`.

---

## Spacing Scale

Declared values must remain multiples of 4:

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | Icon gaps, metadata gaps |
| sm | 8px | Compact list and checklist spacing |
| md | 16px | Default content spacing, form/checklist item padding |
| lg | 24px | Release panel and evidence panel padding |
| xl | 32px | Major layout gaps |
| 2xl | 48px | Section breaks |
| 3xl | 64px | Desktop page-level spacing |

Exceptions: none.

Launch checklist and accessibility results may use compact spacing, but touch
targets and actionable links must remain at least 44px high on mobile.

---

## Typography

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Body | 16px minimum | 400-600 | 1.55-1.7 |
| Label | 12-14px | 600-700 | 1.3-1.45 |
| Heading | 20-32px | 700-800 | 1.15-1.3 |
| Display | 44-88px responsive clamp | 750-800 | 0.98-1.08 |
| Data / paths | 13-16px | 400-600 | 1.45-1.6 |

Typography requirements:

- No body text below 16px on public reading surfaces.
- Dense metadata may use 13-14px only for labels/captions, never for critical instructions.
- Long paths, hashes, URLs, Cloudflare ids, and artifact names must wrap or scroll inside bounded containers.
- Letter spacing must remain `0`; do not use negative letter spacing.

---

## Color

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `#fbfaf4` / current `#f6f7f4` acceptable | Page background and reading surface |
| Secondary (30%) | `#ffffff`, `#f0f4ef`, current border neutrals | Panels, launch checklist rows, evidence surfaces |
| Accent (10%) | `#0f766e` / current teal action color acceptable | Primary CTA, active proof links, launch-passed indicators |
| Destructive | `#8c2525` | Failed launch checks, blocking release status only |
| Warning | `#8a5a00` | Roadmap/partial/manual-review status only |
| Visited | `#5e4b8b` | Visited public links when browser supports state |

Accent reserved for:

- `Inspect the proof trail`
- `Open feedback issue`
- `Open raw artifact`
- `View source commit`
- Release status links/actions
- Active/selected proof navigation

Status colors must communicate check state; do not use red/amber/green as decoration.

---

## Copywriting Contract

| Element | Copy |
|---------|------|
| Primary CTA | `Inspect the proof trail` |
| Public launch URL | `https://ragstudio.dev` |
| Domain pending state | `Domain not connected yet` |
| Domain ready state | `ragstudio.dev is serving the proof viewer` |
| Empty launch checklist | `No launch checks have run yet` |
| Empty launch checklist body | `Run the release gate before connecting public links.` |
| Accessibility failure | `Accessibility gate failed. Fix the listed issue before launch.` |
| Broken link failure | `Launch blocked by broken public link.` |
| Static boundary failure | `Launch blocked: static site boundary failed.` |
| Proof import failure | `Launch blocked: proof packet import failed.` |
| Manual checklist pending | `Manual launch review still needs signoff.` |

Copy rules:

- Use direct verification verbs: `Run gate`, `Open report`, `Review checklist`, `Connect domain`, `Verify link`.
- Do not use marketing inflation such as `unlock`, `all-in-one`, `next-generation`, `seamless`, or `modern AI`.
- README and `jihadaj.com` copy must point to `https://ragstudio.dev` as the canonical site, not duplicate claim evidence.
- Any launch status report must distinguish `preview URL verified` from `ragstudio.dev verified`.

---

## Public Surface Contracts

### Proof Viewer

- Preserve the Phase 04 first viewport, claim groups, evidence dossiers, feedback links, and approved screenshot signoff behavior.
- No new public upload, auth, live provider, or backend API affordance may appear.
- Deep links such as `#claim-RAGSTUDIO-TRACE-VISIBILITY` must remain usable after deployment.
- Missing raw artifacts must continue to show explicit fallback text rather than broken or misleading availability.

### Launch Checklist

If a launch checklist file or rendered report is introduced, it must contain these gates:

| Gate | Blocking |
|------|----------|
| Static boundary | yes |
| Proof import | yes |
| Lint/test/build | yes |
| Playwright proof flow | yes |
| axe accessibility | yes |
| Fixture size/performance | yes |
| Manual keyboard/mobile/overflow review | yes |
| Screenshot/privacy signoff | yes |
| `ragstudio.dev` domain connected | yes |
| README and `jihadaj.com` links verified | yes |

The checklist must make blockers visually and textually clear. Color alone is not enough.

### Cloudflare / Domain States

- Pages preview URL may be shown as `prelaunch`.
- `https://ragstudio.dev` must be shown as the only official launch URL.
- Any release proof must record project name `ragstudio-site`, branch `main`,
  build command `npm run build`, output directory `dist`, and domain status.

---

## Accessibility Contract

Phase 05 targets WCAG 2.2 Level AA for implemented public surfaces.

Required checks:

- Keyboard can reach primary CTA, claim links, raw artifact links, feedback links, and launch/report links.
- Focus indicators remain visible on every actionable element.
- Body text contrast is at least 4.5:1.
- Link purpose is clear from text or surrounding context.
- Status is conveyed by text plus color.
- Page has a single meaningful `h1`, ordered headings, and landmark-friendly structure.
- Images have useful alt text or are not rendered.
- No horizontal overflow at 320px and 390px except inside intentionally bounded code/table scrollers.
- axe checks must run against the homepage and at least one deep-linked claim dossier.

---

## Testing And Release-Gate Contract

Minimum automated commands:

- `cd /Users/meet/Documents/ragstudio-site && npm run check:static`
- `cd /Users/meet/Documents/ragstudio-site && npm run import:proof`
- `cd /Users/meet/Documents/ragstudio-site && npm run lint`
- `cd /Users/meet/Documents/ragstudio-site && npm test`
- `cd /Users/meet/Documents/ragstudio-site && npm run build`

Browser checks must cover:

- Homepage first viewport.
- `Inspect the proof trail` anchor navigation.
- `#claim-RAGSTUDIO-TRACE-VISIBILITY` deep link.
- Feedback issue link context.
- Approved screenshot section.
- 320px and 390px mobile widths with no page-level horizontal overflow.
- Deployed `https://ragstudio.dev` after domain connection.

Accessibility checks must include axe or equivalent automated WCAG tooling.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | none | not required |
| third-party UI blocks | none allowed in Phase 05 without explicit review | rejected by default |

No third-party visual block libraries should be introduced for launch hardening.
Testing/accessibility libraries may be added when they are purpose-built and
scoped to release gates.

---

## Checker Sign-Off

- [x] Dimension 1 Copywriting: PASS
- [x] Dimension 2 Visuals: PASS
- [x] Dimension 3 Color: PASS
- [x] Dimension 4 Typography: PASS
- [x] Dimension 5 Spacing: PASS
- [x] Dimension 6 Registry Safety: PASS

**Approval:** approved 2026-05-14
