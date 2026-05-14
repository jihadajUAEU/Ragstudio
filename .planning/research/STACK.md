# Stack Research

**Domain:** Open-source static proof viewer and replayable RAG evidence packet
**Researched:** 2026-05-14
**Confidence:** HIGH

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| TypeScript | Current stable via site lockfile | Proof viewer, import tooling, and proof CLI validation | Matches existing frontend language and lets site import and local proof command share validation behavior. |
| React | Current stable via site lockfile | Static proof viewer UI | Existing Ragstudio frontend already uses React; the proof viewer is interactive but does not need a live backend. |
| Vite | Current stable via site lockfile | Static site build and local dev server | Vite has a direct Cloudflare Pages static deployment path and matches the existing Ragstudio frontend stack. |
| Cloudflare Pages Git integration | Current service | Production and preview deploys for `ragstudio-site` | Official docs say Pages can connect to GitHub/GitLab and automatically deploy on branch pushes with preview URLs and PR checks. |
| JSON Schema Draft 2020-12 | 2020-12 | Canonical proof packet schemas | Current JSON Schema spec family; supports shared validation across local proof command and site import. |
| Node.js | 22 LTS or 24 current | Evaluator-facing proof command and site tooling | Keeps `./scripts/proof.sh` no-Docker and aligned with the separate site repo tooling. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Ajv | Current stable | JSON Schema 2020-12 validation in TypeScript | Use for `scripts/proof.ts` and `ragstudio-site/scripts/import-proof-packet.ts`. |
| Vitest | Current stable | Unit/component tests for proof contract and viewer | Use for schema, import, redaction, capped-preview, and component tests. |
| Playwright | Current stable | Browser flow and accessibility smoke tests | Use for landing-to-proof-to-artifact flow and viewport checks. |
| `@axe-core/playwright` | Current stable | Automated accessibility checks | Use alongside manual keyboard/screen-reader smoke checks. |
| `fast-glob` or Node built-ins | Current stable | Artifact discovery | Prefer Node built-ins unless glob patterns materially simplify import/export. |
| `crypto` Node built-in | Runtime built-in | SHA-256 hashing | Use built-in hashing instead of adding a dependency. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Cloudflare Pages dashboard Git integration | Connect `ragstudio-site` to GitHub | Choose Git integration first; Cloudflare notes Git-integrated Pages projects cannot later switch to Direct Upload. |
| GitHub Actions or Cloudflare deploy checks | Public CI/release validation | Gate proof command, import script, viewer tests, and accessibility smoke before production deploy. |
| `scripts/proof.sh` | Golden evaluator command | Wrap the TypeScript/Node validator and print packet id, commit/tag, hash, claim counts, and viewer URL. |

## Installation

```bash
# Site repo core
npm install react react-dom
npm install -D typescript vite @vitejs/plugin-react vitest jsdom @testing-library/react @testing-library/jest-dom

# Proof validation and browser gates
npm install -D ajv playwright @playwright/test @axe-core/playwright
```

The Ragstudio repo can keep Python helpers for live capture/export source behavior,
but the no-Docker public proof path should run through Node/TypeScript so local
validation and `ragstudio-site` import validation stay aligned.

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Vite static app | Next.js static export | Use Next.js only if the site later needs framework routing/content conventions that Vite cannot provide. |
| Cloudflare Pages Git integration | Wrangler Direct Upload | Use Direct Upload only if Git integration is blocked before repo creation; do not mix after Git integration is chosen. |
| JSON Schema 2020-12 | Zod-only schemas | Zod can help internal typing, but public proof artifacts need portable JSON Schemas. |
| Node/TypeScript proof command | Python-only proof tooling | Keep Python for Ragstudio internals, but Python-only proof validation would duplicate site import behavior. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Live backend calls from `ragstudio-site` | Reintroduces auth, upload, provider, egress, and uptime risk | Static local proof fixtures imported at build time. |
| A generic SaaS landing template | Weakens the proof-system positioning | Field-guide public shell plus embedded proof instrument from `DESIGN.md`. |
| Separate Python and TypeScript schema definitions | Creates drift between export, local validation, and site import | Canonical JSON Schema files consumed by both sides. |
| Docker as the first proof command | Breaks 2-5 minute evaluator target | `./scripts/proof.sh` with static fixtures and Node tooling. |

## Stack Patterns by Variant

**If building the proof packet in Ragstudio:**
- Use backend Python for live capture helpers and source evidence extraction.
- Use canonical JSON Schema files and shared redaction/manifest rules.
- Because existing evidence APIs and runtime code live in this repo.

**If building the public proof viewer:**
- Use React/Vite/TypeScript in the separate `ragstudio-site` repo.
- Import proof packets into `public/proof-packets/ragstudio-oss-proof-v1/`.
- Because the viewer is a static artifact explorer, not a live app.

**If validating before launch:**
- Run `./scripts/proof.sh` in Ragstudio, then site import tests in `ragstudio-site`.
- Because the same packet must satisfy both the source repo and public site gate.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| JSON Schema 2020-12 | Ajv current stable | Configure Ajv for 2020-12 dialect; do not silently fall back to older drafts. |
| Vite static build | Cloudflare Pages | Vite official docs document Cloudflare Pages Git deployment with build command/output directory. |
| Playwright | `@axe-core/playwright` | Playwright docs recommend axe for automated accessibility checks while warning that manual testing remains required. |

## Sources

- https://developers.cloudflare.com/pages/configuration/git-integration/ - verified Git integration, branch previews, PR checks, and Direct Upload caveat.
- https://vite.dev/guide/static-deploy.html - verified Vite static deployment path for Cloudflare Pages.
- https://json-schema.org/specification - verified latest JSON Schema meta-schema family as 2020-12.
- https://www.w3.org/TR/wcag/ - verified WCAG 2.2 recommendation and W3C advice to use 2.2.
- https://playwright.dev/docs/accessibility-testing - verified Playwright plus axe accessibility testing guidance and automated/manual split.
- https://react.dev/learn/start-a-new-react-project - checked React guidance for build-tool-based apps such as Vite when building a custom client app.

---
*Stack research for: open-source static proof viewer and replayable RAG evidence packet*
*Researched: 2026-05-14*
