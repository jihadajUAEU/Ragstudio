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
    _apply_reference_contract_validation(custom_json)
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

    _validate_identity_groups(contract)
    _validate_anchor_regexes(_executable_anchors(contract))
    if not canonical_enabled:
        raise DomainMetadataContractError(
            "Reference-unit chunking requires custom_json.reference_resolution.enabled=true "
            "and build_canonical_units=true before indexing."
        )

    if contract.verified:
        return

    if _has_satisfied_primary_anchor(contract):
        raise DomainMetadataContractError(
            "custom_json.domain_structure.primary_anchor.regex must be verified "
            "against sampled pages before indexing."
        )
    if _has_satisfied_context_unit_anchors(contract):
        raise DomainMetadataContractError(
            "custom_json.domain_structure.context_anchor.regex and "
            "custom_json.domain_structure.unit_anchor.regex must be verified "
            "against sampled pages before indexing."
        )
    _raise_missing_required_groups(contract)


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
    if _has_satisfied_context_unit_anchors(contract) and not _has_satisfied_primary_anchor(
        contract
    ):
        required.insert(1, "domain_structure.context_anchor.regex")
        required.insert(2, "domain_structure.unit_anchor.regex")
    elif _anchors_by_kind(contract, "primary_anchor"):
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


def _apply_reference_contract_validation(custom_json: dict[str, Any]) -> None:
    validation = _dict_value(custom_json.get("reference_contract_validation"))
    if validation.get("status") != "verified":
        return
    strategy = _string_value(validation.get("selected_strategy"))
    if strategy not in {"single_anchor", "contextual_unit"}:
        return
    domain_structure = _dict_value(custom_json.get("domain_structure"))
    if not domain_structure:
        return

    selected = _selected_validation_candidate(validation, strategy)
    schema_type = _string_value(selected.get("schema_type")) or _string_value(
        _dict_value(custom_json.get("reference_schema")).get("type")
    )
    _demote_reference_anchor_verification(domain_structure)
    if strategy == "single_anchor":
        selected_regex = _string_value(validation.get("selected_primary_anchor_regex"))
        primary_anchor = _dict_value(domain_structure.get("primary_anchor"))
        if selected_regex and _string_value(primary_anchor.get("regex")) == selected_regex:
            primary_anchor["verified"] = True
            if schema_type:
                primary_anchor["type"] = schema_type
            domain_structure["primary_anchor"] = primary_anchor
    else:
        selected_context_regex = _string_value(
            validation.get("selected_context_anchor_regex")
        )
        selected_unit_regex = _string_value(validation.get("selected_unit_anchor_regex"))
        context_anchor = _dict_value(domain_structure.get("context_anchor"))
        unit_anchor = _dict_value(domain_structure.get("unit_anchor"))
        if (
            selected_context_regex
            and selected_unit_regex
            and _string_value(context_anchor.get("regex")) == selected_context_regex
            and _string_value(unit_anchor.get("regex")) == selected_unit_regex
        ):
            context_anchor["verified"] = True
            unit_anchor["verified"] = True
            if schema_type:
                context_anchor["type"] = schema_type
                unit_anchor["type"] = schema_type
            if not _string_value(unit_anchor.get("context_source")):
                unit_anchor["context_source"] = "context_anchor"
            domain_structure["context_anchor"] = context_anchor
            domain_structure["unit_anchor"] = unit_anchor
    custom_json["domain_structure"] = domain_structure


def _selected_validation_candidate(
    validation: dict[str, Any],
    strategy: str,
) -> dict[str, Any]:
    candidates = validation.get("candidates")
    if not isinstance(candidates, list):
        return {}
    primary_regex = _string_value(validation.get("selected_primary_anchor_regex"))
    context_regex = _string_value(validation.get("selected_context_anchor_regex"))
    unit_regex = _string_value(validation.get("selected_unit_anchor_regex"))
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if strategy == "single_anchor" and _string_value(
            candidate.get("primary_anchor_regex")
        ) == primary_regex:
            return candidate
        if (
            strategy == "contextual_unit"
            and _string_value(candidate.get("context_anchor_regex")) == context_regex
            and _string_value(candidate.get("unit_anchor_regex")) == unit_regex
        ):
            return candidate
    return {}


def _demote_reference_anchor_verification(domain_structure: dict[str, Any]) -> None:
    for key in ("primary_anchor", "context_anchor", "unit_anchor"):
        anchor = domain_structure.get(key)
        if isinstance(anchor, dict):
            demoted = dict(anchor)
            demoted["verified"] = False
            domain_structure[key] = demoted


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


def _raise_missing_required_groups(contract: ExecutableReferenceContract) -> None:
    missing = sorted(contract.missing_declared_executable_anchor_groups)
    if not missing:
        raise DomainMetadataContractError(
            "Reference-unit chunking requires a verified primary anchor or "
            "verified context and unit anchors before indexing."
        )
    primary_missing = _primary_anchor_missing_groups(contract)
    context_unit_missing = _context_unit_anchor_missing_groups(contract)
    if primary_missing is not None and primary_missing == set(missing):
        raise DomainMetadataContractError(
            "custom_json.domain_structure.primary_anchor.regex is missing required "
            f"named groups: {', '.join(missing)}."
        )
    if context_unit_missing is not None and context_unit_missing == set(missing):
        raise DomainMetadataContractError(
            "custom_json.domain_structure.context_anchor.regex and "
            "custom_json.domain_structure.unit_anchor.regex are missing required "
            f"named groups: {', '.join(missing)}."
        )
    raise DomainMetadataContractError(
        "Declared reference anchors are missing required named groups: "
        f"{', '.join(missing)}."
    )


def _primary_anchor_missing_groups(contract: ExecutableReferenceContract) -> set[str] | None:
    primary = _first_anchor(contract, "primary_anchor")
    if primary is None:
        return None
    return set(contract.required_groups - primary.group_names)


def _context_unit_anchor_missing_groups(
    contract: ExecutableReferenceContract,
) -> set[str] | None:
    context = _first_anchor(contract, "context_anchor")
    unit = _first_anchor(contract, "unit_anchor")
    if context is None or unit is None:
        return None
    groups = set(context.group_names) | set(unit.group_names)
    return set(contract.required_groups - groups)


def _has_satisfied_primary_anchor(contract: ExecutableReferenceContract) -> bool:
    return any(
        contract.required_groups.issubset(anchor.group_names)
        for anchor in _anchors_by_kind(contract, "primary_anchor")
    )


def _has_satisfied_context_unit_anchors(contract: ExecutableReferenceContract) -> bool:
    context_groups: set[str] = set()
    unit_groups: set[str] = set()
    for anchor in _anchors_by_kind(contract, "context_anchor"):
        context_groups.update(anchor.group_names)
    for anchor in _anchors_by_kind(contract, "unit_anchor"):
        unit_groups.update(anchor.group_names)
    if not context_groups or not unit_groups:
        return False
    return contract.required_groups.issubset(context_groups | unit_groups)


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
