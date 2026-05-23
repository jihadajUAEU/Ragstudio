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
                        "regex": r"(?P<chapter>\d{1,4}):(?P<verse>\d{1,4})",
                        "verified": True,
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
    assert contract["reference_contract"]["verified"] is True
    assert contract["parser_contract"]["required_text_validation_stage"] == (
        "post_recovery_quality_gate"
    )
    assert contract["layout_context"]["vision_recovery_enabled"] is True
    assert contract["retrieval_contract"]["source_of_truth"] == "postgres_canonical_evidence"


def test_index_contract_enables_preflight_for_verified_custom_contract():
    options = IndexDocumentIn(
        domain_metadata=DomainMetadata(
            domain="archive",
            custom_json={
                "reference_schema": {
                    "type": "folio_line",
                    "fields": {"folio": "folio", "line": "line"},
                    "canonical_ref_template": "folio:{folio}:line:{line}",
                },
                "domain_structure": {
                    "primary_anchor": {
                        "regex": r"Folio\s+(?P<folio>\d+)\s+Line\s+(?P<line>\d+)",
                        "unit": "folio_line",
                        "verified": True,
                    }
                },
                "reference_resolution": {
                    "enabled": True,
                    "build_canonical_units": True,
                },
                "quality_policy": {
                    "required_scripts_by_unit_role": {"folio_line": ["latin"]},
                },
                "preprocessing_policy": {"strict_pdf_text_preflight": True},
                "reference_contract_validation": {
                    "status": "verified",
                    "selected_strategy": "single_anchor",
                    "selected_primary_anchor_regex": (
                        r"Folio\s+(?P<folio>\d+)\s+Line\s+(?P<line>\d+)"
                    ),
                    "matched_units": 2,
                    "matched_pages": [1],
                },
            },
        )
    )

    contract = build_document_index_contract(options)

    assert contract["contract_status"] == "compiled_reference_contract"
    assert contract["reference_contract"]["verified"] is True
    assert contract["reference_contract"]["schema_type"] == "folio_line"
    assert contract["reference_contract"]["canonical_ref_template"] == (
        "folio:{folio}:line:{line}"
    )
    assert contract["reference_contract"]["required_groups"] == ["folio", "line"]
    assert contract["reference_contract"]["anchors"] == [
        {
            "kind": "primary_anchor",
            "regex": r"Folio\s+(?P<folio>\d+)\s+Line\s+(?P<line>\d+)",
            "unit_role": "folio_line",
            "context_source": None,
            "policy": None,
            "verified": True,
        }
    ]
    assert contract["preprocessing"]["strict_pdf_text_preflight"] is True


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
                        "regex": r"(?P<chapter>\d{1,4}):(?P<verse>\d{1,4})",
                        "verified": True,
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


def test_build_document_index_contract_derives_preflight_from_quality_policy():
    options = IndexDocumentIn(
        domain_metadata=DomainMetadata(
            domain="quran",
            script="arabic, english",
            custom_json={
                "reference_schema": {"type": "chapter_verse"},
                "chunking": {"unit": "verse"},
                "domain_structure": {
                    "primary_anchor": {
                        "regex": r"\[(?P<chapter>\d{1,4}):(?P<verse>\d{1,4})\]",
                        "verified": True,
                    }
                },
                "reference_resolution": {
                    "enabled": True,
                    "build_canonical_units": True,
                },
                "quality_policy": {
                    "evidence": [
                        {"page": 2, "observation": "Arabic and English text"},
                        {"page": 3, "observation": "Arabic and English text"},
                    ],
                    "required_scripts": ["arabic", "latin"],
                    "missing_required_script_action": "block",
                },
            },
        )
    )

    contract = build_document_index_contract(options)

    assert contract["vision_analysis"]["sample_pages"] == [2, 3]
    assert contract["vision_analysis"]["expected_scripts"] == ["arabic", "latin"]
    assert contract["vision_analysis"]["observed_unit_pattern"] == (
        "reference_units_with_verse_content"
    )
    assert contract["preprocessing"]["strict_pdf_text_preflight"] is True
    assert contract["preprocessing"]["expected_scripts"] == ["arabic", "latin"]
    assert contract["preprocessing"]["sample_pages"] == [2, 3]
    assert contract["preprocessing"]["cleanup_recommended"] is True
    assert contract["preprocessing"]["reject_if_cleanup_fails"] is True


