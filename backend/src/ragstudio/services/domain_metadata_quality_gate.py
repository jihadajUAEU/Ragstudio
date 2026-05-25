from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.arabic_text import arabic_tokens
from ragstudio.services.parser_normalization import ExpectedContentProfile
from ragstudio.services.parser_quality_intelligent_gate import ParserQualityIntelligentGate
from ragstudio.services.parser_warning_utils import (
    dedupe_parser_warnings,
    is_counted_parser_warning,
)
from ragstudio.services.parser_warning_utils import (
    merge_parser_warnings as _shared_merge_parser_warnings,
)
from ragstudio.services.quality_repair_service import QualityRepairPass
from ragstudio.services.reference_metadata import ReferenceSemantics
from ragstudio.services.reference_unit_assembler import provenance_only_quality_policy
from ragstudio.services.script_detection import SCRIPT_PATTERNS

logger = logging.getLogger(__name__)
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
    required_scripts: frozenset[str]
    optional_scripts: frozenset[str]
    required_scripts_by_unit_role: dict[str, frozenset[str]]
    optional_scripts_by_unit_role: dict[str, frozenset[str]]
    reference_patterns: tuple[str, ...]
    parser_strictness: str
    preserve_parallel_text: bool
    reference_unit: str | None
    reference_type: str | None
    equation_blocks_allowed: bool
    structured_references: bool
    require_resolved_reference_unit: bool
    missing_required_script_action: str
    missing_optional_script_action: str
    materialization_policy: str


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
        quality_policy = _dict_value(custom_json, "quality_policy") or {}
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
        expected_scripts = frozenset(
            script for script in expected_profile.expected_scripts if script in SCRIPT_PATTERNS
        )
        required_scripts = _script_policy_set(quality_policy.get("required_scripts"))
        optional_scripts = _script_policy_set(quality_policy.get("optional_scripts"))
        required_scripts_by_unit_role = _script_policy_map(
            quality_policy.get("required_scripts_by_unit_role")
        )
        optional_scripts_by_unit_role = _script_policy_map(
            quality_policy.get("optional_scripts_by_unit_role")
        )
        required_scripts_configured = isinstance(quality_policy.get("required_scripts"), list)
        if not required_scripts_configured:
            required_scripts = frozenset()
        all_policy_scripts = (
            required_scripts
            | optional_scripts
            | _script_map_values(required_scripts_by_unit_role)
            | _script_map_values(optional_scripts_by_unit_role)
        )
        observed_policy_scripts = all_policy_scripts or expected_scripts
        return MetadataQualityProfile(
            domain=str(domain_metadata.domain or "generic").strip().casefold(),
            expected_scripts=frozenset(sorted(observed_policy_scripts)),
            required_scripts=frozenset(sorted(required_scripts)),
            optional_scripts=frozenset(sorted(optional_scripts)),
            required_scripts_by_unit_role=required_scripts_by_unit_role,
            optional_scripts_by_unit_role=optional_scripts_by_unit_role,
            reference_patterns=tuple(reference_patterns),
            parser_strictness=expected_profile.parser_strictness,
            preserve_parallel_text=preserve_parallel_text,
            reference_unit=reference_unit,
            reference_type=reference_type,
            equation_blocks_allowed=expected_profile.allows_equations_as_content(),
            structured_references=semantics.profile_name != "generic",
            require_resolved_reference_unit=_reference_unit_resolution_required(custom_json),
            missing_required_script_action=_quality_action(
                quality_policy.get("missing_required_script_action"),
                default="warn",
            ),
            missing_optional_script_action=_quality_action(
                quality_policy.get("missing_optional_script_action"),
                default="no_warning",
            ),
            materialization_policy=_materialization_policy(
                quality_policy.get("materialization_policy")
            ),
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
        unit_role = self._unit_role({}, metadata)
        required_scripts = self._scripts_for_unit_role(
            profile.required_scripts,
            profile.required_scripts_by_unit_role,
            unit_role,
        )
        optional_scripts = self._scripts_for_unit_role(
            profile.optional_scripts,
            profile.optional_scripts_by_unit_role,
            unit_role,
        )
        if not required_scripts and not optional_scripts:
            return []
        if not self._has_reference(text, metadata, profile, domain_metadata):
            return []

        warnings: list[dict[str, Any]] = []
        for script in sorted(required_scripts):
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
        if profile.missing_optional_script_action != "no_warning":
            for script in sorted(optional_scripts):
                pattern = SCRIPT_PATTERNS.get(script)
                if pattern is None or pattern.search(text):
                    continue
                script_label = script.capitalize()
                severity = profile.missing_optional_script_action
                warnings.append(
                    {
                        "code": "reference_unit_missing_optional_script",
                        "message": (
                            "Reference-bearing chunk can include optional "
                            f"{script_label} script, but no {script_label} letters were detected."
                        ),
                        "expected_script": script,
                        "script_requirement": "optional",
                        "action": self._optional_script_action([script], profile),
                        "severity": severity,
                        "suppressed_from_counts": severity == "info",
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

        profile = self.profile_for(domain_metadata, expected_profile=expected_profile)

        self._apply_intelligent_parser_gate(chunks, domain_metadata=domain_metadata)
        repair_pass = QualityRepairPass()
        pre_quality_repair = repair_pass.apply_pre_quality_repairs(
            chunks,
            profile=profile,
        )
        text = "\n".join(chunk.text for chunk in chunks)
        tokens = arabic_tokens(text)
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
        post_quality_repair = repair_pass.apply_post_quality_repairs(chunks)
        if post_quality_repair["targeted_vision_recovery_requests"]:
            index_quality_report = self.index_quality_report_from_chunks(chunks)
        # Modal-aware validation: verify structure integrity per modality.
        modal_warnings = self._validate_modal_chunks(chunks)
        self._apply_parser_quality_action_policy(chunks)
        quality_summary = self.parser_quality_summary(chunks)
        status = "passed_with_warnings" if quality_summary["warning_counts"] else "passed"
        quality_repair = {
            "layer": "repair_and_quality",
            **pre_quality_repair,
            **post_quality_repair,
        }

        return {
            "status": status,
            "chunk_count": len(chunks),
            "arabic_token_count": len(tokens),
            "quality_profile": {
                "domain": profile.domain,
                "expected_scripts": sorted(profile.expected_scripts),
                "required_scripts": sorted(profile.required_scripts),
                "optional_scripts": sorted(profile.optional_scripts),
                "preserve_parallel_text": profile.preserve_parallel_text,
                "reference_unit": profile.reference_unit,
                "reference_type": profile.reference_type,
            },
            "parser_quality": quality_summary,
            "index_quality_report": index_quality_report,
            "modal_validation": modal_warnings,
            "quality_repair": quality_repair,
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

    def quality_repair_report_from_chunks(self, chunks: list[Any]) -> dict[str, Any]:
        local_script_repairs = 0
        layout_noise_downgrades = 0
        targeted_requests: list[dict[str, Any]] = []
        targeted_status_counts: dict[str, int] = {}
        for chunk in chunks:
            metadata = self._chunk_metadata(chunk)
            repair = metadata.get("quality_repair")
            if not isinstance(repair, dict):
                continue
            local_repair = repair.get("local_script_repair")
            if isinstance(local_repair, dict) and local_repair.get("status") == "applied":
                local_script_repairs += 1
            layout_repair = repair.get("layout_noise_downgrade")
            if isinstance(layout_repair, dict):
                downgraded_count = layout_repair.get("downgraded_warning_count")
                if isinstance(downgraded_count, int):
                    layout_noise_downgrades += downgraded_count
            requests = repair.get("targeted_vision_recovery_requests")
            if isinstance(requests, list):
                for request in requests:
                    if not isinstance(request, dict):
                        continue
                    targeted_requests.append(request)
                    status = request.get("vision_recovery_status")
                    if isinstance(status, str) and status:
                        targeted_status_counts[status] = (
                            targeted_status_counts.get(status, 0) + 1
                        )
        return {
            "layer": "repair_and_quality",
            "local_script_repairs": local_script_repairs,
            "layout_noise_downgrades": layout_noise_downgrades,
            "targeted_vision_recovery_requests": len(targeted_requests),
            "targeted_vision_recovery_status_counts": dict(
                sorted(targeted_status_counts.items())
            ),
            "targeted_vision_recovery_samples": targeted_requests[:25],
        }

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
                "reference_units_missing_optional_script": 0,
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

    def _apply_intelligent_parser_gate(
        self,
        chunks: list[Any],
        *,
        domain_metadata: DomainMetadata | None,
    ) -> None:
        gate = ParserQualityIntelligentGate()
        for chunk in chunks:
            metadata = self._chunk_metadata(chunk)
            extraction_quality = metadata.get("extraction_quality")
            if not isinstance(extraction_quality, dict):
                extraction_quality = getattr(chunk, "extraction_quality", None)
            if not isinstance(extraction_quality, dict):
                continue
            warnings = extraction_quality.get("parser_warnings")
            if not isinstance(warnings, list):
                continue
            classified = gate.classify_warnings(
                [warning for warning in warnings if isinstance(warning, dict)],
                domain_metadata=domain_metadata,
            )
            extraction_quality["parser_warnings"] = classified
            metadata["extraction_quality"] = extraction_quality
            if hasattr(chunk, "metadata") and isinstance(chunk.metadata, dict):
                chunk.metadata["extraction_quality"] = extraction_quality

    def _apply_parser_quality_action_policy(self, chunks: list[Any]) -> None:
        for chunk in chunks:
            blocking_warnings = [
                warning
                for warning in self.parser_warnings_for_chunk(chunk)
                if self._parser_warning_blocks_materialization(warning)
            ]
            if not blocking_warnings:
                continue
            metadata = self._chunk_metadata(chunk)
            existing = metadata.get("quality_action_policy")
            policy = dict(existing) if isinstance(existing, dict) else {}
            existing_flags = policy.get("quality_flags")
            flags = (
                [
                    str(flag)
                    for flag in existing_flags
                    if isinstance(flag, str) and flag
                ]
                if isinstance(existing_flags, list)
                else []
            )
            for warning in blocking_warnings:
                code = warning.get("code")
                if isinstance(code, str) and code:
                    flags.append(f"parser_quality_block:{code}")
            quality_flags = sorted(dict.fromkeys(flags))
            policy.update(
                {
                    "persist_chunk": policy.get("persist_chunk", True),
                    "index_vector": False,
                    "index_exact_arabic": False,
                    "project_graph": False,
                    "graph_confidence": "blocked",
                    "quality_flags": quality_flags,
                    "status": "parser_quality_blocked",
                    "action": "block_parser_quality_materialization",
                }
            )
            metadata["quality_action_policy"] = policy
            metadata["quality_flags"] = quality_flags
            if hasattr(chunk, "metadata") and isinstance(chunk.metadata, dict):
                chunk.metadata["quality_action_policy"] = policy
                chunk.metadata["quality_flags"] = quality_flags

    def _parser_warning_blocks_materialization(self, warning: dict[str, Any]) -> bool:
        severity = str(warning.get("severity") or "").strip().casefold()
        action = str(
            warning.get("quality_gate_action") or warning.get("action") or ""
        ).strip().casefold()
        reason = str(warning.get("quality_gate_reason") or "")
        return action == "block" or (
            severity == "block" and reason.startswith("layout_quality_policy.")
        )

    def parser_quality_summary(self, chunks: list[Any]) -> dict[str, Any]:
        warning_counts: dict[str, int] = {}
        affected_chunks = 0
        for chunk in chunks:
            codes = sorted(
                {
                    str(warning.get("code"))
                    for warning in self.parser_warnings_for_chunk(chunk)
                    if isinstance(warning.get("code"), str)
                    and is_counted_parser_warning(warning)
                }
            )
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
            raw_warnings = self.parser_warnings_for_chunk(chunk)
            warnings = dedupe_parser_warnings(raw_warnings)
            if not warnings:
                continue

            chunk_id = self._chunk_id(chunk)
            source_location = self._chunk_source_location(chunk)
            text_preview = self._chunk_text_preview(chunk)
            seen_codes_for_chunk: set[str] = set()
            seen_raw_codes_for_chunk: set[str] = set()
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
                        "raw_chunk_count": 0,
                        "raw_warning_count": 0,
                        "audit_row_count": 0,
                        "message": "",
                        "block_types": {},
                        "expected_scripts": {},
                        "actions": {},
                        "vision_recovery_statuses": {},
                        "pages": [],
                        "references": [],
                        "examples": [],
                    },
                )
                group["raw_warning_count"] += 1
                group["audit_row_count"] += 1
                if code not in seen_raw_codes_for_chunk:
                    group["raw_chunk_count"] += 1
                    seen_raw_codes_for_chunk.add(code)
                counted = is_counted_parser_warning(warning)
                if counted:
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
                self._count_warning_value(
                    group["vision_recovery_statuses"],
                    warning.get("vision_recovery_status"),
                )
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
                            "vision_recovery_status": warning.get(
                                "vision_recovery_status"
                            ),
                            "counted": counted,
                            "message": message if isinstance(message, str) else None,
                            "text_preview": text_preview,
                        }
                    )

        return {
            "version": 1,
            "sample_limit": sample_limit,
            "groups": sorted(
                groups.values(),
                key=lambda group: (
                    -int(group["chunk_count"]),
                    -int(group["raw_chunk_count"]),
                    str(group["code"]),
                ),
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
                if is_counted_parser_warning(warning)
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
        for warning in dedupe_parser_warnings(warnings):
            if not is_counted_parser_warning(warning):
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
                    unit_role=self._unit_role(unit, chunk.metadata),
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
        semantics = ReferenceSemantics.from_metadata(domain_metadata)
        canonical_reference = self._canonical_reference_unit_reference(metadata)
        if canonical_reference:
            return [
                {
                    "reference": canonical_reference,
                    "text": text,
                    "start": 0,
                    "end": len(text),
                }
            ]
        if (
            semantics.inline_reference_policy == "cross_reference_only"
            and semantics.primary_anchor_pattern
        ):
            anchor_units = self._primary_anchor_reference_units(text, semantics)
            if anchor_units:
                return anchor_units
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
        if (
            semantics.reference_capability == "verified"
            and semantics.has_primary_unit_anchor
        ):
            return self._contract_reference_units(text, semantics)

        if len(references) > 1:
            return []

        semantic_refs = (
            semantics.extract_chunk_references(text)
            if semantics.reference_capability == "verified"
            else []
        )
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

    def _primary_anchor_reference_units(
        self,
        text: str,
        semantics: ReferenceSemantics,
    ) -> list[dict[str, Any]]:
        pattern = semantics._primary_anchor_regex()
        if pattern is None:
            return []
        matches = list(pattern.finditer(text))
        if not matches:
            return []
        units: list[dict[str, Any]] = []
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            reference = semantics._match_to_reference(match).get("ref")
            if reference is None:
                continue
            units.append(
                {
                    "reference": str(reference),
                    "text": text[start:end].strip(),
                    "start": start,
                    "end": end,
                }
            )
        return units

    def _contract_reference_units(
        self,
        text: str,
        semantics: ReferenceSemantics,
    ) -> list[dict[str, Any]]:
        anchor_units = self._primary_anchor_reference_units(text, semantics)
        if anchor_units:
            return anchor_units

        references = semantics.extract_primary_anchor_references(text)
        if not references:
            return []

        split_units = semantics.split_primary_anchor_units(text)
        if split_units and len(split_units) == len(references):
            units: list[dict[str, Any]] = []
            cursor = 0
            for reference, unit_text in zip(references, split_units, strict=False):
                start = text.find(unit_text, cursor)
                if start < 0:
                    start = cursor
                    end = start + len(unit_text)
                else:
                    end = start + len(unit_text)
                    cursor = end
                units.append(
                    {
                        "reference": str(reference["ref"]),
                        "text": unit_text,
                        "start": start,
                        "end": min(end, len(text)),
                        "unit_role": semantics.chunk_unit,
                    }
                )
            return units

        if len(references) == 1:
            return [
                {
                    "reference": str(references[0]["ref"]),
                    "text": text,
                    "start": 0,
                    "end": len(text),
                    "unit_role": semantics.chunk_unit,
                }
            ]
        return []

    def _reference_record(
        self,
        *,
        reference: str,
        text: str,
        text_span: dict[str, int],
        source_location: dict[str, Any] | None,
        parser_warning_codes: list[str],
        profile: MetadataQualityProfile,
        unit_role: str | None = None,
    ) -> dict[str, Any]:
        required_scripts_set = self._scripts_for_unit_role(
            profile.required_scripts,
            profile.required_scripts_by_unit_role,
            unit_role,
        )
        optional_scripts_set = self._scripts_for_unit_role(
            profile.optional_scripts,
            profile.optional_scripts_by_unit_role,
            unit_role,
        )
        expected_scripts = sorted(required_scripts_set | optional_scripts_set)
        required_scripts = sorted(required_scripts_set)
        optional_scripts = sorted(optional_scripts_set)
        observed_scripts = [
            script for script in expected_scripts if SCRIPT_PATTERNS[script].search(text)
        ]
        observed_set = set(observed_scripts)
        missing_required_scripts = [
            script for script in required_scripts if script not in observed_set
        ]
        missing_optional_scripts = [
            script for script in optional_scripts if script not in observed_set
        ]
        actionable_optional_scripts = (
            missing_optional_scripts
            if profile.missing_optional_script_action != "no_warning"
            else []
        )
        flags = [
            f"missing_expected_script:{script}" for script in missing_required_scripts
        ]
        flags.extend(
            f"missing_optional_script:{script}" for script in actionable_optional_scripts
        )
        if missing_required_scripts:
            status = "missing_expected_script"
            action = self._missing_script_action(missing_required_scripts, profile)
        elif actionable_optional_scripts:
            status = "missing_optional_script"
            action = self._optional_script_action(actionable_optional_scripts, profile)
        else:
            status = "passed"
            action = "allow_materialization"
        materialization = self._reference_materialization_policy(
            status=status,
            flags=flags,
            missing_scripts=missing_required_scripts,
            action=action,
        )
        return {
            "reference": reference,
            "text_span": text_span,
            "source_location": dict(source_location or {}),
            "unit_role": unit_role,
            "arabic_token_count": len(arabic_tokens(text)),
            "latin_token_count": len(_latin_tokens(text)),
            "expected_scripts": expected_scripts,
            "observed_scripts": observed_scripts,
            "missing_scripts": missing_required_scripts,
            "missing_optional_scripts": missing_optional_scripts,
            "actionable_optional_scripts": actionable_optional_scripts,
            "parser_warning_codes": sorted(set(parser_warning_codes)),
            "status": status,
            "action": action,
            "optional_script_action": profile.missing_optional_script_action,
            "quality_flags": flags,
            "materialization": materialization,
        }

    def _unit_role(
        self,
        unit: dict[str, Any],
        metadata: dict[str, Any] | None,
    ) -> str | None:
        for key in ("unit_role", "role"):
            value = unit.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_role(value)
        if not isinstance(metadata, dict):
            return None
        for key in ("unit_role", "quality_unit_role", "role"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_role(value)
        canonical_unit = metadata.get("canonical_reference_unit")
        if isinstance(canonical_unit, dict):
            for key in ("unit_role", "role", "unit"):
                value = canonical_unit.get(key)
                if isinstance(value, str) and value.strip():
                    return _normalize_role(value)
        return None

    def _scripts_for_unit_role(
        self,
        base_scripts: frozenset[str],
        role_scripts: dict[str, frozenset[str]],
        unit_role: str | None,
    ) -> frozenset[str]:
        scripts = set(base_scripts)
        for fallback_role in ("*", "all", "default", "reference_unit"):
            scripts.update(role_scripts.get(fallback_role, frozenset()))
        if unit_role:
            scripts.update(role_scripts.get(unit_role, frozenset()))
        return frozenset(scripts)

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

    def _missing_script_action(
        self,
        missing_scripts: list[str],
        profile: MetadataQualityProfile,
    ) -> str:
        if not missing_scripts:
            return "allow_materialization"
        if profile.materialization_policy in {
            "allow",
            "allow_if_required_scripts_present",
            "warn_if_required_scripts_missing",
        }:
            return "warn_reference_quality"
        if profile.missing_required_script_action == "block":
            return "block_reference_materialization"
        if (
            profile.preserve_parallel_text
            and profile.materialization_policy != "allow_if_required_scripts_present"
        ):
            return "block_reference_materialization"
        return "warn_reference_quality"

    def _optional_script_action(
        self,
        missing_scripts: list[str],
        profile: MetadataQualityProfile,
    ) -> str:
        if not missing_scripts or profile.missing_optional_script_action == "no_warning":
            return "allow_materialization"
        if profile.missing_optional_script_action == "block":
            return "block_reference_materialization"
        if profile.missing_optional_script_action == "info":
            return "info_reference_quality"
        return "warn_reference_quality"

    def _quality_action_policy(self, records: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not records:
            return None
        policies: list[dict[str, Any]] = []
        for record in records:
            materialization = record.get("materialization")
            if isinstance(materialization, dict):
                policies.append(materialization)
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
                            "repair": record.get("repair"),
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
            elif status == "missing_optional_script":
                severity = self._optional_warning_severity(record)
                for script in record.get("actionable_optional_scripts", []):
                    if not isinstance(script, str):
                        continue
                    warnings.append(
                        {
                            "code": "reference_unit_missing_optional_script",
                            "message": (
                                "Reference unit can include optional "
                                f"{script.capitalize()} script, but no "
                                f"{script.capitalize()} letters were detected."
                            ),
                            "reference": record.get("reference"),
                            "expected_script": script,
                            "script_requirement": "optional",
                            "source_location": record.get("source_location"),
                            "action": record.get("action"),
                            "severity": severity,
                            "suppressed_from_counts": severity == "info",
                        }
                    )
        return warnings

    def _optional_warning_severity(self, record: dict[str, Any]) -> str:
        action = record.get("optional_script_action")
        if action in {"info", "warn", "block"}:
            return str(action)
        materialization = record.get("materialization")
        if isinstance(materialization, dict) and not materialization.get("index_vector", True):
            return "block"
        return "warn"

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
        optional_missing_count = sum(
            1
            for record in reference_records
            if record.get("status") == "missing_optional_script"
        )
        passed_count = sum(1 for record in reference_records if record.get("status") == "passed")
        total = len(reference_records)
        blocked_count = sum(
            1
            for record in [*reference_records, *unresolved_records]
            if not record.get("materialization", {}).get("index_vector", True)
        )
        if unresolved_records or missing_count or optional_missing_count:
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
                "reference_units_missing_optional_script": optional_missing_count,
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
                "unit_role",
                "arabic_token_count",
                "latin_token_count",
                "expected_scripts",
                "observed_scripts",
                "missing_scripts",
                "missing_optional_scripts",
                "actionable_optional_scripts",
                "parser_warning_codes",
                "status",
                "action",
                "optional_script_action",
                "quality_flags",
                "materialization",
                "unresolved_reason",
                "chunk_index",
                "repair",
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
        return bool(
            profile.structured_references
            and profile.reference_unit
            and profile.require_resolved_reference_unit
        )

    def _is_provenance_only_chunk(self, chunk: AdapterChunk) -> bool:
        if chunk.content_type == "reference_provenance":
            return True
        parser_metadata = chunk.metadata.get("parser_metadata")
        return isinstance(parser_metadata, dict) and bool(parser_metadata.get("provenance_only"))

    def _requires_reference_quality(self, profile: MetadataQualityProfile) -> bool:
        has_optional_policy = profile.missing_optional_script_action != "no_warning" and bool(
            profile.optional_scripts or profile.optional_scripts_by_unit_role
        )
        return bool(
            profile.structured_references
            and profile.reference_unit
            and (
                profile.required_scripts
                or profile.required_scripts_by_unit_role
                or has_optional_policy
            )
        )

    def _has_reference(
        self,
        text: str,
        metadata: dict[str, Any] | None,
        profile: MetadataQualityProfile,
        domain_metadata: DomainMetadata | None,
    ) -> bool:
        if self._metadata_references(metadata):
            return True
        semantics = ReferenceSemantics.from_metadata(domain_metadata or DomainMetadata())
        if (
            semantics.reference_capability == "verified"
            and semantics.has_primary_unit_anchor
        ):
            return bool(semantics.extract_primary_anchor_references(text))

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

    def _canonical_reference_unit_reference(self, metadata: dict[str, Any] | None) -> str | None:
        if not isinstance(metadata, dict):
            return None
        canonical_unit = metadata.get("canonical_reference_unit")
        if not isinstance(canonical_unit, dict):
            return None
        if canonical_unit.get("answerable") is False:
            return None
        reference = canonical_unit.get("reference")
        if isinstance(reference, str) and reference.strip():
            return reference.strip()
        return None

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
        del language
        return "arabic" in profile.required_scripts or any(
            "arabic" in scripts for scripts in profile.required_scripts_by_unit_role.values()
        )

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

        _shared_merge_parser_warnings(extraction_quality, warnings)
        metadata["extraction_quality"] = extraction_quality

    def _validate_modal_chunks(
        self, chunks: list[AdapterChunk]
    ) -> list[dict[str, Any]]:
        """Validate modality-specific structural integrity."""
        warnings: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            chunk_warnings: list[dict[str, Any]] = []
            modality = chunk.metadata.get("modality", "text")
            if modality == "table":
                structured = chunk.metadata.get("structured_data", {})
                if not structured.get("markdown") and not structured.get("raw_body"):
                    chunk_warnings.append(
                        {
                            "chunk_index": index,
                            "modality": "table",
                            "code": "table_missing_structure",
                            "message": "Table chunk has no structured body data.",
                            "source": "modal_validation",
                            "severity": "block",
                            "quality_gate_action": "block",
                            "quality_gate_reason": "modal_validation.table_missing_structure",
                            "suppressed_from_counts": False,
                        }
                    )
            elif modality == "image":
                structured = chunk.metadata.get("structured_data", {})
                caption = structured.get("caption", [])
                if not caption and not chunk.text.strip():
                    chunk_warnings.append(
                        {
                            "chunk_index": index,
                            "modality": "image",
                            "code": "image_missing_description",
                            "message": "Image chunk has no caption or description.",
                            "source": "modal_validation",
                            "severity": "block",
                            "quality_gate_action": "block",
                            "quality_gate_reason": "modal_validation.image_missing_description",
                            "suppressed_from_counts": False,
                        }
                    )
            elif modality == "equation":
                structured = chunk.metadata.get("structured_data", {})
                if not structured.get("latex"):
                    chunk_warnings.append(
                        {
                            "chunk_index": index,
                            "modality": "equation",
                            "code": "equation_missing_latex",
                            "message": "Equation chunk has no LaTeX content.",
                            "source": "modal_validation",
                            "severity": "block",
                            "quality_gate_action": "block",
                            "quality_gate_reason": "modal_validation.equation_missing_latex",
                            "suppressed_from_counts": False,
                        }
                    )
            if chunk_warnings:
                self.merge_parser_warnings(chunk.metadata, chunk_warnings)
                warnings.extend(chunk_warnings)

        if warnings:
            logger.info(
                "Modal validation: %d warning(s) across %d chunks",
                len(warnings), len(chunks),
            )
        return warnings


def _dict_value(value: dict[str, Any], key: str) -> dict[str, Any] | None:
    candidate = value.get(key)
    return candidate if isinstance(candidate, dict) else None


def _script_policy_set(value: Any) -> frozenset[str]:
    if not isinstance(value, list | tuple | set | frozenset):
        return frozenset()
    return frozenset(
        str(item).strip().casefold()
        for item in value
        if isinstance(item, str) and str(item).strip().casefold() in SCRIPT_PATTERNS
    )


def _script_policy_map(value: Any) -> dict[str, frozenset[str]]:
    if not isinstance(value, dict):
        return {}
    mapped: dict[str, frozenset[str]] = {}
    for role, scripts in value.items():
        if not isinstance(role, str):
            continue
        clean_scripts = _script_policy_set(scripts)
        if clean_scripts:
            mapped[_normalize_role(role)] = clean_scripts
    return mapped


def _script_map_values(value: dict[str, frozenset[str]]) -> frozenset[str]:
    scripts: set[str] = set()
    for items in value.values():
        scripts.update(items)
    return frozenset(scripts)


def _normalize_role(value: str) -> str:
    return re.sub(r"[\s-]+", "_", value.strip().casefold())


def _quality_action(value: Any, *, default: str) -> str:
    if value in {"no_warning", "info", "warn", "block"}:
        return str(value)
    return default


def _materialization_policy(value: Any) -> str:
    if value in {
        "allow",
        "allow_if_required_scripts_present",
        "warn_if_required_scripts_missing",
        "block_if_required_scripts_missing",
    }:
        return str(value)
    return "block_if_required_scripts_missing"


def _reference_unit_resolution_required(custom_json: dict[str, Any]) -> bool:
    reference_contract = custom_json.get("reference_contract")
    if isinstance(reference_contract, dict) and reference_contract.get("verified") is False:
        return False
    validation = custom_json.get("reference_contract_validation")
    if isinstance(validation, dict) and validation.get("status") == "unverified":
        return False
    if custom_json.get("contract_status") == "metadata_only":
        return False
    return True


def _string_value(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _latin_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]+", text)
