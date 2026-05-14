# Pitfalls Research

**Domain:** Open-source static proof viewer and replayable RAG evidence packet
**Researched:** 2026-05-14
**Confidence:** HIGH

## Critical Pitfalls

### Pitfall 1: Overclaiming

**What goes wrong:**
Homepage or README claims say reranker, graph gating, GPU, scale, or customer
validation is proven when the packet does not contain matching evidence.

**Why it happens:**
Marketing copy moves faster than artifact validation.

**How to avoid:**
Gate every `status="proven"` claim against existing code, artifact, screenshot,
or run-note evidence. Force absent reranker/graph/scale/GPU evidence into
`disabled` or `roadmap`.

**Warning signs:**
Claim copy appears outside `claims.registry.json`, or a site component hardcodes
public claims.

**Phase to address:**
Phase 1 and Phase 2.

---

### Pitfall 2: Secret or Private Data Leak

**What goes wrong:**
Artifacts, screenshots, run notes, or manifests expose API keys, private hosts,
local absolute paths, LAN IPs, unpublished endpoints, or private corpus text.

**Why it happens:**
Proof packets are copied from live local runs without a fail-closed redaction
gate and manual screenshot signoff.

**How to avoid:**
Run redaction checks before replay/export/import; require screenshot review; block
on `secret_detected`; allowlist only with explicit run-note rationale.

**Warning signs:**
Artifacts include `localhost`, `10.x`, `/Users/`, model endpoints, or screenshots
with settings pages.

**Phase to address:**
Phase 1.

---

### Pitfall 3: Fresh Checkout Cannot Prove Anything

**What goes wrong:**
The proof path requires Docker, a live backend, provider keys, saved settings, or
private PDFs.

**Why it happens:**
Live-capture is treated as the release gate instead of an optional refresh path.

**How to avoid:**
Make `static-fixtures` the required release gate and keep live-capture optional.
Ensure `./scripts/proof.sh` runs without Docker or secrets.

**Warning signs:**
Quickstart begins with `docker compose up`, provider configuration, or upload
steps before proof inspection.

**Phase to address:**
Phase 1 and Phase 3.

---

### Pitfall 4: Schema Drift Across Repos

**What goes wrong:**
Ragstudio export, local proof validation, and `ragstudio-site` import disagree
about artifact shape.

**Why it happens:**
Python, TypeScript, and example JSON schemas evolve separately.

**How to avoid:**
Use canonical JSON Schema files. Test both local proof and site import against the
same files.

**Warning signs:**
TypeScript interface changes without schema changes, or Python model changes
without fixture validation failures.

**Phase to address:**
Phase 1 and Phase 4.

---

### Pitfall 5: Accessibility Treated as an End Polish Step

**What goes wrong:**
Proof viewer has clickable divs, poor focus order, hidden raw links, non-announced
loading/error states, or mobile overflow.

**Why it happens:**
The proof UI is dense and table/JSON heavy; accessibility is postponed until after
layout is built.

**How to avoid:**
Build with WCAG 2.2 AA constraints from the start; run Playwright/axe plus manual
keyboard and screen-reader smoke checks before launch.

**Warning signs:**
Claim rows are not real buttons/links, long hashes widen the page, or evidence
status depends on color alone.

