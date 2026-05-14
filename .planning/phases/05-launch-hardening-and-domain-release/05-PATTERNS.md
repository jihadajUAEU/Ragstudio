---
phase: 05
slug: launch-hardening-and-domain-release
status: complete
created: 2026-05-14
---

# Phase 05 Pattern Map

## Scope

Phase 05 spans the sibling static site repo `/Users/meet/Documents/ragstudio-site`
and planning/docs records in `/Users/meet/Documents/Ragstudio`.

## Implementation Targets and Closest Analogs

| Target | Role | Closest Existing Analog | Pattern To Reuse |
|--------|------|-------------------------|------------------|
| `/Users/meet/Documents/ragstudio-site/package.json` | Add release/a11y/e2e scripts and dev dependencies | Existing `check:static`, `import:proof`, `test`, `build` scripts | Keep command names direct and make release gate compose existing scripts. |
| `/Users/meet/Documents/ragstudio-site/tests/app.test.tsx` | Existing UI proof-viewer coverage | Testing Library tests with user-visible assertions | Keep component tests focused on rendered copy and links. |
| `/Users/meet/Documents/ragstudio-site/tests/static-boundary.test.mjs` | Static boundary guard | Vitest module tests for scripts | Add script checks with explicit failure messages and temp fixtures. |
| `/Users/meet/Documents/ragstudio-site/scripts/check-static-boundary.mjs` | Fail-closed guard script | Existing scanner returns structured findings and exits non-zero | New release scripts should be deterministic, structured, and CI-friendly. |
| `/Users/meet/Documents/ragstudio-site/src/styles.css` | Accessibility and responsive baseline | Phase 04 mobile overflow fix and visible focus ring | Preserve `min-width: 0`, `overflow-wrap: anywhere`, and visible focus rules. |
| `.planning/phases/04-static-proof-viewer-and-public-site-ux/04-VALIDATION.md` | Validation audit record | Nyquist audit trail with commands and gap resolution | Phase 05 should record both automated and manual launch gate evidence. |
| `.planning/phases/04-static-proof-viewer-and-public-site-ux/04-UAT.md` | UAT proof | User-facing tests with pass/issue tracking | Phase 05 manual checklist should be similarly explicit and auditable. |

## Data Flow

1. Source proof packet remains in Ragstudio.
2. `ragstudio-site` imports proof packet through `npm run import:proof`.
3. Local release gate validates static boundary, import, lint, unit tests, build,
   Playwright, axe, fixture size, and manual checklist status.
4. Cloudflare Pages auto-deploys from `main` to preview/production.
5. `ragstudio.dev` is attached as the only official launch domain.
6. README and `jihadaj.com` link to `https://ragstudio.dev` after domain proof.

## Constraints

- Do not introduce live backend calls, public upload, auth, provider runtime env,
  or API client imports in the public site.
- Do not use a Pages preview URL as the final launch URL.
- Do not mark launch complete unless the manual checklist and domain proof pass.
- Do not update public amplifier language to duplicate proof claims; it should
  link to `ragstudio.dev` as canonical.
