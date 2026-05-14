# Ragstudio Open-Source Proof System Launch

## What This Is

Ragstudio is an existing local RAG data-quality workbench for inspecting document
parsing, chunk metadata, runtime retrieval, reranker traces, graph projection, and
quality-gated materialization before bad evidence reaches answers. This project
turns the existing proof machinery into an open-source launch package: a new public
`ragstudio-site` domain with a static proof viewer, replayable proof packet, docs,
screenshots, and claim registry tied back to Ragstudio source artifacts.

The launch should make one public story obvious: RAG failures often start before
retrieval, and Ragstudio makes those failures visible, traceable, and gateable.

## Core Value

Every public Ragstudio claim must be inspectable from claim text to replayable
evidence, source commit, raw artifact, and known limitation.

## Requirements

### Validated

- Existing Ragstudio backend exposes FastAPI routes for documents, jobs, chunks,
  query, settings, variants, evaluation, experiments, optimizer, graph, and
  diagnostics.
- Existing document pipeline can upload files, queue indexing jobs, use MinerU
  strict parsing, persist chunks, and store job status/progress/logs.
- Existing quality gate derives parser/domain/reference warnings and
  `quality_action_policy` metadata that controls vector indexing and graph
  projection behavior.
- Existing query path persists sources, chunk traces, reranker traces, timings,
  token metadata, and failed-run error state.
- Existing frontend provides operator views for documents, warning details, chunk
  inspection, query traces, settings, graph, diagnostics, variants, evaluation,
  experiments, comparison, optimizer, and pipeline status.
- Existing test suite covers many backend services, runtime behavior, frontend
  pages, and selected Playwright flows.
- Phase 1 validated the public proof packet under
  `docs/benchmarks/ragstudio-oss-proof-v1/` with schemas, synthetic fixtures,
  redacted artifacts, approved screenshot signoff, claims registry, claims
  matrix, compatibility docs, limitations, and redaction status.

### Active

- [ ] Implement shared proof-packet validation code under
  `backend/src/ragstudio/proof_packet/` for schema loading, redaction, hashing,
  manifests, structured errors, replay validation, and export validation.
- [ ] Add thin CLI wrappers for proof replay/export, with `./scripts/proof.sh` as
  the first-time developer entrypoint and `static-fixtures` as the required
  fresh-checkout launch gate.
- [ ] Build or prepare a separate `ragstudio-site` repository as the canonical
  public entrypoint, deployed by a new Cloudflare Pages project on a new domain.
- [ ] Make the new domain required for public launch; do not count the release as
  launched until the domain is connected.
- [ ] Design the public site as a short product-story first viewport followed by
  a primary CTA: `Inspect the proof trail`.
- [ ] Implement the site as a static proof viewer plus demo screenshots: no
  upload, no auth, and no live backend calls.
- [ ] Ensure the proof viewer renders local proof fixtures only, with proven,
  roadmap, and disabled claims visible and deep-linkable.
- [ ] Keep `README.md` and `jihadaj.com` as amplifiers that link to the public
  site, not as the source of truth.
- [ ] Meet WCAG 2.2 Level AA for the implemented public site and proof viewer
  surfaces.
- [ ] Add public CI/release gates for schema validation, artifact hashes,
  redaction, claim evidence, fixture size, static viewer import, and core proof
  viewer flows.

### Out of Scope

- Public hosted upload demo - too much security, cost, abuse, auth, quota, and
  provider-egress risk for V1.
- Live backend calls from the launch site - the V1 site is static and renders
  imported fixtures only.
- Customer validation claim - not true until named users, interviews, usage, or
  revenue exists.
- 2000+ page scale claim - roadmap only until a measured scale benchmark exists.
- GPU performance claim - appendix or roadmap only unless the benchmark actually
  uses and measures the GPU path.
- Quran-derived public corpus - deferred until redistribution, screenshot, and
  excerpt rights are verified.
- Full automatic docs update pipeline - phase two after the proof packet is
  credible and stable.
- Dark/neon/terminal launch direction - rejected; use the Technical Field Guide
  direction from `DESIGN.md`.

## Context

