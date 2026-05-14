# Phase 1: Proof Contract and Baseline Packet - Research

**Researched:** 2026-05-14
**Domain:** Public proof packet contracts, JSON schemas, evidence manifests, and safe documentation fixtures
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- The baseline packet must be evidence-complete: schemas, fixtures, raw artifacts, screenshots, run notes, corpus notes, claims registry, claims matrix, and limitations are mandatory for Phase 1.
- The packet must use reviewer-first folders: `schemas/`, `fixtures/`, `artifacts/`, `screenshots/`, `claims/`, and `docs/`.
- Raw artifacts must be full exported run artifacts after redaction, not schema-only examples or hand-curated snippets.
- The top-level manifest must guarantee every artifact path, SHA-256 hash, source commit or tag, packet version, generated timestamp, claim count, and redaction status.
- A claim can be marked `proven` only when it is public-artifact-backed: registry entry, source code path, source commit or tag, raw artifact link, explanation, and redaction pass.
- `roadmap` claims must remain visible and explicitly unproven, with reason, missing evidence, and planned proof path.
- `disabled` claims must remain visible as safety stops, with why disabled, what would be needed to prove them, and no inclusion in proven totals.
- Private or local-only evidence can never support `proven`; the affected claim must become `roadmap` or `disabled`.
- The Phase 1 corpus must be a multi-case synthetic corpus covering parser warnings, multilingual text, reference/unit structure, retrieval traces, and graph/reranker states.
- The corpus must include Arabic + English reference units while avoiding restricted real corpus material.
- The corpus must intentionally include representative parser-quality warnings such as missing script, missing unit/reference patterns, and recovery notes, enough to exercise quality gates.
- Phase 1 must include static approved screenshots from the current Ragstudio UI after manual redaction/signoff.
- Redaction must fail closed on API keys/tokens, private hosts, local absolute paths, LAN IPs, unpublished model endpoints, private content snippets, and unapproved screenshots.
- Screenshot publication requires a manual signoff file; each screenshot entry must include reviewer, date, source path, and safe-to-publish status.
- Unsafe or unapproved artifacts must be excluded with reason; the manifest records the exclusion reason and affected claims cannot be `proven`.
- Host/IP examples may use only reserved documentation examples, such as reserved/example domains or IP ranges; never use real LAN hosts.

### the agent's Discretion
- Exact JSON Schema filenames, manifest field ordering, and fixture filenames.
- Smallest artifact set that still qualifies as full exported run artifacts and satisfies Phase 1 success criteria.

### Deferred Ideas (OUT OF SCOPE)
- No proof command implementation in Phase 1.
- No site import pipeline in Phase 1.
- No public proof viewer or Cloudflare launch work in Phase 1.
</user_constraints>

<architectural_responsibility_map>
## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|--------------|----------------|-----------|
| Proof packet folder and fixtures | Static/docs artifact | Backend/export later | Phase 1 creates reviewed public files under `docs/benchmarks/`; generation code comes later. |
| Canonical JSON schemas | Static contract | Backend/site later | Schemas are the cross-repo contract that Phase 2 validators and Phase 3 importers consume. |
| Claims registry and matrix | Static contract | Static viewer later | Claim status rules must be machine-readable before the viewer exists. |
| Exported run artifacts | Static/docs artifact | Backend evidence sources | Phase 1 stores redacted exported artifacts; Phase 2 can automate validation/export. |
| Screenshot signoff | Static/docs artifact | Public viewer later | Signoff records are public-safety proof and later feed screenshot display. |
| Corpus notes and run notes | Static docs | Backend evidence sources | Humans need to understand what the synthetic packet proves before tooling exists. |
</architectural_responsibility_map>

<research_summary>
## Summary

Phase 1 should be planned as a contract-and-fixtures phase, not a validation-tooling phase. The repo already has the evidence-producing systems: parser quality warnings, `quality_action_policy`, chunk metadata, query traces, reranker traces, graph projection state, and job diagnostics. This phase should freeze a public, safe, versioned packet shape that future tooling can validate and future site code can import.

The standard approach is manifest-first with canonical schemas. Use JSON Schema 2020-12 for the packet contracts, a top-level manifest for provenance and hash coverage, and separate registries/matrices for claims so that public marketing claims cannot drift away from public evidence. Use reserved documentation domains and address blocks for examples instead of any real private hostnames or LAN IPs.

**Primary recommendation:** Create a small but evidence-complete packet under `docs/benchmarks/ragstudio-oss-proof-v1/` with reviewer-first folders, JSON Schema 2020-12 contracts, full provenance manifest, public claim statuses, synthetic Arabic/English fixtures, exported evidence artifacts, screenshot signoff, and explicit limitations.
</research_summary>

<standard_stack>
## Standard Stack

### Core

