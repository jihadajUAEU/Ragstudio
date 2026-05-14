# Project Research Summary

**Project:** Ragstudio Open-Source Proof System Launch
**Domain:** Open-source static proof viewer and replayable RAG evidence packet
**Researched:** 2026-05-14
**Confidence:** HIGH

## Executive Summary

Ragstudio already has the hard part: parser warnings, domain/reference quality
policy, chunk evidence, retrieval traces, reranker traces, graph projection, and
job diagnostics. The launch should not rebuild the app. It should package those
signals into a static, replayable proof system with a new `ragstudio-site` as the
canonical public surface and Ragstudio as the proof-packet source of truth.

The recommended path is contract-first: define canonical JSON Schemas, create a
synthetic public proof packet, implement no-Docker static-fixture validation, then
import that packet into a React/Vite static proof viewer deployed through
Cloudflare Pages Git integration on the required new domain. Live capture remains
optional and must never block fresh-checkout proof validation.

The main risks are overclaiming, secret/private data leaks, schema drift between
Ragstudio and the site repo, and accessibility failures in the dense proof UI.
Mitigate them with claim status gates, redaction and screenshot signoff, shared
schemas, structured proof errors, and WCAG 2.2 AA launch checks.

## Key Findings

### Recommended Stack

Use TypeScript/Node for the public proof command and `ragstudio-site` import path,
React/Vite for the static proof viewer, JSON Schema 2020-12 for canonical
contracts, Ajv for TypeScript validation, Vitest for unit/component tests, and
Playwright plus `@axe-core/playwright` for browser/accessibility gates.

**Core technologies:**
- TypeScript/Node: no-Docker proof validation and site import.
- React/Vite: static proof viewer and field-guide public site.
- JSON Schema 2020-12: portable artifact contract.
- Cloudflare Pages Git integration: preview/production deploys tied to Git.
- Playwright/axe: automated accessibility smoke checks, paired with manual checks.

### Expected Features

**Must have (table stakes):**
- Proof-first landing page with short product story and `Inspect the proof trail`.
- Static proof viewer with claim list, detail panels, raw artifact links, and visible proven/roadmap/disabled statuses.
- Canonical schemas, claims registry, replay/export manifests, and redaction gates.
- `./scripts/proof.sh` golden command that runs without Docker, providers, live backend, or private files.
- Site import script that rejects packets local validation rejects.
- WCAG 2.2 AA automated and manual launch checks.

**Should have (competitive):**
- Deep-linked feedback with claim id, artifact path, packet hash, and commit.
- Demo screenshots showing the real app without hosting upload/backend.
- Domain-pack examples only after flagship proof is stable.

**Defer (v2+):**
- Public hosted upload demo.
- Live read-only API demo.
- GPU/scale/customer claims until measured.
- Community failure-pattern library.

### Architecture Approach

Use a two-repo architecture. Ragstudio owns the proof packet, schemas, replay,
export, and source evidence. `ragstudio-site` imports a validated packet and
renders static fixtures only. Cloudflare Pages deploys the site from Git; the new
domain is a launch blocker.

**Major components:**
1. Canonical proof packet - schemas, fixtures, artifacts, screenshots, claims registry, run notes.
2. Proof validation/export tooling - schema, hash, redaction, manifest, error handling.
3. Site import pipeline - validates packet before committing/deploying fixtures.
4. Static proof viewer - claim rail, evidence panels, lazy artifact loading, raw fallbacks.
5. Launch/deploy gate - Cloudflare Pages project, required domain, accessibility and proof checks.

### Critical Pitfalls

1. **Overclaiming** - render public claims from `claims.registry.json` and gate `proven` status.
2. **Secret/private leaks** - fail closed on redaction, require screenshot signoff.
3. **Fresh checkout failure** - make `static-fixtures` and `./scripts/proof.sh` the required path.
4. **Schema drift** - use canonical JSON Schema files across Ragstudio and `ragstudio-site`.
5. **Late accessibility fixes** - design proof viewer interactions and layout around WCAG 2.2 AA from the first implementation phase.

## Implications for Roadmap

