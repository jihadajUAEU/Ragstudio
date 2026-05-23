from __future__ import annotations

from typing import Any

from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.reference_contracts import build_executable_reference_contract


def build_document_index_contract(options: IndexDocumentIn) -> dict[str, Any]:
    domain_metadata = options.domain_metadata.model_dump(mode="json", exclude_none=True)
    custom_json = _dict_value(domain_metadata.get("custom_json"))
    reference_schema = _dict_value(custom_json.get("reference_schema"))
    reference_resolution = _dict_value(custom_json.get("reference_resolution"))
    reference_contract = _reference_contract_payload(custom_json)
    vision_policy = _dict_value(custom_json.get("vision_recovery_policy"))
    quality_policy = _dict_value(custom_json.get("quality_policy"))
    layout_quality_policy = _dict_value(custom_json.get("layout_quality_policy"))
    vision_analysis = _dict_value(custom_json.get("vision_analysis"))
    preprocessing_policy = _dict_value(custom_json.get("preprocessing_policy"))
    preprocessing = _dict_value(custom_json.get("preprocessing"))
    chunking = _dict_value(custom_json.get("chunking"))
    parser_hints = (
        options.mineru_parse_options.model_dump(mode="json", exclude_none=True)
        if options.mineru_parse_options is not None
        else {}
    )

    verified_reference_contract = reference_contract["verified"]
    has_reference_contract = bool(
        reference_schema.get("type")
        and verified_reference_contract
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
        "reference_contract": reference_contract,
        "parser_contract": {
            "mineru_parse_options": parser_hints,
            "required_text_validation_stage": "post_recovery_quality_gate",
        },
        "vision_analysis": {
            "sample_pages": _sample_pages(vision_analysis, preprocessing_policy, quality_policy),
            "observed_unit_pattern": vision_analysis.get("observed_unit_pattern")
            or vision_analysis.get("unit_pattern")
            or _observed_unit_pattern(reference_schema, chunking),
            "expected_scripts": _expected_scripts(
                preprocessing,
                preprocessing_policy,
                vision_analysis,
                quality_policy,
            ),
        },
        "preprocessing": {
            "strict_pdf_text_preflight": bool(
                verified_reference_contract
                and (
                    preprocessing.get("strict_pdf_text_preflight")
                    or preprocessing_policy.get("strict_pdf_text_preflight")
                    or _should_enable_pdf_preflight(
                        has_reference_contract=has_reference_contract,
                        quality_policy=quality_policy,
                    )
                )
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
                quality_policy,
            ),
            "cleanup_recommended": bool(
                verified_reference_contract
                and (
                    preprocessing.get("cleanup_recommended")
                    or preprocessing_policy.get("cleanup_recommended")
                    or _should_enable_pdf_preflight(
                        has_reference_contract=has_reference_contract,
                        quality_policy=quality_policy,
                    )
                )
            ),
            "cleanup_required_reason": (
                preprocessing.get("cleanup_required_reason")
                or preprocessing_policy.get("cleanup_reason")
                or _cleanup_required_reason(quality_policy)
            ),
            "reject_if_cleanup_fails": bool(
                preprocessing.get("reject_if_cleanup_fails")
                or preprocessing_policy.get("reject_if_cleanup_fails")
                or _reject_if_cleanup_fails(quality_policy, layout_quality_policy)
            ),
            "min_reference_script_pass_ratio": _float_value(
                preprocessing.get("min_reference_script_pass_ratio")
                or preprocessing_policy.get("min_reference_script_pass_ratio")
            ),
            "sample_pages": _list_value(
                preprocessing.get("sample_pages")
                or preprocessing_policy.get("sample_pages")
                or vision_analysis.get("sample_pages")
                or _quality_policy_sample_pages(quality_policy)
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


def _reference_contract_payload(custom_json: dict[str, Any]) -> dict[str, Any]:
    executable = build_executable_reference_contract(custom_json)
    validation = _dict_value(custom_json.get("reference_contract_validation"))
    reference_resolution = _dict_value(custom_json.get("reference_resolution"))
    anchors = [
        {
            "kind": anchor.kind,
            "regex": anchor.regex,
            "unit_role": anchor.unit_role,
            "context_source": anchor.context_source,
            "policy": anchor.policy,
            "verified": anchor.verified,
        }
        for anchor in executable.anchors
    ]
    verified = executable.verified and _validation_matches_executable(validation, anchors)
    strategy = _string_value(validation.get("selected_strategy")) or _executable_strategy(anchors)
    payload = {
        "schema_type": executable.schema_type,
        "canonical_ref_template": executable.canonical_ref_template,
        "required_groups": sorted(executable.required_groups),
        "canonical_units": reference_resolution.get("build_canonical_units") is True,
        "verified": verified,
        "strategy": strategy,
        "anchors": anchors,
    }
    payload.update(_legacy_anchor_fields(anchors, only_verified=verified))
    return payload


def _validation_matches_executable(
    validation: dict[str, Any],
    anchors: list[dict[str, Any]],
) -> bool:
    if not validation:
        return True
    if validation.get("status") != "verified":
        return False
    strategy = _string_value(validation.get("selected_strategy"))
    if strategy == "single_anchor":
        selected_regex = _string_value(validation.get("selected_primary_anchor_regex"))
        return _has_verified_anchor_regex(anchors, "primary_anchor", selected_regex)
    if strategy == "contextual_unit":
        selected_context_regex = _string_value(
            validation.get("selected_context_anchor_regex")
        )
        selected_unit_regex = _string_value(validation.get("selected_unit_anchor_regex"))
        return _has_verified_anchor_regex(
            anchors, "context_anchor", selected_context_regex
        ) and _has_verified_anchor_regex(anchors, "unit_anchor", selected_unit_regex)
    return False


def _has_verified_anchor_regex(
    anchors: list[dict[str, Any]],
    kind: str,
    regex: str | None,
) -> bool:
    if regex is None:
        return False
    return any(
        anchor.get("kind") == kind
        and anchor.get("verified") is True
        and anchor.get("regex") == regex
        for anchor in anchors
    )


def _executable_strategy(anchors: list[dict[str, Any]]) -> str | None:
    if any(
        anchor.get("kind") == "primary_anchor" and anchor.get("verified") is True
        for anchor in anchors
    ):
        return "single_anchor"
    has_context = any(
        anchor.get("kind") == "context_anchor" and anchor.get("verified") is True
        for anchor in anchors
    )
    has_unit = any(
        anchor.get("kind") == "unit_anchor" and anchor.get("verified") is True
        for anchor in anchors
    )
    if has_context and has_unit:
        return "contextual_unit"
    return None


def _legacy_anchor_fields(
    anchors: list[dict[str, Any]],
    *,
    only_verified: bool,
) -> dict[str, str | None]:
    if not only_verified:
        return {
            "primary_anchor_regex": None,
            "context_anchor_regex": None,
            "unit_anchor_regex": None,
            "inline_reference_regex": None,
        }
    return {
        "primary_anchor_regex": _anchor_regex(anchors, "primary_anchor"),
        "context_anchor_regex": _anchor_regex(anchors, "context_anchor"),
        "unit_anchor_regex": _anchor_regex(anchors, "unit_anchor"),
        "inline_reference_regex": _anchor_regex(anchors, "inline_references"),
    }


def _anchor_regex(anchors: list[dict[str, Any]], kind: str) -> str | None:
    for anchor in anchors:
        if anchor.get("kind") == kind and anchor.get("verified") is True:
            return _string_value(anchor.get("regex"))
    return None


def _string_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


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
    quality_policy: dict[str, Any],
) -> list[Any]:
    for payload in (preprocessing, preprocessing_policy, vision_analysis, quality_policy):
        scripts = _list_value(payload.get("expected_scripts"))
        if scripts:
            return scripts
        scripts = _list_value(payload.get("required_scripts"))
        if scripts:
            return scripts
    return []


def _sample_pages(
    vision_analysis: dict[str, Any],
    preprocessing_policy: dict[str, Any],
    quality_policy: dict[str, Any],
) -> list[Any]:
    for pages in (
        vision_analysis.get("sample_pages"),
        preprocessing_policy.get("sample_pages"),
        _quality_policy_sample_pages(quality_policy),
    ):
        normalized = _list_value(pages)
        if normalized:
            return normalized
    return []


def _quality_policy_sample_pages(quality_policy: dict[str, Any]) -> list[int]:
    pages: list[int] = []
    evidence = quality_policy.get("evidence")
    if not isinstance(evidence, list):
        return pages
    for item in evidence:
        if not isinstance(item, dict):
            continue
        page = item.get("page")
        if isinstance(page, int) and page > 0:
            pages.append(page)
    return list(dict.fromkeys(pages))


def _should_enable_pdf_preflight(
    *,
    has_reference_contract: bool,
    quality_policy: dict[str, Any],
) -> bool:
    return has_reference_contract and bool(_list_value(quality_policy.get("required_scripts")))


def _reject_if_cleanup_fails(
    quality_policy: dict[str, Any],
    layout_quality_policy: dict[str, Any],
) -> bool:
    if quality_policy.get("missing_required_script_action") == "block":
        return True
    failure_policy = _dict_value(layout_quality_policy.get("failure_policy"))
    return "block" in set(failure_policy.values())


def _cleanup_required_reason(quality_policy: dict[str, Any]) -> str | None:
    scripts = _list_value(quality_policy.get("required_scripts"))
    if not scripts:
        return None
    return (
        "Vision metadata observed required scripts in reference units; "
        "PDF text layer must preserve those scripts before parsing."
    )


def _observed_unit_pattern(
    reference_schema: dict[str, Any],
    chunking: dict[str, Any],
) -> str | None:
    if not reference_schema.get("type"):
        return None
    unit = chunking.get("unit") or "unit"
    return f"reference_units_with_{unit}_content"
