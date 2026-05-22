from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn
from ragstudio.services.document_contract import build_document_index_contract


def test_build_document_index_contract_marks_reference_contract_ready():
    options = IndexDocumentIn(
        domain_metadata=DomainMetadata(
            domain="quran_tafseer",
            language="arabic",
            custom_json={
                "reference_schema": {"type": "chapter_verse"},
                "chunking": {"unit": "verse"},
                "domain_structure": {
                    "primary_anchor": {
                        "regex": r"(?P<chapter>\d{1,4}):(?P<verse>\d{1,4})"
                    }
                },
                "reference_resolution": {
                    "enabled": True,
                    "build_canonical_units": True,
                },
                "vision_recovery_policy": {"enabled": True},
            },
        )
    )

    contract = build_document_index_contract(options)

    assert contract["contract_status"] == "compiled_reference_contract"
    assert contract["domain_metadata"]["domain"] == "quran_tafseer"
    assert contract["reference_contract"]["schema_type"] == "chapter_verse"
    assert contract["reference_contract"]["canonical_units"] is True
    assert contract["parser_contract"]["required_text_validation_stage"] == (
        "post_recovery_quality_gate"
    )
    assert contract["layout_context"]["vision_recovery_enabled"] is True
    assert contract["retrieval_contract"]["source_of_truth"] == "postgres_canonical_evidence"


def test_build_document_index_contract_marks_generic_metadata():
    contract = build_document_index_contract(IndexDocumentIn())

    assert contract["contract_status"] == "generic"
    assert contract["reference_contract"]["schema_type"] is None
    assert contract["reference_contract"]["canonical_units"] is False
    assert contract["layout_context"]["vision_recovery_enabled"] is False


def test_build_document_index_contract_persists_parser_layout_hints():
    options = IndexDocumentIn(
        domain_metadata=DomainMetadata(
            domain="quran",
            script="arabic",
            reference_pattern="surah:verse",
            custom_json={
                "reference_schema": {"type": "chapter_verse"},
                "chunking": {"unit": "verse"},
                "domain_structure": {
                    "primary_anchor": {
                        "regex": r"(?P<chapter>\d{1,4}):(?P<verse>\d{1,4})"
                    }
                },
                "reference_resolution": {
                    "enabled": True,
                    "build_canonical_units": True,
                },
                "vision_recovery_policy": {"enabled": True},
            },
        ),
        mineru_parse_options={
            "parse_method": "ocr",
            "lang": "arabic",
            "table": False,
            "formula": False,
        },
    )

    contract = build_document_index_contract(options)

    assert contract["parser_contract"]["mineru_parse_options"] == {
        "parse_method": "ocr",
        "lang": "arabic",
        "formula": False,
        "table": False,
    }
    assert contract["layout_context"]["expected_tables"] is False
    assert contract["layout_context"]["expected_equations"] is False
    assert contract["layout_context"]["image_blocks_are_recovery_candidates"] is True
