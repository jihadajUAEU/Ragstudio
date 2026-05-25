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


def test_reference_custom_json_example_uses_generic_reference_vocabulary():
    from ragstudio.services.metadata_json_schema import REFERENCE_CUSTOM_JSON_EXAMPLE

    text = repr(REFERENCE_CUSTOM_JSON_EXAMPLE).casefold()

    assert "boost_same_chapter" not in text
    assert "boost_neighbor_verses" not in text
    assert "chapter" not in REFERENCE_CUSTOM_JSON_EXAMPLE["graph"]["node_types"]
    assert "verse" not in REFERENCE_CUSTOM_JSON_EXAMPLE["graph"]["node_types"]


def test_validate_custom_json_accepts_reference_contract_candidates():
    payload = {
        "reference_contract_candidates": [
            {
                "schema_type": "chapter_verse",
                "unit": "verse",
                "identity": {
                    "fields": ["chapter", "verse"],
                    "canonical_ref_template": "{chapter}:{verse}",
                },
                "extractors": [
                    {
                        "type": "regex",
                        "target": "page_text",
                        "pattern": (
                            r"\[(?P<chapter>\d{1,3}):"
                            r"(?P<verse>\d{1,3})\]"
                        ),
                    }
                ],
                "acceptance": {"min_matched_units": 2, "min_matched_pages": 1},
            }
        ]
    }

    assert validate_custom_json(payload) is payload


def test_validate_custom_json_rejects_invalid_reference_contract_candidate_extractor():
    with pytest.raises(
        ValueError,
        match=r"reference_contract_candidates\.0\.extractors\.0\.type",
    ):
        validate_custom_json(
            {
                "reference_contract_candidates": [
                    {
                        "schema_type": "chapter_verse",
                        "unit": "verse",
                        "identity": {
                            "fields": ["chapter", "verse"],
                            "canonical_ref_template": "{chapter}:{verse}",
                        },
                        "extractors": [{"type": "python", "target": "page_text"}],
                    }
                ]
            }
        )


def test_validate_custom_json_rejects_candidate_template_without_identity_fields():
    with pytest.raises(ValueError, match="uses undeclared fields: verse"):
        validate_custom_json(
            {
                "reference_contract_candidates": [
                    {
                        "schema_type": "chapter_verse",
                        "unit": "verse",
                        "identity": {
                            "fields": ["chapter"],
                            "canonical_ref_template": "{chapter}:{verse}",
                        },
                        "extractors": [
                            {
                                "type": "regex",
                                "pattern": (
                                    r"\[(?P<chapter>\d{1,3}):"
                                    r"(?P<verse>\d{1,3})\]"
                                ),
                            }
                        ],
                    }
                ]
            }
        )


def test_validate_custom_json_accepts_reference_contract_execution_report():
    payload = {
        "reference_contract_execution": {
            "status": "verified",
            "selected_schema_type": "chapter_verse",
            "selected_unit": "verse",
            "selected_canonical_ref_template": "{chapter}:{verse}",
            "matched_units": 2,
            "matched_pages": [1],
            "reports": [
                {
                    "status": "verified",
                    "schema_type": "chapter_verse",
                    "unit": "verse",
                    "identity_fields": ["chapter", "verse"],
                    "canonical_ref_template": "{chapter}:{verse}",
                    "matched_units": 2,
                    "matched_pages": [1],
                    "rejection_reason": None,
                    "examples": [
                        {
                            "canonical_reference": "1:1",
                            "groups": {"chapter": "1", "verse": "1"},
                            "page": 1,
                            "raw": "[1:1]",
                        }
                    ],
                }
            ],
        }
    }

    assert validate_custom_json(payload) is payload


def test_validate_custom_json_rejects_invalid_execution_example_shape():
    with pytest.raises(ValueError, match=r"reports\.0\.examples\.0\.groups"):
        validate_custom_json(
            {
                "reference_contract_execution": {
                    "status": "verified",
                    "matched_units": 1,
                    "matched_pages": [1],
                    "reports": [
                        {
                            "status": "verified",
                            "schema_type": "chapter_verse",
                            "unit": "verse",
                            "identity_fields": ["chapter", "verse"],
                            "canonical_ref_template": "{chapter}:{verse}",
                            "matched_units": 1,
                            "matched_pages": [1],
                            "examples": [
                                {
                                    "canonical_reference": "1:1",
                                    "groups": {"chapter": 1, "verse": "1"},
                                    "page": 1,
                                    "raw": "[1:1]",
                                }
                            ],
                        }
                    ],
                }
            }
        )


def test_validate_custom_json_rejects_invalid_execution_status():
    with pytest.raises(ValueError, match=r"reference_contract_execution\.status"):
        validate_custom_json(
            {
                "reference_contract_execution": {
                    "status": "trusted",
                    "matched_units": 0,
                    "matched_pages": [],
                }
            }
        )
