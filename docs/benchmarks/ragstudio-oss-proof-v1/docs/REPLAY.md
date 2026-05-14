# Proof Replay

## Default Replay

Run this from the repository root:

```bash
./scripts/proof.sh
```

The default packet is `docs/benchmarks/ragstudio-oss-proof-v1/`. The command
validates static fixture files, schema contracts, artifact hashes, claim
evidence, screenshot signoff metadata, and public redaction rules.

## Automation Replay

Use strict JSON for automation and future import gates:

```bash
./scripts/proof.sh --strict --json
```

`--json` emits compact machine-readable output. `--strict` treats warnings as
failures.

## Alternate Packet

```bash
./scripts/proof.sh --packet docs/benchmarks/ragstudio-oss-proof-v1
```

The validator accepts any packet root with the same proof-packet structure.

## Static Fixture Boundary

This replay path uses static fixture evidence only. It does not start Docker,
Postgres, Neo4j, the frontend, live providers, or a backend server.

Live capture and larger benchmark exports are optional future work. They must
produce a public packet first; this command then validates that packet before it
can support public claims.
