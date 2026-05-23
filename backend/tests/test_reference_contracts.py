from ragstudio.services.reference_contracts import (
    build_executable_reference_contract,
    canonical_reference_from_groups,
    declared_required_groups,
)


def test_declared_groups_come_from_fields_and_template_not_schema_family():
    metadata = {
        "reference_schema": {
            "type": "folio_line",
            "canonical_ref_template": "folio:{folio}:line:{line}",
            "fields": {"folio": "folio_number", "line": "line_number"},
        },
        "domain_structure": {
            "primary_anchor": {
                "regex": r"Folio\s+(?P<folio>\d+)\s+Line\s+(?P<line>\d+)",
                "unit": "folio_line",
                "verified": True,
            }
        },
    }

    assert declared_required_groups(metadata) == {"folio", "line"}


def test_canonical_reference_uses_declared_template():
    assert (
        canonical_reference_from_groups(
            {"folio": "12", "line": "7"},
            "folio:{folio}:line:{line}",
        )
        == "folio:12:line:7"
    )


def test_executable_contract_preserves_custom_strategy_and_anchors():
    metadata = {
        "reference_schema": {
            "type": "article_clause",
            "canonical_ref_template": "article:{article}:clause:{clause}",
            "fields": {"article": "article_number", "clause": "clause_number"},
        },
        "domain_structure": {
            "primary_anchor": {
                "regex": r"Article\s+(?P<article>\d+)\.(?P<clause>\d+)",
                "unit": "article_clause",
                "verified": True,
            }
        },
        "quality_policy": {
            "required_scripts_by_unit_role": {"article_clause": ["latin"]},
            "optional_scripts": [],
        },
    }

    contract = build_executable_reference_contract(metadata)

    assert contract.schema_type == "article_clause"
    assert contract.required_groups == frozenset({"article", "clause"})
    assert contract.anchors[0].kind == "primary_anchor"
    assert contract.anchors[0].unit_role == "article_clause"
    assert contract.anchors[0].group_names == frozenset({"article", "clause"})
    assert contract.verified is True
    assert contract.required_scripts_for_role("article_clause") == frozenset(
        {"latin"}
    )


def test_verified_inline_anchor_alone_is_not_executable():
    metadata = {
        "reference_schema": {
            "type": "folio_note",
            "canonical_ref_template": "folio:{folio}",
            "fields": {"folio": "folio_number"},
        },
        "domain_structure": {
            "inline_references": {
                "regex": r"folio\s+(?P<folio>\d+)",
                "unit": "folio_note",
                "verified": True,
            }
        },
    }

    contract = build_executable_reference_contract(metadata)

    assert contract.anchor_group_names("inline_references", require_verified=True) == frozenset(
        {"folio"}
    )
    assert contract.executable_anchor_group_names == frozenset()
    assert contract.missing_required_groups == frozenset({"folio"})
    assert contract.verified is False


def test_verified_primary_anchor_missing_required_template_field_is_not_executable():
    metadata = {
        "reference_schema": {
            "type": "folio_line",
            "canonical_ref_template": "folio:{folio}:line:{line}",
            "fields": {"folio": "folio_number", "line": "line_number"},
        },
        "domain_structure": {
            "primary_anchor": {
                "regex": r"Folio\s+(?P<folio>\d+)",
                "unit": "folio_line",
                "verified": True,
            }
        },
    }

    contract = build_executable_reference_contract(metadata)

    assert contract.declared_executable_anchor_group_names == frozenset({"folio"})
    assert contract.executable_anchor_group_names == frozenset()
    assert contract.missing_required_groups == frozenset({"line"})
    assert contract.verified is False


def test_verified_context_and_unit_anchors_satisfy_declared_required_groups():
    metadata = {
        "reference_schema": {
            "type": "folio_line",
            "canonical_ref_template": "folio:{folio}:line:{line}",
            "fields": {"folio": "folio_number", "line": "line_number"},
        },
        "domain_structure": {
            "context_anchor": {
                "regex": r"Folio\s+(?P<folio>\d+)",
                "unit": "folio",
                "verified": True,
            },
            "unit_anchor": {
                "regex": r"Line\s+(?P<line>\d+)",
                "unit": "line",
                "verified": True,
            },
        },
    }

    contract = build_executable_reference_contract(metadata)

    assert contract.executable_anchor_group_names == frozenset({"folio", "line"})
    assert contract.missing_required_groups == frozenset()
    assert contract.verified is True
