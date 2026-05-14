---
phase: 04
slug: static-proof-viewer-and-public-site-ux
status: verified
threats_open: 0
asvs_level: 1
created: 2026-05-14
---

# Phase 04 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Static proof imports | Generated JSON fixtures are imported into the React viewer at build time. | Public proof metadata, claim text, artifact paths, validation ids |
| Static public assets | Approved screenshot files are served from `public/proof/ragstudio-oss-proof-v1`. | Screenshot image and signoff metadata approved for public release |
| Visitor browser | Visitors open static pages and click local anchors, artifact links, or GitHub feedback links. | Public proof context and encoded issue body text |
| Deferred live systems | Ragstudio backend, upload, auth, provider endpoints, and private data remain outside Phase 04. | No live application data crosses into the static viewer |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-04-01 | Spoofing / Trust | First viewport | mitigate | Viewer uses approved proof-first copy and packet metadata rather than a generic marketing page. Evidence: `/Users/meet/Documents/ragstudio-site/src/App.tsx`, `tests/app.test.tsx`. | closed |
| T-04-02 | Tampering | Claim status model | mitigate | Proven, roadmap, and disabled claim groups are all rendered and tested, preventing hidden or inflated claim states. Evidence: `ClaimGroups` in `/Users/meet/Documents/ragstudio-site/src/App.tsx`; grouped-claim tests. | closed |
| T-04-03 | Information Disclosure | Static-only boundary | mitigate | `scripts/check-static-boundary.mjs` blocks live API routes, auth/upload routes, provider env strings, and live HTTP fetches in the scanned build surface. Latest run passed. | closed |
| T-04-04 | Repudiation | Proof metadata | mitigate | Packet id, validation id, source commit, and claim ids render in dossiers and feedback links. Evidence: `ProofSummary`, `ClaimDossier`, and feedback tests. | closed |
| T-04-05 | Denial of Service / UX Integrity | Long metadata and paths | mitigate | CSS uses `overflow-wrap: anywhere`, constrained max widths, and mobile grid collapse to prevent proof ids, paths, and URLs from breaking layout. | closed |
| T-04-06 | Tampering | Evidence detail | mitigate | Claim dossiers render explicit limitations, missing evidence, disabled reasons, and requirements to prove, so incomplete details are not presented as proof. Evidence: roadmap and disabled detail tests. | closed |
| T-04-07 | Availability / Integrity | Artifact links | mitigate | Static artifact links are deterministic under `/proof/ragstudio-oss-proof-v1/...`; unavailable copied artifacts display `Not available in this static build.` rather than silently implying availability. | closed |
| T-04-08 | Repudiation | Feedback path | mitigate | `Open feedback issue` links encode claim id, artifact path, packet id, validation id, source commit, and viewer hash; external links use `target="_blank"` with `rel="noreferrer"`. | closed |
| T-04-09 | Information Disclosure | Screenshot assets | mitigate | Only screenshot files listed in signoff with `safe_to_publish: true` were copied. The public screenshot folder contains only `signoff.json` and `documents-page-desktop-empty-state.png`. | closed |
| T-04-10 | Information Disclosure / UX Integrity | Screenshot rendering | mitigate | Screenshot sections show reviewer, reviewed date, safe-to-publish state, notes, and alt text; no proven claim depends on screenshot-only evidence. Evidence: signoff file and screenshot tests. | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

No accepted risks.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-05-14 | 10 | 10 | 0 | Codex inline security auditor |

---

## Verification Evidence

- `cd /Users/meet/Documents/ragstudio-site && npm run check:static` — passed
- `cd /Users/meet/Documents/ragstudio-site && npm test` — passed, 3 files and 11 tests
- `find public/proof/ragstudio-oss-proof-v1/screenshots -maxdepth 1 -type f` — only approved signoff JSON and approved screenshot image are present
- Source review confirmed no `fetch`, live API, upload, auth route, provider environment, or Ragstudio frontend import in the scanned static site surface

---

## Residual Follow-Up

- Formal WCAG/axe coverage remains in Phase 05.
- Public domain, Cloudflare Pages release gates, and final launch checklist remain in Phase 05.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-05-14
