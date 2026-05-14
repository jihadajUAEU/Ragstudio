# Proof Validation Errors

Each error includes a code, path, message, and recovery text. Start with:

```bash
./scripts/proof.sh
```

Use automation mode when a machine needs the result:

```bash
./scripts/proof.sh --strict --json
```

| Code | Meaning | Recovery |
|------|---------|----------|
| PACKET_NOT_FOUND | The packet root does not exist. | Check the `--packet` path and run from the repository root. |
| JSON_PARSE_ERROR | A packet JSON file cannot be parsed. | Open the reported JSON file, fix the syntax, and rerun proof validation. |
| SCHEMA_INVALID | A packet file does not match its JSON Schema 2020-12 contract. | Compare the file with its packet schema and restore the required fields. |
| MANIFEST_PATH_MISSING | A manifest path is missing, absolute, or escapes the packet root. | Restore the file or remove the stale manifest reference. |
| HASH_MISMATCH | A file hash does not match `manifest.json`. | Confirm the artifact is safe, then regenerate the SHA-256 hash. |
| REDACTION_LEAK | A text packet file contains a private token, private host, local path, or similar leak pattern. | Remove or redact the private value, then rerun proof validation. |
| CLAIM_EVIDENCE_INVALID | A proven claim lacks valid public redacted artifact evidence. | Attach public evidence or change the claim status to roadmap or disabled. |
| CLAIM_COUNTS_MISMATCH | Manifest claim counts do not match `claims.registry.json`. | Recompute `claim_counts` from the registry. |
| SCREENSHOT_SIGNOFF_INVALID | Screenshot approval metadata is missing or inconsistent. | Fix `screenshots/signoff.json` and ensure referenced screenshots exist. |
| STALE_SOURCE_COMMIT | The manifest source commit is not present in repository history. | Use a source commit that exists in the current repository history. |
| EXPORT_MANIFEST_INVALID | Static export manifest metadata cannot be generated. | Regenerate export manifest metadata from a valid static packet root. |
