from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn, MinerUParseOptionsIn
from ragstudio.services.reference_contracts import (
    ExecutableReferenceContract,
    ReferenceAnchor,
    build_executable_reference_contract,
)


class DomainMetadataContractError(ValueError):
    """Raised when metadata describes reference chunking but is not executable."""


def compile_index_options(options: IndexDocumentIn) -> IndexDocumentIn:
    domain_metadata = compile_domain_metadata(options.domain_metadata)
    mineru_parse_options = options.mineru_parse_options or _compile_mineru_parse_options(
        domain_metadata
    )
    return options.model_copy(
        update={
            "domain_metadata": domain_metadata,
            "mineru_parse_options": mineru_parse_options,
        },
        deep=True,
    )


def compile_domain_metadata(metadata: DomainMetadata) -> DomainMetadata:
    custom_json = deepcopy(metadata.custom_json) if isinstance(metadata.custom_json, dict) else {}
    contract = build_executable_reference_contract(custom_json)
    if not _has_declared_executable_reference_contract(contract):
        return metadata.model_copy(update={"custom_json": custom_json}, deep=True)

    _compile_reference_resolution(custom_json)
    _compile_provenance(custom_json)
    _compile_quality_policy(custom_json, contract)
    return metadata.model_copy(update={"custom_json": custom_json}, deep=True)


def validate_executable_reference_contract(metadata: DomainMetadata) -> None:
    custom_json = metadata.custom_json if isinstance(metadata.custom_json, dict) else {}
    contract = build_executable_reference_contract(custom_json)
    chunking = _dict_value(custom_json.get("chunking"))
    reference_resolution = _dict_value(custom_json.get("reference_resolution"))
    canonical_enabled = reference_resolution.get("enabled") is True and (
        reference_resolution.get("build_canonical_units") is True
    )
    reference_chunking_requested = _reference_chunking_requested(chunking, contract)
    if not reference_chunking_requested and not canonical_enabled:
        return

    executable_anchors = _executable_anchors(contract)
    _validate_anchor_regexes(executable_anchors)
    primary_anchor_verified = _verified_primary_anchor(contract) is not None
    composite_verified = _verified_context_anchor(contract) is not None and (
        _verified_unit_anchor(contract) is not None
    )
    if not primary_anchor_verified and not composite_verified:
        return

    if not canonical_enabled:
        raise DomainMetadataContractError(
            "Reference-unit chunking requires custom_json.reference_resolution.enabled=true "
            "and build_canonical_units=true before indexing."
        )

    if primary_anchor_verified:
        _validate_anchor_required_groups(
            contract,
            _verified_primary_anchor(contract),
            "domain_structure.primary_anchor.regex",
        )
        return

    _validate_composite_anchor_required_groups(contract)


def _compile_reference_resolution(custom_json: dict[str, Any]) -> None:
    reference_resolution = _dict_value(custom_json.get("reference_resolution"))
    reference_resolution.update(
        {
            "enabled": reference_resolution.get("enabled", True),
            "build_canonical_units": reference_resolution.get("build_canonical_units", True),
            "carry_forward_body_blocks": reference_resolution.get(
                "carry_forward_body_blocks", True
            ),
            "header_only_policy": reference_resolution.get(
                "header_only_policy", "provenance_only"
            ),
            "continuation_policy": reference_resolution.get(
                "continuation_policy", "until_next_reference"
            ),
            "max_page_gap": reference_resolution.get("max_page_gap", 2),
            "require_single_reference_per_answerable_chunk": reference_resolution.get(
                "require_single_reference_per_answerable_chunk", True
            ),
        }
    )
    custom_json["reference_resolution"] = reference_resolution


def _compile_provenance(custom_json: dict[str, Any]) -> None:
    provenance = _dict_value(custom_json.get("provenance"))
    provenance.update(
        {
            "preserve_original_blocks": provenance.get("preserve_original_blocks", True),
            "block_preview_chars": provenance.get("block_preview_chars", 160),
            "store_text_hash": provenance.get("store_text_hash", True),
        }
    )
    custom_json["provenance"] = provenance


def _compile_quality_policy(
    custom_json: dict[str, Any],
    contract: ExecutableReferenceContract,
) -> None:
    policy = _dict_value(custom_json.get("quality_policy"))
    gate = _dict_value(policy.get("reference_contract_gate"))
    required = [
        "reference_schema.type",
        "reference_resolution.build_canonical_units",
    ]
    if _anchors_by_kind(contract, "primary_anchor"):
        required.insert(1, "domain_structure.primary_anchor.regex")
    else:
        insertion_index = 1
        if _anchors_by_kind(contract, "context_anchor"):
            required.insert(insertion_index, "domain_structure.context_anchor.regex")
            insertion_index += 1
        if _anchors_by_kind(contract, "unit_anchor"):
            required.insert(insertion_index, "domain_structure.unit_anchor.regex")
    gate.update(
        {
            "enabled": gate.get("enabled", True),
            "action": gate.get("action", "block"),
            "required": gate.get("required") or required,
        }
    )
    policy["reference_contract_gate"] = gate
    custom_json["quality_policy"] = policy


