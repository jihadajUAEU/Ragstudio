# Phase 2: Replay and Export Tooling - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-14T12:53:08Z
**Phase:** 2-Replay and Export Tooling
**Areas discussed:** Proof command behavior

---

## Gray Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Proof command behavior | Should `./scripts/proof.sh` be a single default command only, or also support automation flags? | ✓ |
| Failure/error UX | How should failures read: concise checklist, detailed diagnostics, or both with structured codes? | |
| Export manifest boundary | Should Phase 2 only validate static packets, or add local export/manifest-generation path? | |
| Redaction policy strictness | Should leak scanning be hardcoded, configurable, or extensible with rule files? | |
| All of them | Discuss every area. | |

**User's choice:** `a`, interpreted as the first listed area: Proof command behavior.
**Notes:** User chose to discuss only proof command behavior and then requested context writing.

---

## Proof Command Behavior

### Command Surface

| Option | Description | Selected |
|--------|-------------|----------|
| Single gold-path command | `./scripts/proof.sh` validates the default packet and prints readable output. | |
| Gold path + useful flags | Default command plus `--json`, `--packet <path>`, and maybe `--strict`. | ✓ |
| Full CLI surface | Subcommands like `validate`, `export`, and `inspect`. | |

**User's choice:** `b`
**Notes:** Locked a simple default command plus automation-friendly flags.

### Runtime Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Python module + Bash wrapper | `scripts/proof.sh` calls validation code under `backend/src/ragstudio/proof_packet/`. | ✓ |
| Standalone Node script | Easier for future static site import, but duplicates validation implementation in this repo. | |
| Pure Bash | Minimal install surface, but brittle for JSON/schema/hash work. | |

**User's choice:** `phase 2`
**Notes:** Interpreted as keeping the Phase 2 implementation in the Ragstudio repo: Python module plus Bash wrapper, with Node/site import concerns deferred to Phase 3.

### JSON Output

| Option | Description | Selected |
|--------|-------------|----------|
| Compact CI result | Status, packet path, errors, warnings, hashes, timings. | |
| Full detailed report | Every checked file, artifact, claim, and rule result. | |
| Both | Compact by default, detailed with a verbose-style option. | ✓ |

**User's choice:** `c`
**Notes:** Locked compact `--json` output with detailed diagnostics behind a verbose option.

### Default Strictness

| Option | Description | Selected |
|--------|-------------|----------|
| Release strict by default | Any schema/hash/redaction/stale metadata issue fails. | |
| Developer friendly by default | Hard failures fail, warnings stay warnings; `--strict` makes warnings fail. | ✓ |
| Two commands | `./scripts/proof.sh` friendly, CI uses `./scripts/proof.sh --strict`. | ✓ |

**User's choice:** `b/c`
**Notes:** Locked developer-friendly no-args behavior with strict automation/CI mode. Hard proof blockers still fail by default; warnings fail under `--strict`.

---

## the agent's Discretion

- The agent may decide exact Python module structure and internal function boundaries.
- The agent may decide exact verbose flag shape as long as compact `--json` stays stable.
- The agent may define exact structured error-code names, with documentation.

## Deferred Ideas

- Full subcommand CLI deferred unless Phase 2 research proves it necessary.
- Separate Node/site validator implementation deferred to Phase 3 or later.
- Site import rejection remains Phase 3.
