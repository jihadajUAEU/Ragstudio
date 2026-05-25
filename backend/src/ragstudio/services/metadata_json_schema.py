from __future__ import annotations

import re
from copy import deepcopy
from string import Formatter
from typing import Any

SAFE_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9_?P<>()\[\]\{\}\\\^\$\.\:\-\+\*\,\s|]+$")
UNSAFE_PATTERN_TOKENS = ("(?=", "(?!", "(?<=", "(?<!", "(?:", "\\1", "\\2")
DOMAIN_STRUCTURE_INLINE_POLICIES = {"cross_reference_only", "starts_unit", "ignore"}
QUALITY_SCRIPT_ACTIONS = {"no_warning", "info", "warn", "block"}
QUALITY_MATERIALIZATION_POLICIES = {
    "allow",
    "allow_if_required_scripts_present",
    "warn_if_required_scripts_missing",
    "block_if_required_scripts_missing",
}
LAYOUT_WARNING_LEVELS = {"info", "warn", "block"}
LAYOUT_RECOVERY_ACTIONS = {"recover_as_text", "ignore", "block"}
VISION_RECOVERY_FAILURE_ACTIONS = {"info", "warn", "block"}
REFERENCE_CONTRACT_EXTRACTOR_TYPES = {"regex", "contextual_regex"}
REFERENCE_CONTRACT_EXECUTION_STATUSES = {"verified", "unverified"}
REFERENCE_CONTRACT_ACCEPTANCE_MAX = 10_000
REFERENCE_CONTRACT_EXECUTION_EXAMPLES_MAX = 6


REFERENCE_CUSTOM_JSON_EXAMPLE: dict[str, Any] = {
    "reference_schema": {
        "type": "folio_line",
        "display": "Folio {folio}, line {line}",
        "canonical_ref_template": "folio:{folio}:line:{line}",
        "fields": {
            "folio": "folio_number",
            "line": "line_number",
            "page": "page_number",
        },
    },
    "relationships": {
        "previous": ["same_folio", "line - 1"],
        "next": ["same_folio", "line + 1"],
        "folio": ["same_folio"],
        "page": ["same_page"],
    },
    "chunking": {
        "unit": "folio_line",
        "include_neighbors": 1,
        "preserve_parallel_text": True,
        "merge_reference_header_with_body": True,
    },
    "domain_structure": {
            "primary_anchor": {
                "type": "folio_line",
                "regex": (
                    r"\bFolio\s+(?P<folio>\d{1,4})\s+Line\s+"
                    r"(?P<line>\d{1,4})\b"
                ),
                "unit": "folio_line",
            },
        "inline_references": {
            "type": "folio_line",
            "regex": r"folio:(?P<folio>\d{1,4}):line:(?P<line>\d{1,4})",
            "policy": "cross_reference_only",
        },
    },
    "reference_resolution": {
        "enabled": True,
        "build_canonical_units": True,
        "carry_forward_body_blocks": True,
        "header_only_policy": "provenance_only",
        "continuation_policy": "until_next_reference",
        "max_page_gap": 1,
        "require_single_reference_per_answerable_chunk": True,
    },
    "provenance": {
        "preserve_original_blocks": True,
        "block_preview_chars": 160,
        "store_text_hash": True,
    },
    "parser_normalization": {
        "allow_equations_as_content": False,
        "recover_text_bearing_blocks_as_prose": True,
        "preserve_original_block_type": True,
    },
    "mineru_parse_options": {
        "parser": "mineru",
        "parse_method": "ocr",
        "backend": "pipeline",
        "device": "cuda:0",
        "lang": "auto",
        "formula": False,
        "table": False,
        "max_concurrent_files": 1,
    },
    "vision_recovery_policy": {
        "enabled": False,
        "target_block_types": ["image", "figure", "equation"],
        "triggers": [
            "missing_pdf_text_layer",
            "suspected_text_misclassified_as_equation",
            "missing_required_script",
        ],
        "languages": ["arabic", "latin"],
        "max_blocks_per_page": 3,
        "max_total_blocks": 40,
        "failure_action": "warn",
        "prompt_hint": "Read visible text exactly and preserve line order.",
        "evidence": [{"page": 1, "observation": "Enable only when page images show text."}],
        "confidence": 0.0,
    },
    "retrieval": {
        "exact_reference_top1": True,
        "boost_same_parent_reference": True,
        "boost_neighbor_references": True,
    },
    "graph": {
        "node_types": ["reference_parent", "reference_unit", "chunk"],
        "edge_types": ["contains", "next_reference", "previous_reference", "references"],
        "materialize_from": ["mineru_structure", "reference_metadata"],
        "confidence_policy": "evidence_required",
    },
}


