# Architecture Research

**Domain:** Open-source static proof viewer and replayable RAG evidence packet
**Researched:** 2026-05-14
**Confidence:** HIGH

## Standard Architecture

### System Overview

```text
Ragstudio repo
|-- docs/benchmarks/ragstudio-oss-proof-v1/
|   |-- schemas/
|   |-- artifacts/
|   |-- screenshots/
|   |-- synthetic-corpus/
|   |-- claims.registry.json
|   |-- claims-matrix.md
|   `-- benchmark-run.md
|-- backend/src/ragstudio/proof_packet/
|   |-- schemas.py
|   |-- redaction.py
|   |-- manifests.py
|   |-- replay.py
|   `-- export.py
`-- scripts/
    |-- proof.sh
    |-- proof.ts
    |-- benchmark_replay.py or .ts
    `-- export-proof-packet.ts or .py
        |
        | exported packet with schemas, hashes, source commit/tag
        v
ragstudio-site repo
|-- scripts/import-proof-packet.ts
|-- public/proof-packets/ragstudio-oss-proof-v1/
|-- src/proof-viewer/
|-- src/pages/
`-- Cloudflare Pages Git integration + required new domain
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| Canonical schemas | Define all public artifact shapes | JSON Schema 2020-12 files under benchmark folder. |
| Proof packet module | Validate schema, redaction, manifests, hashes, errors, export | Python helpers in Ragstudio plus shared JSON schemas. |
| Golden proof command | Fast local proof validation | `scripts/proof.sh` wrapping TypeScript/Node validator. |
| Replay/export wrappers | Capture or validate proof artifacts, then export packet | Thin scripts that call shared validation logic. |
| Site import script | Reject stale, malformed, oversized, secret-bearing packets | TypeScript script in `ragstudio-site/scripts/`. |
| Static proof viewer | Let reviewers inspect claims and evidence | React/Vite app reading imported local JSON fixtures. |
| Cloudflare Pages | Build/deploy site from Git and provide previews/checks | Git integration with production branch and custom domain. |

## Recommended Project Structure

```text
docs/benchmarks/ragstudio-oss-proof-v1/
|-- QUICKSTART.md
|-- PROOF-VIEWER.md
|-- REPLAY.md
|-- CLAIMS.md
|-- ERRORS.md
|-- COMPATIBILITY.md
|-- BENCHMARK-CORPUS.md
|-- benchmark-run.md
|-- claims-matrix.md
|-- claims.registry.json
|-- schemas/
|-- artifacts/
|-- screenshots/
|-- synthetic-corpus/
`-- domain-packs/

backend/src/ragstudio/proof_packet/
|-- __init__.py
|-- schemas.py
|-- redaction.py
|-- manifests.py
|-- replay.py
`-- export.py

ragstudio-site/
|-- scripts/import-proof-packet.ts
|-- src/proof-viewer/
|-- src/pages/
|-- src/lib/proof/
`-- public/proof-packets/ragstudio-oss-proof-v1/
```

### Structure Rationale

- **`docs/benchmarks/`:** Public artifact source lives beside docs and can be reviewed in Git.
- **`backend/src/ragstudio/proof_packet/`:** Shared source-side logic is testable without duplicating code in CLI wrappers.
- **`scripts/`:** Thin human-facing commands stay discoverable.
- **`ragstudio-site/public/proof-packets/`:** Viewer loads static imported fixtures without backend calls.

## Architectural Patterns

### Pattern 1: Manifest-First Static Viewer

**What:** Load a small import manifest and claim summary first, then lazy-load heavy artifacts when a claim/detail opens.
**When to use:** Static evidence viewer with potentially large traces and screenshots.
**Trade-offs:** Slightly more client-state complexity, much faster first render and better mobile behavior.

### Pattern 2: Shared Contract, Separate Implementations

**What:** Use JSON Schema files as the canonical contract. Python and TypeScript validators consume the same schema files.
**When to use:** Cross-repo export/import paths.
**Trade-offs:** Requires discipline around schema versioning; avoids silent drift.

### Pattern 3: Structured Expected Failures

**What:** Validation failures write machine-readable error files with code, path, message, severity, cause, fix, docs URL, and example.
**When to use:** Proof tooling where expected errors are part of the user experience.
**Trade-offs:** More up-front error design; much better evaluator DX.

## Data Flow

### Static Fixture Proof Flow

```text
Synthetic corpus + committed fixtures
    -> ./scripts/proof.sh
    -> schema/hash/redaction/claim validation
    -> proof packet id, commit/tag, packet hash, claim counts
    -> import into ragstudio-site
    -> static proof viewer renders claims and evidence
