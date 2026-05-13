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
