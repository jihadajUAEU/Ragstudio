"""Result models for proof packet validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

VALIDATOR_VERSION = "0.1.0"


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    path: str
    recovery: str
    severity: str = "error"

    def to_dict(self, *, include_severity: bool = False) -> dict[str, str]:
        payload = {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "recovery": self.recovery,
        }
        if include_severity:
            payload["severity"] = self.severity
        return payload


@dataclass
class ValidationSummary:
    schema_valid: bool = True
    hashes_valid: bool = True
    redaction_valid: bool = True
    claims_valid: bool = True

    def to_dict(self) -> dict[str, bool]:
        return {
            "schema_valid": self.schema_valid,
            "hashes_valid": self.hashes_valid,
            "redaction_valid": self.redaction_valid,
            "claims_valid": self.claims_valid,
        }


@dataclass(frozen=True)
class ArtifactResult:
    artifact_path: str
    status: str
    hash_valid: bool
    redaction_status: str

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "artifact_path": self.artifact_path,
            "status": self.status,
            "hash_valid": self.hash_valid,
            "redaction_status": self.redaction_status,
        }


@dataclass
class ValidationResult:
    packet_id: str
    status: str = "passed"
    summary: ValidationSummary = field(default_factory=ValidationSummary)
    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    artifact_results: list[ArtifactResult] = field(default_factory=list)
    validation_id: str = field(default_factory=lambda: f"validation-{uuid4()}")
    validated_at: str = field(
        default_factory=lambda: datetime.now(UTC).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
    )
    validator_version: str = VALIDATOR_VERSION

    def add_error(self, finding: Finding) -> None:
        self.errors.append(finding)
        self.status = "failed"

    def add_warning(self, finding: Finding) -> None:
        self.warnings.append(finding)

    def finalize(self, *, strict: bool = False) -> ValidationResult:
        if self.errors:
            self.status = "failed"
        elif strict and self.warnings:
            self.status = "failed"
        else:
            self.status = "passed"
        return self

    def to_dict(self, *, include_severity: bool = False) -> dict[str, object]:
        return {
            "validation_id": self.validation_id,
            "packet_id": self.packet_id,
            "status": self.status,
            "validated_at": self.validated_at,
            "validator_version": self.validator_version,
            "summary": self.summary.to_dict(),
            "errors": [
                finding.to_dict(include_severity=include_severity) for finding in self.errors
            ],
            "warnings": [
                finding.to_dict(include_severity=include_severity) for finding in self.warnings
            ],
            "artifact_results": [artifact.to_dict() for artifact in self.artifact_results],
        }
