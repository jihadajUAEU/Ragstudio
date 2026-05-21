from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.script_detection import SCRIPT_PATTERNS

if TYPE_CHECKING:
    from ragstudio.services.domain_metadata_quality_gate import MetadataQualityProfile

PURE_LAYOUT_BLOCK_TYPES = {
    "header",
    "footer",
    "page_footer",
    "page_header",
    "page_footnote",
    "page_number",
    "aside_text",
}


class QualityRepairPass:
    """Local repair and recovery annotation between canonical assembly and quality gates."""

    def apply_pre_quality_repairs(
        self,
        chunks: list[AdapterChunk],
        *,
        profile: MetadataQualityProfile,
    ) -> dict[str, Any]:
        summary = {
            "local_script_repairs": 0,
            "layout_noise_downgrades": 0,
        }
        for chunk in chunks:
            if self._repair_missing_script_from_provenance(chunk, profile):
                summary["local_script_repairs"] += 1
            summary["layout_noise_downgrades"] += self._downgrade_pure_layout_noise(chunk)
        return summary

    def apply_post_quality_repairs(self, chunks: list[AdapterChunk]) -> dict[str, Any]:
        recovery_requests = 0
        for chunk in chunks:
            quality = chunk.metadata.get("quality")
            if not isinstance(quality, dict):
                continue
            records = quality.get("by_reference")
            if not isinstance(records, list):
                continue
            chunk_requests: list[dict[str, Any]] = []
            for record in records:
                if not isinstance(record, dict):
                    continue
                missing_scripts = [
                    script
                    for script in record.get("missing_scripts", [])
                    if isinstance(script, str) and script
                ]
                if not missing_scripts:
                    continue
                request = self._vision_recovery_request(record, missing_scripts)
                record["repair"] = {
                    "local_repair": "not_recovered",
                    "vision_recovery": request,
                }
                self._annotate_existing_missing_script_warnings(
                    chunk,
                    record=record,
                    repair=record["repair"],
                )
                chunk_requests.append(request)
                recovery_requests += 1
            if chunk_requests:
                repair = self._repair_metadata(chunk)
                repair["targeted_vision_recovery_requests"] = chunk_requests
        return {"targeted_vision_recovery_requests": recovery_requests}

    def _repair_missing_script_from_provenance(
        self,
        chunk: AdapterChunk,
        profile: MetadataQualityProfile,
    ) -> bool:
        required_scripts = sorted(profile.required_scripts)
        if not required_scripts:
            return False
        missing_scripts = [
            script
            for script in required_scripts
            if not self._contains_script(chunk.text, script)
        ]
        if not missing_scripts:
            return False

        candidates: list[str] = []
        for block in self._provenance_blocks(chunk):
            if str(block.get("role") or "") == "parser_warning":
                continue
            preview = block.get("text_preview")
            if not isinstance(preview, str) or not preview.strip():
                continue
            for script in missing_scripts:
                if self._contains_script(preview, script) and preview not in chunk.text:
                    candidates.append(preview.strip())
                    break
        if not candidates:
            return False

        repaired_text = "\n\n".join([chunk.text.strip(), *candidates]).strip()
        object.__setattr__(chunk, "text", repaired_text)
        repair = self._repair_metadata(chunk)
        repair["local_script_repair"] = {
            "status": "applied",
            "source": "same_chunk_provenance_blocks",
            "missing_scripts_before_repair": missing_scripts,
            "added_block_count": len(candidates),
        }
        return True

    def _downgrade_pure_layout_noise(self, chunk: AdapterChunk) -> int:
        extraction_quality = chunk.metadata.get("extraction_quality")
        if not isinstance(extraction_quality, dict):
            return 0
        warnings = extraction_quality.get("parser_warnings")
        if not isinstance(warnings, list):
            return 0

        downgraded = 0
        for warning in warnings:
            if not isinstance(warning, dict):
                continue
            if warning.get("code") != "disallowed_block_type_quarantined":
                continue
            block_type = str(warning.get("block_type") or "").strip().casefold()
            if block_type not in PURE_LAYOUT_BLOCK_TYPES:
                continue
            if self._warning_has_recoverable_text(warning):
                continue
            warning["severity"] = "info"
            warning["quality_gate_action"] = "provenance_only_layout_noise"
            warning["suppressed_from_counts"] = True
            warning["action"] = warning.get("action") or "provenance_only"
            downgraded += 1
        if downgraded:
            repair = self._repair_metadata(chunk)
            repair["layout_noise_downgrade"] = {
                "status": "applied",
                "downgraded_warning_count": downgraded,
                "pure_layout_block_types": sorted(PURE_LAYOUT_BLOCK_TYPES),
            }
        return downgraded

    def _vision_recovery_request(
        self,
        record: dict[str, Any],
        missing_scripts: list[str],
    ) -> dict[str, Any]:
        source_location = record.get("source_location")
        source_location = source_location if isinstance(source_location, dict) else {}
        return {
            "trigger": "missing_required_script",
            "scope": "reference_unit",
            "reference": record.get("reference"),
            "missing_scripts": missing_scripts,
            "page_start": source_location.get("page_start") or source_location.get("page"),
            "page_end": source_location.get("page_end") or source_location.get("page"),
            "failure_action": "warn",
        }

    def _annotate_existing_missing_script_warnings(
        self,
        chunk: AdapterChunk,
        *,
        record: dict[str, Any],
        repair: dict[str, Any],
    ) -> None:
        extraction_quality = chunk.metadata.get("extraction_quality")
        if not isinstance(extraction_quality, dict):
            return
        warnings = extraction_quality.get("parser_warnings")
        if not isinstance(warnings, list):
            return
        reference = record.get("reference")
        missing_scripts = set(record.get("missing_scripts") or [])
        for warning in warnings:
            if not isinstance(warning, dict):
                continue
            if warning.get("code") != "reference_unit_missing_expected_script":
                continue
            if reference and warning.get("reference") not in {None, reference}:
                continue
            expected_script = warning.get("expected_script")
            if missing_scripts and expected_script not in missing_scripts:
                continue
            warning["repair"] = repair
            warning["vision_recovery_required"] = True

    def _repair_metadata(self, chunk: AdapterChunk) -> dict[str, Any]:
        repair = chunk.metadata.get("quality_repair")
        if not isinstance(repair, dict):
            repair = {}
            chunk.metadata["quality_repair"] = repair
        repair.setdefault("layer", "repair_and_quality")
        return repair

    def _provenance_blocks(self, chunk: AdapterChunk) -> list[dict[str, Any]]:
        provenance = chunk.metadata.get("provenance")
        if not isinstance(provenance, dict):
            return []
        blocks = provenance.get("blocks")
        if not isinstance(blocks, list):
            return []
        return [block for block in blocks if isinstance(block, dict)]

    def _contains_script(self, text: str, script: str) -> bool:
        pattern = SCRIPT_PATTERNS.get(script)
        return bool(pattern is not None and pattern.search(text))

    def _warning_has_recoverable_text(self, warning: dict[str, Any]) -> bool:
        for key in ("text_preview", "recovered_text", "text"):
            value = warning.get(key)
            if isinstance(value, str) and value.strip():
                return True
        return False
