"""Manifest and static packet helpers for proof packet validation."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from ragstudio.proof_packet.errors import (
    EXPORT_MANIFEST_INVALID,
    JSON_PARSE_ERROR,
    MANIFEST_PATH_MISSING,
    RECOVERY_GUIDANCE,
)
from ragstudio.proof_packet.models import Finding, ValidationResult


def read_json(path: Path) -> tuple[dict[str, Any] | None, Finding | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, Finding(
            code=MANIFEST_PATH_MISSING,
            path=str(path),
            message="Required JSON file is missing.",
            recovery=RECOVERY_GUIDANCE[MANIFEST_PATH_MISSING],
        )
    except JSONDecodeError as exc:
        return None, Finding(
            code=JSON_PARSE_ERROR,
            path=str(path),
            message=f"JSON parse error at line {exc.lineno}, column {exc.colno}: {exc.msg}",
            recovery=RECOVERY_GUIDANCE[JSON_PARSE_ERROR],
        )


def resolve_packet_path(
    packet_root: Path, relative_path: str
) -> tuple[Path | None, Finding | None]:
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None, Finding(
            code=MANIFEST_PATH_MISSING,
            path=relative_path,
            message="Manifest path must be relative and stay inside the packet root.",
            recovery=RECOVERY_GUIDANCE[MANIFEST_PATH_MISSING],
        )

    resolved_root = packet_root.resolve()
    resolved_path = (packet_root / candidate).resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        return None, Finding(
            code=MANIFEST_PATH_MISSING,
            path=relative_path,
            message="Manifest path resolves outside the packet root.",
            recovery=RECOVERY_GUIDANCE[MANIFEST_PATH_MISSING],
        )
    return resolved_path, None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def packet_text_files(packet_root: Path) -> list[Path]:
    return [
        path
        for path in packet_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".json", ".md"}
    ]


def git_commit_exists(commit: str, *, repo_root: Path | None = None) -> bool:
    cwd = repo_root or Path.cwd()
    completed = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def git_path_exists_at_commit(
    commit: str,
    path: str,
    *,
    repo_root: Path | None = None,
) -> bool:
    cwd = repo_root or Path.cwd()
    completed = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}:{path}"],
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def current_git_commit(*, repo_root: Path | None = None) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root or Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def build_export_manifest(
    packet_root: Path,
    *,
    validation_result: ValidationResult | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    manifest, error = read_json(packet_root / "manifest.json")
    if error is not None or manifest is None:
        raise ValueError(EXPORT_MANIFEST_INVALID)

    artifact_hashes: dict[str, dict[str, str]] = {}
    for artifact_path in manifest.get("artifacts", []):
        resolved_path, path_error = resolve_packet_path(packet_root, artifact_path)
        if path_error is not None or resolved_path is None or not resolved_path.exists():
            raise ValueError(EXPORT_MANIFEST_INVALID)
        artifact_hashes[artifact_path] = {
            "algorithm": "sha256",
            "value": sha256_file(resolved_path),
        }

    packet_hash = hashlib.sha256()
    for path in sorted(path for path in packet_root.rglob("*") if path.is_file()):
        packet_hash.update(str(path.relative_to(packet_root)).encode("utf-8"))
        packet_hash.update(b"\0")
        packet_hash.update(path.read_bytes())

    validation_status = validation_result.status if validation_result is not None else "not_run"
    return {
        "packet_id": manifest.get("packet_id", "unknown"),
        "packet_version": manifest.get("packet_version", "unknown"),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_commit": current_git_commit(repo_root=repo_root),
        "packet_hash": {
            "algorithm": "sha256",
            "value": packet_hash.hexdigest(),
        },
        "artifact_hashes": artifact_hashes,
        "validation_status": validation_status,
        "validation_id": validation_result.validation_id if validation_result is not None else None,
    }
