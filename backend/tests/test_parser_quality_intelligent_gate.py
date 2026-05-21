from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.parser_quality_intelligent_gate import ParserQualityIntelligentGate


def _metadata_with_layout_policy() -> DomainMetadata:
    return DomainMetadata(
        domain="quran_tafseer",
        document_type="commentary",
        content_role="tafseer",
        custom_json={
            "layout_quality_policy": {
                "misclassified_block_policy": {
                    "equation_with_recovered_text": {
                        "treat_as": "prose_or_verse_text",
                        "action": "recover_as_text",
                        "warning_level": "info",
                    }
                },
                "disallowed_block_policy": {
                    "text_bearing_disallowed_block": {
                        "action": "recover_as_text",
                        "warning_level": "info",
                    }
                },
            }
        },
    )


def _metadata_with_blocking_layout_policy() -> DomainMetadata:
    return DomainMetadata(
        domain="quran_tafseer",
        document_type="commentary",
        content_role="tafseer",
        custom_json={
            "layout_quality_policy": {
                "misclassified_block_policy": {
                    "equation_with_recovered_text": {
                        "action": "block",
                        "warning_level": "info",
                    }
                }
            }
        },
    )


def _metadata_with_configurable_warning_policy() -> DomainMetadata:
    return DomainMetadata(
        domain="reports",
        document_type="quality_review",
        custom_json={
            "layout_quality_policy": {
                "warning_policy": {
                    "recovered_text_from_misclassified_block": {
                        "default": {
                            "action": "recover_as_text",
                            "warning_level": "info",
                        },
                        "by_block_type": {
                            "table": {
                                "action": "block",
                                "warning_level": "warn",
                            }
                        },
                    },
                    "low_confidence_block_text": {
                        "default": {
                            "action": "recover_as_text",
                            "warning_level": "info",
                        }
                    },
                }
            }
        },
    )


def _metadata_with_block_type_policy() -> DomainMetadata:
    return DomainMetadata(
        domain="reports",
        document_type="quality_review",
        custom_json={
            "layout_quality_policy": {
                "block_type_policy": {
                    "image": {
                        "action": "ignore",
                        "warning_level": "info",
                    },
                    "equation": {
                        "action": "block",
                        "warning_level": "warn",
                    },
                },
                "misclassified_block_policy": {
                    "equation_with_recovered_text": {
                        "action": "recover_as_text",
                        "warning_level": "info",
                    }
                },
            }
        },
    )


def test_intelligent_gate_marks_misclassified_equation_recovery_as_info():
    warning = {
        "code": "recovered_text_from_misclassified_block",
        "block_type": "equation",
        "message": "Used parser-provided recovered text for a block misclassified as an equation.",
    }

    classified = ParserQualityIntelligentGate().classify_warning(
        warning,
        domain_metadata=_metadata_with_layout_policy(),
    )

    assert classified == {
        **warning,
        "severity": "info",
        "quality_gate_action": "accepted_recovery",
        "suppressed_from_counts": True,
        "quality_gate_reason": "layout_quality_policy.equation_with_recovered_text",
    }


def test_intelligent_gate_marks_disallowed_text_recovery_as_info():
    warning = {
        "code": "recovered_text_from_disallowed_block",
        "block_type": "image",
        "message": "Used parser-provided recovered text for a disallowed block type.",
    }

    classified = ParserQualityIntelligentGate().classify_warning(
        warning,
        domain_metadata=_metadata_with_layout_policy(),
    )

    assert classified["severity"] == "info"
    assert classified["quality_gate_action"] == "accepted_recovery"
    assert classified["suppressed_from_counts"] is True
    assert classified["quality_gate_reason"] == (
        "layout_quality_policy.text_bearing_disallowed_block"
    )


def test_intelligent_gate_defaults_unknown_warning_to_warn():
    warning = {"code": "reference_unit_unresolved", "message": "Could not resolve reference."}

    classified = ParserQualityIntelligentGate().classify_warning(
        warning,
        domain_metadata=_metadata_with_layout_policy(),
    )

    assert classified["severity"] == "warn"
    assert classified["quality_gate_action"] == "review_warning"
    assert classified["suppressed_from_counts"] is False


def test_intelligent_gate_never_suppresses_block_action_even_when_warning_level_info():
    warning = {
        "code": "recovered_text_from_misclassified_block",
        "block_type": "equation",
        "message": "Recovered text is not trusted for this policy.",
    }

    classified = ParserQualityIntelligentGate().classify_warning(
        warning,
        domain_metadata=_metadata_with_blocking_layout_policy(),
    )

    assert classified["severity"] == "block"
    assert classified["quality_gate_action"] == "block"
    assert classified["suppressed_from_counts"] is False


def test_intelligent_gate_blocks_configured_table_recovery_warning():
    warning = {
        "code": "recovered_text_from_misclassified_block",
        "block_type": "table",
        "message": "Recovered text from a table-shaped block.",
    }

    classified = ParserQualityIntelligentGate().classify_warning(
        warning,
        domain_metadata=_metadata_with_configurable_warning_policy(),
    )

    assert classified["severity"] == "block"
    assert classified["quality_gate_action"] == "block"
    assert classified["suppressed_from_counts"] is False
    assert classified["quality_gate_reason"] == (
        "layout_quality_policy.warning_policy."
        "recovered_text_from_misclassified_block.by_block_type.table"
    )


def test_intelligent_gate_applies_warning_default_policy_to_any_block_type():
    warning = {
        "code": "low_confidence_block_text",
        "block_type": "caption",
        "message": "Recovered text confidence was low.",
    }

    classified = ParserQualityIntelligentGate().classify_warning(
        warning,
        domain_metadata=_metadata_with_configurable_warning_policy(),
    )

    assert classified["severity"] == "info"
    assert classified["quality_gate_action"] == "accepted_recovery"
    assert classified["suppressed_from_counts"] is True
    assert classified["quality_gate_reason"] == (
        "layout_quality_policy.warning_policy.low_confidence_block_text.default"
    )


def test_intelligent_gate_applies_block_type_policy_before_legacy_policy():
    warning = {
        "code": "recovered_text_from_misclassified_block",
        "block_type": "equation",
        "message": "Recovered equation text should follow block type policy first.",
    }

    classified = ParserQualityIntelligentGate().classify_warning(
        warning,
        domain_metadata=_metadata_with_block_type_policy(),
    )

    assert classified["severity"] == "block"
    assert classified["quality_gate_action"] == "block"
    assert classified["suppressed_from_counts"] is False
    assert classified["quality_gate_reason"] == "layout_quality_policy.block_type_policy.equation"


def test_intelligent_gate_applies_pure_block_type_policy():
    warning = {
        "code": "low_confidence_block_text",
        "block_type": "image",
        "message": "Image text confidence was low.",
    }

    classified = ParserQualityIntelligentGate().classify_warning(
        warning,
        domain_metadata=_metadata_with_block_type_policy(),
    )

    assert classified["severity"] == "info"
    assert classified["quality_gate_action"] == "ignore"
    assert classified["suppressed_from_counts"] is True
    assert classified["quality_gate_reason"] == "layout_quality_policy.block_type_policy.image"
