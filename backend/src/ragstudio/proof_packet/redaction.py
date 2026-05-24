"""Fail-closed public leak scanning for proof packet text files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ragstudio.proof_packet.errors import RECOVERY_GUIDANCE, REDACTION_LEAK
from ragstudio.proof_packet.models import Finding
from ragstudio.services.redaction_registry import REDACTION_RULES as SHARED_REDACTION_RULES


@dataclass(frozen=True)
class RedactionRule:
    name: str
    pattern: re.Pattern[str]


REDACTION_RULES: tuple[RedactionRule, ...] = tuple(
    RedactionRule(rule.rule_id, rule.pattern) for rule in SHARED_REDACTION_RULES
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
