from ragstudio.services.reference_query_parser import parse_query_references


def test_parse_query_references_uses_contract_patterns():
    contracts = [
        {
            "reference_contract": {
                "verified": True,
                "canonical_ref_template": "article:{article}:clause:{clause}",
                "anchors": [
                    {
                        "kind": "primary_anchor",
                        "regex": r"Article\s+(?P<article>\d+)\.(?P<clause>\d+)",
                    }
                ],
            }
        }
    ]

    assert parse_query_references("show Article 12.7", contracts) == [
        "article:12:clause:7"
    ]


def test_parse_query_references_uses_verified_canonical_template_without_anchors():
    contracts = [
        {
            "reference_contract": {
                "verified": True,
                "canonical_ref_template": "{chapter}:{verse}",
                "required_groups": ["chapter", "verse"],
            }
        }
    ]

    assert parse_query_references("show 19:13.", contracts) == ["19:13"]


def test_parse_query_references_uses_contextual_contract_patterns():
    contracts = [
        {
            "reference_contract": {
                "verified": True,
                "canonical_ref_template": "{chapter}:{verse}",
                "anchors": [
                    {
                        "kind": "context_anchor",
                        "regex": r"\bSurah\s+(?P<chapter>\d+)\b",
                    },
                    {
                        "kind": "unit_anchor",
                        "regex": r"\bAyah\s+(?P<verse>\d+)\b",
                    },
                ],
            }
        }
    ]

    assert parse_query_references("show Surah 7 Ayah 104", contracts) == ["7:104"]


def test_query_reference_parser_ignores_unverified_contracts():
    references = parse_query_references(
        "Find 7:104",
        [
            {
                "reference_contract": {
                    "verified": False,
                    "canonical_ref_template": "{parent_ref}:{unit_ref}",
                }
            }
        ],
    )

    assert references == []


def test_query_reference_parser_has_no_legacy_reference_fallback():
    assert parse_query_references("Find 7:104", []) == []
    assert parse_query_references("Book 13, Hadith 25", []) == []
