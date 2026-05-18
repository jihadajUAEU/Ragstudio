from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ragstudio.schemas.document_parse_evidence import DocumentParseEvidence

EXPORT_RELATIVE_PATH = "artifacts/document-parse-evidence.export.json"
UNSAFE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\"\\s]+"), "local absolute path"),
    (re.compile(r"\\\\[^\s\\/:*?\"<>|]+\\[^\s\"']+"), "local absolute path"),
    (re.compile(r"/Users/|/home/|/tmp/|/var/", re.IGNORECASE), "local absolute path"),
    (
        re.compile(
            r"(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|"
            r"172\.(?:1[6-9]|2\d|3[0-1])\.\d+\.\d+|0\.0\.0\.0|internal\.local|\[::1\]|\[fd[0-9a-f]{2}:[^\]]+\])",
            re.IGNORECASE,
        ),
        "private host",
    ),
    (
        re.compile(r"\"(?:api[_-]?key|token|secret|password|authorization)\"\s*:", re.IGNORECASE),
        "secret-like key",
    ),
    (re.compile(r"sk-[A-Za-z0-9_-]{8,}"), "secret-shaped value"),
    (re.compile(r"ghp_[A-Za-z0-9_]{20,}", re.IGNORECASE), "secret-shaped value"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._=-]{6,}\b", re.IGNORECASE), "secret-shaped value"),
    (
        re.compile(r"Authorization\s*:\s*Bearer\s+[A-Za-z0-9._=-]{6,}\b", re.IGNORECASE),
        "secret-shaped value",
    ),
)


class UnsafeProofExportError(ValueError):
    pass


@dataclass(frozen=True)
class DocumentParseEvidenceExportResult:
    relative_path: str
    bytes_written: int


class DocumentParseEvidenceExporter:
    def export(
        self,
        evidence: DocumentParseEvidence,
        *,
        packet_dir: Path,
        proof_packet_id: str,
        source_commit: str,
    ) -> DocumentParseEvidenceExportResult:
        export_evidence = evidence.model_copy(deep=True)
        export_evidence.proof.mode = "export"
        export_evidence.proof.proof_packet_id = proof_packet_id
        export_evidence.proof.source_commit = source_commit
        if not export_evidence.proof.replay_command:
            export_evidence.proof.replay_command = "./scripts/proof.sh --fixtures static-fixtures"

        payload = export_evidence.model_dump(mode="json")
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._validate_safe(text)

        output_path = packet_dir / EXPORT_RELATIVE_PATH
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        return DocumentParseEvidenceExportResult(
            relative_path=EXPORT_RELATIVE_PATH,
            bytes_written=len(text.encode("utf-8")),
        )

    def _validate_safe(self, text: str) -> None:
        for pattern, label in UNSAFE_PATTERNS:
            if pattern.search(text):
                raise UnsafeProofExportError(f"Proof export contains unsafe {label}.")
