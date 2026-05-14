# Phase 5: Launch Hardening and Domain Release - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-14
**Phase:** 05-launch-hardening-and-domain-release
**Areas discussed:** Public domain and launch URL, Cloudflare Pages release shape, Launch gates and accessibility, Public amplifier links

---

## Public Domain And Launch URL

| Option | Description | Selected |
|--------|-------------|----------|
| `proof.ragstudio.ai` | Dedicated proof-system subdomain if owned or desired. | |
| `ragstudio.jihadaj.com` | Keep the launch under the existing personal/domain ecosystem. | |
| Cloudflare Pages URL first | Use Pages preview for prelaunch, but require a final custom domain before launch. | |
| `ragstudio.dev` | User registered `ragstudio.dev` through Cloudflare and selected it as the launch domain. | ✓ |

**User's choice:** `ragstudio.dev`
**Notes:** Cloudflare Pages preview URLs are acceptable for testing only. Launch is blocked until `https://ragstudio.dev` is connected.

---

## Cloudflare Pages Release Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Auto deploy from `main` | Cloudflare Pages project connected to `ragstudio-site`, build on every push to `main`. | ✓ |
| Manual production promote | Cloudflare builds previews from Git, but production deploy requires manual promotion. | |
| Manual deploy only | No Git auto-deploy; use CLI/manual upload when ready. | |

**User's choice:** Auto deploy from `main`
**Notes:** Capture defaults: project name `ragstudio-site`, production branch `main`, build command `npm run build`, output directory `dist`, no runtime env vars.

---

## Launch Gates And Accessibility

| Option | Description | Selected |
|--------|-------------|----------|
| Strict launch gate | Playwright, axe, static boundary, proof import, build, and manual checklist must all pass before launch. | ✓ |
| Balanced gate | Playwright, static boundary, and build must pass; axe/manual checklist advisory. | |
| Fast gate | Build/static checks only; accessibility/manual checks happen after launch. | |

**User's choice:** Strict launch gate
**Notes:** Launch blockers include proof validation, redaction, site import, accessibility, domain connection, README/profile links, and broken link failures.

---

## Public Amplifier Links

| Option | Description | Selected |
|--------|-------------|----------|
| README + jihadaj.com | Update Ragstudio `README.md` and add/link from `jihadaj.com` to `https://ragstudio.dev`. | ✓ |
| README only | Update repo docs first; leave `jihadaj.com` alone for now. | |
| jihadaj.com only | Personal site points to `ragstudio.dev`; repo README waits. | |

**User's choice:** README + jihadaj.com
**Notes:** Both are amplifiers only; `ragstudio.dev` remains the canonical public proof-system site.

---

## the agent's Discretion

- Exact Playwright/axe file names and package/wrapper shape.
- Exact launch checklist file name and fixture-size thresholds.
- Whether Cloudflare setup is captured through dashboard documentation, Wrangler config, or both.

## Deferred Ideas

- Public upload, authentication, hosted read-only API demo, provider-backed live demo, customer-validation claims, 2000+ page proven claims, GPU performance claims, and Quran-derived public corpus remain out of scope for v1.
