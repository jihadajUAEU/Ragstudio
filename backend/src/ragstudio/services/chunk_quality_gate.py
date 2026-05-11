from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.parser_normalization import ExpectedContentProfile

SCRIPT_PATTERNS = {
    "arabic": re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]"),
    "latin": re.compile(r"[A-Za-z]"),
    "cyrillic": re.compile(r"[\u0400-\u04FF]"),
    "greek": re.compile(r"[\u0370-\u03FF]"),
    "hebrew": re.compile(r"[\u0590-\u05FF]"),
    "devanagari": re.compile(r"[\u0900-\u097F]"),
    "han": re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]"),
}
CHAPTER_VERSE_PATTERN = re.compile(
    r"(?P<prefix>\bQuran\s+)?(?P<bracket>\[)?"
    r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})"
    r"(?(bracket)\])",
    flags=re.IGNORECASE,
)
BOOK_HADITH_PATTERN = re.compile(
    r"\bBook\s+\d+\s*,?\s*Hadith\s+\d+\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class ChunkQualityGate:
    expected_profile: ExpectedContentProfile
    domain_metadata: DomainMetadata | None = None

    def warnings_for(self, text: str) -> list[dict[str, Any]]:
        if not self._has_reference(text):
            return []

        warnings: list[dict[str, Any]] = []
        for script in sorted(self._expected_scripts()):
            pattern = SCRIPT_PATTERNS.get(script)
            if pattern is None or pattern.search(text):
                continue
            script_label = script.capitalize()
            warnings.append(
                {
                    "code": "reference_unit_missing_expected_script",
                    "message": (
                        "Reference-bearing chunk is expected to contain "
                        f"{script_label} script, but no {script_label} letters were detected."
                    ),
                    "expected_script": script,
                }
            )
        return warnings

    def _expected_scripts(self) -> set[str]:
        expected_scripts = {
            script.casefold() for script in self.expected_profile.expected_scripts
        }
        if self.domain_metadata is None:
            return expected_scripts

        metadata_values = {
            self.domain_metadata.script,
            self.domain_metadata.language,
            *self.domain_metadata.tags,
        }
        expected_scripts.update(str(value).strip().casefold() for value in metadata_values if value)
        if "mixed" in expected_scripts:
            expected_scripts.remove("mixed")
            expected_scripts.update({"arabic", "latin"})
        return expected_scripts

    def _has_reference(self, text: str) -> bool:
        if CHAPTER_VERSE_PATTERN.search(text) or BOOK_HADITH_PATTERN.search(text):
            return True

        for pattern in self.expected_profile.reference_patterns:
            try:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    return True
            except re.error:
                continue
        return False
