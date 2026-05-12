from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.arabic_text import arabic_tokens
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


class DomainMetadataQualityGateError(RuntimeError):
    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


@dataclass(frozen=True)
class MetadataQualityProfile:
    domain: str
    expected_scripts: frozenset[str]
    reference_patterns: tuple[str, ...]
    parser_strictness: str
    preserve_parallel_text: bool
    reference_unit: str | None
    reference_type: str | None
    equation_blocks_allowed: bool


class DomainMetadataQualityGate:
    raw_pdf_pattern = re.compile(r"(%PDF-\d|\b\d+\s+\d+\s+obj\b|\bxref\b|\bendobj\b)")

    def profile_for(
        self,
        domain_metadata: DomainMetadata | None = None,
        *,
        expected_profile: ExpectedContentProfile | None = None,
    ) -> MetadataQualityProfile:
        domain_metadata = domain_metadata or DomainMetadata()
        expected_profile = expected_profile or ExpectedContentProfile.from_domain_metadata(
            domain_metadata
        )
        custom_json = (
            domain_metadata.custom_json if isinstance(domain_metadata.custom_json, dict) else {}
        )
        chunking = _dict_value(custom_json, "chunking") or {}
        reference_schema = _dict_value(custom_json, "reference_schema") or {}
        preserve_parallel_text = bool(chunking.get("preserve_parallel_text"))
        reference_unit = _string_value(chunking.get("unit"))
        reference_type = _string_value(reference_schema.get("type")) or _string_value(
            domain_metadata.citation_style
        )
        return MetadataQualityProfile(
            domain=str(domain_metadata.domain or "generic").strip().casefold(),
            expected_scripts=frozenset(
                script
                for script in expected_profile.expected_scripts
                if script in SCRIPT_PATTERNS
            ),
            reference_patterns=expected_profile.reference_patterns,
            parser_strictness=expected_profile.parser_strictness,
            preserve_parallel_text=preserve_parallel_text,
            reference_unit=reference_unit,
            reference_type=reference_type,
            equation_blocks_allowed=expected_profile.allows_equations_as_content(),
        )

    def warnings_for_text(
        self,
        text: str,
        *,
        domain_metadata: DomainMetadata | None = None,
        expected_profile: ExpectedContentProfile | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        profile = self.profile_for(domain_metadata, expected_profile=expected_profile)
        if not profile.expected_scripts:
            return []
        if not self._has_reference(text, metadata, profile):
            return []

        warnings: list[dict[str, Any]] = []
        for script in sorted(profile.expected_scripts):
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

    def validate_adapter_chunks(
        self,
        chunks: list[AdapterChunk],
        *,
        language: str = "unknown",
        domain_metadata: DomainMetadata | None = None,
        expected_profile: ExpectedContentProfile | None = None,
    ) -> dict[str, Any]:
        text = "\n".join(chunk.text for chunk in chunks)
        if self.raw_pdf_pattern.search(text):
            raise DomainMetadataQualityGateError(
                "raw_pdf_persisted",
                "Raw PDF syntax reached chunk persistence.",
            )

        tokens = arabic_tokens(text)
        profile = self.profile_for(domain_metadata, expected_profile=expected_profile)
        if self._requires_document_arabic(language, profile) and not tokens:
            raise DomainMetadataQualityGateError(
                "arabic_tokens_missing",
                "Arabic document has no normalized Arabic search tokens.",
            )

        for chunk in chunks:
            self.annotate_chunk(
                chunk,
                domain_metadata=domain_metadata,
                expected_profile=expected_profile,
            )
        quality_summary = self.parser_quality_summary(chunks)
        status = "passed_with_warnings" if quality_summary["warning_counts"] else "passed"
        return {
            "status": status,
            "chunk_count": len(chunks),
            "arabic_token_count": len(tokens),
            "quality_profile": {
                "domain": profile.domain,
                "expected_scripts": sorted(profile.expected_scripts),
                "preserve_parallel_text": profile.preserve_parallel_text,
                "reference_unit": profile.reference_unit,
                "reference_type": profile.reference_type,
            },
            "parser_quality": quality_summary,
        }

    def annotate_chunk(
        self,
        chunk: AdapterChunk,
        *,
        domain_metadata: DomainMetadata | None = None,
        expected_profile: ExpectedContentProfile | None = None,
    ) -> list[dict[str, Any]]:
        warnings = self.warnings_for_text(
            chunk.text,
            domain_metadata=domain_metadata,
            expected_profile=expected_profile,
            metadata=chunk.metadata,
        )
        self.merge_parser_warnings(chunk.metadata, warnings)
        return warnings

    def parser_quality_summary(self, chunks: list[Any]) -> dict[str, Any]:
        warning_counts: dict[str, int] = {}
        affected_chunks = 0
        for chunk in chunks:
            codes = sorted(set(self.parser_warning_codes_for_chunk(chunk)))
            if not codes:
                continue
            affected_chunks += 1
            for code in codes:
                warning_counts[code] = warning_counts.get(code, 0) + 1
        return {
            "warning_counts": dict(sorted(warning_counts.items())),
            "affected_chunks": affected_chunks,
        }

    def parser_warning_codes_for_chunk(self, chunk: Any) -> list[str]:
        extraction_quality = getattr(chunk, "extraction_quality", None)
        if not isinstance(extraction_quality, dict):
            metadata = getattr(chunk, "metadata", None)
            if isinstance(metadata, dict):
                extraction_quality = metadata.get("extraction_quality")
        if not isinstance(extraction_quality, dict):
            return []
        return self.parser_warning_codes(extraction_quality)

    def parser_warning_codes(self, metadata_or_extraction_quality: dict[str, Any]) -> list[str]:
        extraction_quality = metadata_or_extraction_quality.get("extraction_quality")
        if not isinstance(extraction_quality, dict):
            extraction_quality = metadata_or_extraction_quality
        warnings = extraction_quality.get("parser_warnings")
        if not isinstance(warnings, list):
            return []
        codes: list[str] = []
        for warning in warnings:
            if not isinstance(warning, dict):
                continue
            code = warning.get("code")
            if isinstance(code, str) and code:
                codes.append(code)
        return codes

    def retrieval_trace(
        self,
        warning_counts: dict[str, int],
        affected_candidate_ids: list[str],
    ) -> dict[str, Any] | None:
        if not warning_counts:
            return None
        return {
            "stage": "parser_quality",
            "status": "warnings",
            "warning_counts": dict(sorted(warning_counts.items())),
            "affected_candidate_ids": affected_candidate_ids,
        }

    def _has_reference(
        self,
        text: str,
        metadata: dict[str, Any] | None,
        profile: MetadataQualityProfile,
    ) -> bool:
        if self._metadata_references(metadata):
            return True
        if CHAPTER_VERSE_PATTERN.search(text) or BOOK_HADITH_PATTERN.search(text):
            return True

        for pattern in profile.reference_patterns:
            try:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    return True
            except re.error:
                continue
        return False

    def _metadata_references(self, metadata: dict[str, Any] | None) -> list[str]:
        if not isinstance(metadata, dict):
            return []
        reference_metadata = metadata.get("reference_metadata")
        if not isinstance(reference_metadata, dict):
            return []
        references = reference_metadata.get("references")
        if not isinstance(references, list):
            return []
        return [reference for reference in references if isinstance(reference, str) and reference]

    def _requires_document_arabic(
        self,
        language: str,
        profile: MetadataQualityProfile,
    ) -> bool:
        normalized_language = str(language or "").strip().casefold()
        return normalized_language in {"arabic", "quran"} or "arabic" in profile.expected_scripts

    @staticmethod
    def merge_parser_warnings(
        metadata: dict[str, Any],
        warnings: list[dict[str, Any]],
    ) -> None:
        if not warnings:
            return

        extraction_quality = metadata.get("extraction_quality")
        if isinstance(extraction_quality, dict):
            extraction_quality = dict(extraction_quality)
        else:
            extraction_quality = {}

        existing = extraction_quality.get("parser_warnings")
        parser_warnings = list(existing) if isinstance(existing, list) else []
        seen = {
            json.dumps(warning, sort_keys=True, default=str)
            for warning in parser_warnings
            if isinstance(warning, dict)
        }
        for warning in warnings:
            key = json.dumps(warning, sort_keys=True, default=str)
            if key in seen:
                continue
            parser_warnings.append(dict(warning))
            seen.add(key)

        extraction_quality["parser_warnings"] = parser_warnings
        metadata["extraction_quality"] = extraction_quality


def _dict_value(value: dict[str, Any], key: str) -> dict[str, Any] | None:
    candidate = value.get(key)
    return candidate if isinstance(candidate, dict) else None


def _string_value(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
