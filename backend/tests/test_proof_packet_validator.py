import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from ragstudio.proof_packet.errors import (
    CLAIM_COUNTS_MISMATCH,
    CLAIM_EVIDENCE_INVALID,
    CLAIM_SOURCE_INVALID,
    ERROR_CODES,
    EXPORT_MANIFEST_INVALID,
    HASH_MISMATCH,
    JSON_PARSE_ERROR,
    MANIFEST_PATH_MISSING,
    PACKET_NOT_FOUND,
    REDACTION_LEAK,
    SCHEMA_INVALID,
    SCREENSHOT_SIGNOFF_INVALID,
    STALE_SOURCE_COMMIT,
)
from ragstudio.proof_packet.manifest import build_export_manifest
from ragstudio.proof_packet.validator import validate_packet

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKET_ROOT = REPO_ROOT / "docs" / "benchmarks" / "ragstudio-oss-proof-v1"


@pytest.fixture
def packet_copy(tmp_path: Path) -> Path:
    target = tmp_path / "ragstudio-oss-proof-v1"
    shutil.copytree(PACKET_ROOT, target)
    # Normalize line endings to LF to prevent CRLF hash mismatches on Windows
    for path in target.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".json", ".md"}:
            content = path.read_bytes()
            if b"\r\n" in content:
                path.write_bytes(content.replace(b"\r\n", b"\n"))
    return target


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _codes(result) -> set[str]:
    return {finding.code for finding in [*result.errors, *result.warnings]}


def _run_proof(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (str(REPO_ROOT / "backend" / "src"), existing_pythonpath)
        if part
    )
    command = (
        [sys.executable, "-m", "ragstudio.proof_packet.cli", *args]
        if os.name == "nt"
        else [str(REPO_ROOT / "scripts" / "proof.sh"), *args]
    )
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_default_packet_validates_successfully():
    result = validate_packet(PACKET_ROOT, repo_root=REPO_ROOT)

    assert result.status == "passed", result.to_dict(include_severity=True)
    assert result.errors == []
    assert result.summary.schema_valid is True
    assert result.summary.hashes_valid is True
    assert result.summary.redaction_valid is True
    assert result.summary.claims_valid is True
    assert result.artifact_results


def test_validation_result_compact_shape_has_stable_fields():
    payload = validate_packet(PACKET_ROOT, repo_root=REPO_ROOT).to_dict()

    assert {
        "validation_id",
        "packet_id",
        "status",
        "validated_at",
        "validator_version",
        "summary",
        "errors",
        "warnings",
        "artifact_results",
    } <= set(payload)
    assert "severity" not in json.dumps(payload)


def test_missing_packet_reports_packet_not_found(tmp_path: Path):
    result = validate_packet(tmp_path / "missing", repo_root=REPO_ROOT)

    assert result.status == "failed"
    assert PACKET_NOT_FOUND in _codes(result)


def test_missing_artifact_reports_manifest_path_missing(packet_copy: Path):
    (packet_copy / "artifacts" / "chunks.export.json").unlink()

    result = validate_packet(packet_copy, repo_root=REPO_ROOT)

    assert MANIFEST_PATH_MISSING in _codes(result)


def test_hash_mismatch_reports_hash_mismatch(packet_copy: Path):
    artifact = packet_copy / "artifacts" / "chunks.export.json"
    payload = _read_json(artifact)
    payload["status"] = "changed-after-hash"
    _write_json(artifact, payload)

    result = validate_packet(packet_copy, repo_root=REPO_ROOT)

    assert HASH_MISMATCH in _codes(result)


def test_invalid_json_reports_json_parse_error(packet_copy: Path):
    (packet_copy / "claims" / "claims.registry.json").write_text("{", encoding="utf-8")

    result = validate_packet(packet_copy, repo_root=REPO_ROOT)

    assert JSON_PARSE_ERROR in _codes(result)


def test_schema_invalid_reports_schema_invalid(packet_copy: Path):
    manifest = _read_json(packet_copy / "manifest.json")
    manifest.pop("packet_id")
    _write_json(packet_copy / "manifest.json", manifest)

    result = validate_packet(packet_copy, repo_root=REPO_ROOT)

    assert SCHEMA_INVALID in _codes(result)


def test_manifest_path_traversal_is_rejected(packet_copy: Path):
    manifest = _read_json(packet_copy / "manifest.json")
    manifest["fixtures"].append("../private.json")
    _write_json(packet_copy / "manifest.json", manifest)

    result = validate_packet(packet_copy, repo_root=REPO_ROOT)

    assert MANIFEST_PATH_MISSING in _codes(result)


def test_redaction_leak_reports_redaction_leak(packet_copy: Path):
    (packet_copy / "docs" / "leak.md").write_text("private endpoint 10.10.9.10\n", encoding="utf-8")

    result = validate_packet(packet_copy, repo_root=REPO_ROOT)

    assert REDACTION_LEAK in _codes(result)
    assert result.summary.redaction_valid is False


def test_claim_without_public_artifact_evidence_fails(packet_copy: Path):
    registry_path = packet_copy / "claims" / "claims.registry.json"
    registry = _read_json(registry_path)
    registry["claims"][0]["evidence"][0]["public"] = False
    _write_json(registry_path, registry)

    result = validate_packet(packet_copy, repo_root=REPO_ROOT)

    assert CLAIM_EVIDENCE_INVALID in _codes(result)


