from __future__ import annotations

from typing import Any

from ragstudio.schemas.parsing import IndexDocumentIn


def build_document_index_contract(options: IndexDocumentIn) -> dict[str, Any]:
    domain_metadata = options.domain_metadata.model_dump(mode="json", exclude_none=True)
    custom_json = _dict_value(domain_metadata.get("custom_json"))
    reference_schema = _dict_value(custom_json.get("reference_schema"))
    reference_resolution = _dict_value(custom_json.get("reference_resolution"))
    domain_structure = _dict_value(custom_json.get("domain_structure"))
    primary_anchor = _dict_value(domain_structure.get("primary_anchor"))
    vision_policy = _dict_value(custom_json.get("vision_recovery_policy"))
    chunking = _dict_value(custom_json.get("chunking"))
    parser_hints = (
        options.mineru_parse_options.model_dump(mode="json", exclude_none=True)
        if options.mineru_parse_options is not None
        else {}
    )

    has_reference_contract = bool(
        reference_schema.get("type")
        and primary_anchor.get("regex")
        and reference_resolution.get("build_canonical_units") is True
    )
    is_generic = (
        domain_metadata.get("domain", "generic") == "generic" and not has_reference_contract
    )

    return {
        "contract_version": 1,
        "contract_status": (
            "compiled_reference_contract"
            if has_reference_contract
            else "generic"
            if is_generic
            else "metadata_only"
        ),
        "parser_mode": options.parser_mode,
        "domain_metadata": domain_metadata,
        "reference_contract": {
            "schema_type": reference_schema.get("type"),
            "chunk_unit": chunking.get("unit"),
            "primary_anchor_regex": primary_anchor.get("regex"),
            "canonical_units": reference_resolution.get("build_canonical_units") is True,
        },
        "parser_contract": {
            "mineru_parse_options": parser_hints,
            "required_text_validation_stage": "post_recovery_quality_gate",
        },
        "layout_context": {
            "vision_recovery_enabled": vision_policy.get("enabled") is True,
            "preserve_original_blocks": bool(
                _dict_value(custom_json.get("provenance")).get("preserve_original_blocks")
            ),
            "expected_tables": parser_hints.get("table"),
            "expected_equations": parser_hints.get("formula"),
            "image_blocks_are_recovery_candidates": vision_policy.get("enabled") is True,
        },
        "retrieval_contract": {
            "source_of_truth": "postgres_canonical_evidence",
            "allow_raganything_runtime_lane": True,
        },
    }


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
