# Walking Skeleton - Ragstudio Open-Source Proof System Launch

**Phase:** 1
**Generated:** 2026-05-14

## Capability Proven End-to-End

A maintainer can inspect a static public proof packet root and trace a public claim from registry entry to fixture/artifact paths, manifest provenance, limitation text, and safety status.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Proof source | Ragstudio repo under `docs/benchmarks/ragstudio-oss-proof-v1/` | Ragstudio remains the source of truth for proof packets and exported evidence. |
| Contract format | JSON Schema 2020-12 + JSON fixtures | Portable across backend validation, Node proof tooling, and `ragstudio-site` import. |
| Public claim source | `claims/claims.registry.json` | Claims must be data-driven so the public viewer cannot overclaim. |
| Human review surface | Markdown docs plus `claims/claims.matrix.md` | Reviewers need a readable path before CLI/site tooling exists. |
| Safety gate | Manifest redaction status + screenshot signoff + exclusion reasons | Public proof must fail closed on private evidence and unapproved screenshots. |
| Later runtime | Phase 2 `./scripts/proof.sh`, Phase 3 `ragstudio-site`, Phase 4 viewer | Phase 1 defines the packet contract only; execution tooling comes later. |

## Stack Touched in Phase 1

- [x] Project scaffold already exists as a brownfield Ragstudio app.
- [ ] Static proof packet root under `docs/benchmarks/ragstudio-oss-proof-v1/`.
- [ ] Canonical schemas and fixtures for one small synthetic evidence packet.
- [ ] Machine-readable claims registry and full provenance manifest.
- [ ] Human-readable packet docs, limitations, compatibility notes, and screenshot signoff.

## Out of Scope (Deferred to Later Slices)

- `backend/src/ragstudio/proof_packet/` implementation.
- `./scripts/proof.sh` and executable validation.
- `ragstudio-site` repository and import pipeline.
- Static proof viewer UX.
- Cloudflare Pages deployment and domain launch.

## Subsequent Slice Plan

- Phase 2: Add replay/export tooling and `./scripts/proof.sh`.
- Phase 3: Create `ragstudio-site` scaffold and import pipeline.
- Phase 4: Build the static proof viewer and public UX.
- Phase 5: Add launch hardening, Cloudflare Pages deployment, and domain release.

