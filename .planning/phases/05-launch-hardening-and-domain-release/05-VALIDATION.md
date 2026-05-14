---
phase: 05
slug: launch-hardening-and-domain-release
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-14
---

# Phase 05 - Validation Strategy

> Per-phase validation contract for launch hardening and public-domain release.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Vitest, Testing Library, Vite build, Playwright, `@axe-core/playwright`, release-gate scripts |
| **Site root** | `/Users/meet/Documents/ragstudio-site` |
| **Planning root** | `/Users/meet/Documents/Ragstudio` |
| **Target domain** | `https://ragstudio.dev` |
| **Quick run command** | `cd /Users/meet/Documents/ragstudio-site && npm run check:static && npm test` |
| **Full phase command** | `cd /Users/meet/Documents/ragstudio-site && npm run launch:check` |
| **Manual gate** | Phase 05 launch checklist |
| **Estimated runtime** | ~1-5 minutes locally, domain checks depend on Cloudflare/DNS propagation |

---

## Sampling Rate

- **After 05-01:** Verify deployment config/proof records and run existing static/build checks.
- **After 05-02:** Run full local launch gate including Playwright and axe.
- **After 05-03:** Run full launch gate against `https://ragstudio.dev` and verify README/`jihadaj.com` links.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | SITE-02 | T-05-01 | Cloudflare Pages project and Git production branch are recorded and verifiable. | config/proof | `npm run build` plus release-proof check | W0 | pending |
| 05-01-02 | 01 | 1 | SITE-03 | T-05-02 | `ragstudio.dev` is required before launch complete. | domain/proof | `curl -I https://ragstudio.dev` or release script equivalent | W0 | pending |
| 05-02-01 | 02 | 2 | QA-01 | T-05-03 | Accessibility gate blocks launch on axe/manual failures. | browser/a11y | `npm run test:a11y` | W0 | pending |
| 05-02-02 | 02 | 2 | QA-02 | T-05-04 | Playwright covers homepage, CTA, deep-linked claim, screenshot, and feedback links. | browser/e2e | `npm run test:e2e` | W0 | pending |
| 05-02-03 | 02 | 2 | QA-03 | T-05-05 | Manual checklist blocks unresolved keyboard/mobile/overflow/fallback review. | checklist | `npm run launch:check` | W0 | pending |
| 05-02-04 | 02 | 2 | QA-04 | T-05-06 | Fixture-size/performance checks prevent unusable public bundle/proof assets. | perf/script | `npm run check:fixtures` | W0 | pending |
| 05-02-05 | 02 | 2 | QA-05 | T-05-07 | Launch gate fails closed until proof, static, accessibility, domain, and links pass. | release-gate | `npm run launch:check` | W0 | pending |
| 05-03-01 | 03 | 3 | SITE-05 | T-05-08 | README and `jihadaj.com` link only to the canonical domain after verification. | docs/link | `npm run launch:check` | W0 | pending |

*Status: pending - green - red - flaky*

---

## Wave 0 Requirements

- [ ] `/Users/meet/Documents/ragstudio-site` has Playwright/axe launch checks.
- [ ] `/Users/meet/Documents/ragstudio-site` has a single full release-gate command.
- [ ] Phase 05 release proof records Cloudflare project, branch, build command, output directory, Pages URL, and `ragstudio.dev` status.
- [ ] Manual launch checklist exists and blocks release until signed off.

---

## Manual-Only Verifications

- Confirm Cloudflare dashboard project name `ragstudio-site`.
- Confirm production branch is `main` and automatic production deploys are enabled.
- Confirm `ragstudio.dev` custom domain is active in Cloudflare Pages.
- Confirm keyboard traversal and visible focus on deployed site.
- Confirm `jihadaj.com` source or update path is available before claiming that link is live.

---

## Validation Sign-Off

- [ ] All tasks have automated verification or manual visual/domain smoke coverage
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all launch references
- [ ] No watch-mode flags
- [ ] Full launch gate passes from `/Users/meet/Documents/ragstudio-site`

**Approval:** pending
