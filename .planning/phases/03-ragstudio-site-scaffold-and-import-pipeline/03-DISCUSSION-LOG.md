# Phase 3: `ragstudio-site` Scaffold and Import Pipeline - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-14
**Phase:** 3-`ragstudio-site` Scaffold and Import Pipeline
**Areas discussed:** Repo boundary, Import gate, Static-only boundary

---

## Gray Areas Selected

| Option | Description | Selected |
|--------|-------------|----------|
| All three | Covers repo location, import rejection contract, and static-only build boundaries. | ✓ |
| Import gate | Focuses only on how the site rejects packets that proof validation rejects. | |
| Repo boundary | Focuses only on where the separate `ragstudio-site` scaffold should live. | |

**User's choice:** A / All three.
**Notes:** Phase 3 decisions should cover the separate repo boundary, validator
parity, and static-only enforcement before planning.

---

## Repo Boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Sibling folder next to Ragstudio | Create or use `/Users/meet/Documents/ragstudio-site` as the separate repo boundary. | ✓ |
| Subfolder inside current repo temporarily | Scaffold under the Ragstudio checkout first, then split later. | |
| GitHub-first empty repo | Create or target a remote repo first, then clone/scaffold into it. | |

**User's choice:** A / sibling folder.
**Notes:** The sibling path gives a real separate site boundary while avoiding
remote setup during Phase 3.

---

## Import Gate

| Option | Description | Selected |
|--------|-------------|----------|
| Shell out to Ragstudio proof command | Importer runs `../Ragstudio/scripts/proof.sh --strict --json --packet <packet>`. | ✓ |
| Reimplement validation in TypeScript | Site importer validates schemas and hashes itself. | |
| Hybrid | Shell out for Phase 3 plus a small TypeScript shape check. | |

**User's choice:** A / shell out to Ragstudio validator.
**Notes:** Validator parity matters more than standalone site validation in
Phase 3.

---

## Static-Only Boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Build/test guardrails | Fail if the site imports backend clients, uses live API URLs, auth/upload routes, or provider env vars. | ✓ |
| Convention only | Document the static-only rules and enforce later in Phase 5 QA. | |
| Very strict package boundary | No runtime network libraries at all in Phase 3. | |

**User's choice:** A / build and test guardrails.
**Notes:** Static-only behavior should be enforced now, not left as convention.

---

## the agent's Discretion

- Exact React/Vite scaffold details.
- Exact import output folder and fixture filenames.
- Exact test/script names for static-only guardrails.

## Deferred Ideas

- GitHub remote creation and Cloudflare Pages deployment.
- Full proof viewer UX and launch page.
- TypeScript reimplementation of the proof validator.
