from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.arabic_text import arabic_tokens
from ragstudio.services.parser_normalization import ExpectedContentProfile
from ragstudio.services.reference_metadata import ReferenceSemantics
from ragstudio.services.reference_unit_assembler import provenance_only_quality_policy

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
QUALITY_REPORT_VERSION = 1


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
    structured_references: bool


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
        semantics = ReferenceSemantics.from_metadata(domain_metadata)
        preserve_parallel_text = bool(chunking.get("preserve_parallel_text"))
        reference_unit = _string_value(chunking.get("unit")) or (
            semantics.chunk_unit if semantics.profile_name != "generic" else None
        )
        reference_type = _string_value(reference_schema.get("type")) or _string_value(
            domain_metadata.citation_style
        ) or semantics.reference_type
        reference_patterns = list(expected_profile.reference_patterns)
        if semantics.reference_pattern and semantics.reference_pattern not in reference_patterns:
            reference_patterns.append(semantics.reference_pattern)
        return MetadataQualityProfile(
            domain=str(domain_metadata.domain or "generic").strip().casefold(),
            expected_scripts=frozenset(
                script
                for script in expected_profile.expected_scripts
                if script in SCRIPT_PATTERNS
            ),
            reference_patterns=tuple(reference_patterns),
            parser_strictness=expected_profile.parser_strictness,
            preserve_parallel_text=preserve_parallel_text,
            reference_unit=reference_unit,
            reference_type=reference_type,
            equation_blocks_allowed=expected_profile.allows_equations_as_content(),
            structured_references=semantics.profile_name != "generic",
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

        if self._requires_reference_quality(profile):
            index_quality_report = self.annotate_reference_quality(
                chunks,
                domain_metadata=domain_metadata,
                expected_profile=expected_profile,
            )
        else:
            for chunk in chunks:
                self.annotate_chunk(
                    chunk,
                    domain_metadata=domain_metadata,
                    expected_profile=expected_profile,
                )
            index_quality_report = self.index_quality_report_from_chunks(chunks)
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
            "index_quality_report": index_quality_report,
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

    def annotate_reference_quality(
        self,
        chunks: list[AdapterChunk],
        *,
        domain_metadata: DomainMetadata | None = None,
        expected_profile: ExpectedContentProfile | None = None,
    ) -> dict[str, Any]:
        profile = self.profile_for(domain_metadata, expected_profile=expected_profile)
        all_records: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            if self._is_provenance_only_chunk(chunk):
                policy = provenance_only_quality_policy()
                chunk.metadata["quality_action_policy"] = policy
                chunk.metadata["quality_flags"] = policy["quality_flags"]
                continue
            records = self._reference_quality_records_for_chunk(
                chunk,
                chunk_index=index,
                profile=profile,
                domain_metadata=domain_metadata or DomainMetadata(),
            )
            all_records.extend(records)
            if records:
                quality = dict(chunk.metadata.get("quality") or {})
                quality["by_reference"] = records
                chunk.metadata["quality"] = quality
            policy = self._quality_action_policy(records)
            if policy:
                chunk.metadata["quality_action_policy"] = policy
                chunk.metadata["quality_flags"] = policy["quality_flags"]
            self.merge_parser_warnings(
                chunk.metadata,
                self._parser_warnings_from_reference_records(records),
            )

        report = self._index_quality_report(
            all_records,
            profile=profile,
        )
        for chunk in chunks:
            chunk.metadata["index_quality_report_version"] = QUALITY_REPORT_VERSION
        return report

    def index_quality_report_from_chunks(
        self,
        chunks: list[Any],
        *,
        document_id: str | None = None,
        runtime_profile_id: str | None = None,
    ) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        domain_profile = "generic"
        for chunk in chunks:
            metadata = self._chunk_metadata(chunk)
            if document_id is None:
                candidate_document_id = getattr(chunk, "document_id", None) or metadata.get(
                    "document_id"
                )
                if isinstance(candidate_document_id, str) and candidate_document_id:
                    document_id = candidate_document_id
            if runtime_profile_id is None:
                candidate_profile_id = getattr(chunk, "runtime_profile_id", None)
                if isinstance(candidate_profile_id, str) and candidate_profile_id:
                    runtime_profile_id = candidate_profile_id
            domain_metadata = metadata.get("domain_metadata")
            if isinstance(domain_metadata, dict):
                domain_profile = str(domain_metadata.get("domain") or domain_profile)
            quality = metadata.get("quality")
            if not isinstance(quality, dict):
                continue
            by_reference = quality.get("by_reference")
            if not isinstance(by_reference, list):
                continue
            records.extend(item for item in by_reference if isinstance(item, dict))

        if not records:
            return self.unknown_quality_report(
                document_id=document_id,
                runtime_profile_id=runtime_profile_id,
                domain_profile=domain_profile,
            )

        report = self._index_quality_report(
            records,
            profile=None,
            domain_profile=domain_profile,
        )
        if document_id:
            report["document_id"] = document_id
        if runtime_profile_id:
            report["runtime_profile_id"] = runtime_profile_id
        return report

    def unknown_quality_report(
        self,
        *,
        document_id: str | None = None,
        runtime_profile_id: str | None = None,
        domain_profile: str = "unknown",
    ) -> dict[str, Any]:
        report: dict[str, Any] = {
            "quality_report_version": None,
            "status": "quality_unknown",
            "domain_profile": domain_profile,
            "references": [],
            "summary": {
                "reference_unit_count": 0,
                "reference_units_with_expected_script": 0,
                "reference_units_missing_expected_script": 0,
                "reference_script_coverage_ratio": None,
                "reference_unit_unresolved_count": 0,
                "quality_unknown_document_count": 1,
                "materialization_blocked_reference_count": 0,
            },
        }
        if document_id:
            report["document_id"] = document_id
        if runtime_profile_id:
            report["runtime_profile_id"] = runtime_profile_id
        return report

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

    def parser_quality_details(
        self,
        chunks: list[Any],
        *,
        sample_limit: int = 5,
        value_limit: int = 20,
    ) -> dict[str, Any]:
        groups: dict[str, dict[str, Any]] = {}
        for chunk in chunks:
            warnings = self.parser_warnings_for_chunk(chunk)
            if not warnings:
                continue

            chunk_id = self._chunk_id(chunk)
            source_location = self._chunk_source_location(chunk)
            text_preview = self._chunk_text_preview(chunk)
            seen_codes_for_chunk: set[str] = set()
            for warning in warnings:
                code = warning.get("code")
                if not isinstance(code, str) or not code:
                    continue

                group = groups.setdefault(
                    code,
                    {
                        "code": code,
                        "chunk_count": 0,
                        "warning_count": 0,
                        "message": "",
                        "block_types": {},
                        "expected_scripts": {},
                        "actions": {},
                        "pages": [],
                        "references": [],
                        "examples": [],
                    },
                )
                group["warning_count"] += 1
                if code not in seen_codes_for_chunk:
                    group["chunk_count"] += 1
                    seen_codes_for_chunk.add(code)

                message = warning.get("message")
                if isinstance(message, str) and message and not group["message"]:
                    group["message"] = message

                self._count_warning_value(group["block_types"], warning.get("block_type"))
                self._count_warning_value(
                    group["expected_scripts"],
                    warning.get("expected_script"),
                )
                self._count_warning_value(group["actions"], warning.get("action"))
                self._append_limited_value(
                    group["pages"],
                    self._warning_page(warning, source_location),
                    value_limit,
                )
                self._append_limited_value(
                    group["references"],
                    self._warning_reference(warning, source_location),
                    value_limit,
                )

                examples = group["examples"]
                if len(examples) < sample_limit:
                    examples.append(
                        {
                            "chunk_id": chunk_id,
                            "page": self._warning_page(warning, source_location),
                            "reference": self._warning_reference(warning, source_location),
                            "block_type": warning.get("block_type"),
                            "expected_script": warning.get("expected_script"),
                            "action": warning.get("action"),
                            "message": message if isinstance(message, str) else None,
                            "text_preview": text_preview,
                        }
                    )

        return {
            "version": 1,
            "sample_limit": sample_limit,
            "groups": sorted(
                groups.values(),
                key=lambda group: (-int(group["chunk_count"]), str(group["code"])),
            ),
        }

    def parser_warnings_for_chunk(self, chunk: Any) -> list[dict[str, Any]]:
        extraction_quality = getattr(chunk, "extraction_quality", None)
        if not isinstance(extraction_quality, dict):
            metadata = getattr(chunk, "metadata", None)
            if isinstance(metadata, dict):
                extraction_quality = metadata.get("extraction_quality")
        if not isinstance(extraction_quality, dict):
            return []
        warnings = extraction_quality.get("parser_warnings")
        if not isinstance(warnings, list):
            return []
        return [warning for warning in warnings if isinstance(warning, dict)]

    def parser_warning_codes_for_chunk(self, chunk: Any) -> list[str]:
        return [
            code
            for code in (
                warning.get("code")
                for warning in self.parser_warnings_for_chunk(chunk)
            )
            if isinstance(code, str) and code
        ]

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

    def _chunk_id(self, chunk: Any) -> str | None:
        chunk_id = getattr(chunk, "id", None)
        return chunk_id if isinstance(chunk_id, str) else None

    def _chunk_source_location(self, chunk: Any) -> dict[str, Any]:
        source_location = getattr(chunk, "source_location", None)
        if isinstance(source_location, dict):
            return source_location
        metadata = getattr(chunk, "metadata", None)
        if isinstance(metadata, dict):
            source_location = metadata.get("source_location")
            if isinstance(source_location, dict):
                return source_location
        return {}

    def _chunk_text_preview(self, chunk: Any, limit: int = 240) -> str:
        text = getattr(chunk, "text", "")
        if not isinstance(text, str):
            return ""
        collapsed = " ".join(text.split())
        return collapsed[:limit]

    def _warning_page(
        self,
        warning: dict[str, Any],
        source_location: dict[str, Any],
    ) -> str | int | None:
        page = warning.get("page")
        if page is None:
            page = source_location.get("page")
        return page if isinstance(page, str | int) else None

    def _warning_reference(
        self,
        warning: dict[str, Any],
        source_location: dict[str, Any],
    ) -> str | None:
        reference = warning.get("reference")
        if reference is None:
            reference = source_location.get("reference")
        return reference if isinstance(reference, str) and reference else None

    def _count_warning_value(self, counter: dict[str, int], value: Any) -> None:
        if not isinstance(value, str) or not value:
            return
        counter[value] = counter.get(value, 0) + 1

    def _append_limited_value(self, values: list[Any], value: Any, limit: int) -> None:
        if value is None or value in values or len(values) >= limit:
            return
        values.append(value)

    def _reference_quality_records_for_chunk(
        self,
        chunk: AdapterChunk,
        *,
        chunk_index: int,
        profile: MetadataQualityProfile,
        domain_metadata: DomainMetadata,
    ) -> list[dict[str, Any]]:
        units = self._reference_text_units(
            chunk.text,
            chunk.metadata,
            domain_metadata,
            profile,
        )
        if not units:
            if not self._chunk_requires_reference_unit(chunk, profile):
                return []
            return [
                self._unresolved_reference_record(
                    chunk,
                    chunk_index=chunk_index,
                    profile=profile,
                    reason="reference_metadata_missing",
                )
            ]

        records: list[dict[str, Any]] = []
        for unit in units:
            reference = unit.get("reference")
            text = str(unit.get("text") or "")
            start = int(unit.get("start") or 0)
            end = int(unit.get("end") or len(text))
            if not isinstance(reference, str) or not reference:
                records.append(
                    self._unresolved_reference_record(
                        chunk,
                        chunk_index=chunk_index,
                        profile=profile,
                        reason="reference_unit_unresolved",
                    )
                )
                continue
            records.append(
                self._reference_record(
                    reference=reference,
                    text=text,
                    text_span={"start": start, "end": end},
                    source_location=chunk.source_location,
                    parser_warning_codes=self.parser_warning_codes_for_chunk(chunk),
                    profile=profile,
                )
            )
        return records

    def _reference_text_units(
        self,
        text: str,
        metadata: dict[str, Any] | None,
        domain_metadata: DomainMetadata,
        profile: MetadataQualityProfile,
    ) -> list[dict[str, Any]]:
        label_units = self._labelled_reference_units(text)
        if label_units:
            return label_units

        references = self._metadata_references(metadata)
        if len(references) == 1:
            return [
                {
                    "reference": references[0],
                    "text": text,
                    "start": 0,
                    "end": len(text),
                }
            ]
        if len(references) > 1:
            return []

        semantics = ReferenceSemantics.from_metadata(domain_metadata)
        semantic_refs = semantics.extract_chunk_references(text)
        if len(semantic_refs) == 1:
            return [
                {
                    "reference": str(semantic_refs[0]["ref"]),
                    "text": text,
                    "start": 0,
                    "end": len(text),
                }
            ]
        if profile.structured_references:
            return []
        return []

    def _labelled_reference_units(self, text: str) -> list[dict[str, Any]]:
        matches = list(CHAPTER_VERSE_PATTERN.finditer(text))
        if not matches:
            return []
        units: list[dict[str, Any]] = []
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            chapter = int(match.group("chapter"))
            verse = int(match.group("verse"))
            units.append(
                {
                    "reference": f"{chapter}:{verse}",
                    "text": text[start:end].strip(),
                    "start": start,
                    "end": end,
                }
            )
        return units

    def _reference_record(
        self,
        *,
        reference: str,
        text: str,
        text_span: dict[str, int],
        source_location: dict[str, Any] | None,
        parser_warning_codes: list[str],
        profile: MetadataQualityProfile,
    ) -> dict[str, Any]:
        expected_scripts = sorted(profile.expected_scripts)
        observed_scripts = [
            script for script in expected_scripts if SCRIPT_PATTERNS[script].search(text)
        ]
        missing_scripts = [
            script for script in expected_scripts if script not in set(observed_scripts)
        ]
        flags = [
            f"missing_expected_script:{script}" for script in missing_scripts
        ]
        status = "missing_expected_script" if missing_scripts else "passed"
        action = (
            "block_reference_materialization"
            if missing_scripts and profile.preserve_parallel_text
            else "warn_reference_quality"
            if missing_scripts
            else "allow_materialization"
        )
        materialization = self._reference_materialization_policy(
            status=status,
            flags=flags,
            missing_scripts=missing_scripts,
            action=action,
        )
        return {
            "reference": reference,
            "text_span": text_span,
            "source_location": dict(source_location or {}),
            "arabic_token_count": len(arabic_tokens(text)),
            "latin_token_count": len(_latin_tokens(text)),
            "expected_scripts": expected_scripts,
            "observed_scripts": observed_scripts,
            "missing_scripts": missing_scripts,
            "parser_warning_codes": sorted(set(parser_warning_codes)),
            "status": status,
            "action": action,
            "quality_flags": flags,
            "materialization": materialization,
        }

    def _unresolved_reference_record(
        self,
        chunk: AdapterChunk,
        *,
        chunk_index: int,
        profile: MetadataQualityProfile,
        reason: str,
    ) -> dict[str, Any]:
        flags = ["reference_unit_unresolved"]
        materialization = self._reference_materialization_policy(
            status="unresolved",
            flags=flags,
            missing_scripts=[],
            action="quarantine_reference_unit",
        )
        return {
            "reference": None,
            "text_span": {"start": 0, "end": len(chunk.text)},
            "source_location": dict(chunk.source_location or {}),
            "arabic_token_count": len(arabic_tokens(chunk.text)),
            "latin_token_count": len(_latin_tokens(chunk.text)),
            "expected_scripts": sorted(profile.expected_scripts),
            "observed_scripts": [
                script
                for script in sorted(profile.expected_scripts)
                if SCRIPT_PATTERNS[script].search(chunk.text)
            ],
            "missing_scripts": [],
            "parser_warning_codes": sorted(set(self.parser_warning_codes_for_chunk(chunk))),
            "status": "unresolved",
            "action": "quarantine_reference_unit",
            "quality_flags": flags,
            "materialization": materialization,
            "unresolved_reason": reason,
            "chunk_index": chunk_index,
        }

    def _reference_materialization_policy(
        self,
        *,
        status: str,
        flags: list[str],
        missing_scripts: list[str],
        action: str,
    ) -> dict[str, Any]:
        blocked = action in {"block_reference_materialization", "quarantine_reference_unit"}
        exact_arabic_blocked = blocked or "arabic" in missing_scripts
        return {
            "persist_chunk": True,
            "index_vector": not blocked,
            "index_exact_arabic": not exact_arabic_blocked,
            "project_graph": not blocked,
            "graph_confidence": "blocked" if blocked else "degraded" if flags else "high",
            "quality_flags": list(flags),
            "status": status,
            "action": action,
        }

    def _quality_action_policy(self, records: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not records:
            return None
        policies = [
            record.get("materialization")
            for record in records
            if isinstance(record.get("materialization"), dict)
        ]
        if not policies:
            return None
        flags = sorted(
            {
                str(flag)
                for policy in policies
                for flag in policy.get("quality_flags", [])
                if flag
            }
        )
        index_vector = all(bool(policy.get("index_vector", True)) for policy in policies)
        index_exact_arabic = all(
            bool(policy.get("index_exact_arabic", True)) for policy in policies
        )
        project_graph = all(bool(policy.get("project_graph", True)) for policy in policies)
        if not project_graph:
            graph_confidence = "blocked"
        elif flags:
            graph_confidence = "degraded"
        else:
            graph_confidence = "high"
        return {
            "persist_chunk": True,
            "index_vector": index_vector,
            "index_exact_arabic": index_exact_arabic,
            "project_graph": project_graph,
            "graph_confidence": graph_confidence,
            "quality_flags": flags,
        }

    def _parser_warnings_from_reference_records(
        self,
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        for record in records:
            status = record.get("status")
            if status == "missing_expected_script":
                for script in record.get("missing_scripts", []):
                    if not isinstance(script, str):
                        continue
                    warnings.append(
                        {
                            "code": "reference_unit_missing_expected_script",
                            "message": (
                                "Reference unit is expected to contain "
                                f"{script.capitalize()} script, but no "
                                f"{script.capitalize()} letters were detected."
                            ),
                            "reference": record.get("reference"),
                            "expected_script": script,
                            "source_location": record.get("source_location"),
                            "action": record.get("action"),
                        }
                    )
            elif status == "unresolved":
                warnings.append(
                    {
                        "code": "reference_unit_unresolved",
                        "message": (
                            "Structured metadata requires a resolvable reference unit, "
                            "but this chunk could not be tied to one reference."
                        ),
                        "source_location": record.get("source_location"),
                        "action": record.get("action"),
                    }
                )
        return warnings

    def _index_quality_report(
        self,
        records: list[dict[str, Any]],
        *,
        profile: MetadataQualityProfile | None,
        domain_profile: str | None = None,
    ) -> dict[str, Any]:
        reference_records = [
            self._public_reference_record(record)
            for record in records
            if record.get("reference") is not None
        ]
        unresolved_records = [
            self._public_reference_record(record)
            for record in records
            if record.get("reference") is None and record.get("status") == "unresolved"
        ]
        missing_count = sum(
            1
            for record in reference_records
            if record.get("status") == "missing_expected_script"
        )
        passed_count = sum(1 for record in reference_records if record.get("status") == "passed")
        total = len(reference_records)
        blocked_count = sum(
            1
            for record in [*reference_records, *unresolved_records]
            if not record.get("materialization", {}).get("index_vector", True)
        )
        if unresolved_records or missing_count:
            status = "ready_with_warnings"
        else:
            status = "passed"
        return {
            "quality_report_version": QUALITY_REPORT_VERSION,
            "status": status,
            "domain_profile": domain_profile
            or (profile.domain if profile is not None else "generic"),
            "references": reference_records,
            "unresolved": unresolved_records,
            "summary": {
                "reference_unit_count": total,
                "reference_units_with_expected_script": passed_count,
                "reference_units_missing_expected_script": missing_count,
                "reference_script_coverage_ratio": (
                    round(passed_count / total, 6) if total else None
                ),
                "reference_unit_unresolved_count": len(unresolved_records),
                "quality_unknown_document_count": 0,
                "materialization_blocked_reference_count": blocked_count,
            },
        }

    def _public_reference_record(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in record.items()
            if key
            in {
                "reference",
                "text_span",
                "source_location",
                "arabic_token_count",
                "latin_token_count",
                "expected_scripts",
                "observed_scripts",
                "missing_scripts",
                "parser_warning_codes",
                "status",
                "action",
                "quality_flags",
                "materialization",
                "unresolved_reason",
                "chunk_index",
            }
        }

    def _chunk_requires_reference_unit(
        self,
        chunk: AdapterChunk,
        profile: MetadataQualityProfile,
    ) -> bool:
        if not self._requires_reference_quality(profile):
            return False
        if self._is_provenance_only_chunk(chunk):
            return False
        parser_metadata = chunk.metadata.get("parser_metadata")
        if isinstance(parser_metadata, dict) and parser_metadata.get("parser_quality_only"):
            return True
        if not chunk.text.strip():
            return False
        return bool(profile.reference_unit in {"verse", "reference", "hadith", "section"})

    def _is_provenance_only_chunk(self, chunk: AdapterChunk) -> bool:
        if chunk.content_type == "reference_provenance":
            return True
        parser_metadata = chunk.metadata.get("parser_metadata")
        return isinstance(parser_metadata, dict) and bool(parser_metadata.get("provenance_only"))

    def _requires_reference_quality(self, profile: MetadataQualityProfile) -> bool:
        return bool(
            profile.structured_references
            and profile.reference_unit in {"verse", "reference", "hadith", "section"}
            and profile.expected_scripts
        )

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
        references: list[str] = []
        for key in ("reference_metadata", "relationship_metadata"):
            reference_metadata = metadata.get(key)
            if not isinstance(reference_metadata, dict):
                continue
            values = reference_metadata.get("references")
            if not isinstance(values, list):
                continue
            references.extend(
                reference for reference in values if isinstance(reference, str) and reference
            )
        return list(dict.fromkeys(references))

    def _chunk_metadata(self, chunk: Any) -> dict[str, Any]:
        metadata = getattr(chunk, "metadata", None)
        if isinstance(metadata, dict):
            return metadata
        metadata_json = getattr(chunk, "metadata_json", None)
        if isinstance(metadata_json, dict):
            return metadata_json
        return {}

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


def _latin_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]+", text)