Ragstudio already has the technical proof signals, but the evidence is scattered
across code, UI, API payloads, docs, tests, and local runs. The active project is
packaging those scattered signals into a public, repeatable proof trail.

The approved GStack plan is:
`/Users/meet/.gstack/projects/Ragstudio/ceo-plans/2026-05-13-ragstudio-open-source-proof-system.md`.

The codebase map is in `.planning/codebase/` and identifies the current system as
a local full-stack RAG workbench with:

- Python/FastAPI backend in `backend/src/ragstudio`.
- React/Vite frontend in `frontend/src`.
- Async indexing worker in `backend/src/ragstudio/workers/index_worker.py`.
- PostgreSQL/PGVector and Neo4j storage from `docker-compose.yml`.
- Native RAG-Anything, LightRAG, MinerU, OCR, reranker, and provider-manifest
  integrations.
- Existing tests under `backend/tests`, `frontend/tests`, and `e2e`.

The public launch decisions gathered during initialization are:

- Public launch shape: new `ragstudio-site` first as the canonical public entrypoint.
- Site target: new Cloudflare Pages project plus new domain.
- Launch blocker: the new domain is required before the release counts as public.
- Repo boundary: new `ragstudio-site` repo, separate from the Ragstudio app repo.
- Site behavior: static proof viewer plus demo screenshots.
- First viewport: short product story before the proof viewer.
- Main CTA: `Inspect the proof trail`.

## Constraints

- **Security**: Public artifacts must not leak API keys, private endpoints, private
  hostnames, local absolute paths, unpublished model hosts, or private content.
- **Architecture**: Ragstudio remains the proof-packet source of truth; the site
  imports and renders exported proof packets.
- **Deployment**: Public site deploys through Cloudflare Pages Git integration and
  does not count as launched until the new domain is connected.
- **Runtime**: Fresh-checkout proof validation must use `static-fixtures`; live
  capture is optional and must not require private providers.
- **Corpus**: V1 public baseline is a deterministic synthetic
  multilingual/reference-heavy corpus unless a publishability review approves a
  real public corpus.
- **Accessibility**: Implemented public surfaces must meet WCAG 2.2 Level AA.
- **Design**: `DESIGN.md` is the visual source of truth; avoid generic SaaS,
  decorative hero art, dark neon terminals, and card-heavy marketing patterns.
- **Developer Experience**: The first-time proof path should target a 2-5 minute
  trust moment through `./scripts/proof.sh` and the proof viewer.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Launch as an open-source proof system, not just another RAG dashboard | The distinctive value is evidence-backed document quality before retrieval | Pending |
| Use a separate `ragstudio-site` repo | Keeps public brand/deploy surface clean and prevents the site from becoming the product-claim source of truth | Pending |
| Require a new domain for public launch | Clean public launch surface matters more than a temporary Pages URL | Pending |
| Use static proof viewer plus demo screenshots | Provides inspectable trust without public upload/auth/backend risk | Pending |
| Put short product story before proof viewer | Visitors need the problem and category before entering the evidence instrument | Pending |
| Make `Inspect the proof trail` the main CTA | The proof trail is the trust moment | Pending |
| Use `static-fixtures` as the required gate | Fresh checkouts must validate without Docker providers, secrets, or live backend dependencies | Pending |
| Keep live capture optional | Live evidence refresh is valuable but too environment-dependent for a public release gate | Pending |
| Make disabled and roadmap claims visible | Honest non-claims improve trust and prevent inflated marketing | Pending |
| Follow Technical Field Guide design direction | Matches the proof-system personality and prior design review decision | Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `$gsd-transition`):
1. Requirements invalidated? Move to Out of Scope with reason.
2. Requirements validated? Move to Validated with phase reference.
3. New requirements emerged? Add to Active.
4. Decisions to log? Add to Key Decisions.
5. "What This Is" still accurate? Update if drifted.

**After each milestone** (via `$gsd-complete-milestone`):
1. Full review of all sections.
2. Core Value check - still the right priority?
3. Audit Out of Scope - reasons still valid?
4. Update Context with current state.

---
*Last updated: 2026-05-14 after initialization*
