# Ragstudio OSS Proof Packet Quickstart

## What This Packet Is

This packet gives reviewers a safe, static proof trail under
`docs/benchmarks/ragstudio-oss-proof-v1/` and a fresh-checkout validation command.

Open these files first:

1. `manifest.json`
2. `claims/claims.registry.json`
3. `claims/claims.matrix.md`
4. `artifacts/parser-quality.export.json`
5. `artifacts/retrieval-run.export.json`
6. `fixtures/retrieval-traces.synthetic.json`
7. `docs/CLAIMS.md`
8. `docs/LIMITATIONS.md`
9. `docs/REDACTION.md`

## What To Check

- The manifest lists packet version `0.1.0`, JSON Schema version `2020-12`,
  source commit, artifact paths, artifact hashes, claim counts, redaction status,
  exclusions, and limitations.
- Proven claims in `claims/claims.registry.json` cite public `artifacts/` paths.
- Roadmap and disabled claims remain visible instead of being hidden.
- The retrieval architecture claim shows domain-aware, layout-aware, and
  context-aware trace propagation through route planning, lane results,
  reranking, and context assembly.
- The corpus is synthetic and safe to redistribute.
- Screenshots are excluded unless `screenshots/signoff.json` marks them safe to
  publish.

## Validate The Packet

From the repository root:

```bash
./scripts/proof.sh
```

Expected result: `Status: passed`.

For automation, CI, or future site import gates:

```bash
./scripts/proof.sh --strict --json
```

The command validates only static fixtures and public packet files. It does not
require Docker, secrets, live providers, a running backend, or private files.
