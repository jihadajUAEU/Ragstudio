"""Reusable proof packet validation orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry, Resource

from ragstudio.proof_packet.errors import (
    CLAIM_COUNTS_MISMATCH,
    CLAIM_EVIDENCE_INVALID,
    HASH_MISMATCH,
    MANIFEST_PATH_MISSING,
    PACKET_NOT_FOUND,
    RECOVERY_GUIDANCE,
    SCHEMA_INVALID,
    SCREENSHOT_SIGNOFF_INVALID,
    STALE_SOURCE_COMMIT,
)
from ragstudio.proof_packet.manifest import (
    git_commit_exists,
    packet_text_files,
    read_json,
    resolve_packet_path,
    sha256_file,
)
from ragstudio.proof_packet.models import ArtifactResult, Finding, ValidationResult
from ragstudio.proof_packet.redaction import scan_text_file

DEFAULT_PACKET_ROOT = Path("docs/benchmarks/ragstudio-oss-proof-v1")
PACKET_ID = "ragstudio-oss-proof-v1"


def validate_packet(
    packet_root: Path | str = DEFAULT_PACKET_ROOT,
    *,
    strict: bool = False,
    repo_root: Path | None = None,
) -> ValidationResult:
    root = Path(packet_root)
    result = ValidationResult(packet_id=PACKET_ID)
    if not root.exists() or not root.is_dir():
        result.add_error(
            Finding(
                code=PACKET_NOT_FOUND,
                path=str(root),
                message="Proof packet directory does not exist.",
                recovery=RECOVERY_GUIDANCE[PACKET_NOT_FOUND],
            )
        )
        return result.finalize(strict=strict)

    manifest, error = read_json(root / "manifest.json")
    if error is not None:
        result.add_error(error)
        result.summary.schema_valid = False
        return result.finalize(strict=strict)
    if manifest is None:
        return result.finalize(strict=strict)
    result.packet_id = str(manifest.get("packet_id", PACKET_ID))

    schemas = _load_schemas(root, manifest, result)
    _validate_core_documents(root, manifest, schemas, result)
    _validate_manifest_paths(root, manifest, result)
    _validate_artifact_hashes(root, manifest, result)
    _validate_claims(root, manifest, result)
    _validate_screenshots(root, manifest, result)
    _validate_source_commit(manifest, result, repo_root=repo_root)
    _validate_redaction(root, result)

    result.summary.schema_valid = not any(
        finding.code in {SCHEMA_INVALID, PACKET_NOT_FOUND} for finding in result.errors
    )
    result.summary.hashes_valid = not any(
        finding.code == HASH_MISMATCH for finding in result.errors
    )
    result.summary.redaction_valid = not any(
        finding.code == "REDACTION_LEAK" for finding in result.errors
    )
    result.summary.claims_valid = not any(
        finding.code in {CLAIM_COUNTS_MISMATCH, CLAIM_EVIDENCE_INVALID}
        for finding in result.errors
    )
    return result.finalize(strict=strict)


def _load_schemas(
    packet_root: Path, manifest: dict[str, Any], result: ValidationResult
) -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for name, relative_path in manifest.get("schemas", {}).items():
        schema_path, path_error = resolve_packet_path(packet_root, relative_path)
        if path_error is not None:
            result.add_error(path_error)
            continue
        if schema_path is None:
            continue
        schema, error = read_json(schema_path)
        if error is not None:
            result.add_error(error)
            continue
        if schema is not None:
            schemas[name] = schema
    return schemas


def _validate_core_documents(
    packet_root: Path,
    manifest: dict[str, Any],
    schemas: dict[str, dict[str, Any]],
    result: ValidationResult,
) -> None:
    _validate_schema_instance(manifest, schemas.get("manifest"), "manifest.json", schemas, result)

    claims_path = manifest.get("claims", {}).get("registry")
    if isinstance(claims_path, str):
        claims = _read_referenced_json(packet_root, claims_path, result)
        if claims is not None:
            _validate_schema_instance(claims, schemas.get("claim"), claims_path, schemas, result)

    signoff_path = manifest.get("screenshots", {}).get("signoff")
    if isinstance(signoff_path, str):
        signoff = _read_referenced_json(packet_root, signoff_path, result)
        if signoff is not None:
            _validate_schema_instance(
                signoff, schemas.get("screenshot_signoff"), signoff_path, schemas, result
            )

    artifact_schema = schemas.get("artifact")
    for artifact_path in manifest.get("artifacts", []):
        artifact = _read_referenced_json(packet_root, artifact_path, result)
        if artifact is not None:
            _validate_schema_instance(artifact, artifact_schema, artifact_path, schemas, result)


def _validate_schema_instance(
    instance: dict[str, Any],
    schema: dict[str, Any] | None,
    path: str,
    schemas: dict[str, dict[str, Any]],
    result: ValidationResult,
) -> None:
    if schema is None:
        result.add_error(
            Finding(
                code=SCHEMA_INVALID,
                path=path,
                message="Required schema is missing.",
                recovery=RECOVERY_GUIDANCE[SCHEMA_INVALID],
            )
        )
        return
    registry = _schema_registry(schemas)
    try:
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(
            schema, registry=registry, format_checker=FormatChecker()
        )
        errors = sorted(validator.iter_errors(instance), key=lambda err: list(err.path))
    except SchemaError as exc:
        result.add_error(
            Finding(
                code=SCHEMA_INVALID,
                path=path,
                message=f"Invalid schema: {exc.message}",
                recovery=RECOVERY_GUIDANCE[SCHEMA_INVALID],
            )
        )
        return

    for error in errors:
        result.add_error(_schema_finding(path, error))


def _schema_registry(schemas: dict[str, dict[str, Any]]) -> Registry:
    resources = []
    for filename, schema in {
        "manifest.schema.json": schemas.get("manifest"),
        "claim.schema.json": schemas.get("claim"),
        "artifact.schema.json": schemas.get("artifact"),
        "screenshot-signoff.schema.json": schemas.get("screenshot_signoff"),
        "validation-result.schema.json": schemas.get("validation_result"),
    }.items():
        if schema is None:
            continue
        resource = Resource.from_contents(schema)
        resources.append((filename, resource))
        resources.append((f"schemas/{filename}", resource))
        schema_id = schema.get("$id")
        if isinstance(schema_id, str):
            resources.append((schema_id, resource))
    return Registry().with_resources(resources)


def _schema_finding(path: str, error: ValidationError) -> Finding:
    location = "/".join(str(part) for part in error.absolute_path)
    suffix = f" at {location}" if location else ""
    return Finding(
        code=SCHEMA_INVALID,
        path=path,
        message=f"Schema validation failed{suffix}: {error.message}",
        recovery=RECOVERY_GUIDANCE[SCHEMA_INVALID],
    )


def _validate_manifest_paths(
    packet_root: Path, manifest: dict[str, Any], result: ValidationResult
) -> None:
    paths: list[str] = []
    paths.extend(manifest.get("fixtures", []))
    paths.extend(manifest.get("artifacts", []))
    paths.extend(manifest.get("schemas", {}).values())
    claims = manifest.get("claims", {})
    paths.extend(
        path
        for path in [claims.get("registry"), claims.get("matrix")]
        if isinstance(path, str)
    )
    signoff_path = manifest.get("screenshots", {}).get("signoff")
    if isinstance(signoff_path, str):
        paths.append(signoff_path)
    paths.extend(manifest.get("artifact_hashes", {}).keys())

    seen: set[str] = set()
    for relative_path in paths:
        if not isinstance(relative_path, str) or relative_path in seen:
            continue
        seen.add(relative_path)
        resolved_path, path_error = resolve_packet_path(packet_root, relative_path)
        if path_error is not None:
            result.add_error(path_error)
            continue
        if resolved_path is None or not resolved_path.exists():
            result.add_error(
                Finding(
                    code=MANIFEST_PATH_MISSING,
                    path=relative_path,
                    message="Manifest-referenced path does not exist.",
                    recovery=RECOVERY_GUIDANCE[MANIFEST_PATH_MISSING],
                )
            )


def _validate_artifact_hashes(
    packet_root: Path, manifest: dict[str, Any], result: ValidationResult
) -> None:
    for artifact_path, recorded in manifest.get("artifact_hashes", {}).items():
        resolved_path, path_error = resolve_packet_path(packet_root, artifact_path)
        if path_error is not None:
            result.add_error(path_error)
            continue
        if resolved_path is None or not resolved_path.exists():
            result.artifact_results.append(
                ArtifactResult(
                    artifact_path=artifact_path,
                    status="blocked",
                    hash_valid=False,
                    redaction_status="blocked",
                )
            )
            continue
        actual = sha256_file(resolved_path)
        expected = recorded.get("value") if isinstance(recorded, dict) else None
        redaction_status = recorded.get("redaction_status", "pending")
        hash_valid = actual == expected
        result.artifact_results.append(
            ArtifactResult(
                artifact_path=artifact_path,
                status="passed" if hash_valid else "failed",
                hash_valid=hash_valid,
                redaction_status=redaction_status,
            )
        )
        if not hash_valid:
            result.add_error(
                Finding(
                    code=HASH_MISMATCH,
                    path=artifact_path,
                    message="Artifact SHA-256 does not match manifest artifact_hashes.",
                    recovery=RECOVERY_GUIDANCE[HASH_MISMATCH],
                )
            )


def _validate_claims(packet_root: Path, manifest: dict[str, Any], result: ValidationResult) -> None:
    registry_path = manifest.get("claims", {}).get("registry")
    if not isinstance(registry_path, str):
        return
    registry = _read_referenced_json(packet_root, registry_path, result)
    if registry is None:
        return

    claims = registry.get("claims", [])
    counts = {"proven": 0, "roadmap": 0, "disabled": 0, "total": len(claims)}
    artifact_paths = set(manifest.get("artifacts", []))
    for claim in claims:
        status = claim.get("status")
        if status in {"proven", "roadmap", "disabled"}:
            counts[status] += 1
        if status == "proven":
            evidence = claim.get("evidence") or []
            if not evidence or not claim.get("explanation"):
                _claim_error(
                    result,
                    registry_path,
                    "Proven claim is missing evidence or explanation.",
                )
            for item in evidence:
                if (
                    item.get("public") is not True
                    or item.get("redaction_status") != "passed"
                    or item.get("artifact_path") not in artifact_paths
                ):
                    _claim_error(
                        result,
                        registry_path,
                        "Proven claim cites invalid public evidence.",
                    )
        elif status == "roadmap":
            if not claim.get("missing_evidence") or not claim.get("planned_proof_path"):
                _claim_error(
                    result,
                    registry_path,
                    "Roadmap claim is missing future proof metadata.",
                )
        elif status == "disabled":
            if not claim.get("disabled_reason") or not claim.get("requirements_to_prove"):
                _claim_error(
                    result,
                    registry_path,
                    "Disabled claim is missing disabled proof metadata.",
                )

    if counts != manifest.get("claim_counts"):
        result.add_error(
            Finding(
                code=CLAIM_COUNTS_MISMATCH,
                path=registry_path,
                message="Claim counts do not match manifest claim_counts.",
                recovery=RECOVERY_GUIDANCE[CLAIM_COUNTS_MISMATCH],
            )
        )


def _claim_error(result: ValidationResult, path: str, message: str) -> None:
    result.add_error(
        Finding(
            code=CLAIM_EVIDENCE_INVALID,
            path=path,
            message=message,
            recovery=RECOVERY_GUIDANCE[CLAIM_EVIDENCE_INVALID],
        )
    )


def _validate_screenshots(
    packet_root: Path, manifest: dict[str, Any], result: ValidationResult
) -> None:
    signoff_path = manifest.get("screenshots", {}).get("signoff")
    if not isinstance(signoff_path, str):
        return
    signoff = _read_referenced_json(packet_root, signoff_path, result)
    if signoff is None:
        return
    screenshots = signoff.get("screenshots", [])
    approved_count = 0
    pending_count = 0
    for screenshot in screenshots:
        safe = screenshot.get("safe_to_publish") is True
        if safe:
            approved_count += 1
        else:
            pending_count += 1
        if safe and not screenshot.get("reviewer"):
            _screenshot_error(result, signoff_path, "Approved screenshot is missing reviewer.")
        if safe and not screenshot.get("reviewed_at"):
            _screenshot_error(result, signoff_path, "Approved screenshot is missing reviewed_at.")
        screenshot_path = screenshot.get("screenshot_path")
        if safe and isinstance(screenshot_path, str):
            resolved_path, path_error = resolve_packet_path(packet_root, screenshot_path)
            if path_error is not None or resolved_path is None or not resolved_path.exists():
                _screenshot_error(result, signoff_path, "Approved screenshot path is missing.")

    expected = manifest.get("screenshots", {})
    if (
        approved_count != expected.get("approved_count")
        or pending_count != expected.get("pending_count")
    ):
        _screenshot_error(result, signoff_path, "Screenshot approval counts do not match manifest.")


def _screenshot_error(result: ValidationResult, path: str, message: str) -> None:
    result.add_error(
        Finding(
            code=SCREENSHOT_SIGNOFF_INVALID,
            path=path,
            message=message,
            recovery=RECOVERY_GUIDANCE[SCREENSHOT_SIGNOFF_INVALID],
        )
    )


def _validate_source_commit(
    manifest: dict[str, Any], result: ValidationResult, *, repo_root: Path | None
) -> None:
    source_commit = manifest.get("source_commit")
    if isinstance(source_commit, str) and len(source_commit) == 40 and not git_commit_exists(
        source_commit, repo_root=repo_root
    ):
        result.add_error(
            Finding(
                code=STALE_SOURCE_COMMIT,
                path="manifest.json",
                message="Manifest source_commit is not present in repository history.",
                recovery=RECOVERY_GUIDANCE[STALE_SOURCE_COMMIT],
            )
        )


def _validate_redaction(packet_root: Path, result: ValidationResult) -> None:
    for path in packet_text_files(packet_root):
        for finding in scan_text_file(path, packet_root=packet_root):
            result.add_error(finding)


def _read_referenced_json(
    packet_root: Path, relative_path: str, result: ValidationResult
) -> dict[str, Any] | None:
    resolved_path, path_error = resolve_packet_path(packet_root, relative_path)
    if path_error is not None:
        result.add_error(path_error)
        return None
    if resolved_path is None:
        return None
    payload, error = read_json(resolved_path)
    if error is not None:
        error = Finding(
            code=error.code,
            path=relative_path,
            message=error.message,
            recovery=error.recovery,
            severity=error.severity,
        )
        result.add_error(error)
        return None
    return payload
