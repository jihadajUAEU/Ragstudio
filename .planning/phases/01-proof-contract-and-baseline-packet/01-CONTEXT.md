# Phase 1: Proof Contract and Baseline Packet - Context

**Gathered:** 2026-05-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 1 defines the public proof packet contract and baseline evidence package for Ragstudio. It must create a safe, versioned, reviewer-readable packet under `docs/benchmarks/ragstudio-oss-proof-v1/` with canonical schemas, fixtures, exported artifacts, screenshots, run notes, corpus notes, claims registry, claims matrix, and limitations. It does not implement the proof command, site import pipeline, public proof viewer, Cloudflare deploy, or launch-domain work; those are later phases.

</domain>

<decisions>
## Implementation Decisions

### Proof Packet Contents
- **D-01:** The baseline packet must be evidence-complete: schemas, fixtures, raw artifacts, screenshots, run notes, corpus notes, claims registry, claims matrix, and limitations are mandatory for Phase 1.
- **D-02:** The packet must use reviewer-first folders: `schemas/`, `fixtures/`, `artifacts/`, `screenshots/`, `claims/`, and `docs/`.
- **D-03:** Raw artifacts must be full exported run artifacts after redaction, not schema-only examples or hand-curated snippets.
- **D-04:** The top-level manifest must guarantee every artifact path, SHA-256 hash, source commit or tag, packet version, generated timestamp, claim count, and redaction status.

### Claim Status Rules
- **D-05:** A claim can be marked `proven` only when it is public-artifact-backed: it has a registry entry, source code path, source commit or tag, raw artifact link, human-readable explanation, and redaction pass.
- **D-06:** `roadmap` claims must remain visible and explicitly unproven, with reason, missing evidence, and planned proof path.
- **D-07:** `disabled` claims must remain visible as safety stops, with why disabled, what would be needed to prove them, and no inclusion in proven totals.
- **D-08:** Private or local-only evidence can never support `proven`; the affected claim must become `roadmap` or `disabled`.

### Synthetic Corpus Shape
- **D-09:** The Phase 1 corpus must be a multi-case synthetic corpus covering parser warnings, multilingual text, reference/unit structure, retrieval traces, and graph/reranker states.
- **D-10:** The corpus must include Arabic + English reference units while avoiding restricted real corpus material.
- **D-11:** The corpus must intentionally include representative parser-quality warnings such as missing script, missing unit/reference patterns, and recovery notes, enough to exercise quality gates.
- **D-12:** Phase 1 must include static approved screenshots from the current Ragstudio UI after manual redaction/signoff.

### Public Safety Boundary
- **D-13:** Redaction must fail closed on API keys/tokens, private hosts, local absolute paths, LAN IPs, unpublished model endpoints, private content snippets, and unapproved screenshots.
- **D-14:** Screenshot publication requires a manual signoff file; each screenshot entry must include reviewer, date, source path, and safe-to-publish status.
- **D-15:** Unsafe or unapproved artifacts must be excluded with reason; the manifest records the exclusion reason and affected claims cannot be `proven`.
- **D-16:** Host/IP examples may use only reserved documentation examples, such as reserved/example domains or IP ranges; never use real LAN hosts.

### the agent's Discretion
- The agent may choose exact JSON Schema filenames, manifest field ordering, and fixture filenames as long as the locked folders, provenance guarantees, claim statuses, and public-safety rules above are honored.
- The agent may choose the smallest artifact set that still qualifies as full exported run artifacts and satisfies the Phase 1 success criteria.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Scope
- `.planning/PROJECT.md` - Project definition, constraints, public launch decisions, and out-of-scope boundaries.
- `.planning/REQUIREMENTS.md` - Phase 1 requirement IDs and v1 requirement definitions.
- `.planning/ROADMAP.md` - Phase 1 goal, success criteria, and dependency boundary.
- `.planning/STATE.md` - Current project status and known blockers.

### Research
- `.planning/research/SUMMARY.md` - Research synthesis and phase-ordering rationale.
- `.planning/research/FEATURES.md` - Table-stakes features and anti-features for the public proof system.
- `.planning/research/ARCHITECTURE.md` - Proposed proof packet and site import architecture.
- `.planning/research/PITFALLS.md` - Overclaiming, redaction, fresh-checkout, schema drift, and accessibility risks.

### Codebase Map
- `.planning/codebase/ARCHITECTURE.md` - Existing Ragstudio data flow, quality policy, retrieval traces, and observability architecture.
- `.planning/codebase/STRUCTURE.md` - Where proof/benchmark tooling and docs should live.
- `.planning/codebase/CONVENTIONS.md` - Naming, error-handling, and module conventions for future implementation.

### Approved Plan
- `/Users/meet/.gstack/projects/Ragstudio/ceo-plans/2026-05-13-ragstudio-open-source-proof-system.md` - Approved GStack launch plan and review addenda.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `docs/` already exists and is the right parent for public benchmark/proof artifacts.
- `scripts/` already holds developer commands and is the later home for `proof.sh`; Phase 1 should not implement that command yet.
- Backend services already persist parser warnings, chunk metadata, `quality_action_policy`, run sources, chunk traces, reranker traces, graph projection records, and job diagnostics that later export tooling can turn into artifacts.

### Established Patterns
- Backend code uses service classes and Pydantic/JSON-like schemas; future proof-packet code should follow that service/schema split.
- Public proof artifacts should avoid runtime/generated directories such as `.ragstudio/`, `reports/`, `artifacts/`, and `output/` unless exported into the reviewed `docs/benchmarks/ragstudio-oss-proof-v1/` packet.
- Documentation uses Markdown with explicit sections and should keep limitations near claims to prevent overclaiming.

### Integration Points
- Phase 1 creates packet/docs/schema artifacts only. Phase 2 will add shared proof-packet validation code under `backend/src/ragstudio/proof_packet/` and CLI wrappers.
- Phase 3 will import the packet into `ragstudio-site`; schema and manifest choices in Phase 1 must be stable enough for that cross-repo contract.
- Phase 4 will render screenshots and evidence states; Phase 1 screenshot signoff and claim metadata must provide enough context for the later viewer.

</code_context>

<specifics>
## Specific Ideas

- Use `docs/benchmarks/ragstudio-oss-proof-v1/` as the packet root.
- Use reviewer-first folders: `schemas/`, `fixtures/`, `artifacts/`, `screenshots/`, `claims/`, and `docs/`.
- Use `claims.registry.json` or an equivalent registry file that can express `proven`, `roadmap`, and `disabled`.
- Treat `proven` as public evidence only; tests or maintainer approval alone are not enough.
- Include Arabic + English synthetic reference units and representative parser-quality warnings.
- Include manual screenshot signoff as a first-class packet artifact.
- Use reserved/example domains or IP ranges for documentation examples; never use actual LAN/private hosts.

</specifics>

<deferred>
## Deferred Ideas

None - discussion stayed within phase scope.

</deferred>

---

*Phase: 1-Proof Contract and Baseline Packet*
*Context gathered: 2026-05-14*
