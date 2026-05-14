---
phase: 03
slug: ragstudio-site-scaffold-and-import-pipeline
status: complete
researched_at: 2026-05-14
requirements:
  - VAL-06
  - SITE-01
  - SITE-04
---

# Phase 3 Research: `ragstudio-site` Scaffold and Import Pipeline

## Objective

Plan the separate `ragstudio-site` repository boundary and import pipeline. The
site must import only proof packets accepted by the Ragstudio local validator and
must build from static fixtures without Ragstudio backend calls, upload flows,
authentication, or live providers.

## Key Findings

### Sibling Site Folder Does Not Exist Yet

`/Users/meet/Documents/ragstudio-site` does not currently exist. Phase 3 should
create this sibling folder and initialize it as its own Git repository if it is
not already a repo. The Ragstudio app repo remains the proof packet and validator
source of truth.

### Reuse The Existing Frontend Stack Shape, Not The App Frontend

The current app frontend uses React, Vite, TypeScript, Vitest, Testing Library,
Tailwind v4, and ESLint. Phase 3 should create a small standalone Vite React app
with equivalent baseline tooling where useful, but it should not import from
`../Ragstudio/frontend/src` or reuse app API clients.

Recommended site scaffold:

```text
/Users/meet/Documents/ragstudio-site/
  package.json
  package-lock.json
  index.html
  vite.config.ts
  tsconfig.json
  eslint.config.js
  src/
    main.tsx
    App.tsx
    styles.css
    data/
      proof-packet.generated.json
      proof-validation.generated.json
  scripts/
    import-proof-packet.mjs
    check-static-boundary.mjs
  tests/
    import-proof-packet.test.mjs
    static-boundary.test.mjs
```

Phase 4 will build the full proof viewer. Phase 3 only needs enough UI to prove
the app builds from imported static fixtures and exposes a placeholder/static
entry surface for later work.

### Import Gate Should Shell Out To `proof.sh`

The locked decision is to call:

```bash
../Ragstudio/scripts/proof.sh --strict --json --packet <packet>
```

This avoids duplicating validation logic in TypeScript and guarantees parity
with local validation. The importer should treat nonzero exit, invalid JSON, or
`status !== "passed"` as import rejection.

The Phase 2 compact JSON output includes:

- `validation_id`
- `packet_id`
- `status`
- `validated_at`
- `validator_version`
- `summary`
- `errors`
- `warnings`
- `artifact_results`

The site should store this validation result alongside imported fixture metadata
so Phase 4 can display packet hash/source/validation context.

### Import Output Should Be Static And Typed Enough For Phase 4

The importer should copy or summarize the public packet into site-owned static
fixtures. A good Phase 3 target is:

- `public/proof/ragstudio-oss-proof-v1/manifest.json`
- `public/proof/ragstudio-oss-proof-v1/claims/claims.registry.json`
- selected public artifacts/screenshots/docs needed by Phase 4
- `src/data/proof-packet.generated.json` with packet id, version, source commit,
  claim counts, claim summaries, artifact paths, and import timestamp
- `src/data/proof-validation.generated.json` with the validator JSON result

The exact fixture names may vary, but the build must not need the Ragstudio repo
at runtime. It can need the Ragstudio repo only during import.

### Static-Only Boundary Needs Automated Guardrails

Phase 3 must fail if the site adds live backend paths. Guardrails should scan
source/config files for:

- imports from `../Ragstudio/frontend`, `ragstudio/api`, or generated API clients;
- fetch/axios/live HTTP API usage;
- `/api`, `/upload`, `/auth`, `/login`, `/settings`, or provider config routes;
- `VITE_API_*`, `RAGSTUDIO_*`, `OPENAI_API_KEY`, and similar provider env names.

Keep the guardrail focused so normal Vite dev/build URLs are not falsely
blocked. It should scan site `src/`, `scripts/`, and config files, while allowing
the import script to reference `../Ragstudio/scripts/proof.sh` and packet paths.

## Recommended Plan Shape

1. **Scaffold separate static site repo**: create `/Users/meet/Documents/ragstudio-site`,
   initialize React/Vite/TypeScript tooling, add minimal static app, add package
   scripts, and prove `npm test`/`npm run build` works.
2. **Implement import gate and guardrails**: add `import-proof-packet.mjs`,
   generated fixture outputs, tests that valid packet imports and corrupted
   packet rejects, and static-only boundary checks.

## Validation Architecture

### Site Commands

From `/Users/meet/Documents/ragstudio-site`:

```bash
npm test
npm run build
npm run import:proof
npm run check:static
```

### Required Test Coverage

1. Sibling site folder exists and is a Git repository.
2. Site builds without Ragstudio runtime/backend dependencies.
3. Import script runs proof validation with `--strict --json`.
4. Valid default packet imports successfully into static fixture outputs.
5. Invalid/corrupted packet is rejected.
6. Static boundary guard fails on backend/API/upload/auth/provider patterns.
7. Static boundary guard passes for the generated Phase 3 scaffold.

### Nyquist Mapping

- `SITE-01`: sibling repo exists, package metadata identifies `ragstudio-site`,
  and it is independent from the Ragstudio app checkout.
- `VAL-06`: import rejects any packet rejected by `proof.sh --strict --json`.
- `SITE-04`: build/test/static guardrails prove no backend calls, upload flows,
  auth, live providers, or provider env vars are present.

## Risks And Landmines

- Do not scaffold inside `/Users/meet/Documents/Ragstudio`.
- Do not import existing app frontend API clients or generated OpenAPI types.
- Do not reimplement proof validation as TypeScript schema/hash/redaction logic.
- Do not require Cloudflare Pages, a public domain, or GitHub remote in Phase 3.
- Do not build the full proof viewer UI in Phase 3; leave that for Phase 4.