def validate_custom_json(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Custom JSON must be an object.")

    _validate_reference_schema(value.get("reference_schema"))
    _validate_reference_contract_candidates(value.get("reference_contract_candidates"))
    _validate_reference_contract_execution(value.get("reference_contract_execution"))
    _validate_relationships(value.get("relationships"))
    _validate_chunking(value.get("chunking"))
    _validate_domain_structure(value.get("domain_structure"))
    _validate_quality_policy(value.get("quality_policy"))
    _validate_layout_quality_policy(value.get("layout_quality_policy"))
    _validate_reference_resolution(value.get("reference_resolution"))
    _validate_provenance(value.get("provenance"))
    _validate_parser_normalization(value.get("parser_normalization"))
    _validate_mineru_parse_options(value.get("mineru_parse_options"))
    _validate_vision_recovery_policy(value.get("vision_recovery_policy"))
    _validate_retrieval(value.get("retrieval"))
    _validate_search_intents(value.get("search_intents"))
    _validate_domain_vocabulary(value.get("domain_vocabulary"))
    _validate_hybrid_search_weights(value.get("hybrid_search_weights"))
    _validate_graph(value.get("graph"))
    return value


def reference_custom_json_example() -> dict[str, Any]:
    return deepcopy(REFERENCE_CUSTOM_JSON_EXAMPLE)


def _validate_reference_schema(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.reference_schema must be an object.")

    fields = value.get("fields")
    if fields is not None:
        if not isinstance(fields, dict):
            raise ValueError("custom_json.reference_schema.fields must be an object.")
        for key, field_value in fields.items():
            if not isinstance(key, str) or not isinstance(field_value, str):
                raise ValueError(
                    "custom_json.reference_schema.fields must map strings to strings."
                )

    for key in ("type", "display", "canonical_ref_template"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            raise ValueError(f"custom_json.reference_schema.{key} must be a string.")

    for key in ("identity_fields", "required_fields"):
        _validate_string_list(value.get(key), f"custom_json.reference_schema.{key}")

    _validate_canonical_ref_template(value, fields)

    for key in ("reference_regex", "pattern", "regex"):
        pattern = value.get(key)
        if pattern is None:
            continue
        _validate_reference_pattern(pattern, key)


def _validate_reference_contract_candidates(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ValueError("custom_json.reference_contract_candidates must be a list.")
    for index, candidate in enumerate(value):
        path = f"custom_json.reference_contract_candidates.{index}"
        if not isinstance(candidate, dict):
            raise ValueError(f"{path} must be an object.")
        for key in ("schema_type", "unit"):
            item = candidate.get(key)
            if item is not None and not isinstance(item, str):
                raise ValueError(f"{path}.{key} must be a string.")
        identity = candidate.get("identity")
        if not isinstance(identity, dict):
            raise ValueError(f"{path}.identity must be an object.")
        fields = identity.get("fields")
        _validate_string_list(fields, f"{path}.identity.fields")
        template = identity.get("canonical_ref_template")
        if not isinstance(template, str):
            raise ValueError(f"{path}.identity.canonical_ref_template must be a string.")
        _validate_reference_contract_template(
            template,
            set(fields or []),
            f"{path}.identity.canonical_ref_template",
        )
        _validate_reference_contract_extractors(candidate.get("extractors"), path)
        _validate_reference_contract_acceptance(candidate.get("acceptance"), path)


def _validate_reference_contract_template(
    template: str,
    declared_fields: set[str],
    path: str,
) -> None:
    try:
        template_fields = _template_fields(template)
    except ValueError as exc:
        raise ValueError(f"{path} must be a valid Python format template: {exc}") from exc
    missing = sorted(template_fields - declared_fields)
    if missing:
        raise ValueError(f"{path} uses undeclared fields: {', '.join(missing)}")


def _validate_reference_contract_extractors(value: Any, path: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path}.extractors must be a non-empty list.")
    for index, extractor in enumerate(value):
        extractor_path = f"{path}.extractors.{index}"
        if not isinstance(extractor, dict):
            raise ValueError(f"{extractor_path} must be an object.")
        extractor_type = extractor.get("type")
        if extractor_type not in REFERENCE_CONTRACT_EXTRACTOR_TYPES:
            raise ValueError(
                f"{extractor_path}.type must be one of: "
                f"{', '.join(sorted(REFERENCE_CONTRACT_EXTRACTOR_TYPES))}."
            )
        target = extractor.get("target")
        if target is not None and not isinstance(target, str):
            raise ValueError(f"{extractor_path}.target must be a string.")
        if extractor_type == "regex":
            _validate_reference_pattern(extractor.get("pattern"), f"{extractor_path}.pattern")
        else:
            _validate_reference_pattern(
                extractor.get("context_pattern"),
                f"{extractor_path}.context_pattern",
            )
            _validate_reference_pattern(
                extractor.get("unit_pattern"),
                f"{extractor_path}.unit_pattern",
            )


def _validate_reference_contract_acceptance(value: Any, path: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError(f"{path}.acceptance must be an object.")
    for key in ("min_matched_units", "min_matched_pages"):
        item = value.get(key)
        if item is None:
            continue
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"{path}.acceptance.{key} must be an integer.")
        if item < 1 or item > REFERENCE_CONTRACT_ACCEPTANCE_MAX:
            raise ValueError(
                f"{path}.acceptance.{key} must be between 1 and "
                f"{REFERENCE_CONTRACT_ACCEPTANCE_MAX}."
            )


def _validate_reference_contract_execution(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.reference_contract_execution must be an object.")
    _validate_reference_contract_status(
        value.get("status"),
        "custom_json.reference_contract_execution.status",
    )
    for key in ("selected_schema_type", "selected_unit", "selected_canonical_ref_template"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            raise ValueError(f"custom_json.reference_contract_execution.{key} must be a string.")
    _validate_non_negative_int(
        value.get("matched_units"),
        "custom_json.reference_contract_execution.matched_units",
    )
    _validate_int_list(
        value.get("matched_pages"),
        "custom_json.reference_contract_execution.matched_pages",
    )
    reports = value.get("reports")
    if reports is None:
        return
    if not isinstance(reports, list):
        raise ValueError("custom_json.reference_contract_execution.reports must be a list.")
    for index, report in enumerate(reports):
        _validate_reference_contract_execution_report(report, index)


def _validate_reference_contract_execution_report(value: Any, index: int) -> None:
    path = f"custom_json.reference_contract_execution.reports.{index}"
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object.")
    _validate_reference_contract_status(value.get("status"), f"{path}.status")
    for key in ("schema_type", "unit", "canonical_ref_template", "rejection_reason"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            raise ValueError(f"{path}.{key} must be a string.")
    _validate_string_list(value.get("identity_fields"), f"{path}.identity_fields")
    _validate_non_negative_int(value.get("matched_units"), f"{path}.matched_units")
    _validate_int_list(value.get("matched_pages"), f"{path}.matched_pages")
    examples = value.get("examples")
    if examples is None:
        return
    if not isinstance(examples, list):
        raise ValueError(f"{path}.examples must be a list.")
    if len(examples) > REFERENCE_CONTRACT_EXECUTION_EXAMPLES_MAX:
        raise ValueError(
            f"{path}.examples must contain "
            f"{REFERENCE_CONTRACT_EXECUTION_EXAMPLES_MAX} examples or fewer."
        )
    for example_index, example in enumerate(examples):
        _validate_reference_contract_execution_example(
            example,
            f"{path}.examples.{example_index}",
        )


def _validate_reference_contract_execution_example(value: Any, path: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object.")
    for key in ("canonical_reference", "raw"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            raise ValueError(f"{path}.{key} must be a string.")
    page = value.get("page")
    if page is not None and (isinstance(page, bool) or not isinstance(page, int)):
        raise ValueError(f"{path}.page must be an integer.")
    groups = value.get("groups")
    if groups is None:
        return
    if not isinstance(groups, dict):
        raise ValueError(f"{path}.groups must be an object.")
    if any(
        not isinstance(key, str) or not isinstance(group_value, str)
        for key, group_value in groups.items()
    ):
        raise ValueError(f"{path}.groups must map strings to strings.")


def _validate_reference_contract_status(value: Any, path: str) -> None:
    if value not in REFERENCE_CONTRACT_EXECUTION_STATUSES:
        raise ValueError(
            f"{path} must be one of: "
            f"{', '.join(sorted(REFERENCE_CONTRACT_EXECUTION_STATUSES))}."
        )


def _validate_non_negative_int(value: Any, path: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path} must be an integer.")
    if value < 0:
        raise ValueError(f"{path} must be greater than or equal to 0.")


def _validate_int_list(value: Any, path: str) -> None:
    if value is None:
        return
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, int) for item in value
    ):
        raise ValueError(f"{path} must be a list of integers.")


def _validate_canonical_ref_template(reference_schema: dict[str, Any], fields: Any) -> None:
    template = reference_schema.get("canonical_ref_template")
    if template is None:
        return
    if not isinstance(template, str):
        raise ValueError("custom_json.reference_schema.canonical_ref_template must be a string.")
    try:
        template_fields = _template_fields(template)
    except ValueError as exc:
        raise ValueError(
            "custom_json.reference_schema.canonical_ref_template must be a valid "
            f"Python format template: {exc}"
        ) from exc
    if not template_fields:
        return

    declared_fields = _declared_reference_template_fields(reference_schema, fields)
    if not template_fields.issubset(declared_fields):
        missing = sorted(template_fields - declared_fields)
        raise ValueError(
            "custom_json.reference_schema.canonical_ref_template uses undeclared "
            f"fields: {', '.join(missing)}"
        )


def _template_fields(template: str) -> set[str]:
    fields: set[str] = set()
    for _, field_name, format_spec, conversion in Formatter().parse(template):
        if field_name is None:
            continue
        if not field_name:
            raise ValueError("positional placeholders are not supported")
        if (
            "." in field_name
            or "[" in field_name
            or "]" in field_name
            or format_spec
            or conversion
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field_name)
        ):
            raise ValueError(
                "only direct named placeholders such as {folio} are supported"
            )
        fields.add(field_name)
    return fields


def _declared_reference_template_fields(
    reference_schema: dict[str, Any],
    fields: Any,
) -> set[str]:
    declared: set[str] = set()
    if isinstance(fields, dict):
        declared.update(key for key in fields if isinstance(key, str))
    for key in ("identity_fields", "required_fields"):
        values = reference_schema.get(key)
        if isinstance(values, list):
            declared.update(item for item in values if isinstance(item, str))
    return declared


def _validate_reference_pattern(pattern: Any, key: str) -> None:
    path = _reference_pattern_path(key)
    if not isinstance(pattern, str):
        raise ValueError(f"{path} must be a string.")
    if len(pattern) > 160:
        raise ValueError(f"{path} must be 160 characters or less.")
    if not SAFE_REFERENCE_PATTERN.match(pattern):
        raise ValueError(
            f"{path} contains unsupported regex characters."
        )
    if any(token in pattern for token in UNSAFE_PATTERN_TOKENS):
        raise ValueError(
            f"{path} contains unsupported regex constructs."
        )
    if re.search(r"\([^)]*(?:\+|\*|\{\d+,?\d*\})[^)]*\)\s*(?:\+|\*|\{)", pattern):
        raise ValueError(
            f"{path} contains nested or adjacent quantifiers."
        )
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise ValueError(
            f"{path} must be a valid regex: {exc.msg}"
        ) from exc
    if not compiled.groupindex:
        raise ValueError(
            f"{path} must include at least one named group."
        )


def _reference_pattern_path(key: str) -> str:
    return f"custom_json.{key}" if "." in key else f"custom_json.reference_schema.{key}"


def _validate_relationships(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.relationships must be an object.")

    for key, relationships in value.items():
        if not isinstance(key, str):
            raise ValueError("custom_json.relationships keys must be strings.")
        if not isinstance(relationships, list) or not all(
            isinstance(item, str) for item in relationships
        ):
            raise ValueError("custom_json.relationships values must be lists of strings.")


def _validate_chunking(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.chunking must be an object.")

    unit = value.get("unit")
    if unit is not None and not isinstance(unit, str):
        raise ValueError("custom_json.chunking.unit must be a string.")

    include_neighbors = value.get("include_neighbors")
    if include_neighbors is not None:
        if isinstance(include_neighbors, bool) or not isinstance(include_neighbors, int):
            raise ValueError("custom_json.chunking.include_neighbors must be an integer.")
        if include_neighbors < 0:
            raise ValueError("custom_json.chunking.include_neighbors must be non-negative.")

    preserve_parallel_text = value.get("preserve_parallel_text")
    if preserve_parallel_text is not None and not isinstance(preserve_parallel_text, bool):
        raise ValueError("custom_json.chunking.preserve_parallel_text must be a boolean.")

    merge_reference_header_with_body = value.get("merge_reference_header_with_body")
    if (
        merge_reference_header_with_body is not None
        and not isinstance(merge_reference_header_with_body, bool)
    ):
        raise ValueError(
            "custom_json.chunking.merge_reference_header_with_body must be a boolean."
        )


def _validate_domain_structure(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.domain_structure must be an object.")

    primary_anchor = value.get("primary_anchor")
    if primary_anchor is not None:
        _validate_anchor_policy(primary_anchor, "domain_structure.primary_anchor")

    context_anchor = value.get("context_anchor")
    if context_anchor is not None:
        _validate_anchor_policy(context_anchor, "domain_structure.context_anchor")

    unit_anchor = value.get("unit_anchor")
    if unit_anchor is not None:
        _validate_anchor_policy(unit_anchor, "domain_structure.unit_anchor")

    inline_references = value.get("inline_references")
    if inline_references is not None:
        _validate_anchor_policy(inline_references, "domain_structure.inline_references")
        policy = inline_references.get("policy") if isinstance(inline_references, dict) else None
        if policy is not None and policy not in DOMAIN_STRUCTURE_INLINE_POLICIES:
            raise ValueError(
                "custom_json.domain_structure.inline_references.policy must be one of: "
                f"{', '.join(sorted(DOMAIN_STRUCTURE_INLINE_POLICIES))}."
            )


def _validate_anchor_policy(value: Any, path: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"custom_json.{path} must be an object.")
    for key in ("type", "unit", "pattern", "display", "context_source"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            raise ValueError(f"custom_json.{path}.{key} must be a string.")
    verified = value.get("verified")
    if verified is not None and not isinstance(verified, bool):
        raise ValueError(f"custom_json.{path}.verified must be a boolean.")
    regex = value.get("regex")
    if regex is not None:
        _validate_reference_pattern(regex, f"{path}.regex")


def _validate_quality_policy(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.quality_policy must be an object.")

    document_role = value.get("document_role")
    if document_role is not None and not isinstance(document_role, str):
        raise ValueError("custom_json.quality_policy.document_role must be a string.")

    for key in ("observed_scripts", "required_scripts", "optional_scripts"):
        item = value.get(key)
        if item is not None and (
            not isinstance(item, list) or any(not isinstance(entry, str) for entry in item)
        ):
            raise ValueError(f"custom_json.quality_policy.{key} must be a list of strings.")

    for key in ("required_scripts_by_unit_role", "optional_scripts_by_unit_role"):
        item = value.get(key)
        if item is None:
            continue
        if not isinstance(item, dict):
            raise ValueError(f"custom_json.quality_policy.{key} must be an object.")
        for role, scripts in item.items():
            if (
                not isinstance(role, str)
                or not isinstance(scripts, list)
                or any(not isinstance(script, str) for script in scripts)
            ):
                raise ValueError(
                    f"custom_json.quality_policy.{key} must map strings to script lists."
                )

    for key in ("missing_required_script_action", "missing_optional_script_action"):
        action = value.get(key)
        if action is not None and action not in QUALITY_SCRIPT_ACTIONS:
            raise ValueError(
                f"custom_json.quality_policy.{key} must be one of: "
                f"{', '.join(sorted(QUALITY_SCRIPT_ACTIONS))}."
            )

    materialization_policy = value.get("materialization_policy")
    if (
        materialization_policy is not None
        and materialization_policy not in QUALITY_MATERIALIZATION_POLICIES
    ):
        raise ValueError(
            "custom_json.quality_policy.materialization_policy must be one of: "
            f"{', '.join(sorted(QUALITY_MATERIALIZATION_POLICIES))}."
        )

    evidence = value.get("evidence")
    if evidence is not None:
        if not isinstance(evidence, list):
            raise ValueError("custom_json.quality_policy.evidence must be a list.")
        for entry in evidence:
            if not isinstance(entry, dict):
                raise ValueError("custom_json.quality_policy.evidence entries must be objects.")
            page = entry.get("page")
            observation = entry.get("observation")
            if page is not None and (isinstance(page, bool) or not isinstance(page, int)):
                raise ValueError("custom_json.quality_policy.evidence.page must be an integer.")
            if observation is not None and not isinstance(observation, str):
                raise ValueError(
                    "custom_json.quality_policy.evidence.observation must be a string."
                )

    confidence = value.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, int | float):
            raise ValueError("custom_json.quality_policy.confidence must be a number.")
        if confidence < 0 or confidence > 1:
            raise ValueError("custom_json.quality_policy.confidence must be between 0 and 1.")


def _validate_layout_quality_policy(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.layout_quality_policy must be an object.")

    expected_block_roles = value.get("expected_block_roles")
    if expected_block_roles is not None:
        if not isinstance(expected_block_roles, dict):
            raise ValueError(
                "custom_json.layout_quality_policy.expected_block_roles must be an object."
            )
        for role, block_types in expected_block_roles.items():
            if (
                not isinstance(role, str)
                or not isinstance(block_types, list)
                or any(not isinstance(block_type, str) for block_type in block_types)
            ):
                raise ValueError(
                    "custom_json.layout_quality_policy.expected_block_roles must map "
                    "strings to lists of strings."
                )

    for section_name in (
        "misclassified_block_policy",
        "disallowed_block_policy",
        "block_type_policy",
    ):
        section = value.get(section_name)
        if section is None:
            continue
        if not isinstance(section, dict):
            raise ValueError(
                f"custom_json.layout_quality_policy.{section_name} must be an object."
            )
        for policy_name, policy in section.items():
            if not isinstance(policy_name, str) or not isinstance(policy, dict):
                raise ValueError(
                    f"custom_json.layout_quality_policy.{section_name} must map "
                    "strings to objects."
                )
            _validate_layout_quality_policy_item(
                policy,
                f"custom_json.layout_quality_policy.{section_name}.{policy_name}",
            )

    warning_policy = value.get("warning_policy")
    if warning_policy is not None:
        if not isinstance(warning_policy, dict):
            raise ValueError(
                "custom_json.layout_quality_policy.warning_policy must be an object."
            )
        for warning_code, policy in warning_policy.items():
            if not isinstance(warning_code, str) or not isinstance(policy, dict):
                raise ValueError(
                    "custom_json.layout_quality_policy.warning_policy must map "
                    "strings to objects."
                )

            default_policy = policy.get("default")
            if default_policy is not None:
                if not isinstance(default_policy, dict):
                    raise ValueError(
                        "custom_json.layout_quality_policy.warning_policy."
                        f"{warning_code}.default must be an object."
                    )
                _validate_layout_quality_policy_item(
                    default_policy,
                    "custom_json.layout_quality_policy.warning_policy."
                    f"{warning_code}.default",
                )

            by_block_type = policy.get("by_block_type")
            if by_block_type is not None:
                if not isinstance(by_block_type, dict):
                    raise ValueError(
                        "custom_json.layout_quality_policy.warning_policy."
                        f"{warning_code}.by_block_type must be an object."
                    )
                for block_type, block_policy in by_block_type.items():
                    if not isinstance(block_type, str) or not isinstance(
                        block_policy,
                        dict,
                    ):
                        raise ValueError(
                            "custom_json.layout_quality_policy.warning_policy."
                            f"{warning_code}.by_block_type must map strings to objects."
                        )
                    _validate_layout_quality_policy_item(
                        block_policy,
                        "custom_json.layout_quality_policy.warning_policy."
                        f"{warning_code}.by_block_type.{block_type}",
                    )

    failure_policy = value.get("failure_policy")
    if failure_policy is not None:
        if not isinstance(failure_policy, dict):
            raise ValueError("custom_json.layout_quality_policy.failure_policy must be an object.")
        for failure_name, action in failure_policy.items():
            if not isinstance(failure_name, str) or action not in LAYOUT_WARNING_LEVELS:
                raise ValueError(
                    "custom_json.layout_quality_policy.failure_policy must map strings "
                    "to info, warn, or block."
                )


def _validate_layout_quality_policy_item(policy: dict[str, Any], path: str) -> None:
    action = policy.get("action")
    if action is not None and action not in LAYOUT_RECOVERY_ACTIONS:
        raise ValueError(f"{path}.action is invalid.")
    warning_level = policy.get("warning_level")
    if warning_level is not None and warning_level not in LAYOUT_WARNING_LEVELS:
        raise ValueError(f"{path}.warning_level is invalid.")
    treat_as = policy.get("treat_as")
    if treat_as is not None and not isinstance(treat_as, str):
        raise ValueError(f"{path}.treat_as must be a string.")


def _validate_reference_resolution(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.reference_resolution must be an object.")

    for key in (
        "enabled",
        "build_canonical_units",
        "carry_forward_body_blocks",
        "require_single_reference_per_answerable_chunk",
        "carry_forward_previous_reference",
        "continuation_reference_carry_forward",
        "mark_title_front_matter_non_reference_chunks",
    ):
        item = value.get(key)
        if item is not None and not isinstance(item, bool):
            raise ValueError(f"custom_json.reference_resolution.{key} must be a boolean.")

    for key in ("header_only_policy", "continuation_policy"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            raise ValueError(f"custom_json.reference_resolution.{key} must be a string.")

    max_page_gap = value.get("max_page_gap")
    if max_page_gap is not None:
        if isinstance(max_page_gap, bool) or not isinstance(max_page_gap, int):
            raise ValueError("custom_json.reference_resolution.max_page_gap must be an integer.")
        if max_page_gap < 0:
            raise ValueError(
                "custom_json.reference_resolution.max_page_gap must be non-negative."
            )


def _validate_provenance(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.provenance must be an object.")

    for key in ("preserve_original_blocks", "store_text_hash"):
        item = value.get(key)
        if item is not None and not isinstance(item, bool):
            raise ValueError(f"custom_json.provenance.{key} must be a boolean.")

    block_preview_chars = value.get("block_preview_chars")
    if block_preview_chars is not None:
        if isinstance(block_preview_chars, bool) or not isinstance(block_preview_chars, int):
            raise ValueError("custom_json.provenance.block_preview_chars must be an integer.")
        if block_preview_chars < 0:
            raise ValueError(
                "custom_json.provenance.block_preview_chars must be non-negative."
            )


def _validate_parser_normalization(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.parser_normalization must be an object.")

    for key in (
        "allow_equations_as_content",
        "recover_text_bearing_blocks_as_prose",
        "preserve_original_block_type",
    ):
        item = value.get(key)
        if item is not None and not isinstance(item, bool):
            raise ValueError(f"custom_json.parser_normalization.{key} must be a boolean.")

    for key in ("parser_strictness", "strictness"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            raise ValueError(f"custom_json.parser_normalization.{key} must be a string.")

    for key in ("allowed_block_types", "expected_scripts", "reference_patterns"):
        item = value.get(key)
        if item is None:
            continue
        if not isinstance(item, list) or any(not isinstance(entry, str) for entry in item):
            raise ValueError(
                f"custom_json.parser_normalization.{key} must be a list of strings."
            )


def _validate_mineru_parse_options(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.mineru_parse_options must be an object.")

    for key in ("parser", "parse_method", "backend", "device", "lang", "source"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            raise ValueError(f"custom_json.mineru_parse_options.{key} must be a string.")

    for key in ("formula", "table"):
        item = value.get(key)
        if item is not None and not isinstance(item, bool):
            raise ValueError(f"custom_json.mineru_parse_options.{key} must be a boolean.")

    max_concurrent_files = value.get("max_concurrent_files")
    if max_concurrent_files is not None:
        if isinstance(max_concurrent_files, bool) or not isinstance(max_concurrent_files, int):
            raise ValueError(
                "custom_json.mineru_parse_options.max_concurrent_files must be an integer."
            )
        if max_concurrent_files < 1 or max_concurrent_files > 8:
            raise ValueError(
                "custom_json.mineru_parse_options.max_concurrent_files must be between 1 and 8."
            )


def _validate_vision_recovery_policy(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.vision_recovery_policy must be an object.")

    enabled = value.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError("custom_json.vision_recovery_policy.enabled must be a boolean.")

    for key in ("target_block_types", "triggers", "languages"):
        _validate_string_list(value.get(key), f"custom_json.vision_recovery_policy.{key}")

    max_blocks_per_page = value.get("max_blocks_per_page")
    if max_blocks_per_page is not None:
        if isinstance(max_blocks_per_page, bool) or not isinstance(max_blocks_per_page, int):
            raise ValueError(
                "custom_json.vision_recovery_policy.max_blocks_per_page must be an integer."
            )
        if max_blocks_per_page < 1 or max_blocks_per_page > 20:
            raise ValueError(
                "custom_json.vision_recovery_policy.max_blocks_per_page must be between 1 and 20."
            )

    max_total_blocks = value.get("max_total_blocks")
    if max_total_blocks is not None:
        if isinstance(max_total_blocks, bool) or not isinstance(max_total_blocks, int):
            raise ValueError(
                "custom_json.vision_recovery_policy.max_total_blocks must be an integer."
            )
        if max_total_blocks < 1 or max_total_blocks > 500:
            raise ValueError(
                "custom_json.vision_recovery_policy.max_total_blocks must be between 1 and 500."
            )

    failure_action = value.get("failure_action")
    if failure_action is not None and failure_action not in VISION_RECOVERY_FAILURE_ACTIONS:
        raise ValueError(
            "custom_json.vision_recovery_policy.failure_action must be one of: "
            f"{', '.join(sorted(VISION_RECOVERY_FAILURE_ACTIONS))}."
        )

    prompt_hint = value.get("prompt_hint")
    if prompt_hint is not None and not isinstance(prompt_hint, str):
        raise ValueError("custom_json.vision_recovery_policy.prompt_hint must be a string.")

    evidence = value.get("evidence")
    if evidence is not None:
        if not isinstance(evidence, list):
            raise ValueError("custom_json.vision_recovery_policy.evidence must be a list.")
        for entry in evidence:
            if not isinstance(entry, dict):
                raise ValueError(
                    "custom_json.vision_recovery_policy.evidence entries must be objects."
                )
            page = entry.get("page")
            observation = entry.get("observation")
            if page is not None and (isinstance(page, bool) or not isinstance(page, int)):
                raise ValueError(
                    "custom_json.vision_recovery_policy.evidence.page must be an integer."
                )
            if observation is not None and not isinstance(observation, str):
                raise ValueError(
                    "custom_json.vision_recovery_policy.evidence.observation must be a string."
                )

    confidence = value.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, int | float):
            raise ValueError("custom_json.vision_recovery_policy.confidence must be a number.")
        if confidence < 0 or confidence > 1:
            raise ValueError(
                "custom_json.vision_recovery_policy.confidence must be between 0 and 1."
            )


def _validate_retrieval(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.retrieval must be an object.")

    for key, retrieval_value in value.items():
        if not isinstance(key, str):
            raise ValueError("custom_json.retrieval keys must be strings.")
        if not isinstance(retrieval_value, bool):
            raise ValueError("custom_json.retrieval values must be booleans.")


def _validate_search_intents(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ValueError("custom_json.search_intents must be a list.")
    for index, intent in enumerate(value):
        path = f"custom_json.search_intents[{index}]"
        if not isinstance(intent, dict):
            raise ValueError(f"{path} must be an object.")
        _validate_string_list(intent.get("query_terms"), f"{path}.query_terms")
        _validate_string_list(intent.get("vocabulary"), f"{path}.vocabulary")
        requires_numeric = intent.get("requires_numeric_evidence")
        if requires_numeric is not None and not isinstance(requires_numeric, bool):
            raise ValueError(f"{path}.requires_numeric_evidence must be a boolean.")
        boost = intent.get("boost")
        if boost is not None:
            _validate_non_negative_number(boost, f"{path}.boost")


def _validate_domain_vocabulary(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.domain_vocabulary must be an object.")
    for key, vocabulary in value.items():
        if not isinstance(key, str):
            raise ValueError("custom_json.domain_vocabulary keys must be strings.")
        if key == "term_aliases":
            if not isinstance(vocabulary, dict):
                raise ValueError("custom_json.domain_vocabulary.term_aliases must be an object.")
            for term, aliases in vocabulary.items():
                if not isinstance(term, str):
                    raise ValueError(
                        "custom_json.domain_vocabulary.term_aliases keys must be strings."
                    )
                _validate_string_list(
                    aliases,
                    f"custom_json.domain_vocabulary.term_aliases.{term}",
                )
            continue
        _validate_string_list(vocabulary, f"custom_json.domain_vocabulary.{key}")


def _validate_hybrid_search_weights(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.hybrid_search_weights must be an object.")
    for key, weight in value.items():
        if not isinstance(key, str):
            raise ValueError("custom_json.hybrid_search_weights keys must be strings.")
        _validate_non_negative_number(weight, f"custom_json.hybrid_search_weights.{key}")


def _validate_graph(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.graph must be an object.")

    for key in ("node_types", "edge_types", "materialize_from"):
        _validate_string_list(value.get(key), f"custom_json.graph.{key}")

    confidence_policy = value.get("confidence_policy")
    if confidence_policy != "evidence_required":
        raise ValueError(
            "custom_json.graph.confidence_policy must be 'evidence_required'."
        )


def _validate_string_list(value: Any, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings.")


def _validate_non_negative_number(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number.")
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to 0.")