| Tool/Standard | Version | Purpose | Why Standard |
|---------------|---------|---------|--------------|
| JSON Schema | 2020-12 | Define portable packet, claim, manifest, artifact, screenshot, and validation-result contracts | Current JSON Schema spec and latest meta-schema; shared by Node/site and backend tooling. |
| SHA-256 | n/a | Artifact integrity hashes in the top-level manifest | Stable, common artifact hashing algorithm for reproducible manifests. |
| Markdown | n/a | Human-readable run notes, corpus notes, limitations, and claim docs | Git-reviewable and already used throughout `docs/`. |
| JSON fixtures | n/a | Machine-readable claims, manifests, synthetic corpus, and evidence artifacts | Easy to validate with JSON Schema and import into static site tooling. |

### Supporting

| Tool/Standard | Purpose | When to Use |
|---------------|---------|-------------|
| RFC 5737 TEST-NET ranges | Safe IPv4 examples | Use `192.0.2.0/24`, `198.51.100.0/24`, or `203.0.113.0/24` when documentation needs example IPs. |
| IANA Special-Use Domain Names | Safe domain examples | Use `example.com`, `example.net`, `example.org`, `.example`, `.invalid`, `.test`, or `.localhost` where appropriate. |
| Existing Ragstudio docs conventions | Consistent repository docs | Put proof docs under the packet's `docs/` folder and keep limitations near claims. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| JSON Schema 2020-12 | TypeScript-only types | TS types help implementation but do not validate backend/site/runtime-independent JSON artifacts. |
| Full manifest hash coverage | Folder-only manifests | Folder manifests are useful later, but Phase 1 needs one top-level provenance source. |
| Evidence-complete packet | Minimal schema examples | Minimal examples would not satisfy the public proof promise or user-selected decisions. |
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### System Architecture Diagram

```text
Synthetic corpus notes
    -> fixtures/*.json
    -> exported evidence artifacts
        -> claims/claims.registry.json
        -> claims/claims.matrix.md
            -> manifest.json with hashes, source commit/tag, redaction status
                -> Phase 2 proof validator
                -> Phase 3 site importer
                -> Phase 4 static proof viewer

Screenshots
    -> screenshots/*.png
    -> screenshots/signoff.json
        -> manifest.json
        -> affected claim evidence links
```

### Recommended Project Structure

```text
docs/benchmarks/ragstudio-oss-proof-v1/
|-- manifest.json
|-- schemas/
|   |-- manifest.schema.json
|   |-- claim.schema.json
|   |-- artifact.schema.json
|   |-- screenshot-signoff.schema.json
|   `-- validation-result.schema.json
|-- fixtures/
|   |-- corpus.synthetic.json
|   |-- parser-warnings.synthetic.json
|   |-- retrieval-traces.synthetic.json
|   `-- graph-reranker.synthetic.json
|-- artifacts/
|   |-- parser-quality.export.json
|   |-- chunks.export.json
|   |-- retrieval-run.export.json
|   |-- graph-projection.export.json
|   `-- reranker-trace.export.json
|-- screenshots/
|   |-- signoff.json
|   `-- *.png
|-- claims/
|   |-- claims.registry.json
|   `-- claims.matrix.md
`-- docs/
    |-- QUICKSTART.md
    |-- CLAIMS.md
    |-- COMPATIBILITY.md
    |-- RUN-NOTES.md
    |-- CORPUS.md
    |-- LIMITATIONS.md
    `-- REDACTION.md