```

### Optional Live Capture Flow

```text
Running Ragstudio backend
    -> benchmark_replay --mode live-capture
    -> API outputs and screenshots
    -> redaction + schema validation
    -> export manifest
    -> site import
```

### State Management

- Ragstudio source state: Git-tracked schemas, fixtures, manifests, docs, and tests.
- Site state: Imported static files under `public/proof-packets/`.
- Viewer runtime state: Selected claim, selected detail panel, loaded artifact cache, loading/error states.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 1 proof packet, small claim set | Static manifest-first viewer and local JSON files are enough. |
| Multiple proof packets/domain packs | Add packet selector, versioned directories, and search/filter. |
| Large traces/artifacts | Keep preview caps, raw artifact links, and lazy loads; consider artifact splitting by claim id. |

### Scaling Priorities

1. **First bottleneck:** Large JSON traces slowing initial render. Fix with manifest-first loading and preview caps.
2. **Second bottleneck:** Cross-repo schema drift. Fix with one canonical schema directory and import/replay tests.
3. **Third bottleneck:** Too many claims for a simple rail. Fix with grouping/filtering after V1.

## Anti-Patterns

### Anti-Pattern 1: Website as Source of Truth

**What people do:** Copy claims into the marketing site manually.
**Why it's wrong:** Claims drift from artifacts and source code.
**Do this instead:** Render claims from `claims.registry.json` and link to raw evidence/source commit.

### Anti-Pattern 2: Live Demo as Proof

**What people do:** Use a hosted backend demo as the only evidence path.
**Why it's wrong:** Uptime, data, cost, auth, and provider config become part of proof.
**Do this instead:** Static proof fixtures plus optional live-capture refresh.

### Anti-Pattern 3: Duplicate Schemas

**What people do:** Maintain Python models, TypeScript types, and JSON examples separately.
**Why it's wrong:** Import can pass while replay fails or vice versa.
**Do this instead:** Validate everything against canonical JSON Schema files.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Cloudflare Pages | Git integration from `ragstudio-site` | Provides preview deployments and PR status checks; custom domain is launch blocker. |
| GitHub | Source repo, site repo, issues/discussions | Feedback links should include claim id, artifact path, packet hash, and commit. |
| Existing Ragstudio APIs | Optional live capture only | Static proof path must not require these APIs. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Ragstudio proof exporter -> site importer | Exported folder/manifest | Site import must reject stale or invalid exports. |
| Proof schemas -> Python/TypeScript validators | File reads | One schema directory should drive both validators. |
| Viewer claim rail -> evidence panels | Static JSON artifact fetch | Detail URLs must be deep-linkable. |

## Sources

- `.planning/codebase/ARCHITECTURE.md` - existing Ragstudio architecture.
- `.planning/PROJECT.md` - chosen launch shape and constraints.
- https://developers.cloudflare.com/pages/configuration/git-integration/ - deployment and preview architecture.
- https://json-schema.org/specification - schema contract basis.
- https://vite.dev/guide/static-deploy.html - Vite/Pages static deployment path.

---
*Architecture research for: open-source static proof viewer and replayable RAG evidence packet*
*Researched: 2026-05-14*
