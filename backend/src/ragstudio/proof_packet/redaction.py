"""Fail-closed public leak scanning for proof packet text files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ragstudio.proof_packet.errors import RECOVERY_GUIDANCE, REDACTION_LEAK
from ragstudio.proof_packet.models import Finding


@dataclass(frozen=True)
class RedactionRule:
    name: str
    pattern: re.Pattern[str]


REDACTION_RULES: tuple[RedactionRule, ...] = (
    RedactionRule("openai_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    RedactionRule("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    RedactionRule("github_pat", re.compile(r"github_pat_[A-Za-z0-9_]+")),
    RedactionRule("github_token", re.compile(r"ghp_[A-Za-z0-9_]{20,}")),
    RedactionRule("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]+")),
    RedactionRule("google_api_key", re.compile(r"AIza[0-9A-Za-z_-]{20,}")),
    RedactionRule("bearer_token", re.compile(r"bearer\s+[a-z0-9._=-]{12,}", re.IGNORECASE)),
    RedactionRule("localhost", re.compile(r"localhost|127\.0\.0\.1|0\.0\.0\.0")),
    RedactionRule("private_10_net", re.compile(r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}")),
    RedactionRule("private_172_net", re.compile(r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}")),
    RedactionRule("private_192_net", re.compile(r"192\.168\.\d{1,3}\.\d{1,3}")),
    RedactionRule(
        "local_absolute_path",
        re.compile(r"/Users/[^\s\"']+|/home/[^\s\"']+|C:\\Users\\"),
    ),
    RedactionRule("file_uri", re.compile(r"file://")),
)


def scan_text_file(path: Path, *, packet_root: Path) -> list[Finding]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    relative = str(path.relative_to(packet_root))
    findings: list[Finding] = []
    for rule in REDACTION_RULES:
        if rule.pattern.search(text):
            findings.append(
                Finding(
                    code=REDACTION_LEAK,
                    path=relative,
                    message=f"Public leak pattern matched: {rule.name}.",
                    recovery=RECOVERY_GUIDANCE[REDACTION_LEAK],
                )
            )
    return findings
