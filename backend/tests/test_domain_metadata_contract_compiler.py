import pytest
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn, MinerUParseOptionsIn
from ragstudio.services.domain_metadata_contract_compiler import (
    DomainMetadataContractError,
    compile_domain_metadata,
    compile_index_options,
    validate_executable_reference_contract,
)
from ragstudio.services.reference_contracts import build_executable_reference_contract


def single_anchor_validation(regex: str) -> dict[str, object]:
    return {
        "status": "verified",
        "selected_strategy": "single_anchor",
        "selected_primary_anchor_regex": regex,
        "matched_units": 2,
        "matched_pages": [1],
    }


def contextual_validation(context_regex: str, unit_regex: str) -> dict[str, object]:
    return {
        "status": "verified",
        "selected_strategy": "contextual_unit",
        "selected_context_anchor_regex": context_regex,
        "selected_unit_anchor_regex": unit_regex,
        "matched_units": 2,
        "matched_pages": [1],
    }


def test_custom_folio_line_contract_gets_generic_gate_without_family_rewrite():
    primary_regex = r"Folio\s+(?P<folio>\d+)\s+Line\s+(?P<line>\d+)"
    metadata = DomainMetadata(
        domain="manuscript",
        document_type="folio",
        tags=["archive"],
        custom_json={
            "reference_schema": {
                "type": "folio_line",
                "canonical_ref_template": "folio:{folio}:line:{line}",
                "fields": {
                    "folio": "folio_number",
                    "line": "line_number",
                },
            },
            "chunking": {"unit": "folio_line"},
            "domain_structure": {
                "primary_anchor": {
                    "regex": primary_regex,
                    "unit": "folio_line",
                    "verified": True,
                }
            },
            "reference_contract_validation": single_anchor_validation(primary_regex),
        },
    )

    compiled = compile_domain_metadata(metadata)

    custom_json = compiled.custom_json
    assert custom_json["reference_schema"] == metadata.custom_json["reference_schema"]
    assert custom_json["domain_structure"]["primary_anchor"] == {
        "regex": primary_regex,
        "unit": "folio_line",
        "verified": True,
        "type": "folio_line",
    }
    assert custom_json["reference_resolution"]["enabled"] is True
    assert custom_json["reference_resolution"]["build_canonical_units"] is True
    assert custom_json["provenance"] == {
        "preserve_original_blocks": True,
        "block_preview_chars": 160,
        "store_text_hash": True,
    }
    assert custom_json["quality_policy"]["reference_contract_gate"] == {
        "enabled": True,
        "action": "block",
        "required": [
            "reference_schema.type",
            "domain_structure.primary_anchor.regex",
            "reference_resolution.build_canonical_units",
        ],
    }

    validate_executable_reference_contract(compiled)


def test_quran_like_contract_uses_template_identity_groups_not_all_fields():
    primary_regex = r"\[(?P<chapter>\d{1,4}):(?P<verse>\d{1,4})\]"
    metadata = DomainMetadata(
        domain="quran",
        document_type="translation",
        citation_style="surah:verse",
        tags=["quran", "translation"],
        custom_json={
            "reference_schema": {
                "type": "quran_tafseer",
                "canonical_ref_template": "{chapter}:{verse}",
                "fields": {
                    "chapter": "chapter_number",
                    "verse": "verse_number",
                    "page": "page_number",
                },
            },
            "chunking": {"unit": "verse"},
            "domain_structure": {
                "primary_anchor": {
                    "regex": primary_regex,
                    "unit": "verse",
                    "verified": True,
                }
            },
            "reference_contract_validation": single_anchor_validation(primary_regex),
        },
    )

    compiled = compile_domain_metadata(metadata)

    assert compiled.custom_json["reference_schema"]["type"] == "quran_tafseer"
    assert compiled.custom_json["reference_schema"]["fields"]["page"] == "page_number"
    validate_executable_reference_contract(compiled)