def test_build_document_index_contract_treats_unverified_reference_as_metadata_only():
    options = IndexDocumentIn(
        domain_metadata=DomainMetadata(
            domain="quran",
            custom_json={
                "reference_schema": {"type": "chapter_verse"},
                "chunking": {"unit": "verse"},
                "domain_structure": {
                    "primary_anchor": {
                        "regex": r"\[(?P<chapter>\d{1,4}):(?P<verse>\d{1,4})\]",
                        "verified": False,
                    }
                },
                "reference_resolution": {
                    "enabled": True,
                    "build_canonical_units": True,
                },
                "quality_policy": {
                    "required_scripts": ["arabic", "latin"],
                    "missing_required_script_action": "block",
                },
            },
        )
    )

    contract = build_document_index_contract(options)

    assert contract["contract_status"] == "metadata_only"
    assert contract["reference_contract"]["verified"] is False
    assert contract["preprocessing"]["strict_pdf_text_preflight"] is False
    assert contract["preprocessing"]["cleanup_recommended"] is False


def test_build_document_index_contract_uses_contextual_strategy_when_primary_incomplete():
    options = IndexDocumentIn(
        domain_metadata=DomainMetadata(
            domain="archive",
            custom_json={
                "reference_schema": {
                    "type": "folio_line",
                    "fields": {"folio": "folio", "line": "line"},
                    "canonical_ref_template": "folio:{folio}:line:{line}",
                },
                "domain_structure": {
                    "primary_anchor": {
                        "regex": r"Folio\s+(?P<folio>\d+)",
                        "unit": "folio_line",
                        "verified": True,
                    },
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
                "reference_resolution": {
                    "enabled": True,
                    "build_canonical_units": True,
                },
                "preprocessing_policy": {"strict_pdf_text_preflight": True},
            },
        )
    )

    contract = build_document_index_contract(options)

    assert contract["contract_status"] == "compiled_reference_contract"
    assert contract["reference_contract"]["verified"] is True
    assert contract["reference_contract"]["strategy"] == "contextual_unit"
    assert contract["reference_contract"]["primary_anchor_regex"] is None
    assert contract["reference_contract"]["context_anchor_regex"] == (
        r"Folio\s+(?P<folio>\d+)"
    )
    assert contract["reference_contract"]["unit_anchor_regex"] == (
        r"Line\s+(?P<line>\d+)"
    )


def test_build_document_index_contract_rejects_fake_verified_validation_status():
    options = IndexDocumentIn(
        domain_metadata=DomainMetadata(
            domain="quran",
            custom_json={
                "reference_schema": {"type": "chapter_verse"},
                "reference_contract_validation": {
                    "status": "verified",
                    "selected_strategy": "single_anchor",
                    "selected_primary_anchor_regex": r"\[(?P<chapter>\d+):(?P<verse>\d+)\]",
                },
                "reference_resolution": {
                    "enabled": True,
                    "build_canonical_units": True,
                },
                "quality_policy": {
                    "required_scripts": ["arabic", "latin"],
                    "missing_required_script_action": "block",
                },
            },
        )
    )

    contract = build_document_index_contract(options)

    assert contract["contract_status"] == "metadata_only"
    assert contract["reference_contract"]["verified"] is False
    assert contract["reference_contract"]["primary_anchor_regex"] is None
    assert contract["preprocessing"]["strict_pdf_text_preflight"] is False
    assert contract["preprocessing"]["cleanup_recommended"] is False


def test_build_document_index_contract_uses_sibling_layout_quality_failure_policy():
    options = IndexDocumentIn(
        domain_metadata=DomainMetadata(
            domain="quran",
            custom_json={
                "reference_schema": {"type": "chapter_verse"},
                "chunking": {"unit": "verse"},
                "domain_structure": {
                    "primary_anchor": {
                        "regex": r"\[(?P<chapter>\d{1,4}):(?P<verse>\d{1,4})\]",
                    },
                },
                "reference_resolution": {
                    "enabled": True,
                    "build_canonical_units": True,
                },
                "quality_policy": {
                    "required_scripts": ["arabic", "latin"],
                },
                "layout_quality_policy": {
                    "failure_policy": {
                        "missing_required_script": "block",
                    },
                },
            },
        )
    )

    contract = build_document_index_contract(options)

    assert contract["preprocessing"]["reject_if_cleanup_fails"] is True
