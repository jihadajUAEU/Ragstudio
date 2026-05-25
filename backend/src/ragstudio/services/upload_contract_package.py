from __future__ import annotations

import copy
import hashlib
from typing import Any

from ragstudio.schemas.parsing import AnalysisBinding, ContractStateSummary, DomainMetadata


def build_analysis_binding(*, filename: str, content: bytes) -> AnalysisBinding:
    return AnalysisBinding(
        filename=filename,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def assert_analysis_binding_matches(
    binding: AnalysisBinding | None,
    *,
    filename: str,
    content: bytes,
) -> None:
    if binding is None:
        return
    actual = build_analysis_binding(filename=filename, content=content)
    if binding.size_bytes != actual.size_bytes or binding.sha256 != actual.sha256:
        raise ValueError(
            "Vision analysis does not match the uploaded file. "
            "Run Analyze with Vision again."
        )


def normalize_upload_ready_domain_metadata(
    metadata: DomainMetadata,
) -> tuple[DomainMetadata, ContractStateSummary]:
    custom_json = (
        copy.deepcopy(metadata.custom_json)
        if isinstance(metadata.custom_json, dict)
        else {}
    )
    state = derive_contract_state(custom_json)
    if state.state != "verified" and _has_reference_signal(custom_json):
        _demote_reference_unit_chunking(custom_json)
        reference_resolution = _dict_value(custom_json.get("reference_resolution"))
        reference_resolution["enabled"] = False
        reference_resolution["build_canonical_units"] = False
        custom_json["reference_resolution"] = reference_resolution
        state = derive_contract_state(custom_json)
    return metadata.model_copy(update={"custom_json": custom_json}, deep=True), state


def derive_contract_state(custom_json: dict[str, Any]) -> ContractStateSummary:
    validation = _dict_value(custom_json.get("reference_contract_validation"))
    execution = _dict_value(custom_json.get("reference_contract_execution"))
    reference_resolution = _dict_value(custom_json.get("reference_resolution"))
    reference_schema = _dict_value(custom_json.get("reference_schema"))
    validation_status = _normalized_status(validation.get("status"))
    execution_status = _normalized_status(execution.get("status"))
    canonical_units = (
        reference_resolution.get("enabled") is True
        and reference_resolution.get("build_canonical_units") is True
    )
    identity_fields = _identity_fields(reference_schema)
    matched_units = _int_value(validation.get("matched_units"))
    if matched_units is None:
        matched_units = _int_value(execution.get("matched_units"))
    selected_strategy = _str_value(validation.get("selected_strategy"))
    if selected_strategy is None:
        selected_strategy = _str_value(execution.get("selected_strategy"))

    verified_status = validation_status == "verified" or (
        validation_status is None and execution_status == "verified"
    )
    if verified_status and canonical_units and identity_fields:
        return ContractStateSummary(
            state="verified",
            canonical_units=True,
            reason="Executable reference contract verified on sampled pages.",
            matched_units=matched_units,
            selected_strategy=selected_strategy,
            identity_fields=identity_fields,
        )
    if _has_reference_signal(custom_json):
        return ContractStateSummary(
            state="metadata_only",
            canonical_units=False,
            reason=(
                "Reference observations are metadata hints because no executable "
                "canonical-unit contract is verified."
            ),
            matched_units=matched_units,
            selected_strategy=selected_strategy,
            identity_fields=identity_fields,
        )
    return ContractStateSummary(
        state="generic",
        canonical_units=False,
        reason="No reference contract was detected.",
    )


def _has_reference_signal(custom_json: dict[str, Any]) -> bool:
    return any(
        isinstance(custom_json.get(key), expected_type)
        for key, expected_type in (
            ("reference_schema", dict),
            ("domain_structure", dict),
            ("reference_contract_execution", dict),
            ("reference_contract_validation", dict),
            ("reference_contract_candidates", list),
        )
    )


def _demote_reference_unit_chunking(custom_json: dict[str, Any]) -> None:
    chunking = custom_json.get("chunking")
    if not isinstance(chunking, dict):
        return
    demoted = dict(chunking)
    demoted.pop("unit", None)
    if demoted:
        custom_json["chunking"] = demoted
    else:
        custom_json.pop("chunking", None)


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _identity_fields(reference_schema: dict[str, Any]) -> list[str]:
    for key in ("identity_fields", "required_fields"):
        values = reference_schema.get(key)
        if isinstance(values, list):
            return [item.strip() for item in values if isinstance(item, str) and item.strip()]
    fields = reference_schema.get("fields")
    if isinstance(fields, dict):
        return [key.strip() for key in fields if isinstance(key, str) and key.strip()]
    return []


def _int_value(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _normalized_status(value: Any) -> str | None:
    return value.strip().casefold() if isinstance(value, str) and value.strip() else None


def _str_value(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