def test_compile_domain_metadata_accepts_execution_verified_contract():
    metadata = DomainMetadata(
        domain="scripture",
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "fields": {"chapter": "chapter", "verse": "verse"},
                "canonical_ref_template": "{chapter}:{verse}",
            },
            "domain_structure": {
                "primary_anchor": {
                    "type": "chapter_verse",
                    "regex": r"\[(?P<chapter>\d{1,3}):(?P<verse>\d{1,3})\]",
                    "unit": "verse",
                    "verified": True,
                }
            },
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
            },
            "reference_contract_execution": {
                "status": "verified",
                "matched_units": 2,
                "matched_pages": [1],
            },
        },
    )

    compiled = compile_domain_metadata(metadata)
    contract = build_executable_reference_contract(compiled.custom_json)

    assert contract.verified is True
    assert compiled.custom_json["reference_resolution"]["build_canonical_units"] is True
    assert compiled.custom_json["quality_policy"]["reference_contract_gate"]["enabled"] is True


def test_compile_domain_metadata_leaves_failed_execution_as_metadata_only_hint():
    metadata = DomainMetadata(
        domain="scripture",
        custom_json={
            "reference_schema": {"type": "chapter_verse"},
            "reference_contract_execution": {
                "status": "unverified",
                "matched_units": 0,
                "matched_pages": [],
                "reports": [
                    {
                        "status": "unverified",
                        "schema_type": "chapter_verse",
                        "rejection_reason": "identity_fields_missing_from_extractor",
                    }
                ],
            },
        },
    )

    compiled = compile_domain_metadata(metadata)
    contract = build_executable_reference_contract(compiled.custom_json)

    assert contract.verified is False
    assert contract.required_groups == frozenset()
    assert "reference_resolution" not in compiled.custom_json


def test_compile_domain_metadata_demotes_stale_anchor_after_failed_execution():
    metadata = DomainMetadata(
        domain="scripture",
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "fields": {"chapter": "chapter", "verse": "verse"},
                "canonical_ref_template": "{chapter}:{verse}",
            },
            "domain_structure": {
                "primary_anchor": {
                    "type": "chapter_verse",
                    "regex": r"\[(?P<chapter>\d{1,3}):(?P<verse>\d{1,3})\]",
                    "unit": "verse",
                    "verified": True,
                }
            },
            "reference_contract_execution": {
                "status": "unverified",
                "matched_units": 0,
                "matched_pages": [],
            },
        },
    )

    compiled = compile_domain_metadata(metadata)
    contract = build_executable_reference_contract(compiled.custom_json)

    assert compiled.custom_json["domain_structure"]["primary_anchor"]["verified"] is False
    assert contract.verified is False
    assert "reference_resolution" not in compiled.custom_json


def test_domain_and_tags_without_declared_anchors_do_not_create_reference_contract():
    metadata = DomainMetadata(
        domain="quran",
        citation_style="surah:verse",
        tags=["quran", "clearquran"],
        custom_json={
            "quality_policy": {"observed_scripts": ["arabic", "latin"]},
        },
    )

    compiled = compile_domain_metadata(metadata)

    custom_json = compiled.custom_json
    assert "reference_schema" not in custom_json
    assert "domain_structure" not in custom_json
    assert "reference_resolution" not in custom_json
    assert custom_json["quality_policy"] == {"observed_scripts": ["arabic", "latin"]}


def test_bad_verified_primary_anchor_raises_for_contract_missing_groups():
    metadata = DomainMetadata(
        domain="manuscript",
        custom_json={
            "reference_schema": {
                "type": "folio_line",
                "canonical_ref_template": "folio:{folio}:line:{line}",
                "fields": {
                    "folio": "folio_number",
                    "line": "line_number",
                },
            },
            "domain_structure": {
                "primary_anchor": {
                    "regex": r"Folio\s+(?P<folio>\d+)",
                    "unit": "folio_line",
                    "verified": True,
                }
            },
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
            },
        },
    )

    with pytest.raises(DomainMetadataContractError, match="line"):
        validate_executable_reference_contract(metadata)


def test_unverified_bad_primary_anchor_raises_when_reference_chunking_requested():
    metadata = DomainMetadata(
        domain="manuscript",
        custom_json={
            "reference_schema": {
                "type": "folio_line",
                "canonical_ref_template": "folio:{folio}:line:{line}",
                "fields": {
                    "folio": "folio_number",
                    "line": "line_number",
                },
            },
            "chunking": {"unit": "folio_line"},
            "domain_structure": {
                "primary_anchor": {
                    "regex": r"Folio\s+(?P<folio>\d+)",
                    "unit": "folio_line",
                    "verified": False,
                }
            },
        },
    )

    compiled = compile_domain_metadata(metadata)

    with pytest.raises(DomainMetadataContractError, match="reference_resolution\\.enabled"):
        validate_executable_reference_contract(compiled)


