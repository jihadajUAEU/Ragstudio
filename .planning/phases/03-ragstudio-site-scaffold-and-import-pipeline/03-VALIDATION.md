---
phase: 03
slug: ragstudio-site-scaffold-and-import-pipeline
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-14
---

# Phase 03 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | npm scripts, Vitest or Node test runner, Vite build |
| **Site root** | `/Users/meet/Documents/ragstudio-site` |
| **Import source** | `/Users/meet/Documents/Ragstudio/docs/benchmarks/ragstudio-oss-proof-v1` |
| **Proof command** | `../Ragstudio/scripts/proof.sh --strict --json --packet <packet>` |
| **Quick run command** | `cd /Users/meet/Documents/ragstudio-site && npm test` |
| **Full phase command** | `cd /Users/meet/Documents/ragstudio-site && npm run import:proof && npm run check:static && npm test && npm run build` |
| **Estimated runtime** | ~5-20 seconds after dependencies are installed |

---

## Sampling Rate

- **After scaffold task:** Run `npm test` and `npm run build`.
- **After import task:** Run `npm run import:proof` and inspect generated fixture files.
- **After guardrail task:** Run `npm run check:static`, `npm test`, and `npm run build`.
- **Before `$gsd-verify-work`:** Run the full phase command above and confirm `../Ragstudio/scripts/proof.sh --strict --json --packet ../Ragstudio/docs/benchmarks/ragstudio-oss-proof-v1` still passes.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | SITE-01 | T-03-01 | Sibling site folder exists outside the Ragstudio app repo and is initialized independently. | filesystem/git | `test -d /Users/meet/Documents/ragstudio-site && git -C /Users/meet/Documents/ragstudio-site status --short --branch` | W0 | pending |
| 03-01-02 | 01 | 1 | SITE-04 | T-03-02 | Scaffold builds from local static React code and does not import Ragstudio app frontend. | build/test | `cd /Users/meet/Documents/ragstudio-site && npm test && npm run build` | W0 | pending |
| 03-02-01 | 02 | 2 | VAL-06 | T-03-03 | Importer rejects packets when Ragstudio proof validation rejects them. | import/test | `cd /Users/meet/Documents/ragstudio-site && npm test` | W0 | pending |
| 03-02-02 | 02 | 2 | SITE-04 | T-03-04 | Generated fixture outputs are static and build-time only. | import/build | `cd /Users/meet/Documents/ragstudio-site && npm run import:proof && npm run build` | W0 | pending |
| 03-02-03 | 02 | 2 | SITE-04 | T-03-05 | Guardrails fail on backend/API/upload/auth/provider patterns. | guard/test | `cd /Users/meet/Documents/ragstudio-site && npm run check:static && npm test` | W0 | pending |

*Status: pending - green - red - flaky*

---

## Wave 0 Requirements

- [ ] `/Users/meet/Documents/ragstudio-site/package.json` - independent site package scripts.
- [ ] `/Users/meet/Documents/ragstudio-site/scripts/import-proof-packet.mjs` - import gate that shells out to `proof.sh`.
- [ ] `/Users/meet/Documents/ragstudio-site/scripts/check-static-boundary.mjs` - static-only guardrail.
- [ ] `/Users/meet/Documents/ragstudio-site/tests/` - import and guardrail coverage.

---

## Manual-Only Verifications

No manual-only verification should be required in Phase 3. Public UX and
accessibility manual review are deferred to Phases 4 and 5.

---

## Validation Sign-Off

- [ ] All tasks have automated verification or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Full phase command passes from `/Users/meet/Documents/ragstudio-site`
- [ ] `nyquist_compliant: true` set in frontmatter after implementation

**Approval:** pending
