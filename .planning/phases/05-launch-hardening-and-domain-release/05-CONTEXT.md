# Phase 5: Launch Hardening and Domain Release - Context

**Gathered:** 2026-05-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 5 turns the completed static proof viewer in `/Users/meet/Documents/ragstudio-site`
into a public release on Cloudflare Pages. The release is not considered launched
until the custom domain `ragstudio.dev` is connected and the strict launch gate
passes.

This phase owns Cloudflare Pages project configuration, Git auto-deploy from
`main`, custom domain connection for `ragstudio.dev`, launch-blocking checks,
accessibility and browser-flow checks, fixture-size/performance checks, manual
launch checklist records, and public amplifier links from Ragstudio `README.md`
and `jihadaj.com`.

This phase does not add public upload, authentication, live backend calls, hosted
API demo behavior, customer validation claims, 2000+ page proven claims, or GPU
performance claims.

</domain>

<decisions>
## Implementation Decisions

### Public Domain And Launch URL
- **D-01:** The official launch domain is `https://ragstudio.dev`.
- **D-02:** Cloudflare Pages preview URLs may be used for prelaunch testing only.
  The release does not count as publicly launched until `ragstudio.dev` is
  connected and serving the static site.
- **D-03:** Domain ownership is through Cloudflare, so planning may assume the
  custom domain can be managed through Cloudflare Pages/DNS workflows.

### Cloudflare Pages Release Shape
- **D-04:** Create or configure a Cloudflare Pages project named `ragstudio-site`.
- **D-05:** Connect the Pages project to the `ragstudio-site` Git repository and
  auto-deploy production from the `main` branch.
- **D-06:** Use `npm run build` as the build command and `dist` as the output
  directory.
- **D-07:** The static site should require no runtime environment variables. Any
  launch configuration should preserve the Phase 3/4 static-only boundary.

### Launch Gates And Accessibility
- **D-08:** Use a strict launch gate. Launch is blocked until all automated and
  manual release checks pass.
- **D-09:** Required automated checks include `npm run check:static`,
  `npm run import:proof`, `npm run lint`, `npm test`, `npm run build`,
  Playwright proof-viewer flow checks, axe accessibility checks, and
  fixture-size/performance checks.
- **D-10:** Required manual checks include keyboard navigation, mobile layout,
  text overflow, raw artifact fallback states, no incoherent overlap, no private
  screenshot/content exposure, and confirmation that `ragstudio.dev` is connected.
- **D-11:** The launch checklist must block release on proof validation,
  redaction, site import, accessibility, domain connection, README/profile links,
  and broken link failures.

### Public Amplifier Links
- **D-12:** After `ragstudio.dev` is live, update Ragstudio `README.md` to link
  to `https://ragstudio.dev` as the canonical public proof-system site.
- **D-13:** After `ragstudio.dev` is live, update or add a `jihadaj.com` link to
  `https://ragstudio.dev`.
- **D-14:** `README.md` and `jihadaj.com` are amplifiers only. They should point
  visitors to `ragstudio.dev`; they should not become the source of truth for
  claims or proof artifacts.

### the agent's Discretion
- The agent may choose exact Playwright test file names, axe integration package
  and wrapper shape, launch checklist file name, fixture-size thresholds, and
  Cloudflare configuration file shape after researching the existing site repo
  and Cloudflare Pages conventions.
- The agent may decide whether Cloudflare setup is implemented through dashboard
  documentation, Wrangler config, or both, as long as the release proof records
  the actual project name, production branch, build command, output directory,
  Pages URL, and `ragstudio.dev` custom-domain status.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Scope
- `.planning/PROJECT.md` - Public launch definition, required new domain,
  static-only site constraint, and amplifier-link boundary.
- `.planning/REQUIREMENTS.md` - Phase 5 requirement IDs `SITE-02`, `SITE-03`,
  `SITE-05`, `QA-01`, `QA-02`, `QA-03`, `QA-04`, and `QA-05`.
- `.planning/ROADMAP.md` - Phase 5 goal, success criteria, dependency on Phase
  4, and planned launch-hardening slices.
- `.planning/STATE.md` - Current project status and Phase 5 readiness.

### Prior Phase Handoff
- `.planning/phases/04-static-proof-viewer-and-public-site-ux/04-CONTEXT.md` -
  Static proof viewer decisions, Phase 5 boundary, and Technical Field Guide
  direction.