### Phase 1: Proof Contract and Baseline Packet
**Rationale:** Every later site/import/viewer feature depends on stable schemas,
fixtures, claim statuses, and redaction rules.
**Delivers:** Benchmark folder, schemas, synthetic corpus, required artifacts,
claims registry, run notes, errors catalog, compatibility notes.
**Addresses:** Proof packet, claims registry, redaction, overclaim prevention.
**Avoids:** Schema drift and overclaiming.

### Phase 2: Replay and Export Tooling
**Rationale:** The packet needs a fast no-Docker trust command before public site work can be meaningful.
**Delivers:** `./scripts/proof.sh`, proof validator, structured errors, export manifest, tests.
**Uses:** TypeScript/Node public validator plus Ragstudio backend proof helpers where useful.
**Implements:** Fresh-checkout static-fixtures gate.

### Phase 3: `ragstudio-site` Scaffold and Import Pipeline
**Rationale:** Site import can start once the schema/import manifest shape is stable.
**Delivers:** Separate repo scaffold, Vite/React app, import script, imported fixtures, CI checks.
**Uses:** Cloudflare Pages Git integration and JSON Schema validation.
**Implements:** Cross-repo proof packet contract.

### Phase 4: Static Proof Viewer and Public Site UX
**Rationale:** The viewer is the public trust moment and should be built on already validated fixtures.
**Delivers:** Landing page, proof viewer, claim/evidence panels, screenshot/demo pages, raw links, feedback handoff.
**Addresses:** Skeptical reviewer journey.
**Avoids:** Generic SaaS launch feel and claim-context loss.

### Phase 5: Launch Hardening and Domain Release
**Rationale:** Public launch requires the domain, accessibility gates, performance checks, README/profile links, and release proof.
**Delivers:** Cloudflare Pages project, required new domain, WCAG 2.2 AA gates, Playwright flow, README proof-first update, `jihadaj.com` card update.
**Addresses:** Launch blocker and credibility gates.

### Phase Ordering Rationale

- Schemas and packet contract must come before replay/export and site import.
- Replay/export must come before proof viewer polish because the viewer should not render unvalidated claims.
- Site scaffold can run after the import manifest stabilizes.
- Domain/deploy hardening comes last because it should publish only a verified packet and accessible viewer.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2:** Ajv 2020-12 configuration and structured error CLI conventions.
- **Phase 3:** Cloudflare Pages Git integration and repo/domain setup details.
- **Phase 5:** WCAG 2.2 AA accessibility implementation and test tooling details.

Phases with standard patterns:
- **Phase 1:** JSON fixture/schema layout is well-defined by the approved plan.
- **Phase 4:** React/Vite static viewer patterns are standard, but design should follow `DESIGN.md`.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Based on existing Ragstudio stack plus official Cloudflare, Vite, JSON Schema, WCAG, and Playwright docs. |
| Features | HIGH | Approved GStack plan and user decisions are specific. |
| Architecture | HIGH | Two-repo source/import/viewer model is explicit in the approved plan. |
| Pitfalls | HIGH | Risks are directly tied to launch constraints and codebase map concerns. |

**Overall confidence:** HIGH

### Gaps to Address

- Exact public domain name: choose before launch hardening.
- Exact `ragstudio-site` repository location/owner: confirm before scaffold.
- Exact TypeScript proof-contract sharing method: package vs copied source can be decided during Phase 2/3 planning.
- Screenshot review procedure: define manual signoff format before export.

## Sources

### Primary (HIGH confidence)
- `.planning/PROJECT.md` - current project definition and user decisions.
- `.planning/codebase/*.md` - existing Ragstudio architecture, stack, tests, integrations, and concerns.
- `/Users/meet/.gstack/projects/Ragstudio/ceo-plans/2026-05-13-ragstudio-open-source-proof-system.md` - approved launch plan and review addenda.
- https://developers.cloudflare.com/pages/configuration/git-integration/ - Cloudflare Pages Git integration.
- https://vite.dev/guide/static-deploy.html - Vite static deployment to Cloudflare Pages.
- https://json-schema.org/specification - JSON Schema 2020-12 basis.
- https://www.w3.org/TR/wcag/ - WCAG 2.2 basis.
- https://playwright.dev/docs/accessibility-testing - Playwright/axe accessibility testing guidance.

### Secondary (MEDIUM confidence)
- https://react.dev/learn/start-a-new-react-project - React build-tool guidance.

---
*Research completed: 2026-05-14*
*Ready for roadmap: yes*
