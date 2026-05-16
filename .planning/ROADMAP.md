# Roadmap: Ragstudio Open-Source Proof System Launch

## Overview

This roadmap turns Ragstudio's existing RAG evidence machinery into a public, replayable proof system. The build moves vertically from a canonical proof packet, to a no-Docker proof command, to a separate static site import path, to the proof-viewer experience, and finally to public launch gates on Cloudflare Pages with a connected domain.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Proof Contract and Baseline Packet** - Create the canonical public proof packet, schemas, claims registry, and safe baseline evidence.
- [x] **Phase 2: Replay and Export Tooling** - Make `./scripts/proof.sh` validate the static proof packet from a fresh checkout.
- [ ] **Phase 3: `ragstudio-site` Scaffold and Import Pipeline** - Create the separate static site repo boundary and packet import gate.
- [ ] **Phase 4: Static Proof Viewer and Public Site UX** - Build the inspectable public proof viewer and demo screenshot experience.
- [ ] **Phase 5: Launch Hardening and Domain Release** - Connect Cloudflare/domain, enforce accessibility and launch gates, and publish links.
- [x] **Phase 6: App Evidence Viewer and Runtime Trust Banner** - Add in-app evidence inspection and compact runtime trust visibility for Ragstudio operators.

## Phase Details

### Phase 1: Proof Contract and Baseline Packet
**Goal**: A maintainer can inspect a safe, versioned proof packet with canonical schemas, claims, fixtures, artifacts, screenshots, run notes, and known limitations.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: PROOF-01, PROOF-02, PROOF-03, PROOF-04, PROOF-05, PROOF-06, DOCS-03, DOCS-05
**UI hint**: no
**Success Criteria** (what must be TRUE):
  1. Maintainer can open `docs/benchmarks/ragstudio-oss-proof-v1/` and see schemas, fixtures, artifacts, screenshots, run notes, corpus notes, claims registry, and claims matrix.
  2. Maintainer can verify the baseline corpus is synthetic, multilingual/reference-heavy, and safe to redistribute.
  3. Each public claim has a status, source reference, evidence paths, and visible limitation language when it is not proven.
  4. Claim and compatibility docs explain claim status, schema version, packet version, supported runtime, and site import compatibility.
**Plans**: 3 plans

Plans:
- [x] 01-01: Create proof packet folder, synthetic corpus notes, and artifact layout.
- [x] 01-02: Define JSON Schemas, claims registry, claims matrix, and compatibility metadata.
- [x] 01-03: Add claim docs, status rules, and baseline redaction expectations.

### Phase 2: Replay and Export Tooling
**Goal**: A developer can run one fresh-checkout command that validates static fixtures, rejects unsafe or stale proof packets, and reports structured failures.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: VAL-01, VAL-02, VAL-03, VAL-04, VAL-05, VAL-07, DOCS-01, DOCS-02, DOCS-04
**UI hint**: no
**Success Criteria** (what must be TRUE):
  1. Developer can run `./scripts/proof.sh` without Docker, secrets, live providers, a running backend, or private files.
  2. Validator rejects invalid schemas, missing artifacts, broken hashes, stale metadata, and public-leak patterns.
  3. Proof output includes both a readable summary and structured error codes with recovery docs.
  4. Replay/export tests cover the happy path and representative validation failures.
**Plans**: 3 plans

Plans:
- [x] 02-01: Implement proof validator, schema loading, hashing, and redaction checks.
- [x] 02-02: Add `./scripts/proof.sh`, export manifest generation, and structured proof errors.
- [x] 02-03: Add replay/export tests and QUICKSTART, REPLAY, and ERRORS docs.

### Phase 3: `ragstudio-site` Scaffold and Import Pipeline
**Goal**: The separate `ragstudio-site` repository can import only validated proof packets and build a static site without Ragstudio backend dependencies.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: VAL-06, SITE-01, SITE-04
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. `ragstudio-site` exists as a separate repository boundary for the canonical public site.
  2. Site import rejects every packet that local proof validation rejects.
  3. Site build uses imported static fixtures only and contains no upload, auth, provider, or live backend path.
  4. Import/build checks can run before any public deploy work begins.
**Plans**: 2 plans

Plans:
- [x] 03-01: Scaffold `ragstudio-site` with React/Vite, fixture layout, and static-only build constraints.
- [x] 03-02: Implement packet import validation, fixture generation, and import failure tests.