- `.planning/phases/04-static-proof-viewer-and-public-site-ux/04-VERIFICATION.md`
  - Evidence that the static proof viewer passed automated and runtime smoke
  checks.
- `.planning/phases/04-static-proof-viewer-and-public-site-ux/04-VALIDATION.md`
  - Validation audit, including the 320px overflow gap fixed before launch
  hardening.
- `.planning/phases/04-static-proof-viewer-and-public-site-ux/04-SECURITY.md`
  - Phase 4 security register confirming static-only and screenshot-safety
  mitigations.
- `.planning/phases/04-static-proof-viewer-and-public-site-ux/04-UAT.md` -
  User acceptance record with 6 passed checks and 0 issues.

### Site Source
- `/Users/meet/Documents/ragstudio-site/package.json` - Site scripts, build
  command, and dependency surface.
- `/Users/meet/Documents/ragstudio-site/src/App.tsx` - Current proof-viewer UI
  and feedback-link implementation.
- `/Users/meet/Documents/ragstudio-site/src/styles.css` - Responsive/accessibility
  styling baseline and mobile overflow fix.
- `/Users/meet/Documents/ragstudio-site/scripts/import-proof-packet.mjs` - Proof
  import command used by the launch gate.
- `/Users/meet/Documents/ragstudio-site/scripts/check-static-boundary.mjs` -
  Static-only boundary guard required by the launch gate.
- `/Users/meet/Documents/ragstudio-site/tests/app.test.tsx` - Existing proof
  viewer render coverage.
- `/Users/meet/Documents/ragstudio-site/tests/static-boundary.test.mjs` -
  Existing static-boundary guard coverage.
- `/Users/meet/Documents/ragstudio-site/tests/import-proof-packet.test.mjs` -
  Existing proof import coverage.

### Public Documentation And Amplifiers
- `README.md` - Ragstudio repository README that should link to
  `https://ragstudio.dev` after the domain is live.
- `TODOS.md` - Existing launch/accessibility notes, including WCAG 2.2 AA and
  Playwright/axe checklist context.

### Codebase Map
- `.planning/codebase/STACK.md` - React/Vite/TypeScript stack and test tooling.
- `.planning/codebase/TESTING.md` - Existing Vitest and Playwright testing
  patterns.
- `.planning/codebase/STRUCTURE.md` - Repository and static/public asset
  conventions.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `/Users/meet/Documents/ragstudio-site` is already a Vite React static site
  with `npm run build`, `npm run lint`, `npm test`, `npm run import:proof`, and
  `npm run check:static`.
- The proof viewer currently passes Phase 4 verification and UAT; Phase 5 should
  harden, test, deploy, and link it rather than redesign it.
- Playwright is available locally through existing workspace dependencies and
  has already been used for responsive smoke checks during Phase 4 validation.

### Established Patterns
- Keep the public site static: no backend calls, upload flows, authentication,
  provider env vars, or live HTTP fetches.
- Treat roadmap and disabled claims as visible truth, not hidden marketing
  liabilities.
- Record release proof in planning artifacts rather than relying on memory or
  transient terminal output.

### Integration Points
- Cloudflare Pages production branch: `main`.
- Cloudflare Pages build command: `npm run build`.
- Cloudflare Pages output directory: `dist`.
- Official launch domain: `https://ragstudio.dev`.
- Public amplifier targets: Ragstudio `README.md` and `jihadaj.com`.

</code_context>

<specifics>
## Specific Ideas

- Use `ragstudio-site` as the Cloudflare Pages project name.
- Use `ragstudio.dev` as the custom domain and the only URL that counts as
  launched.
- Strict launch gate should be runnable before deployment and re-runnable after
  deployment/domain connection.
- The launch checklist should be explicit enough to block release if domain,
  accessibility, proof validation, redaction, import, links, or browser flows
  fail.

</specifics>

<deferred>
## Deferred Ideas

- Public upload, authentication, hosted read-only API demo, provider-backed live
  demo, customer-validation claims, 2000+ page proven claims, GPU performance
  claims, and Quran-derived public corpus remain out of scope for v1.

</deferred>

---

*Phase: 5-Launch Hardening and Domain Release*
*Context gathered: 2026-05-14*