def test_claim_count_mismatch_fails(packet_copy: Path):
    manifest_path = packet_copy / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["claim_counts"]["proven"] = 99
    _write_json(manifest_path, manifest)

    result = validate_packet(packet_copy, repo_root=REPO_ROOT)

    assert CLAIM_COUNTS_MISMATCH in _codes(result)


def test_screenshot_signoff_invalid_fails(packet_copy: Path):
    signoff_path = packet_copy / "screenshots" / "signoff.json"
    signoff = _read_json(signoff_path)
    signoff["screenshots"][0]["reviewer"] = ""
    _write_json(signoff_path, signoff)

    result = validate_packet(packet_copy, repo_root=REPO_ROOT)

    assert SCREENSHOT_SIGNOFF_INVALID in _codes(result)


def test_stale_source_commit_fails(packet_copy: Path):
    manifest_path = packet_copy / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["source_commit"] = "f" * 40
    _write_json(manifest_path, manifest)

    result = validate_packet(packet_copy, repo_root=REPO_ROOT)

    assert STALE_SOURCE_COMMIT in _codes(result)


def test_claim_source_path_missing_at_source_commit_fails(packet_copy: Path):
    registry_path = packet_copy / "claims" / "claims.registry.json"
    registry = _read_json(registry_path)
    registry["claims"][0]["source"]["source_commit"] = "ad1febe626fd96afff414bf5c425b4a672213a14"
    registry["claims"][0]["source"]["code_paths"] = [
        "docs/benchmarks/ragstudio-oss-proof-v1/docs/LIMITATIONS.md"
    ]
    _write_json(registry_path, registry)

    result = validate_packet(packet_copy, repo_root=REPO_ROOT)

    assert CLAIM_SOURCE_INVALID in _codes(result)
    assert result.summary.claims_valid is False


def test_export_manifest_records_static_packet_metadata(packet_copy: Path):
    result = validate_packet(packet_copy, repo_root=REPO_ROOT)

    export_manifest = build_export_manifest(
        packet_copy, validation_result=result, repo_root=REPO_ROOT
    )

    assert export_manifest["packet_id"] == "ragstudio-oss-proof-v1"
    assert export_manifest["validation_status"] == "passed"
    assert export_manifest["packet_hash"]["algorithm"] == "sha256"
    chunks_hash = export_manifest["artifact_hashes"]["artifacts/chunks.export.json"]
    assert chunks_hash["algorithm"] == "sha256"


def test_export_manifest_invalid_packet_raises(tmp_path: Path):
    with pytest.raises(ValueError, match=EXPORT_MANIFEST_INVALID):
        build_export_manifest(tmp_path)


def test_proof_script_no_args_succeeds():
    completed = _run_proof()

    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert "Status: passed" in completed.stdout
    assert "docs/benchmarks/ragstudio-oss-proof-v1" in completed.stdout.replace("\\", "/")


def test_proof_script_json_is_compact_parseable():
    completed = _run_proof("--json")

    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["packet_id"] == "ragstudio-oss-proof-v1"


def test_proof_script_packet_strict_json_succeeds():
    completed = _run_proof("--packet", str(PACKET_ROOT), "--strict", "--json")

    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert json.loads(completed.stdout)["status"] == "passed"


def test_proof_script_invalid_packet_exits_nonzero(tmp_path: Path):
    completed = _run_proof("--packet", str(tmp_path / "missing"), "--json")

    assert completed.returncode != 0
    assert json.loads(completed.stdout)["errors"][0]["code"] == PACKET_NOT_FOUND


def test_strict_mode_turns_warning_into_failure(packet_copy: Path, monkeypatch: pytest.MonkeyPatch):
    from ragstudio.proof_packet import validator
    from ragstudio.proof_packet.models import Finding

    original = validator._validate_source_commit

    def warning_source_commit(manifest, result, *, repo_root):
        original(manifest, result, repo_root=repo_root)
        result.add_warning(
            Finding(
                code="ADVISORY_TEST_WARNING",
                path="manifest.json",
                message="Advisory warning for strict mode.",
                recovery="Fix the advisory before CI.",
                severity="warning",
            )
        )

    monkeypatch.setattr(validator, "_validate_source_commit", warning_source_commit)

    non_strict_result = validator.validate_packet(packet_copy, strict=False, repo_root=REPO_ROOT)
    strict_result = validator.validate_packet(packet_copy, strict=True, repo_root=REPO_ROOT)

    assert non_strict_result.status == "passed"
    assert strict_result.status == "failed"


def test_verbose_output_includes_recovery_for_failures(tmp_path: Path):
    completed = _run_proof("--packet", str(tmp_path / "missing"), "--verbose")

    assert completed.returncode != 0
    assert PACKET_NOT_FOUND in completed.stdout
    assert "Recovery:" in completed.stdout


def test_errors_doc_covers_exported_error_codes():
    errors_doc = (PACKET_ROOT / "docs" / "ERRORS.md").read_text(encoding="utf-8")

    for code in ERROR_CODES:
        assert code in errors_doc
