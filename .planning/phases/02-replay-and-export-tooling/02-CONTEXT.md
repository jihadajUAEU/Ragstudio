# Phase 2: Replay and Export Tooling - Context

**Gathered:** 2026-05-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 2 delivers the fresh-checkout proof command and shared validator for the
Phase 1 proof packet. A developer must be able to run `./scripts/proof.sh` from a
clean checkout and validate `docs/benchmarks/ragstudio-oss-proof-v1/` using
static fixtures only, without Docker, secrets, live providers, a running backend,
or private files.

This phase owns local proof validation, structured proof output, redaction/leak
checks, packet hash and metadata validation, export-manifest support, and docs
for replay/error recovery. It does not build the separate `ragstudio-site` import
pipeline or public proof viewer; those remain Phase 3 and Phase 4 work.

</domain>

<decisions>
## Implementation Decisions

### Proof Command Behavior
- **D-01:** `./scripts/proof.sh` must work with no arguments against the default
  packet root `docs/benchmarks/ragstudio-oss-proof-v1/`.
- **D-02:** The command should keep a human-friendly gold path while exposing
  useful automation flags: `--json`, `--packet <path>`, and `--strict`.
- **D-03:** Do not plan a broad subcommand CLI such as `validate`, `export`, and
  `inspect` unless research proves it is necessary. Phase 2 should stay centered
  on the first-time trust path and CI/import handoff.

### Runtime Shape
- **D-04:** Implement validation as a Python module under
  `backend/src/ragstudio/proof_packet/`, with `./scripts/proof.sh` as a thin Bash
  wrapper.
- **D-05:** Tests should live in `backend/tests` and follow the existing pytest
  style. The validator should avoid database, Docker, backend server, provider,
  and frontend runtime dependencies.
- **D-06:** Node/site-import concerns should be represented through stable output
  contracts for Phase 3, not by adding a second validator implementation in this
  repo during Phase 2.

### Output Contract
- **D-07:** Default command output should be readable by a first-time evaluator:
  a concise summary of pass/fail state, checked packet path, failures, warnings,
  and recovery pointers.
- **D-08:** `--json` should emit a compact machine-readable result with stable
  fields for status, packet path, errors, warnings, hashes or packet identity,
  and timings where useful.
- **D-09:** Detailed per-file/per-rule output should be available only through a
  verbose-style option such as `--verbose` or `--json --verbose`; compact JSON
  remains the default for automation.

### Strictness Policy
- **D-10:** No-argument `./scripts/proof.sh` should be developer-friendly but
  fail real proof blockers: invalid schemas, missing artifacts, hash mismatches,
  public-leak patterns, broken manifest/claim contracts, and stale or invalid
  metadata when that metadata invalidates the proof.
- **D-11:** Advisory compatibility issues may appear as warnings in the default
  command.
- **D-12:** `--strict` must treat warnings as failures for CI, launch, and future
  import gates. Documentation should tell humans to start with no args and
  automation to use `--strict --json`.

### the agent's Discretion
- The agent may choose exact Python module names, Pydantic/dataclass structures,
  and internal function boundaries as long as the public `./scripts/proof.sh`
  contract and JSON output contract above are honored.
- The agent may choose whether verbose output is a separate `--verbose` flag,
  `--json --verbose`, or both, as long as compact `--json` remains stable.
- The agent may choose the exact error-code naming scheme, but codes must be
  structured, documented, and suitable for Phase 3 site-import rejection.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Scope
- `.planning/PROJECT.md` - Project definition, public launch decisions,
  constraints, active Phase 2 proof-packet validation requirement, and out-of-scope
  boundaries.
- `.planning/REQUIREMENTS.md` - Phase 2 requirement IDs `VAL-01`, `VAL-02`,
  `VAL-03`, `VAL-04`, `VAL-05`, `VAL-07`, `DOCS-01`, `DOCS-02`, and `DOCS-04`.
- `.planning/ROADMAP.md` - Phase 2 goal, success criteria, dependency on Phase 1,
  and three planned slices.
- `.planning/STATE.md` - Current project status, Phase 2 focus, and known
  launch/repo blockers.

### Phase 1 Proof Packet
- `.planning/phases/01-proof-contract-and-baseline-packet/01-CONTEXT.md` - Locked
  Phase 1 packet, claim, corpus, and public-safety decisions that Phase 2 must
  validate rather than reinterpret.
