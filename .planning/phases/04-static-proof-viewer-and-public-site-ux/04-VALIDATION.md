---
phase: 04
slug: static-proof-viewer-and-public-site-ux
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-14
---

# Phase 04 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Vitest, Testing Library, Vite build, static boundary script |
| **Site root** | `/Users/meet/Documents/ragstudio-site` |
| **Primary data** | `src/data/proof-packet.generated.json`, `src/data/proof-validation.generated.json`, `public/proof/ragstudio-oss-proof-v1/claims/claims.registry.json` |
| **Quick run command** | `cd /Users/meet/Documents/ragstudio-site && npm test` |
| **Full phase command** | `cd /Users/meet/Documents/ragstudio-site && npm run check:static && npm run lint && npm test && npm run build` |
| **Estimated runtime** | ~5-20 seconds |

---

## Sampling Rate

- **After 04-01:** Run `npm test`, `npm run check:static`, and `npm run build`.
- **After 04-02:** Run `npm test`, `npm run lint`, and inspect feedback links in test assertions.
- **After 04-03:** Run the full phase command and perform desktop/mobile visual smoke review.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | VIEW-01 | T-04-01 | First viewport uses exact proof-first copy and CTA. | render/test | `npm test` | W0 | pending |
| 04-01-02 | 01 | 1 | VIEW-02 | T-04-02 | Viewer reads imported static fixtures only. | guard/build | `npm run check:static && npm run build` | W0 | pending |
| 04-01-03 | 01 | 1 | VIEW-03 | T-04-03 | Claim list shows proven, roadmap, and disabled groups. | render/test | `npm test` | W0 | pending |
| 04-02-01 | 02 | 2 | VIEW-04 | T-04-04 | Claim detail exposes evidence type panels and non-proven language. | render/test | `npm test` | W0 | pending |
| 04-02-02 | 02 | 2 | VIEW-05 | T-04-05 | Deep links and feedback URLs include required proof context. | render/test | `npm test` | W0 | pending |
| 04-03-01 | 03 | 3 | VIEW-06 | T-04-06 | Screenshots come only from approved signoff records. | render/source | `npm test` | W0 | pending |
| 04-03-02 | 03 | 3 | VIEW-07 | T-04-07 | Screenshot signoff metadata is visible or fallback-safe. | render/source | `npm test` | W0 | pending |
| 04-03-03 | 03 | 3 | VIEW-02 | T-04-08 | Responsive polish preserves static-only build and no broken artifacts. | full/build | `npm run check:static && npm run lint && npm test && npm run build` | W0 | pending |

*Status: pending - green - red - flaky*

---

## Wave 0 Requirements

- [ ] `/Users/meet/Documents/ragstudio-site/src/App.tsx` renders the complete Phase 4 flow.
- [ ] `/Users/meet/Documents/ragstudio-site/src/styles.css` implements UI-SPEC spacing, typography, color, focus, and responsive rules.
- [ ] `/Users/meet/Documents/ragstudio-site/tests/app.test.tsx` covers first viewport, claim groups, dossiers, feedback, screenshot/fallback states.
- [ ] `/Users/meet/Documents/ragstudio-site/scripts/check-static-boundary.mjs` still passes.

---

## Manual-Only Verifications

- Desktop visual smoke review after Phase 4 UI exists.
- Mobile visual smoke review at 320px and a common phone width.
- Focus ring and keyboard navigation spot check.

---

## Validation Sign-Off

- [ ] All tasks have automated verification or manual visual smoke coverage
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all missing UI references
- [ ] No watch-mode flags
- [ ] Full phase command passes from `/Users/meet/Documents/ragstudio-site`

**Approval:** pending
