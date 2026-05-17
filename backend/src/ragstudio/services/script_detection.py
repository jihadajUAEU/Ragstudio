"""Centralized script detection utilities.

Single source of truth for Unicode script patterns and detection functions.
Replaces duplicate definitions across parser_normalization.py,
domain_metadata_quality_gate.py, and mineru_extraction_validator.py.
"""

from __future__ import annotations

import re

# Full Unicode ranges, including Arabic Presentation Forms and supplements.
SCRIPT_PATTERNS: dict[str, re.Pattern[str]] = {
    "arabic": re.compile(
        r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]"
    ),
    "latin": re.compile(r"[A-Za-z]"),
    "cyrillic": re.compile(r"[\u0400-\u04ff]"),
    "greek": re.compile(r"[\u0370-\u03ff]"),
    "hebrew": re.compile(r"[\u0590-\u05ff]"),
    "devanagari": re.compile(r"[\u0900-\u097f]"),
    "han": re.compile(r"[\u4e00-\u9fff]"),
}


def has_script(text: str, script: str) -> bool:
    """Return True if *text* contains at least one character of *script*."""
    pattern = SCRIPT_PATTERNS.get(script.lower())
    if pattern is None:
        return False
    return bool(pattern.search(text))


def detect_scripts(text: str) -> set[str]:
    """Return the set of script names present in *text*."""
    return {name for name, pattern in SCRIPT_PATTERNS.items() if pattern.search(text)}


def missing_scripts(text: str, expected: set[str]) -> set[str]:
    """Return which of *expected* scripts are absent from *text*."""
    present = detect_scripts(text)
    return {s.lower() for s in expected} - present