def test_unverified_malformed_template_raises_when_reference_chunking_requested():
    metadata = DomainMetadata(
        domain="manuscript",
        custom_json={
            "reference_schema": {
                "type": "folio_line",
                "canonical_ref_template": "folio:{folio:line:{line}",
                "fields": {
                    "folio": "folio_number",
                    "line": "line_number",
                },
            },
            "chunking": {"unit": "folio_line"},
            "domain_structure": {
                "primary_anchor": {
                    "regex": r"Folio\s+(?P<folio>\d+)\s+Line\s+(?P<line>\d+)",
                    "unit": "folio_line",
                    "verified": False,
                }
            },
        },
    )

    compiled = compile_domain_metadata(metadata)

    with pytest.raises(DomainMetadataContractError, match="canonical_ref_template"):
        validate_executable_reference_contract(compiled)


def test_contextual_anchor_pair_can_satisfy_contract_when_primary_is_incomplete():
    context_regex = r"Folio\s+(?P<folio>\d+)"
    unit_regex = r"Line\s+(?P<line>\d+)"
    metadata = DomainMetadata(
        domain="manuscript",
        custom_json={
            "reference_schema": {
                "type": "folio_line",
                "canonical_ref_template": "folio:{folio}:line:{line}",
                "fields": {
                    "folio": "folio_number",
                    "line": "line_number",
                },
            },
            "chunking": {"unit": "line"},
            "domain_structure": {
                "primary_anchor": {
                    "regex": context_regex,
                    "unit": "folio_line",
                    "verified": True,
                },
                "context_anchor": {
                    "regex": context_regex,
                    "unit": "folio",
                    "verified": True,
                },
                "unit_anchor": {
                    "regex": unit_regex,
                    "unit": "line",
                    "verified": True,
                },
            },
            "reference_contract_validation": contextual_validation(context_regex, unit_regex),
        },
    )

    compiled = compile_domain_metadata(metadata)

    assert compiled.custom_json["quality_policy"]["reference_contract_gate"]["required"] == [
        "reference_schema.type",
        "domain_structure.context_anchor.regex",
        "domain_structure.unit_anchor.regex",
        "reference_resolution.build_canonical_units",
    ]
    validate_executable_reference_contract(compiled)


def test_domain_label_no_longer_forces_mineru_parser_hints():
    options = compile_index_options(
        IndexDocumentIn(
            domain_metadata=DomainMetadata(
                domain="quran",
                script="arabic",
                reference_pattern="surah:verse",
                custom_json={"chunking": {"unit": "verse"}},
            )
        )
    )

    assert options.mineru_parse_options is None


def test_compile_index_options_preserves_explicit_mineru_parser_hints():
    options = compile_index_options(
        IndexDocumentIn(
            domain_metadata=DomainMetadata(
                domain="quran",
                script="arabic",
                reference_pattern="surah:verse",
                custom_json={"chunking": {"unit": "verse"}},
            ),
            mineru_parse_options=MinerUParseOptionsIn(
                parse_method="auto",
                lang="en",
                table=True,
                formula=True,
            ),
        )
    )

    assert options.mineru_parse_options is not None
    assert options.mineru_parse_options.parse_method == "auto"
    assert options.mineru_parse_options.lang == "en"
    assert options.mineru_parse_options.table is True
    assert options.mineru_parse_options.formula is True


def test_compile_index_options_uses_explicit_custom_json_mineru_hints():
    options = compile_index_options(
        IndexDocumentIn(
            domain_metadata=DomainMetadata(
                custom_json={
                    "mineru_parse_options": {
                        "parser": "mineru",
                        "parse_method": "ocr",
                        "lang": "arabic",
                        "formula": False,
                        "table": False,
                        "max_concurrent_files": 1,
                    }
                },
            ),
        )
    )

    assert options.mineru_parse_options is not None
    assert options.mineru_parse_options.parser == "mineru"
    assert options.mineru_parse_options.parse_method == "ocr"
    assert options.mineru_parse_options.lang == "arabic"
    assert options.mineru_parse_options.table is False
    assert options.mineru_parse_options.formula is False
    assert options.mineru_parse_options.max_concurrent_files == 1
