---
phase: 01
slug: proof-contract-and-baseline-packet
status: verified
threats_open: 0
asvs_level: 1
created: 2026-05-14
---

# Phase 01 - Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Local development evidence to public proof packet | Phase 1 converts implementation-adjacent evidence into a static packet under `docs/benchmarks/ragstudio-oss-proof-v1/`. | Synthetic fixtures, redacted JSON artifacts, provenance metadata, and claim records. |
| Public proof packet to external reviewer | Reviewers inspect the packet without Docker, live providers, private corpora, or a running backend. | Public-safe docs, schemas, claims, manifest, screenshots, and hashes. |
| Screenshot source to public screenshot | A local UI screenshot is copied into the public packet only after human signoff. | Approved empty-state screenshot plus signoff metadata. |
| Phase 1 contracts to future tooling | Phase 2 and later site/import tooling will consume the schemas and claim registry from this packet. | JSON Schema 2020-12 contracts, claim statuses, artifact paths, and validation-result shape. |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-01-01 | Information Disclosure | Fixtures and exported artifacts | mitigate | Packet uses synthetic Arabic and English reference units, `redaction_status: "passed"`, and artifact-level redaction checks. | closed |
| T-01-02 | Information Disclosure | Docs, examples, and metadata | mitigate | Redaction policy forbids API keys, tokens, private hosts, LAN IPs, unpublished model endpoints, private snippets, and local absolute paths; public-safety scan found no private host/path hits. | closed |
| T-01-03 | Tampering | Manifest artifact coverage and provenance | mitigate | `manifest.json` lists every fixture/artifact/schema/claim path and records SHA-256 hashes for current JSON artifacts plus the approved screenshot; verification found no missing paths or hash mismatches. | closed |
| T-01-04 | Denial of Service | Public packet size and unrelated exports | mitigate | Phase 1 includes small representative static fixtures and excludes live provider exports with an explicit reason in `excluded_artifacts`. | closed |
| T-01-05 | Tampering | Schema contracts | mitigate | JSON Schema 2020-12 contracts use required fields, status enums, and `additionalProperties: false` across manifest, claim, artifact, screenshot-signoff, and validation-result schemas. | closed |
| T-01-06 | Spoofing / Repudiation | Public claims registry | mitigate | `claims.registry.json` records two proven, one roadmap, and one disabled claim; proven claims require public redacted evidence, while roadmap/disabled claims remain visible with missing evidence or requirements to prove. | closed |
| T-01-07 | Information Disclosure | Screenshot publication | mitigate | `screenshots/signoff.json` records reviewer, review time, source path, public path, affected claims, checks, and `safe_to_publish: true`; manifest reports one approved screenshot and zero pending screenshots. | closed |
| T-01-08 | Repudiation | Limitations and omitted evidence | mitigate | `docs/CLAIMS.md`, `docs/LIMITATIONS.md`, and manifest exclusions keep limitations next to claims, and unsafe omitted artifacts cannot silently support proven claims. | closed |

*Status: open - closed*
*Disposition: mitigate (implementation required) - accept (documented risk) - transfer (third-party)*

---

## Accepted Risks Log

No accepted risks.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-05-14 | 8 | 8 | 0 | Codex inline security audit |

---

## Evidence Checked

- `docs/benchmarks/ragstudio-oss-proof-v1/manifest.json`
- `docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.registry.json`
- `docs/benchmarks/ragstudio-oss-proof-v1/claims/claims.matrix.md`
- `docs/benchmarks/ragstudio-oss-proof-v1/schemas/*.schema.json`
- `docs/benchmarks/ragstudio-oss-proof-v1/fixtures/*.json`
- `docs/benchmarks/ragstudio-oss-proof-v1/artifacts/*.json`
- `docs/benchmarks/ragstudio-oss-proof-v1/screenshots/signoff.json`
- `docs/benchmarks/ragstudio-oss-proof-v1/docs/*.md`

## Verification Notes

- JSON parse check passed for all packet JSON files.
- Manifest references resolved with no missing expected paths.
- Manifest SHA-256 values matched all current JSON artifacts plus the approved screenshot.
- Manifest claim counts matched `claims.registry.json`.
- Proven claims had public evidence with `redaction_status: "passed"` and no evidence outside manifest artifacts.
- Secret-key scan only matched redaction-check label names such as `no_api_keys`, not credential values.
- Private host, private IP, localhost, local absolute path, and file URL scan returned no hits.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-05-14
