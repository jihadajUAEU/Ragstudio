# Requirements: Ragstudio Open-Source Proof System Launch

**Defined:** 2026-05-14
**Core Value:** Every public Ragstudio claim must be inspectable from claim text to replayable evidence, source commit, raw artifact, and known limitation.

## v1 Requirements

Requirements for the initial public proof-system release. Each requirement maps to exactly one roadmap phase.

### Proof Packet

- [x] **PROOF-01**: Maintainer can find the public proof packet under `docs/benchmarks/ragstudio-oss-proof-v1/` with schemas, fixtures, artifacts, screenshots, run notes, corpus notes, claims registry, and claims matrix.
- [x] **PROOF-02**: Proof packet uses a deterministic synthetic multilingual and reference-heavy corpus that is safe to redistribute publicly.
- [x] **PROOF-03**: Proof packet includes canonical JSON Schema 2020-12 files for claims, artifacts, manifests, validation results, and site import fixtures.
- [x] **PROOF-04**: Claims registry records each public claim with status, source commit or tag, evidence links, code paths, artifact paths, and screenshot references where applicable.
- [x] **PROOF-05**: Each `proven` claim maps to at least one raw artifact and one human-readable explanation.
- [x] **PROOF-06**: `roadmap` and `disabled` claims remain visible with reasons and without implied proof.

### Replay And Validation

- [ ] **VAL-01**: Developer can run `./scripts/proof.sh` in a fresh checkout using `static-fixtures` without Docker, secrets, live providers, a running backend, or private files.
- [ ] **VAL-02**: Proof validator rejects invalid schemas, missing artifacts, broken hashes, and stale commit or packet metadata.
- [ ] **VAL-03**: Proof validator fails closed on API keys, private endpoints, private hostnames, local absolute paths, known local IP patterns, and other public-leak patterns.
- [ ] **VAL-04**: Proof validation output includes a human-readable summary and structured error codes.
- [ ] **VAL-05**: Export manifest records source commit or tag, packet hash, artifact hashes, validation status, and timestamps.
- [ ] **VAL-06**: Site import rejects any proof packet that local validation rejects.
- [ ] **VAL-07**: Proof replay, export, and import tests cover success paths and common failure paths.

### Public Site And Deployment

- [ ] **SITE-01**: Separate `ragstudio-site` repository exists as the canonical public entrypoint.
- [ ] **SITE-02**: `ragstudio-site` deploys through a new Cloudflare Pages project connected to Git.
- [ ] **SITE-03**: New public domain is connected before the release is counted as publicly launched.
- [ ] **SITE-04**: Public site builds and runs without Ragstudio backend calls, upload flows, authentication, or live providers.
- [ ] **SITE-05**: `README.md` and `jihadaj.com` link to the public site as amplifiers rather than acting as the source of truth.

### Static Proof Viewer

- [ ] **VIEW-01**: First viewport presents a short product story and the primary CTA `Inspect the proof trail`.
- [ ] **VIEW-02**: Proof viewer renders imported static fixtures only and does not call a live backend.
- [ ] **VIEW-03**: User can scan a claim list with visible `proven`, `roadmap`, and `disabled` statuses.
- [ ] **VIEW-04**: User can open a claim detail and inspect warning or unit evidence, chunk or source evidence, retrieval trace evidence, graph or reranker evidence states, and raw artifact links where available.
- [ ] **VIEW-05**: User can deep link to a claim, and feedback links include claim id, artifact path, packet hash, and source commit.
- [ ] **VIEW-06**: Demo screenshots show real Ragstudio UI states using static or approved public data.
- [ ] **VIEW-07**: Screenshot review records manual signoff that images contain no private content, secrets, or private infrastructure details.

### Documentation

- [ ] **DOCS-01**: `QUICKSTART` explains the fresh-checkout `./scripts/proof.sh` path in 2-5 minute terms.
- [ ] **DOCS-02**: `REPLAY` explains static fixture validation and clearly labels live capture as optional.
- [x] **DOCS-03**: `CLAIMS` explains claim statuses, claims matrix, and how evidence links prove or limit each claim.
- [ ] **DOCS-04**: `ERRORS` documents structured proof, export, and import errors with recovery guidance.
- [x] **DOCS-05**: `COMPATIBILITY` records schema version, supported Node runtime, packet version, and site import compatibility.

### Launch Quality Gates

