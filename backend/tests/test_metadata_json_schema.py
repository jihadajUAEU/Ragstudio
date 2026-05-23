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
