# Compatibility

## Packet Version

- Packet id: `ragstudio-oss-proof-v1`
- Packet version: `0.1.0`
- Schema version: JSON Schema 2020-12
- Capture mode: static fixtures

## Schemas

The packet includes these JSON Schema 2020-12 contracts:

- `schemas/manifest.schema.json`
- `schemas/claim.schema.json`
- `schemas/artifact.schema.json`
- `schemas/screenshot-signoff.schema.json`
- `schemas/validation-result.schema.json`

## Runtime Expectations

The packet has no live runtime dependency. The JSON files parse with a current
Node.js runtime, and `./scripts/proof.sh` performs executable schema, hash,
claim, screenshot signoff, and redaction validation.

`./scripts/proof.sh` runs from a fresh checkout without:

- Docker,
- secrets,
- live providers,
- a running Ragstudio backend,
- private files.

## Site Import Contract

The later `ragstudio-site` importer should treat this packet as static input. It
must reject packets that fail the Phase 2 validator and must not call Ragstudio
backend APIs during build or runtime.