### Phase 4: Static Proof Viewer and Public Site UX
**Goal**: A skeptical visitor can land on the public story, click `Inspect the proof trail`, and inspect claim-to-artifact evidence through an accessible static viewer.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: VIEW-01, VIEW-02, VIEW-03, VIEW-04, VIEW-05, VIEW-06, VIEW-07
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. Visitor sees a short product story and primary `Inspect the proof trail` CTA in the first viewport.
  2. Visitor can scan proven, roadmap, and disabled claims without hidden or inflated claims.
  3. Visitor can open a claim and inspect warning/unit, chunk/source, retrieval, graph/reranker, screenshot, and raw artifact evidence where available.
  4. Visitor can deep link or give feedback with claim id, artifact path, packet hash, and source commit context.
  5. Demo screenshots show approved Ragstudio UI states and have manual no-private-content signoff.
**Plans**: 3 plans

Plans:
- [x] 04-01: Build first viewport, navigation, claim list, status model, and static routing.
- [x] 04-02: Build claim detail panels, evidence views, raw artifact links, and feedback deep links.
- [x] 04-03: Add demo screenshots, screenshot signoff records, responsive polish, and fixture loading behavior.

### Phase 5: Launch Hardening and Domain Release
**Goal**: The proof system is publicly launched through Cloudflare Pages on the required domain with accessibility, validation, and release gates passing.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: SITE-02, SITE-03, SITE-05, QA-01, QA-02, QA-03, QA-04, QA-05
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. `ragstudio-site` deploys from Git through a new Cloudflare Pages project.
  2. New public domain is connected before launch is marked complete.
  3. Playwright and axe checks cover the main proof-viewer flow and launch checklist blocks release on proof, redaction, import, accessibility, domain, or link failures.
  4. Manual launch checks cover keyboard navigation, mobile layout, text overflow, raw artifact fallbacks, and no incoherent overlap.
  5. `README.md` and `jihadaj.com` link to the public site as amplifiers.
**Plans**: 3 plans

Plans:
- [x] 05-01: Configure Cloudflare Pages Git deployment and required domain release gate.
- [x] 05-02: Add Playwright/axe checks, manual launch checklist, performance/fixture-size checks, and release blocking behavior.
- [ ] 05-03: Update README/profile links, run final proof/import/site launch verification, and record release proof.

### Phase 6: App Evidence Viewer and Runtime Trust Banner
**Goal**: Ragstudio operators can inspect the trust state of the running app and open query evidence in context without leaving the Studio shell.
**Mode:** mvp
**Depends on**: Phase 5
**Requirements**: APP-UI-01, APP-UI-02
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. The app shell shows a compact runtime trust status derived from current diagnostics.
  2. The status detail panel explains which runtime dependency or projection state is ready, degraded, or blocking.
  3. Query result sources can open a focused evidence view with chunk text, metadata, parser warnings, quality status, and reranker context where available.
  4. Evidence links can route back to existing Documents, Chunks, Query, Graph, and Diagnostics surfaces without duplicating those pages.
  5. The phase does not introduce exportable investigation reports; reporting remains a later phase after the viewer and status primitives exist.
**Plans**: 3 plans

Plans:
- [x] 06-01: Add runtime trust chip, diagnostics polling, detail panel, and provider test actions.
- [x] 06-02: Build the shared evidence viewer and wire Query source inspection.
- [x] 06-03: Add Chunk Inspector evidence entry, graph/missing-state behavior, and final accessibility/build verification.

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Proof Contract and Baseline Packet | 3/3 | Complete | 2026-05-14 |
| 2. Replay and Export Tooling | 3/3 | Complete | 2026-05-14 |
| 3. `ragstudio-site` Scaffold and Import Pipeline | 2/2 | Complete | 2026-05-14 |
| 4. Static Proof Viewer and Public Site UX | 3/3 | Complete | 2026-05-14 |
| 5. Launch Hardening and Domain Release | 2/3 | In Progress | - |
| 6. App Evidence Viewer and Runtime Trust Banner | 3/3 | Complete | 2026-05-16 |

## Coverage

| Phase | Requirements |
|-------|--------------|
| Phase 1 | PROOF-01, PROOF-02, PROOF-03, PROOF-04, PROOF-05, PROOF-06, DOCS-03, DOCS-05 |
| Phase 2 | VAL-01, VAL-02, VAL-03, VAL-04, VAL-05, VAL-07, DOCS-01, DOCS-02, DOCS-04 |
| Phase 3 | VAL-06, SITE-01, SITE-04 |
| Phase 4 | VIEW-01, VIEW-02, VIEW-03, VIEW-04, VIEW-05, VIEW-06, VIEW-07 |
| Phase 5 | SITE-02, SITE-03, SITE-05, QA-01, QA-02, QA-03, QA-04, QA-05 |
| Phase 6 | APP-UI-01, APP-UI-02 |

**Coverage:**
- v1 requirements: 35 total
- Mapped to phases: 35
- Unmapped: 0

---
*Roadmap created: 2026-05-14*