def _compile_mineru_parse_options(metadata: DomainMetadata) -> MinerUParseOptionsIn | None:
    custom_json = metadata.custom_json if isinstance(metadata.custom_json, dict) else {}
    mineru_options = _dict_value(custom_json.get("mineru_parse_options"))
    values: dict[str, Any] = {}
    for key in ("parser", "parse_method", "backend", "device", "lang", "source"):
        value = mineru_options.get(key)
        if isinstance(value, str) and value.strip():
            values[key] = value.strip()
    for key in ("formula", "table"):
        value = mineru_options.get(key)
        if isinstance(value, bool):
            values[key] = value
    max_concurrent_files = mineru_options.get("max_concurrent_files")
    if isinstance(max_concurrent_files, int) and not isinstance(max_concurrent_files, bool):
        values["max_concurrent_files"] = max_concurrent_files
    if values:
        return MinerUParseOptionsIn(**values)
    return None


def _has_declared_executable_reference_contract(
    contract: ExecutableReferenceContract,
) -> bool:
    return bool(
        contract.schema_type
        and contract.required_groups
        and (
            _anchors_by_kind(contract, "primary_anchor")
            or (
                _anchors_by_kind(contract, "context_anchor")
                and _anchors_by_kind(contract, "unit_anchor")
            )
        )
    )


def _reference_chunking_requested(
    chunking: dict[str, Any],
    contract: ExecutableReferenceContract,
) -> bool:
    return bool(contract.schema_type and _string_value(chunking.get("unit")))


def _validate_anchor_regexes(anchors: tuple[ReferenceAnchor, ...]) -> None:
    for anchor in anchors:
        try:
            _ = anchor.group_names
        except re.error as exc:
            raise DomainMetadataContractError(
                f"custom_json.domain_structure.{anchor.kind}.regex must compile "
                f"before indexing: {exc.msg}"
            ) from exc


def _validate_anchor_required_groups(
    contract: ExecutableReferenceContract,
    anchor: ReferenceAnchor | None,
    path: str,
) -> None:
    if anchor is None:
        return
    _validate_identity_groups(contract)
    missing = sorted(contract.required_groups - anchor.group_names)
    if missing:
        raise DomainMetadataContractError(
            f"custom_json.{path} is missing required named "
            f"groups: {', '.join(missing)}."
        )


def _validate_composite_anchor_required_groups(contract: ExecutableReferenceContract) -> None:
    _validate_identity_groups(contract)
    groups: set[str] = set()
    for anchor in (
        _verified_context_anchor(contract),
        _verified_unit_anchor(contract),
    ):
        if anchor is not None:
            groups.update(anchor.group_names)
    missing = sorted(contract.required_groups - groups)
    if missing:
        raise DomainMetadataContractError(
            "custom_json.domain_structure.context_anchor.regex and "
            "custom_json.domain_structure.unit_anchor.regex are missing required "
            f"named groups: {', '.join(missing)}."
        )


def _validate_identity_groups(contract: ExecutableReferenceContract) -> None:
    if not contract.canonical_ref_template_valid:
        raise DomainMetadataContractError(
            "custom_json.reference_schema.canonical_ref_template must be a valid "
            "Python format template before indexing."
        )
    if not contract.required_groups:
        raise DomainMetadataContractError(
            "custom_json.reference_schema must declare identity groups with "
            "canonical_ref_template, identity_fields, required_fields, or fields."
        )


def _executable_anchors(contract: ExecutableReferenceContract) -> tuple[ReferenceAnchor, ...]:
    return (
        _anchors_by_kind(contract, "primary_anchor")
        + _anchors_by_kind(contract, "context_anchor")
        + _anchors_by_kind(contract, "unit_anchor")
    )


def _verified_primary_anchor(contract: ExecutableReferenceContract) -> ReferenceAnchor | None:
    return _first_anchor(contract, "primary_anchor", require_verified=True)


def _verified_context_anchor(contract: ExecutableReferenceContract) -> ReferenceAnchor | None:
    return _first_anchor(contract, "context_anchor", require_verified=True)


def _verified_unit_anchor(contract: ExecutableReferenceContract) -> ReferenceAnchor | None:
    return _first_anchor(contract, "unit_anchor", require_verified=True)


def _first_anchor(
    contract: ExecutableReferenceContract,
    kind: str,
    *,
    require_verified: bool = False,
) -> ReferenceAnchor | None:
    anchors = _anchors_by_kind(contract, kind, require_verified=require_verified)
    return anchors[0] if anchors else None


def _anchors_by_kind(
    contract: ExecutableReferenceContract,
    kind: str,
    *,
    require_verified: bool = False,
) -> tuple[ReferenceAnchor, ...]:
    normalized_kind = kind.strip().casefold()
    return tuple(
        anchor
        for anchor in contract.anchors
        if anchor.kind.strip().casefold() == normalized_kind
        and (not require_verified or anchor.verified)
    )


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
