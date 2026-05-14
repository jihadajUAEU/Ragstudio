# Feature Research

**Domain:** Open-source static proof viewer and replayable RAG evidence packet
**Researched:** 2026-05-14
**Confidence:** HIGH

## Feature Landscape

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Proof-first landing page | Evaluators need to know what claim is being made before inspecting artifacts | MEDIUM | First viewport should state product/category, proof-backed claim, source commit/tag, and CTA. |
| Static proof viewer | Public claim needs an inspectable evidence trail | HIGH | Claim rail, claim detail, warning/chunk/trace panels, raw artifact links, disabled/roadmap claims. |
| Claims registry | Public claims must be machine-readable and gated | MEDIUM | `claims.registry.json` with statuses, evidence links, code paths, artifact paths, and screenshots. |
| Canonical JSON Schemas | Export, local validation, and site import need one contract | MEDIUM | Store under `docs/benchmarks/ragstudio-oss-proof-v1/schemas/`. |
| Static fixture validation | Fresh checkout must prove the packet without private services | HIGH | `static-fixtures` is the launch gate; live capture is optional. |
| Redaction checks | Public proof artifacts can leak secrets or private paths | HIGH | Fail closed on API keys, private hosts, local paths, and known local IP/host patterns. |
| Replay/export manifests | Reviewers need commit/hash provenance | MEDIUM | Include source commit/tag, packet hash, artifact hashes, validation status, and timestamps. |
| Proof docs and errors catalog | Developers need setup, replay, claim, and failure guidance | MEDIUM | QUICKSTART, REPLAY, CLAIMS, ERRORS, COMPATIBILITY. |
| Accessibility and responsive gates | Public site must be usable and credible | MEDIUM | WCAG 2.2 AA, keyboard path, mobile no-overflow checks. |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Claim-to-warning-to-chunk-to-trace trail | Turns "trust us" into inspectable evidence | HIGH | This is the core launch moment. |
| Honest disabled/roadmap claims | Builds trust by showing what is not proven | MEDIUM | Disabled claims should not feel like broken features. |
| Proof packet import contract | Keeps website from becoming an unverified marketing copy | HIGH | Site import must reject packets local proof rejects. |
| Demo screenshots with static data | Shows real Studio UI without hosting upload/backend | MEDIUM | Screenshot review must include manual secret/private-content signoff. |
| `./scripts/proof.sh` golden command | Makes evaluator hello-world fast and repeatable | MEDIUM | Output should be human-readable and include machine-readable structured errors on failure. |
| Deep-linked proof feedback | Lets reviewers challenge a claim with artifact context | MEDIUM | Include claim id, artifact path, packet hash, and commit in issue/discussion template links. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Public upload demo | Looks impressive and interactive | Requires auth, quotas, abuse controls, egress controls, and provider cost management | Static proof viewer plus screenshots. |
| Live API-backed proof viewer | Feels current | Adds uptime and backend drift risk to an evidence page | Import immutable proof packet fixtures. |
| Big "2000+ pages" claim | Sounds powerful | Unproven until a scale benchmark exists | Roadmap label until measured. |
| GPU performance claim | Attractive to RAG users | False unless benchmark actually uses/measures GPU path | Appendix or disabled/roadmap claim. |
| Hide disabled claims | Makes launch look cleaner | Reduces trust and invites overclaiming | Show disabled and roadmap claims with reasons. |

## Feature Dependencies

```text
Canonical JSON Schemas
    -> Proof Fixtures
        -> Replay Validation
            -> Export Manifest
                -> Site Import
                    -> Static Proof Viewer

Claims Registry
    -> Claim Detail UI
        -> Feedback Deep Links

Redaction Rules
    -> Replay Validation
    -> Export Validation
    -> Screenshot Signoff

Cloudflare Pages Project
    -> New Domain
        -> Public Launch
```

### Dependency Notes

- **Proof viewer requires site import:** The viewer should render only imported, validated fixtures.
- **Site import requires schemas and manifests:** Otherwise stale or malformed packets can deploy.
- **Launch requires domain:** The chosen launch blocker means a Pages preview URL is not enough.
- **Screenshots require redaction signoff:** Text scanners do not prove images are safe.

## MVP Definition

### Launch With (v1)

- [ ] New `ragstudio-site` repo and Cloudflare Pages project with required new domain.
- [ ] Landing page with short product story and `Inspect the proof trail` CTA.
- [ ] Static proof viewer with claim list, claim detail, warning/unit, chunk/source, retrieval trace, graph/reranker evidence states, and raw artifact links.
- [ ] Public proof packet with synthetic corpus, schemas, artifacts, screenshots, run notes, claims registry, and claims matrix.
- [ ] `./scripts/proof.sh` no-Docker validation command.
- [ ] Site import script that validates schema, hash, source commit/tag, redaction, fixture size, and structured import errors.
- [ ] WCAG 2.2 AA automated and manual launch checks.

### Add After Validation (v1.x)

- [ ] More domain packs once flagship proof is credible.
- [ ] Optional live-capture refresh path documentation and UX.
- [ ] More proof viewer filtering/search once claim volume grows.
- [ ] Release-note automation for proof packet schema updates.

### Future Consideration (v2+)

- [ ] Hosted read-only API demo.
- [ ] Public upload sandbox.
- [ ] Community-submitted failure-pattern library.
- [ ] Scale benchmarks and measured GPU claims.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Proof packet schemas and fixtures | HIGH | MEDIUM | P1 |
| Redaction/hash/claim validation | HIGH | HIGH | P1 |
| `./scripts/proof.sh` | HIGH | MEDIUM | P1 |
| `ragstudio-site` scaffold | HIGH | MEDIUM | P1 |
| Static proof viewer | HIGH | HIGH | P1 |
| Cloudflare Pages + domain | HIGH | MEDIUM | P1 |
| Screenshots | MEDIUM | MEDIUM | P1 |
| Feedback templates | MEDIUM | LOW | P2 |
| Starter domain packs | MEDIUM | MEDIUM | P2 |
| Live capture | MEDIUM | HIGH | P3 |

## Competitor Feature Analysis

| Feature | Observability/eval tools | Static docs sites | Our Approach |
|---------|--------------------------|-------------------|--------------|
| Claim proof | Usually dashboards/traces or benchmark results | Usually prose/screenshots | Claim registry plus raw artifacts plus source commit. |
| First-time proof path | SDK install or hosted login | Read docs | Static viewer plus no-Docker proof command. |
| Disabled claims | Often omitted | Often roadmap prose | Visible statuses: proven, roadmap, disabled. |
| Reproducibility | Usually code examples or notebooks | Rarely enforced | Static fixture gate and import contract. |

## Sources

- `.planning/PROJECT.md` - approved launch context and constraints.
- `.planning/codebase/ARCHITECTURE.md` - existing Ragstudio proof machinery.
- `/Users/meet/.gstack/projects/Ragstudio/ceo-plans/2026-05-13-ragstudio-open-source-proof-system.md` - accepted scope, UX, DX, and test requirements.
- https://developers.cloudflare.com/pages/configuration/git-integration/ - Pages deploy/preview expectations.
- https://www.w3.org/TR/wcag/ - WCAG 2.2 AA target basis.
- https://playwright.dev/docs/accessibility-testing - accessibility test strategy.

---
*Feature research for: open-source static proof viewer and replayable RAG evidence packet*
*Researched: 2026-05-14*
