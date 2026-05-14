# Phase 05 Research — Launch Hardening and Domain Release

**Date:** 2026-05-14
**Phase:** 05-launch-hardening-and-domain-release
**Status:** Complete

## Research Question

What needs to be true to plan Phase 05 well: Cloudflare Pages Git deployment,
`ragstudio.dev` domain release, strict proof/accessibility launch gates, and
public amplifier links?

## Current Local State

- `/Users/meet/Documents/ragstudio-site` is a Vite React static site.
- Site scripts already include `npm run check:static`, `npm run import:proof`,
  `npm run lint`, `npm test`, and `npm run build`.
- The site is on branch `main`.
- `git remote -v` in `/Users/meet/Documents/ragstudio-site` produced no remote
  entries during research, so Phase 05 must include an explicit Git remote /
  repository connection check before Cloudflare Pages Git integration can be
  considered complete.
- Phase 04 UAT passed 6/6 with no issues.
- Phase 04 validation found and fixed mobile overflow at 320px before Phase 05.

## External Research

### Cloudflare Pages Git Integration

Cloudflare Pages can connect a project to a GitHub or GitLab repository and
automatically deploy when commits are pushed to a branch. Git integration also
provides preview deployments for custom branches, PR preview URLs, and repository
status checks.

Source: Cloudflare Pages Git integration docs  
https://developers.cloudflare.com/pages/configuration/git-integration/

Planning implications:

- Phase 05 should make the `ragstudio-site` repository remote explicit.
- The Cloudflare project should be Git-integrated, not Direct Upload, because the
  user selected auto-deploy from `main`.
- Production branch must be `main`.
- Preview URLs are useful for prelaunch checks, but not the official launch URL.

### Branch Deployment Controls

Cloudflare Pages supports production branch control and automatic production
branch deployments. Pages can enable or disable automatic deployments per project
and control preview branch deployments.

Source: Cloudflare Pages branch deployment controls  
https://developers.cloudflare.com/pages/configuration/branch-build-controls/

Planning implications:

- The plan should require "Enable automatic production branch deployments" for
  `main`.
- The launch proof should record production branch and deployment status.
- Preview deployment behavior may be left default unless implementation finds a
  reason to restrict it.

### Vite Static Deployment to Cloudflare Pages

Vite's static deployment docs describe Cloudflare Pages with Git as: push code
to Git, create a Pages project, connect Git, choose the framework preset/build
settings, then production branch changes deploy to production. Vite build output
is normally `dist`.

Source: Vite static deployment docs  
https://v3.vite.dev/guide/static-deploy

Planning implications:

- Build command remains `npm run build`.
- Output directory remains `dist`.
- No runtime environment variables should be required.

### Cloudflare Pages Custom Domains

Cloudflare Pages custom domains are added from Workers & Pages > Pages project >
Custom domains > Set up a domain. For an apex domain such as `ragstudio.dev`, the
domain must be a Cloudflare zone / nameservers must point to Cloudflare; when the
zone is already in Cloudflare, Cloudflare can create the CNAME record for Pages.

Source: Cloudflare Pages custom domains docs  
https://developers.cloudflare.com/pages/configuration/custom-domains/

Planning implications:

- `ragstudio.dev` is an apex domain, so the launch checklist must verify the
  Cloudflare zone/nameserver/DNS state and Pages custom-domain activation.
- Manually adding DNS alone is insufficient; the domain must be associated in
  the Pages project custom-domain flow.
- Release proof must record that `https://ragstudio.dev` serves the site.

### Wrangler Pages Commands

Wrangler supports Pages project creation, deployment listing, direct deploy, and
configuration download. `pages project create` accepts `--production-branch`.
`pages deployment list` can inspect deployments by project/environment.
`pages deploy dist` can deploy a directory directly, but direct upload is not the
selected release path.

Source: Wrangler Pages command docs  
https://developers.cloudflare.com/workers/wrangler/commands/pages/

Planning implications:

- Wrangler can be used for verification and release proof, but Git integration is
  the desired production path.
- A plan may add a release-proof script that uses Wrangler only when credentials
  are available, with graceful manual fallback.
- Avoid requiring Cloudflare secrets in the static app runtime.

