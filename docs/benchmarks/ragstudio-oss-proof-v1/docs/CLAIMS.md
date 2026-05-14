# Claim Status Rules

The machine-readable source of truth is `claims/claims.registry.json`. The
reviewer table is `claims/claims.matrix.md`.

## Statuses

`proven` means the claim is backed by public artifacts in this packet. A proven
claim must have:

- a registry entry,
- a source commit or source tag,
- source code paths,
- at least one public raw artifact path,
- a human-readable explanation,
- redaction status `passed`,
- limitations next to the claim.

`roadmap` means the claim is visible but unproven. It must explain missing
evidence and the planned proof path. Roadmap claims do not count as proven.

`disabled` means the claim is intentionally stopped for safety or scope reasons.
It must explain why it is disabled and what would be required before it could be
proved. Disabled claims do not count as proven.

## Current Proven Claims

`RAGSTUDIO-PARSER-GATE` is proven by:

- `artifacts/parser-quality.export.json`
- `artifacts/chunks.export.json`

It demonstrates a synthetic reference-bearing chunk with
`reference_unit_missing_expected_script` and a `quality_action_policy` that blocks
unsafe materialization.

`RAGSTUDIO-TRACE-VISIBILITY` is proven by:

- `artifacts/retrieval-run.export.json`
- `artifacts/graph-projection.export.json`
- `artifacts/reranker-trace.export.json`

It demonstrates that retrieval traces, graph projection state, and reranker
evidence can be inspected as public static artifacts.

## Visible Non-Claims

`RAGSTUDIO-SCALE-2000P` is roadmap because no measured 2000+ page public packet
exists yet.

`RAGSTUDIO-PUBLIC-UPLOAD` is disabled because v1 uses a static public site with
no upload, auth, live backend, or provider calls.

## Safety Rule

Private or local-only evidence can never support a proven claim. If evidence is
private, local-only, unsafe, or unapproved, the claim must be roadmap or disabled.
