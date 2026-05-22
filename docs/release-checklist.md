# Release Checklist

Use this before making a public release or updating public launch copy.

## Repository

- [ ] `README.md` explains what Ragstudio is, quick start, architecture, and demo workflow.
- [ ] Architecture docs explain the implemented domain-aware, layout-aware, and
  context-aware retrieval flow and distinguish static proof from production
  quality claims.
- [ ] `LICENSE`, `CONTRIBUTING.md`, and `SECURITY.md` are present.
- [ ] Issue templates and PR template are present.
- [ ] No private documents, `.env` files, provider keys, database dumps, generated caches, or local reports are tracked.
- [ ] Docker Compose remains the primary local try-it path.

## Proof And Claims

- [ ] Public claims are backed by a validated proof packet or marked roadmap/disabled.
- [ ] `RAGSTUDIO-RETRIEVAL-ARCHITECTURE` remains backed by public-safe static
  retrieval artifacts and its limitations remain visible.
- [ ] Proof packet validates:

```bash
./scripts/proof.sh --strict --json --packet docs/benchmarks/ragstudio-oss-proof-v1
```

- [ ] Screenshots are approved and safe to publish.
- [ ] Limitations are visible.

## Docs And Website

- [ ] Public site builds.
- [ ] Docs pages build.
- [ ] API reference is regenerated from FastAPI OpenAPI when API changes.
- [ ] Settings/config reference is regenerated when schemas change.
- [ ] Changelog is updated from tags/releases.
- [ ] Cloudflare Pages preview is reviewed before promoting.

## Validation

```bash
./scripts/test-all.sh
```

Record command output in the release notes or PR.
