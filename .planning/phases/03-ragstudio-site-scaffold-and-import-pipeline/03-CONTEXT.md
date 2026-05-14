# Phase 3: `ragstudio-site` Scaffold and Import Pipeline - Context

**Gathered:** 2026-05-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 3 creates the separate `ragstudio-site` repository boundary and a static
packet import pipeline. The site repo must be able to import the Phase 1 proof
packet only after Phase 2 validation passes, build from imported static fixtures,
and prove that it contains no Ragstudio backend calls, upload flows,
authentication, or live provider paths.

This phase owns the site scaffold, local sibling repo location, import command,
import fixture output shape, import rejection behavior, and static-only
guardrails. It does not build the final public proof-viewer experience, design
the full landing page, configure Cloudflare Pages, connect a domain, or add
launch accessibility gates; those remain Phases 4 and 5.

</domain>

<decisions>
## Implementation Decisions

### Repository Boundary
- **D-01:** `ragstudio-site` should live as a sibling separate repo/folder at
  `/Users/meet/Documents/ragstudio-site`, not as a subfolder inside the current
  Ragstudio app checkout.
- **D-02:** Phase 3 should scaffold or reuse that sibling folder as the canonical
  site boundary. The current Ragstudio repo remains the source of truth for the
  proof packet and validator.
- **D-03:** The Phase 3 plan should keep repo/owner remotes optional unless an
  existing remote is already configured. Public GitHub/Cloudflare deployment is
  Phase 5 work.

### Import Gate
- **D-04:** The site import gate must shell out to Ragstudio's validator rather
  than reimplementing the validator in TypeScript during Phase 3.
- **D-05:** The canonical import validation command shape is:
  `../Ragstudio/scripts/proof.sh --strict --json --packet <packet>`.
- **D-06:** The importer must reject any proof packet that the local Ragstudio
  proof validator rejects. The `--strict --json` result is the compatibility
  contract between the app repo and the site repo.
- **D-07:** TypeScript-side validation in Phase 3 may perform lightweight shape
  checks on imported fixture output, but it must not become a second source of
  truth for proof validity.

### Static-Only Site Boundary
- **D-08:** Phase 3 must enforce static-only boundaries with build/test
  guardrails, not just documentation.
- **D-09:** Guardrails should fail if the site imports Ragstudio backend clients,
  uses live API URLs, adds auth/upload routes, or depends on provider
  environment variables.
- **D-10:** The site build should use imported static fixtures only. Runtime
  network calls, upload/auth surfaces, live provider configuration, and Ragstudio
  backend API dependencies are out of scope for Phase 3.

### the agent's Discretion
- The agent may choose the exact React/Vite scaffold details, package scripts,
  import output filenames, and test framework conventions after researching the
  sibling site folder state.
- The agent may choose whether import fixtures are written under `src/data/`,
  `public/proof/`, or another static fixture folder, as long as the build is
  static-only and the import output is easy for Phase 4 to render.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Scope
- `.planning/PROJECT.md` - Public launch definition, separate site repo
  decision, static proof viewer constraint, and launch/domain boundaries.
- `.planning/REQUIREMENTS.md` - Phase 3 requirement IDs `VAL-06`, `SITE-01`,
  and `SITE-04`.
- `.planning/ROADMAP.md` - Phase 3 goal, success criteria, dependency on Phase
  2, and two planned slices.
- `.planning/STATE.md` - Current project status and Phase 3 readiness.

### Upstream Proof Packet And Validator
- `.planning/phases/01-proof-contract-and-baseline-packet/01-CONTEXT.md` -
  Locked proof packet folders, claim rules, synthetic corpus shape, and
  public-safety decisions.
- `.planning/phases/02-replay-and-export-tooling/02-CONTEXT.md` - Locked proof
  command, validator output, strictness, and Phase 3 handoff decisions.
- `.planning/phases/02-replay-and-export-tooling/02-VERIFICATION.md` - Evidence
  that `./scripts/proof.sh` and strict JSON validation are complete.
- `scripts/proof.sh` - Import gate command that the site importer must call.
- `backend/src/ragstudio/proof_packet/cli.py` - CLI flags and JSON output
  behavior for proof validation.
- `backend/src/ragstudio/proof_packet/models.py` - Validation result model and
  compact JSON result fields.
- `docs/benchmarks/ragstudio-oss-proof-v1/manifest.json` - Default packet
  manifest the site importer consumes.
- `docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.registry.json` - Claim
  status and evidence source of truth for imported fixtures.
- `docs/benchmarks/ragstudio-oss-proof-v1/schemas/validation-result.schema.json`
  - Machine-readable validation result contract.

### Codebase Map
- `.planning/codebase/STACK.md` - React/Vite/TypeScript stack, npm workflow,
  frontend test tools, and Python proof tooling context.
- `.planning/codebase/STRUCTURE.md` - Existing repo layout and separate
  frontend/script/doc conventions.
- `.planning/codebase/CONVENTIONS.md` - Naming, TypeScript style, testing, and
  frontend import patterns.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/proof.sh` already validates a packet with `--strict --json`; Phase 3
  should call it as the source of truth before importing packet fixtures.
- `backend/src/ragstudio/proof_packet/` contains the validator and result model;
  the site should consume its CLI JSON contract, not import Python internals.
- `docs/benchmarks/ragstudio-oss-proof-v1/` contains the default packet with
  manifest, schemas, claims, artifacts, screenshots, and docs.
- `frontend/` shows existing React/Vite/Tailwind/Testing Library patterns in
  this repo, but Phase 3 should create a separate sibling site boundary instead
  of extending that app frontend.

### Established Patterns
- Frontend code uses TypeScript, React, Vite, npm scripts, kebab-case feature
  files, Vitest, and Testing Library.
- Existing app frontend is operational UI; `ragstudio-site` should be a public
  static site/import boundary with no live app backend dependency.
- Validation scripts and first-time developer commands live under `scripts/`;
  the sibling site can have its own npm scripts while calling the Ragstudio
  proof command through a relative path.

### Integration Points
- Sibling site path: `/Users/meet/Documents/ragstudio-site`.
- Upstream app repo path from the sibling site: `../Ragstudio`.
- Import input: `../Ragstudio/docs/benchmarks/ragstudio-oss-proof-v1/`.
- Import validation gate: `../Ragstudio/scripts/proof.sh --strict --json --packet <packet>`.
- Phase 4 will render imported fixtures into the proof viewer, so Phase 3 output
  should be stable, typed, and easy to consume from static React components.

</code_context>

<specifics>
## Specific Ideas

- Create or reuse `/Users/meet/Documents/ragstudio-site` as a separate sibling
  folder.
- Keep the importer command focused on validation plus fixture generation.
- Treat the Phase 2 compact JSON validation result as the compatibility contract.
- Add tests or scripts that fail static-only boundary violations such as backend
  client imports, live API URL usage, auth/upload routes, and provider env vars.
- Leave final proof viewer UX, Cloudflare Pages, public domain, and WCAG launch
  gates for later phases.

</specifics>

<deferred>
## Deferred Ideas

- Public GitHub repo/remote setup and Cloudflare Pages deployment remain Phase 5.
- Full proof viewer and first-viewport public story remain Phase 4.
- A standalone TypeScript reimplementation of the proof validator is deferred;
  Phase 3 shells out to the Ragstudio validator to preserve parity.

</deferred>

---

*Phase: 3-`ragstudio-site` Scaffold and Import Pipeline*
*Context gathered: 2026-05-14*
