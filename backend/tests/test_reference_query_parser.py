from ragstudio.services.reference_query_parser import (
    parse_legacy_reference_query,
    parse_query_references,
)


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


def test_legacy_reference_query_is_only_compatibility_parser():
    assert parse_legacy_reference_query("Book 13, Hadith 25 and 2:255") == [
        "2:255",
        "book:13:hadith:25",
    ]