- [ ] **QA-01**: Public site and proof viewer meet WCAG 2.2 Level AA for implemented surfaces.
- [ ] **QA-02**: Automated Playwright and axe checks cover the main proof-viewer flow.
- [ ] **QA-03**: Manual launch checks cover keyboard navigation, mobile layout, text overflow, raw artifact fallbacks, and no incoherent overlap.
- [ ] **QA-04**: Fixture size, lazy loading, and raw artifact fallback behavior keep the proof viewer usable on desktop and mobile.
- [ ] **QA-05**: Launch checklist blocks release until proof validation, redaction, site import, accessibility, domain connection, and README/profile links pass.

## v2 Requirements

Deferred to future releases. Tracked here, but not part of the current roadmap.

### Expanded Proof Coverage

- **EXP-01**: Maintainer can publish additional domain proof packs after the flagship proof packet is stable.
- **EXP-02**: Maintainer can refresh proof packets from optional live capture without changing the required static-fixture launch gate.
- **EXP-03**: Public proof viewer supports richer filtering and search once claim volume grows.
- **EXP-04**: Release notes can be generated automatically when proof packet schemas or claims change.

### Public Demos

- **DEMO-01**: Visitor can inspect a hosted read-only API demo after uptime, abuse, cost, and drift controls exist.
- **DEMO-02**: Visitor can try a public upload sandbox after authentication, quota, abuse, and provider-egress controls exist.

### Benchmarks

- **BENCH-01**: Public site can show measured scale benchmarks after the benchmark actually runs and publishes artifacts.
- **BENCH-02**: Public site can show GPU performance claims after GPU path usage and measurement are proven in artifacts.

## Out of Scope

Explicitly excluded from v1 to keep the launch credible, reproducible, and safe.

| Feature | Reason |
|---------|--------|
| Public hosted upload demo | Requires auth, quotas, abuse controls, egress controls, provider cost controls, and safety hardening beyond v1. |
| Live API-backed launch site | Adds uptime and backend drift risk to a proof page; v1 renders imported static fixtures only. |
| Customer validation claim | Not true until named users, interviews, usage, or revenue exists. |
| 2000+ page scale claim | Roadmap only until a measured scale benchmark exists. |
| GPU performance claim | Appendix or roadmap only unless the benchmark actually uses and measures the GPU path. |
| Quran-derived public corpus | Deferred until redistribution, screenshot, and excerpt rights are verified. |
| Full automatic docs update pipeline | Deferred until the proof packet is credible and stable. |
| Hidden disabled claims | Hiding non-proven claims invites overclaiming; v1 must show disabled and roadmap claims honestly. |
| Dark/neon/terminal launch direction | Rejected by design review; use the Technical Field Guide direction from `DESIGN.md`. |

## Traceability

Roadmap creation fills the phase mapping. Every v1 requirement must map to exactly one phase.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PROOF-01 | Phase 1 | Complete |
| PROOF-02 | Phase 1 | Complete |
| PROOF-03 | Phase 1 | Complete |
| PROOF-04 | Phase 1 | Complete |
| PROOF-05 | Phase 1 | Complete |
| PROOF-06 | Phase 1 | Complete |
| VAL-01 | Phase 2 | Pending |
| VAL-02 | Phase 2 | Pending |
| VAL-03 | Phase 2 | Pending |
| VAL-04 | Phase 2 | Pending |
| VAL-05 | Phase 2 | Pending |
| VAL-06 | Phase 3 | Pending |
| VAL-07 | Phase 2 | Pending |
| SITE-01 | Phase 3 | Pending |
| SITE-02 | Phase 5 | Pending |
| SITE-03 | Phase 5 | Pending |
| SITE-04 | Phase 3 | Pending |
| SITE-05 | Phase 5 | Pending |
| VIEW-01 | Phase 4 | Pending |
| VIEW-02 | Phase 4 | Pending |
| VIEW-03 | Phase 4 | Pending |
| VIEW-04 | Phase 4 | Pending |
| VIEW-05 | Phase 4 | Pending |
| VIEW-06 | Phase 4 | Pending |
| VIEW-07 | Phase 4 | Pending |
| DOCS-01 | Phase 2 | Pending |
| DOCS-02 | Phase 2 | Pending |
| DOCS-03 | Phase 1 | Complete |
| DOCS-04 | Phase 2 | Pending |
| DOCS-05 | Phase 1 | Complete |
| QA-01 | Phase 5 | Pending |
| QA-02 | Phase 5 | Pending |
| QA-03 | Phase 5 | Pending |
| QA-04 | Phase 5 | Pending |
| QA-05 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 35 total
- Mapped to phases: 35
- Unmapped: 0

---
*Requirements defined: 2026-05-14*
*Last updated: 2026-05-14 after roadmap creation*