**Phase to address:**
Phase 4 and Phase 5.

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Hardcode claims in React | Fast prototype | Claim drift and unverified copy | Never for public claims. |
| Validate screenshots only by filename | Easy export | Private visual leaks | Never for public launch. |
| Use live backend as proof gate | Realistic data | Fresh-checkout failure and flaky launch | Optional live-capture only. |
| Duplicate schema definitions | Faster local coding | Cross-repo drift | Only temporary before first public packet; remove before launch. |
| Skip Cloudflare domain until later | Faster preview | Violates chosen launch blocker | Not acceptable for public launch. |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Cloudflare Pages Git integration | Assuming Direct Upload can be switched on later | Choose Git integration deliberately; Cloudflare documents that Git-integrated projects cannot switch to Direct Upload later. |
| JSON Schema 2020-12 | Using older draft defaults silently | Configure validator for 2020-12 and test invalid fixtures. |
| Playwright/axe | Treating automated checks as complete WCAG proof | Combine automated checks with keyboard, screen-reader label, and mobile overflow smoke tests. |
| GitHub feedback | Linking only to generic issues | Include claim id, artifact path, packet hash, and commit. |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Load all artifacts at first render | Slow landing/proof route | Manifest-first loading and lazy artifact panels | Larger traces/screenshots. |
| Render entire trace tables | Browser jank and mobile overflow | Preview caps plus hidden count and raw link | Long retrieval/chunk traces. |
| Oversized fixture bundle | Slow deploy and viewer load | Import/export size gate | Multiple packets or screenshots. |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Publishing live provider URLs | Exposes private infrastructure | Fail closed on private host patterns. |
| Publishing local paths | Leaks machine/user structure | Redaction scanner blocks `/Users/`, drive roots, and absolute local paths. |
| Treating screenshot text scanning as sufficient | OCR can miss visual secrets | Require manual screenshot signoff. |
| Hosted upload in V1 | Abuse and data exposure | Keep site static. |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Generic feature-grid homepage | Reviewer cannot tell what is proven | Lead with product story and proof CTA. |
| Hidden disabled claims | Reviewer distrusts omitted claims | Show disabled/roadmap status and reason. |
| Claim detail loses context | Reviewer forgets what is being verified | Keep selected claim visible while evidence changes. |
| Error says only "failed" | Developer cannot recover | Show path, code, cause, fix, and raw fallback. |
| Long JSON widens page | Mobile unusable | Local scroll containers and capped previews. |

## "Looks Done But Isn't" Checklist

- [ ] **Proof viewer:** Often missing raw artifact fallback - verify every capped/failed panel links to raw JSON or notes.
- [ ] **Claims registry:** Often missing disabled/roadmap rationale - verify every non-proven claim explains missing evidence.
- [ ] **Replay command:** Often passes happy path only - verify each required error code has mutation/failure coverage.
- [ ] **Redaction:** Often scans text but not screenshots - verify manual screenshot signoff is recorded.
- [ ] **Cloudflare deploy:** Often works on Pages URL only - verify required domain is connected before launch.
- [ ] **Accessibility:** Often only automated axe runs - verify keyboard and screen-reader smoke path.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Overclaiming | MEDIUM | Move claim to disabled/roadmap, regenerate registry, update site copy from registry. |
| Secret leak in artifact | HIGH | Revoke leaked credential if real, remove artifact, add scanner pattern, regenerate packet. |
| Schema drift | MEDIUM | Promote canonical schema, regenerate fixtures/types, add import/replay regression. |
| Domain not ready | LOW/MEDIUM | Continue private preview, but do not mark launch complete. |
| Accessibility failure late | MEDIUM/HIGH | Fix semantic structure and layout before content polish; rerun gates. |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Overclaiming | Phase 1: Proof contract and fixtures | Bad claim evidence test fails release. |
| Secret/private leak | Phase 1: Proof contract and fixtures | Redaction tests and screenshot signoff. |
| Fresh checkout failure | Phase 2: Replay/export command | `./scripts/proof.sh` clean-checkout stopwatch. |
| Schema drift | Phase 1 and Phase 4 | Site import rejects schema/hash mismatches. |
| Accessibility late failure | Phase 5: Accessibility/deploy hardening | Playwright/axe plus manual smoke checks. |

## Sources

- https://developers.cloudflare.com/pages/configuration/git-integration/ - Cloudflare Pages Git integration caveats.
- https://www.w3.org/TR/wcag/ - WCAG 2.2 basis.
- https://playwright.dev/docs/accessibility-testing - automated accessibility limits and axe integration.
- `.planning/codebase/CONCERNS.md` - local codebase risks and proof-system gaps.
- Approved GStack open-source proof plan - launch pitfalls, redaction, DX, and design contracts.

---
*Pitfalls research for: open-source static proof viewer and replayable RAG evidence packet*
*Researched: 2026-05-14*
