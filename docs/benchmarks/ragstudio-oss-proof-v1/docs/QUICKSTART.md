# Ragstudio OSS Proof Packet Quickstart

## What This Packet Is

This Phase 1 packet is inspect-only. It gives reviewers a safe, static proof trail
under `docs/benchmarks/ragstudio-oss-proof-v1/` before executable validation and
the public site exist.

Open these files first:

1. `manifest.json`
2. `claims/claims.registry.json`
3. `claims/claims.matrix.md`
4. `artifacts/parser-quality.export.json`
5. `docs/CLAIMS.md`
6. `docs/LIMITATIONS.md`
7. `docs/REDACTION.md`

## What To Check

- The manifest lists packet version `0.1.0`, JSON Schema version `2020-12`,
  source commit, artifact paths, artifact hashes, claim counts, redaction status,
  exclusions, and limitations.
- Proven claims in `claims/claims.registry.json` cite public `artifacts/` paths.
- Roadmap and disabled claims remain visible instead of being hidden.
- The corpus is synthetic and safe to redistribute.
- Screenshots are excluded unless `screenshots/signoff.json` marks them safe to
  publish.

## What Arrives In Phase 2

Executable `./scripts/proof.sh` validation arrives in Phase 2. Until then, this
packet can be inspected with normal file, JSON, and text checks:

```bash
node -e 'for (const f of process.argv.slice(1)) JSON.parse(require("fs").readFileSync(f,"utf8"));' \
  docs/benchmarks/ragstudio-oss-proof-v1/manifest.json \
  docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.registry.json
```

Phase 2 will turn these contracts into a fresh-checkout validation path that does
not require Docker, secrets, live providers, a running backend, or private files.
