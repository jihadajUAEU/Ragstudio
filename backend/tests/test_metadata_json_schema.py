import pytest
from ragstudio.services.metadata_json_schema import validate_custom_json


def test_validate_custom_json_accepts_contextual_reference_anchors():
    payload = {
        "domain_structure": {
            "context_anchor": {
                "regex": r"Folio\s+(?P<folio>\d+)",
                "unit": "folio",
                "verified": True,
            },
            "unit_anchor": {
                "regex": r"Line\s+(?P<line>\d+)",
                "unit": "line",
                "context_source": "context_anchor",
                "verified": False,
            },
        }
    }

    assert validate_custom_json(payload) is payload


def test_validate_custom_json_rejects_invalid_contextual_anchor_values():
    with pytest.raises(ValueError, match=r"context_anchor\.verified"):
        validate_custom_json(
            {
                "domain_structure": {
                    "context_anchor": {
                        "regex": r"Folio\s+(?P<folio>\d+)",
                        "verified": "true",
                    }
                }
            }
        )


def test_validate_custom_json_rejects_template_without_declared_fields():
    with pytest.raises(ValueError, match="uses undeclared fields: folio"):
        validate_custom_json(
            {
                "reference_schema": {
                    "type": "folio_line",
                    "canonical_ref_template": "folio:{folio}",
                }
            }
        )


def test_validate_custom_json_rejects_non_direct_template_placeholders():
    for template in ("folio:{}", "folio:{folio.id}", "folio:{folio[0]}", "folio:{folio:03d}"):
        with pytest.raises(ValueError, match="canonical_ref_template"):
            validate_custom_json(
                {
                    "reference_schema": {
                        "type": "folio_line",
                        "canonical_ref_template": template,
                        "fields": {"folio": "folio_number"},
                    }
                }
            )


def test_validate_custom_json_checks_template_against_identity_fields():
    with pytest.raises(ValueError, match="uses undeclared fields: line"):
        validate_custom_json(
            {
                "reference_schema": {
                    "type": "folio_line",
                    "canonical_ref_template": "folio:{folio}:line:{line}",
                    "identity_fields": ["folio"],
                }
            }
        )

    payload = {
        "reference_schema": {
            "type": "folio_line",
            "canonical_ref_template": "folio:{folio}:line:{line}",
            "identity_fields": ["folio", "line"],
        }
    }
    assert validate_custom_json(payload) is payload

    with pytest.raises(ValueError, match=r"unit_anchor\.context_source"):
        validate_custom_json(
            {
                "domain_structure": {
                    "unit_anchor": {
                        "regex": r"Line\s+(?P<line>\d+)",
                        "context_source": 7,
                    }
                }
            }
        )