### Playwright + axe Accessibility Checks

Playwright's accessibility testing guide recommends `@axe-core/playwright` for
automated axe scans. It notes automated tests catch common issues such as
contrast, unlabeled controls, and duplicate IDs, but many accessibility issues
still require manual testing. The guide shows scanning whole pages and checking
`violations` equals an empty list.

Source: Playwright accessibility testing docs  
https://playwright.dev/docs/accessibility-testing

Planning implications:

- Add `@playwright/test` and `@axe-core/playwright` to `ragstudio-site` dev
  dependencies.
- Add Playwright config/tests for homepage and deep-linked claim dossier.
- Add axe scans for at least `/` and `/#claim-RAGSTUDIO-TRACE-VISIBILITY`.
- Keep manual checklist as blocking because axe is not complete WCAG coverage.

## Recommended Implementation Shape

### Plan 05-01 — Cloudflare Pages and Domain Gate

Create deployment docs/config/checklist for:

- Git remote/repository check for `ragstudio-site`.
- Cloudflare Pages project `ragstudio-site`.
- Production branch `main`.
- Build command `npm run build`.
- Output directory `dist`.
- No runtime environment variables.
- Custom domain `ragstudio.dev`.
- Release proof file recording preview URL, production deployment, and domain
  status.

### Plan 05-02 — Strict Launch Gate Automation

Add a local release-gate script plus browser/accessibility tests:

- `npm run check:static`
- `npm run import:proof`
- `npm run lint`
- `npm test`
- `npm run build`
- Playwright proof flow
- axe homepage/deep-link scans
- fixture-size/performance check
- manual checklist status parser

### Plan 05-03 — Public Links and Final Release Proof

Update the public amplifiers only after domain verification:

- Ragstudio `README.md` links to `https://ragstudio.dev`.
- `jihadaj.com` link/update is documented or implemented where the site source
  is available.
- Final release proof records deployment URL, domain URL, launch checks, and
  manual review state.

## Validation Architecture

| Requirement | Validation Approach |
|-------------|---------------------|
| SITE-02 | Verify `ragstudio-site` Git remote, Pages project setup records, production branch `main`, build command `npm run build`, output `dist`, and deploy proof. |
| SITE-03 | Verify `https://ragstudio.dev` returns the built site and release proof records custom-domain activation. |
| SITE-05 | Verify Ragstudio `README.md` and `jihadaj.com` link or release-proof task both point to `https://ragstudio.dev`. |
| QA-01 | Run axe checks plus manual checklist for WCAG 2.2 AA-critical surfaces. |
| QA-02 | Run Playwright proof-viewer and axe tests for homepage and deep-linked claim. |
| QA-03 | Manual checklist covers keyboard navigation, mobile layout, text overflow, raw artifact fallbacks, and overlap. |
| QA-04 | Fixture-size/performance script validates public proof assets remain usable on desktop/mobile. |
| QA-05 | Release gate script fails closed unless proof validation, redaction/static import, accessibility, domain, and public links pass. |

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| No Git remote in local `ragstudio-site` checkout | Plan 05-01 must make remote setup/verification explicit before Cloudflare Git integration. |
| Cloudflare credentials not available locally | Plans should support dashboard/manual proof capture and optional Wrangler verification, not hard-fail planning on missing credentials. |
| axe creates false confidence | Keep manual checklist blocking. |
| Pages preview gets mistaken for public launch | Release proof distinguishes preview URL from `https://ragstudio.dev`; launch complete only when domain is verified. |
| README/jihadaj.com updated too early | Plan 05-03 should gate public amplifier links behind domain verification. |

## Sources

- Cloudflare Pages Git integration: https://developers.cloudflare.com/pages/configuration/git-integration/
- Cloudflare Pages branch deployment controls: https://developers.cloudflare.com/pages/configuration/branch-build-controls/
- Cloudflare Pages custom domains: https://developers.cloudflare.com/pages/configuration/custom-domains/
- Wrangler Pages commands: https://developers.cloudflare.com/workers/wrangler/commands/pages/
- Vite static deployment: https://v3.vite.dev/guide/static-deploy
- Playwright accessibility testing: https://playwright.dev/docs/accessibility-testing
