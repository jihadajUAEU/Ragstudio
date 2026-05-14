"""Stable proof packet validation error codes and recovery guidance."""

PACKET_NOT_FOUND = "PACKET_NOT_FOUND"
JSON_PARSE_ERROR = "JSON_PARSE_ERROR"
SCHEMA_INVALID = "SCHEMA_INVALID"
MANIFEST_PATH_MISSING = "MANIFEST_PATH_MISSING"
HASH_MISMATCH = "HASH_MISMATCH"
REDACTION_LEAK = "REDACTION_LEAK"
CLAIM_EVIDENCE_INVALID = "CLAIM_EVIDENCE_INVALID"
CLAIM_COUNTS_MISMATCH = "CLAIM_COUNTS_MISMATCH"
SCREENSHOT_SIGNOFF_INVALID = "SCREENSHOT_SIGNOFF_INVALID"
STALE_SOURCE_COMMIT = "STALE_SOURCE_COMMIT"
EXPORT_MANIFEST_INVALID = "EXPORT_MANIFEST_INVALID"

ERROR_CODES = (
    PACKET_NOT_FOUND,
    JSON_PARSE_ERROR,
    SCHEMA_INVALID,
    MANIFEST_PATH_MISSING,
    HASH_MISMATCH,
    REDACTION_LEAK,
    CLAIM_EVIDENCE_INVALID,
    CLAIM_COUNTS_MISMATCH,
    SCREENSHOT_SIGNOFF_INVALID,
    STALE_SOURCE_COMMIT,
    EXPORT_MANIFEST_INVALID,
)

RECOVERY_GUIDANCE = {
    PACKET_NOT_FOUND: "Check the --packet path and run from the repository root.",
    JSON_PARSE_ERROR: "Open the reported JSON file, fix the syntax, and rerun proof validation.",
    SCHEMA_INVALID: "Compare the file with its packet schema and restore the required fields.",
    MANIFEST_PATH_MISSING: "Restore the missing file or remove the stale manifest reference.",
    HASH_MISMATCH: "Regenerate the artifact hash after confirming the artifact is safe to publish.",
    REDACTION_LEAK: "Remove or redact the private value, then rerun proof validation.",
    CLAIM_EVIDENCE_INVALID: "Attach public redacted artifact evidence or change the claim status.",
    CLAIM_COUNTS_MISMATCH: "Recompute claim_counts from claims.registry.json.",
    SCREENSHOT_SIGNOFF_INVALID: (
        "Fix screenshots/signoff.json and ensure referenced screenshots exist."
    ),
    STALE_SOURCE_COMMIT: "Use a source_commit that exists in the current repository history.",
    EXPORT_MANIFEST_INVALID: "Regenerate export manifest metadata from the static packet root.",
}
