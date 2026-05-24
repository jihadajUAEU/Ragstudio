from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RedactionRule:
    rule_id: str
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class RedactionMatch:
    rule_id: str
    start: int
    end: int
    value: str


REDACTION_RULES: tuple[RedactionRule, ...] = (
    RedactionRule("openai_key", re.compile(r"sk-[A-Za-z0-9_-]{8,}")),
    RedactionRule("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    RedactionRule("github_pat", re.compile(r"github_pat_[A-Za-z0-9_]+")),
    RedactionRule("github_token", re.compile(r"ghp_[A-Za-z0-9_]{20,}", re.IGNORECASE)),
    RedactionRule("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]+")),
    RedactionRule("google_api_key", re.compile(r"AIza[0-9A-Za-z_-]{20,}")),
    RedactionRule(
        "bearer_token",
        re.compile(r"\bBearer\s+[A-Za-z0-9._=-]{6,}\b", re.IGNORECASE),
    ),
    RedactionRule("localhost", re.compile(r"localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]")),
    RedactionRule("private_10_net", re.compile(r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}")),
    RedactionRule(
        "private_172_net",
        re.compile(r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}"),
    ),
    RedactionRule("private_192_net", re.compile(r"192\.168\.\d{1,3}\.\d{1,3}")),
    RedactionRule(
        "local_absolute_path",
        re.compile(
            r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\"'\s]+"
            r"|/Users/[^\s\"']+|/home/[^\s\"']+|/tmp/[^\s\"']+|/var/[^\s\"']+",
            re.IGNORECASE,
        ),
    ),
    RedactionRule("unc_path", re.compile(r"\\\\[A-Za-z0-9][^\s\\/:*?\"<>|]*\\[^\s\"']+")),
    RedactionRule("file_uri", re.compile(r"file://", re.IGNORECASE)),
)


def find_redaction_matches(text: str) -> list[RedactionMatch]:
    matches: list[RedactionMatch] = []
    for rule in REDACTION_RULES:
        for match in rule.pattern.finditer(text):
            matches.append(
                RedactionMatch(
                    rule_id=rule.rule_id,
                    start=match.start(),
                    end=match.end(),
                    value=match.group(0),
                )
            )
    return sorted(matches, key=lambda item: (item.start, item.end, item.rule_id))


def redact_text(text: str) -> str:
    redacted = text
    for rule in REDACTION_RULES:
        redacted = rule.pattern.sub(f"[REDACTED:{rule.rule_id}]", redacted)
    return redacted
