from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ragstudio.schemas.document_parse_evidence import DocumentParseEvidence
from ragstudio.services.redaction_registry import find_redaction_matches

EXPORT_RELATIVE_PATH = "artifacts/document-parse-evidence.export.json"
EXPORT_ONLY_UNSAFE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"internal\.local", re.IGNORECASE), "private host"),
    (re.compile(r"\[fd[0-9a-f]{2}:[^\]]+\]", re.IGNORECASE), "private host"),
    (
        re.compile(
            r'\\?"(?:api[_-]?key|token|secret|password|authorization)\\?"\s*:',
            re.IGNORECASE,
        ),
        "secret-like key",
    ),
)
PUBLIC_SAFETY_LABELS = {
    "local_absolute_path": "local absolute path",
    "unc_path": "local absolute path",
    "file_uri": "local absolute path",
    "localhost": "private host",
    "private_10_net": "private host",
    "private_172_net": "private host",
    "private_192_net": "private host",
    "openai_key": "secret-shaped value",
    "aws_access_key": "secret-shaped value",
    "github_token": "secret-shaped value",
    "github_pat": "secret-shaped value",
    "slack_token": "secret-shaped value",
    "google_api_key": "secret-shaped value",
    "bearer_token": "secret-shaped value",
}


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
        for match in find_redaction_matches(text):
            label = PUBLIC_SAFETY_LABELS.get(match.rule_id, "public-safety pattern")
            raise UnsafeProofExportError(f"Proof export contains unsafe {label}.")
        for pattern, label in EXPORT_ONLY_UNSAFE_PATTERNS:
            if pattern.search(text):
                raise UnsafeProofExportError(f"Proof export contains unsafe {label}.")
