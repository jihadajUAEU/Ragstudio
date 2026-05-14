---
phase: 03
slug: ragstudio-site-scaffold-and-import-pipeline
status: complete
created: 2026-05-14
---

# Phase 3 Pattern Map: `ragstudio-site` Scaffold and Import Pipeline

## Repository Boundary

Phase 3 writes implementation files primarily outside this checkout:

`/Users/meet/Documents/ragstudio-site`

This sibling folder is the canonical public site boundary. It should be created
or reused by execution. It must not be nested under
`/Users/meet/Documents/Ragstudio`.

The current Ragstudio app checkout remains responsible for:

- proof packet source files under `docs/benchmarks/ragstudio-oss-proof-v1/`;
- validator source under `backend/src/ragstudio/proof_packet/`;
- planning artifacts under `.planning/phases/03-ragstudio-site-scaffold-and-import-pipeline/`.

## Scaffold Pattern

Use a small Vite + React + TypeScript site, following the existing frontend's
tooling shape but not importing from it.

Recommended files:

```text
/Users/meet/Documents/ragstudio-site/
  package.json
  package-lock.json
  index.html
  vite.config.ts
  tsconfig.json
  eslint.config.js
  src/main.tsx
  src/App.tsx
  src/styles.css
  src/data/proof-packet.generated.json
  src/data/proof-validation.generated.json
  scripts/import-proof-packet.mjs
  scripts/check-static-boundary.mjs
  tests/import-proof-packet.test.mjs
  tests/static-boundary.test.mjs
```

Keep the Phase 3 UI minimal. It only needs to prove the site builds from imported
static fixtures. Full proof viewer UX belongs to Phase 4.

## Import Gate Pattern

The importer should shell out to:

```bash
../Ragstudio/scripts/proof.sh --strict --json --packet <packet>
```

Rules:

- nonzero exit rejects the import;
- invalid JSON rejects the import;
- JSON with `status` other than `passed` rejects the import;
- importer writes generated static files only after validation passes;
- importer records the validation result alongside imported packet metadata;
- importer may copy public packet files into `public/proof/`, but runtime code
  should consume static/generated data rather than reading from `../Ragstudio`.

## Static Boundary Guard Pattern

Create a guard script that scans site source/config files for forbidden live-app
patterns.

Suggested forbidden families:

- imports from `../Ragstudio/frontend` or generated Ragstudio API clients;
- `/api`, `/upload`, `/auth`, `/login`, provider settings routes in runtime code;
- `VITE_API_`, `RAGSTUDIO_`, `OPENAI_API_KEY`, provider host/env names;
- direct `fetch("http...")` or backend URL constants in `src/`.

Allowlist:

- `scripts/import-proof-packet.mjs` may reference `../Ragstudio/scripts/proof.sh`
  and `../Ragstudio/docs/benchmarks/...` because that is a build/import-time
  path, not a runtime dependency.
- Vite and npm package metadata may contain normal dev/build package URLs only
  if they are not app runtime API endpoints.

## Test Pattern

Prefer tests that run entirely inside `/Users/meet/Documents/ragstudio-site`:

- valid import test: run importer against `../Ragstudio/docs/benchmarks/ragstudio-oss-proof-v1`;
- rejection test: copy the packet to a temp directory, corrupt one manifest hash
  or remove a required artifact, then assert importer exits nonzero;
- guardrail pass test: current scaffold passes `npm run check:static`;
- guardrail fail test: create a temp source file with a forbidden `/api` or
  `VITE_API_BASE_URL` pattern and assert the guard detects it.

## Verification Commands

From `/Users/meet/Documents/ragstudio-site`:

```bash
npm run import:proof
npm run check:static
npm test
npm run build
```

From `/Users/meet/Documents/Ragstudio`:

```bash
./scripts/proof.sh --strict --json --packet docs/benchmarks/ragstudio-oss-proof-v1
```

## Plan Implications

Plan 01 should create the sibling site repo/scaffold and prove it builds.
Plan 02 should add the import gate, generated fixtures, rejection tests, and
static-only guardrails.