```

### Pattern 1: Contract Before Generator

**What:** Hand-author the public packet contract and a small baseline packet first; automate validation/export in Phase 2.
**When to use:** When later tooling and site import depend on stable JSON shapes.
**Planning implication:** Phase 1 tasks should create schemas/fixtures/docs only. Do not add `backend/src/ragstudio/proof_packet/` implementation yet.

### Pattern 2: Claims as Data, Not Copy

**What:** Store each public claim in `claims.registry.json` with status, evidence paths, code paths, source commit/tag, limitations, and missing proof path when not proven.
**When to use:** Any claim that will be rendered publicly later.
**Planning implication:** `claims.matrix.md` can be a human table generated/maintained from the same claim IDs, but the registry is the source of truth.

### Pattern 3: Safety as Packet Metadata

**What:** Redaction status, screenshot signoff, exclusion reasons, and private-evidence blockers live in the packet and manifest.
**When to use:** For any artifact, screenshot, or claim that might leak local infrastructure or private content.
**Planning implication:** Do not merely document "reviewed"; make the status machine-readable.

### Anti-Patterns to Avoid

- **Marketing claims without artifacts:** A claim that lacks public raw evidence must not be `proven`.
- **Real local examples:** Do not use actual LAN IPs, local paths, hostnames, or model endpoints in examples.
- **Generated-looking screenshots without signoff:** Screenshots need source path, reviewer, date, and safe-to-publish status.
- **Phase leakage:** Do not implement proof CLI, validators, site import, or viewer code in Phase 1.
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON artifact validation contract | Custom prose-only field list | JSON Schema 2020-12 | Later validators/site import need executable schemas. |
| Safe example IP/domain values | Invented fake-looking private hosts | RFC 5737 TEST-NET ranges and IANA special-use/example domains | Prevents accidental real infrastructure references. |
| Claim proof status | Freeform Markdown badges | Machine-readable enum in `claims.registry.json` | Prevents overclaiming and viewer drift. |
| Artifact integrity | Manual "looks present" checklist | SHA-256 hash list in `manifest.json` | Makes missing or changed artifacts detectable later. |

**Key insight:** The hard part is not folder creation; it is preventing public claims, artifacts, and screenshots from drifting apart. Use data contracts and manifest coverage from the beginning.
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Proving With Private Evidence
**What goes wrong:** A claim is marked `proven` because a local run or private screenshot exists, but the public packet cannot show it.
**Why it happens:** Maintainers conflate local confidence with public evidence.
**How to avoid:** Require public artifact paths and redaction pass for every `proven` claim.
**Warning signs:** Claim registry has `proven` entries with missing artifact paths, private path references, or "see local run" notes.

### Pitfall 2: Schema Drift Before Tooling
**What goes wrong:** Manifest, claim registry, and artifacts use inconsistent field names before Phase 2 validation exists.
**Why it happens:** Humans hand-edit several JSON files without a single contract.
**How to avoid:** Create schemas first and make every JSON fixture declare or map to one schema.
**Warning signs:** Same concept appears as `claimId`, `claim_id`, and `id` in different files.

### Pitfall 3: Screenshot Safety Treated as Informal
**What goes wrong:** Screenshots are committed without proof that private content, local paths, endpoints, or real documents were reviewed.
**Why it happens:** Image redaction cannot be fully proven by text scanners.
**How to avoid:** Require screenshot signoff metadata and exclude unapproved images.
**Warning signs:** `screenshots/` contains images but no `signoff.json`, reviewer, source path, or status.

### Pitfall 4: Full Exported Artifacts Become Too Big
**What goes wrong:** "Full exported run artifacts" becomes a large local dump that is hard to review and unsafe to publish.
**Why it happens:** Export is interpreted as entire database/runtime output.
**How to avoid:** Use a deliberately small synthetic run and include complete exported artifacts for that run only.
**Warning signs:** Artifacts contain unrelated documents, runtime cache paths, provider config, or multi-megabyte dumps not tied to claims.
</common_pitfalls>

<code_examples>
## Code Examples

No implementation code is needed in Phase 1. The planner should prefer JSON/Markdown artifact creation tasks and leave executable validation/export examples for Phase 2.
</code_examples>

<sota_updates>
## State of the Art (2024-2026)

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Prose-only benchmark reports | Machine-readable evidence packets plus human docs | Enables static site import and local validation. |
| Draft-07 era schemas by habit | JSON Schema 2020-12 where new contracts are created | Better alignment with current meta-schema and modern validation tooling. |
| Screenshots as marketing assets | Screenshots as signed proof artifacts | Reduces public-leak and overclaim risk. |
</sota_updates>

<open_questions>
## Open Questions

1. **Exact source commit/tag**
   - What we know: manifest must include source commit or tag.
   - What's unclear: whether Phase 1 should pin the current commit immediately or use a placeholder until artifacts are finalized.
   - Recommendation: Planner should include a task that records the current source commit at artifact finalization time, not at plan-writing time.

2. **Exact screenshot set**
   - What we know: screenshots must be current Ragstudio UI states and manually signed off.
   - What's unclear: which views best prove Phase 1 claims before the viewer exists.
   - Recommendation: Use a small set tied to claims: warning/details, chunk/source, query trace, graph/reranker state if available.
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- `.planning/phases/01-proof-contract-and-baseline-packet/01-CONTEXT.md` - locked user decisions for Phase 1.
- `.planning/ROADMAP.md` - Phase 1 boundary and success criteria.
- `.planning/REQUIREMENTS.md` - Phase 1 requirement IDs.
- `.planning/research/SUMMARY.md` - project-level research synthesis.
- `.planning/codebase/ARCHITECTURE.md` - existing evidence-producing systems.
- `.planning/codebase/STRUCTURE.md` - docs and script locations.
- https://json-schema.org/specification - JSON Schema current version, spec split, and 2020-12 meta-schema.
- https://www.rfc-editor.org/rfc/rfc5737 - IPv4 documentation address blocks.
- https://www.iana.org/assignments/special-use-domain-names/special-use-domain-names.xhtml - special-use/example domain registry.

### Secondary (MEDIUM confidence)
- `.planning/research/FEATURES.md` - feature table stakes and anti-features.
- `.planning/research/PITFALLS.md` - launch risk analysis.
</sources>

---
*Phase research completed: 2026-05-14*
