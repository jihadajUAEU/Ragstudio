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
    vision_analysis = _dict_value(custom_json.get("vision_analysis"))
    preprocessing_policy = _dict_value(custom_json.get("preprocessing_policy"))
    preprocessing = _dict_value(custom_json.get("preprocessing"))
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
        "vision_analysis": {
            "sample_pages": _list_value(vision_analysis.get("sample_pages")),
            "observed_unit_pattern": vision_analysis.get("observed_unit_pattern")
            or vision_analysis.get("unit_pattern"),
            "expected_scripts": _list_value(vision_analysis.get("expected_scripts")),
        },
        "preprocessing": {
            "strict_pdf_text_preflight": bool(
                preprocessing.get("strict_pdf_text_preflight")
                or preprocessing_policy.get("strict_pdf_text_preflight")
            ),
            "expected_scripts_source": (
                preprocessing.get("expected_scripts_source")
                or preprocessing_policy.get("expected_scripts_source")
                or "vision_analysis"
            ),
            "expected_scripts": _expected_scripts(
                preprocessing,
                preprocessing_policy,
                vision_analysis,
            ),
            "cleanup_recommended": bool(
                preprocessing.get("cleanup_recommended")
                or preprocessing_policy.get("cleanup_recommended")
            ),
            "cleanup_required_reason": (
                preprocessing.get("cleanup_required_reason")
                or preprocessing_policy.get("cleanup_reason")
            ),
            "reject_if_cleanup_fails": bool(
                preprocessing.get("reject_if_cleanup_fails")
                or preprocessing_policy.get("reject_if_cleanup_fails")
            ),
            "min_reference_script_pass_ratio": _float_value(
                preprocessing.get("min_reference_script_pass_ratio")
                or preprocessing_policy.get("min_reference_script_pass_ratio")
            ),
            "sample_pages": _list_value(
                preprocessing.get("sample_pages")
                or preprocessing_policy.get("sample_pages")
                or vision_analysis.get("sample_pages")
            ),
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


def _list_value(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _float_value(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _expected_scripts(
    preprocessing: dict[str, Any],
    preprocessing_policy: dict[str, Any],
    vision_analysis: dict[str, Any],
) -> list[Any]:
    for payload in (preprocessing, preprocessing_policy, vision_analysis):
        scripts = _list_value(payload.get("expected_scripts"))
        if scripts:
            return scripts
    return []