- `.planning/phases/01-proof-contract-and-baseline-packet/01-VERIFICATION.md` -
  Verified Phase 1 evidence and residual note that executable schema/redaction
  checks belong to Phase 2.
- `.planning/phases/01-proof-contract-and-baseline-packet/01-VALIDATION.md` -
  Existing proof-packet contract tests and Nyquist map that Phase 2 can extend
  into executable validation.
- `.planning/phases/01-proof-contract-and-baseline-packet/01-SECURITY.md` -
  Security threat register and redaction/public-safety expectations Phase 2 must
  enforce.
- `docs/benchmarks/ragstudio-oss-proof-v1/manifest.json` - Current default packet
  manifest.
- `docs/benchmarks/ragstudio-oss-proof-v1/schemas/` - JSON Schema 2020-12 contracts
  for manifest, claims, artifacts, screenshot signoff, and validation results.
- `docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.registry.json` - Current
  claim status and evidence source of truth.
- `docs/benchmarks/ragstudio-oss-proof-v1/docs/REDACTION.md` - Redaction and
  fail-closed public safety rules.
- `docs/benchmarks/ragstudio-oss-proof-v1/docs/COMPATIBILITY.md` - Compatibility
  and future import boundary.

### Existing Codebase Patterns
- `.planning/codebase/STACK.md` - Python, pytest, Bash, package, and runtime
  constraints relevant to `proof.sh`.
- `.planning/codebase/ARCHITECTURE.md` - Existing service/schema/test layering and
  proof-related data flow.
- `.planning/codebase/INTEGRATIONS.md` - Existing local/runtime integration
  boundaries and public-launch site separation.
- `backend/tests/test_proof_packet_contract.py` - Existing static proof-packet
  contract tests to extend or complement.
- `scripts/test-all.sh` - Existing full validation script style and Docker-heavy
  command that `./scripts/proof.sh` must not require for the fresh-checkout path.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/tests/test_proof_packet_contract.py` already verifies manifest path
  coverage, artifact hashes, schema strictness, claim honesty, redaction policy,
  screenshot signoff, and docs boundaries. Phase 2 should convert these checks
  from test-only assertions into reusable validator behavior.
- `docs/benchmarks/ragstudio-oss-proof-v1/` is the default packet root for
  `./scripts/proof.sh`.
- `scripts/` is the existing home for developer shell entrypoints; `proof.sh`
  should follow the thin-wrapper style but avoid Docker dependencies.

### Established Patterns
- Backend code is Python 3.12 with service-style modules under
  `backend/src/ragstudio/` and pytest coverage under `backend/tests`.
- The full project validation path is Docker-heavy through `scripts/test-all.sh`,
  but Phase 2's first-time proof path must be lightweight and static-fixture only.
- Public proof artifacts use JSON, Markdown, hashes, and explicit manifest links;
  validation should rely on structured parsing and hashing rather than ad hoc
  string-only checks wherever practical.

### Integration Points
- `./scripts/proof.sh` connects developer UX to the Python validator.
- `backend/src/ragstudio/proof_packet/` is the planned shared validation module
  boundary for local replay/export checks and future Phase 3 import validation.
- `docs/benchmarks/ragstudio-oss-proof-v1/docs/QUICKSTART.md`, a new
  `docs/REPLAY.md`, and a new `docs/ERRORS.md` are the likely docs surfaces for
  the 2-5 minute trust path and recovery guidance.

</code_context>

<specifics>
## Specific Ideas

- Default command: `./scripts/proof.sh`.
- Default packet: `docs/benchmarks/ragstudio-oss-proof-v1/`.
- Automation command shape: `./scripts/proof.sh --strict --json`.
- Additional useful flags: `--packet <path>`, `--json`, `--strict`, and a
  verbose-style option for detailed rule/file breakdown.
- Keep the human trust moment simple: no args should be enough for a reviewer to
  understand whether the packet is credible and what to do if it is not.

</specifics>

<deferred>
## Deferred Ideas

- Full multi-subcommand CLI (`validate`, `export`, `inspect`) is deferred unless
  Phase 2 research proves it is necessary.
- A separate Node/site validator implementation is deferred to Phase 3 or later;
  Phase 2 should provide stable contracts that the site import can consume.
- Site import rejection itself remains Phase 3.

</deferred>

---

*Phase: 2-Replay and Export Tooling*
*Context gathered: 2026-05-14*
