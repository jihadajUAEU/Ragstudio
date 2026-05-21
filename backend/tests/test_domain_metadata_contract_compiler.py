import pytest
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.domain_metadata_contract_compiler import (
    DomainMetadataContractError,
    compile_domain_metadata,
    validate_executable_reference_contract,
)
from ragstudio.services.reference_metadata import ReferenceSemantics


def test_compiler_turns_vision_quran_metadata_into_executable_contract():
    metadata = DomainMetadata(
        domain="quran",
        document_type="translation",
        citation_style="surah:verse",
        reference_pattern=r"\[\d+:\d+\]",
        tags=["quran", "translation"],
        metadata_sources=["ai_vision"],
        custom_json={
            "reference_schema": {"type": "surah:verse"},
            "chunking": {"unit": "verse"},
            "domain_structure": {
                "primary_anchor": {"type": "surah:verse", "unit": "verse"},
                "inline_references": {
                    "type": "surah:verse",
                    "policy": "cross_reference_only",
                },
            },
        },
    )

    compiled = compile_domain_metadata(metadata)

    custom_json = compiled.custom_json
    assert custom_json["reference_schema"]["type"] == "chapter_verse"
    assert custom_json["reference_schema"]["canonical_ref_template"] == "{chapter}:{verse}"
    assert custom_json["domain_structure"]["primary_anchor"]["regex"]
    assert custom_json["domain_structure"]["inline_references"]["regex"]
    assert custom_json["reference_resolution"]["enabled"] is True
    assert custom_json["reference_resolution"]["build_canonical_units"] is True
    assert custom_json["quality_policy"]["reference_contract_gate"] == {
        "enabled": True,
        "action": "block",
        "required": [
            "reference_schema.type",
            "domain_structure.primary_anchor.regex",
            "reference_resolution.build_canonical_units",
        ],
        "reference_family": "chapter_verse",
    }

    validate_executable_reference_contract(compiled)
    semantics = ReferenceSemantics.from_metadata(compiled)
    assert semantics.canonical_units_enabled is True
    assert semantics.derive_reference_metadata("[43:74]\nEnglish translation.")[
        "references"
    ] == ["43:74"]


def test_reference_contract_gate_rejects_bad_primary_anchor_groups():
    metadata = DomainMetadata(
        domain="quran",
        tags=["quran"],
        custom_json={
            "reference_schema": {"type": "chapter_verse"},
            "chunking": {"unit": "verse"},
            "domain_structure": {
                "primary_anchor": {
                    "type": "chapter_verse",
                    "unit": "verse",
                    "regex": r"\[(?P<chapter>\d{1,4})\]",
                }
            },
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
            },
        },
    )

    with pytest.raises(DomainMetadataContractError, match="verse"):
        validate_executable_reference_contract(metadata)


def test_compiler_preserves_hadith_contract_defaults():
    metadata = DomainMetadata(
        domain="hadith",
        document_type="collection",
        tags=["hadith"],
        custom_json={
            "reference_schema": {"type": "hadith_reference"},
            "chunking": {"unit": "hadith"},
        },
    )

    compiled = compile_domain_metadata(metadata)

    assert compiled.custom_json["reference_schema"]["type"] == "book_hadith"
    assert "book" in compiled.custom_json["domain_structure"]["primary_anchor"]["regex"]
    assert compiled.custom_json["reference_resolution"]["build_canonical_units"] is True
    validate_executable_reference_contract(compiled)
