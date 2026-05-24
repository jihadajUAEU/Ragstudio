"""Centralized script detection utilities.

Single source of truth for Unicode script patterns and detection functions.
Replaces duplicate definitions across parser_normalization.py,
domain_metadata_quality_gate.py, and mineru_extraction_validator.py.
"""

from __future__ import annotations

from ragstudio.services.reference_regex_registry import SCRIPT_PATTERNS


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
