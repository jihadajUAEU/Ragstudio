from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.domain_metadata_service import DomainMetadataService
from ragstudio.services.reference_metadata import ReferenceSemantics


def quran_metadata() -> DomainMetadata:
    return DomainMetadata(
        domain="religion",
        document_type="religious_text",
        tags=["quran", "islam", "translation"],
        expected_structure="parallel_text",
        reference_pattern="surah_number:verse_number",
        script="arabic_latin",
        content_role="primary_text",
        custom_json={
            "reference_schema": {
                "type": "surah_ayah",
                "display": "Quran {chapter}:{verse}",
                "fields": {
                    "chapter": "surah",
                    "verse": "ayah",
                    "page": "page_start",
                },
            },
            "relationships": {
                "previous": ["same_chapter", "verse - 1"],
                "next": ["same_chapter", "verse + 1"],
                "chapter": ["same_chapter"],
                "page": ["same_page"],
            },
            "chunking": {
                "unit": "verse",
                "include_neighbors": 1,
                "preserve_parallel_text": True,
            },
            "retrieval": {
                "exact_reference_top1": True,
                "boost_same_parent_reference": True,
                "boost_neighbor_references": True,
            },
        },
    )


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


def verified_quran_metadata() -> DomainMetadata:
    metadata = quran_metadata()
    custom_json = dict(metadata.custom_json or {})
    reference_schema = dict(custom_json["reference_schema"])
    reference_schema["canonical_ref_template"] = "{chapter}:{verse}"
    custom_json["reference_schema"] = reference_schema
    primary_regex = r"(?:\bQuran\s+|\[)?(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})\]?"
    custom_json["domain_structure"] = {
        "primary_anchor": {
            "regex": primary_regex,
            "unit": "verse",
            "verified": True,
        },
        "inline_references": {"policy": "starts_unit"},
    }
    custom_json["reference_resolution"] = {
        "enabled": True,
        "build_canonical_units": True,
    }
    custom_json["reference_contract_validation"] = single_anchor_validation(primary_regex)
    return metadata.model_copy(update={"custom_json": custom_json})


def test_reference_semantics_detects_scripture_profile_from_metadata_json():
    semantics = ReferenceSemantics.from_metadata(quran_metadata())

    assert semantics.profile_name == "reference_hint"
    assert semantics.reference_capability == "hint"
    assert semantics.reference_type == "surah_ayah"
    assert semantics.chunk_unit == "verse"
    assert semantics.include_neighbors == 1
    assert semantics.exact_reference_top1 is True
    assert semantics.preserve_parallel_text is True
    assert semantics.boost_same_parent_reference is True
    assert semantics.boost_neighbor_references is True
    assert semantics.relationships["previous"] == ["same_chapter", "verse - 1"]


def test_reference_semantics_does_not_infer_contract_from_standard_metadata_fields():
    metadata = DomainMetadata(
        domain="religion",
        document_type="religious_text",
        tags=["quran"],
        reference_pattern="surah_number:verse_number",
        expected_structure="parallel_text",
    )

    semantics = ReferenceSemantics.from_metadata(metadata)

    assert semantics.profile_name == "generic"
    assert semantics.reference_capability == "none"
    assert semantics.reference_type is None
    assert semantics.chunk_unit == "section"
    assert semantics.exact_reference_top1 is False
    assert semantics.preserve_parallel_text is True


def test_reference_semantics_supports_generic_chapter_verse_schema():
    metadata = DomainMetadata(
        domain="literature",
        document_type="commentary",
        reference_pattern="chapter_number:verse_number",
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "fields": {"chapter": "chapter", "verse": "verse"},
            },
            "chunking": {"unit": "stanza", "include_neighbors": "2"},
            "retrieval": {"exact_reference_top1": False},
        },
    )

    semantics = ReferenceSemantics.from_metadata(metadata)

    assert semantics.profile_name == "reference_hint"
    assert semantics.reference_capability == "hint"
    assert semantics.reference_type == "chapter_verse"
    assert semantics.chunk_unit == "stanza"
    assert semantics.include_neighbors == 2
    assert semantics.exact_reference_top1 is False


def test_metadata_only_reference_schema_does_not_enable_enforcement_defaults():
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(
            custom_json={
                "reference_schema": {
                    "type": "parent_item",
                    "fields": {"parent_ref": "parent", "unit_ref": "unit"},
                    "canonical_ref_template": "{parent_ref}:{unit_ref}",
                }
            }
        )
    )

    assert semantics.profile_name == "reference_hint"
    assert semantics.reference_capability == "hint"
    assert semantics.chunk_unit == "section"
    assert semantics.exact_reference_top1 is False
    assert semantics.boost_neighbor_references is False
    assert semantics.canonical_units_enabled is False


def test_verified_generic_reference_contract_enables_reference_defaults():
    primary_regex = r"Part\s+(?P<parent_ref>\d+)\s+Item\s+(?P<unit_ref>\d+)"
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(
            custom_json={
                "reference_schema": {
                    "type": "parent_item",
                    "fields": {"parent_ref": "parent", "unit_ref": "unit"},
                    "canonical_ref_template": "{parent_ref}:{unit_ref}",
                },
                "domain_structure": {
                    "primary_anchor": {
                        "regex": primary_regex,
                        "unit": "item",
                        "verified": True,
                    }
                },
                "reference_resolution": {
                    "enabled": True,
                    "build_canonical_units": True,
                },
                "reference_contract_validation": single_anchor_validation(primary_regex),
            }
        )
    )

    assert semantics.profile_name == "verified_reference"
    assert semantics.reference_capability == "verified"
    assert semantics.chunk_unit == "item"
    assert semantics.exact_reference_top1 is True
    assert semantics.canonical_units_enabled is True


def test_reference_metadata_records_generic_identity_ranges():
    primary_regex = r"Part\s+(?P<parent_ref>\d+)\s+Item\s+(?P<unit_ref>\d+)"
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(
            custom_json={
                "reference_schema": {
                    "type": "parent_item",
                    "fields": {"parent_ref": "parent", "unit_ref": "unit"},
                    "canonical_ref_template": "{parent_ref}:{unit_ref}",
                },
                "domain_structure": {
                    "primary_anchor": {
                        "regex": primary_regex,
                        "unit": "item",
                        "verified": True,
                    }
                },
                "reference_resolution": {"enabled": True, "build_canonical_units": True},
                "chunking": {"unit": "item", "include_neighbors": 1},
                "reference_contract_validation": single_anchor_validation(primary_regex),
            }
        )
    )

    metadata = semantics.derive_reference_metadata("Part 7 Item 104 Body text")

    assert metadata["references"] == ["7:104"]
    assert metadata["identity_ranges"] == {
        "parent_ref": {"start": 7, "end": 7},
        "unit_ref": {"start": 104, "end": 104},
    }
    assert metadata["reference_identity_range"] == metadata["identity_ranges"]
    assert metadata["previous_ref"] == "7:103"
    assert metadata["next_ref"] == "7:105"


def test_verified_generic_identity_range_does_not_emit_chapter_or_hadith_fields():
    primary_regex = r"Part\s+(?P<part>\d+),\s+Item\s+(?P<item>\d+)"
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(
            custom_json={
                "reference_schema": {
                    "type": "part_item",
                    "fields": {"part": "part", "item": "item"},
                    "canonical_ref_template": "{part}:{item}",
                },
                "domain_structure": {
                    "primary_anchor": {
                        "regex": primary_regex,
                        "unit": "item",
                        "verified": True,
                    }
                },
                "reference_resolution": {"enabled": True, "build_canonical_units": True},
                "reference_contract_validation": single_anchor_validation(primary_regex),
            }
        )
    )

    metadata = semantics.derive_reference_metadata("Part 2, Item 7", {"page": 4})

    assert metadata["reference_identity_range"] == {
        "part": {"start": 2, "end": 2},
        "item": {"start": 7, "end": 7},
    }
    assert "chapter_start" not in metadata
    assert "verse_start" not in metadata
    assert "book_start" not in metadata
    assert "hadith_start" not in metadata


def test_unverified_legacy_schema_does_not_use_builtin_reference_adapter():
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(
            reference_pattern="chapter_number:verse_number",
            custom_json={"reference_schema": {"type": "chapter_verse"}},
        )
    )

    assert semantics.reference_capability == "hint"
    assert semantics.extract_query_reference("Text [3:9]") is None
    assert semantics.derive_reference_metadata("Text [3:9]") == {}


def test_hint_chapter_verse_anchor_does_not_materialize_reference_metadata():
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(
            custom_json={
                "reference_schema": {
                    "type": "chapter_verse",
                    "fields": {"chapter": "chapter", "verse": "verse"},
                    "canonical_ref_template": "{chapter}:{verse}",
                },
                "domain_structure": {
                    "primary_anchor": {
                        "regex": r"\bVerse\s+(?P<chapter>\d{1,4}):(?P<verse>\d{1,4})\b",
                        "unit": "verse",
                        "verified": True,
                    }
                },
            }
        )
    )

    metadata = semantics.derive_reference_metadata("Verse 18:30 body.")

    assert semantics.reference_capability == "hint"
    assert metadata == {}
    assert "chapter_start" not in metadata
    assert "verse_start" not in metadata


def test_reference_semantics_extracts_custom_anchor_references():
    primary_regex = r"Folio\s+(?P<folio>\d+)\s+Line\s+(?P<line>\d+)"
    metadata = DomainMetadata(
        domain="archive",
        custom_json={
            "reference_schema": {
                "type": "folio_line",
                "fields": {"folio": "folio", "line": "line"},
                "canonical_ref_template": "folio:{folio}:line:{line}",
            },
            "domain_structure": {
                "primary_anchor": {
                    "regex": primary_regex,
                    "unit": "folio_line",
                    "verified": True,
                }
            },
            "reference_resolution": {"enabled": True, "build_canonical_units": True},
            "reference_contract_validation": single_anchor_validation(primary_regex),
        },
    )

    refs = ReferenceSemantics.from_metadata(metadata).extract_chunk_references(
        "Folio 12 Line 7 The record begins."
    )

    assert refs[0]["ref"] == "folio:12:line:7"


def test_reference_metadata_extracts_contextual_surah_verse_units():
    context_regex = r"\bSurah\s+(?P<chapter>\d{1,4})\b"
    unit_regex = r"\b(?P<verse>10[45])\b"
    metadata = DomainMetadata(
        domain="quran",
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "display": "{chapter}:{verse}",
                "canonical_ref_template": "{chapter}:{verse}",
            },
            "domain_structure": {
                "context_anchor": {
                    "type": "chapter_verse",
                    "regex": context_regex,
                    "unit": "chapter",
                    "verified": True,
                },
                "unit_anchor": {
                    "type": "chapter_verse",
                    "regex": unit_regex,
                    "unit": "verse",
                    "context_source": "context_anchor",
                    "verified": True,
                },
            },
            "reference_resolution": {"enabled": True, "build_canonical_units": True},
            "reference_contract_validation": contextual_validation(context_regex, unit_regex),
        },
    )
    semantics = ReferenceSemantics.from_metadata(metadata)

    assert semantics.chunk_unit == "verse"
    refs = semantics.extract_primary_anchor_references(
        "Surah 7\nThe Elevations\n104 Moses said...\n105 It is only proper..."
    )

    assert [ref["canonical"] for ref in refs] == ["7:104", "7:105"]


def test_contextual_reference_extraction_ignores_context_anchor_overlap():
    context_regex = r"\bSurah\s+(?P<chapter>\d{1,4})\b"
    unit_regex = r"\b(?P<verse>\d{1,4})\b"
    metadata = DomainMetadata(
        domain="quran",
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "fields": {"chapter": "chapter", "verse": "verse"},
                "canonical_ref_template": "{chapter}:{verse}",
            },
            "domain_structure": {
                "context_anchor": {
                    "regex": context_regex,
                    "unit": "chapter",
                    "verified": True,
                },
                "unit_anchor": {
                    "regex": unit_regex,
                    "unit": "verse",
                    "context_source": "context_anchor",
                    "verified": True,
                },
            },
            "reference_resolution": {"enabled": True, "build_canonical_units": True},
            "reference_contract_validation": contextual_validation(context_regex, unit_regex),
        },
    )

    refs = ReferenceSemantics.from_metadata(metadata).extract_primary_anchor_references(
        "Surah 7\nThe Elevations\n104 Moses said...\n105 It is only proper..."
    )

    assert [ref["canonical"] for ref in refs] == ["7:104", "7:105"]


def test_contextual_reference_contract_does_not_use_builtin_primary_fallback():
    context_regex = r"\bSurah\s+(?P<chapter>\d{1,4})\b"
    unit_regex = r"\bAyah\s+(?P<verse>\d{1,4})\b"
    metadata = DomainMetadata(
        domain="quran",
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "fields": {"chapter": "chapter", "verse": "verse"},
                "canonical_ref_template": "{chapter}:{verse}",
            },
            "domain_structure": {
                "context_anchor": {
                    "regex": context_regex,
                    "unit": "chapter",
                    "verified": True,
                },
                "unit_anchor": {
                    "regex": unit_regex,
                    "unit": "verse",
                    "context_source": "context_anchor",
                    "verified": True,
                },
            },
            "reference_resolution": {"enabled": True, "build_canonical_units": True},
            "reference_contract_validation": contextual_validation(context_regex, unit_regex),
        },
    )
    semantics = ReferenceSemantics.from_metadata(metadata)

    assert semantics.extract_primary_anchor_references("Cross reference only 7:104") == []
    assert semantics.derive_reference_metadata("Cross reference only 7:104") == {}


def test_contextual_reference_split_stops_at_next_context_anchor():
    context_regex = r"\bSurah\s+(?P<chapter>\d{1,4})\b"
    unit_regex = r"\b(?P<verse>\d{1,4})\b"
    metadata = DomainMetadata(
        domain="quran",
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "fields": {"chapter": "chapter", "verse": "verse"},
                "canonical_ref_template": "{chapter}:{verse}",
            },
            "domain_structure": {
                "context_anchor": {
                    "regex": context_regex,
                    "unit": "chapter",
                    "verified": True,
                },
                "unit_anchor": {
                    "regex": unit_regex,
                    "unit": "verse",
                    "context_source": "context_anchor",
                    "verified": True,
                },
            },
            "reference_resolution": {"enabled": True, "build_canonical_units": True},
            "reference_contract_validation": contextual_validation(context_regex, unit_regex),
        },
    )

    units = ReferenceSemantics.from_metadata(metadata).split_primary_anchor_units(
        "Surah 1\n1 first verse\n2 second verse\nSurah 2\n1 new chapter"
    )

    assert units == [
        "Surah 1\n\n1 first verse",
        "Surah 1\n2 second verse",
        "Surah 2\n1 new chapter",
    ]


def test_contextual_reference_split_preserves_context_intro_before_first_unit():
    context_regex = r"\bSurah\s+(?P<chapter>\d{1,4})\b"
    unit_regex = r"\b(?P<verse>\d{1,4})\b"
    metadata = DomainMetadata(
        domain="quran",
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "fields": {"chapter": "chapter", "verse": "verse"},
                "canonical_ref_template": "{chapter}:{verse}",
            },
            "domain_structure": {
                "context_anchor": {
                    "regex": context_regex,
                    "unit": "chapter",
                    "verified": True,
                },
                "unit_anchor": {
                    "regex": unit_regex,
                    "unit": "verse",
                    "context_source": "context_anchor",
                    "verified": True,
                },
            },
            "reference_resolution": {"enabled": True, "build_canonical_units": True},
            "reference_contract_validation": contextual_validation(context_regex, unit_regex),
        },
    )

    units = ReferenceSemantics.from_metadata(metadata).split_primary_anchor_units(
        "Surah 1\n1 first verse\nSurah 2\nThe Cow\n1 new chapter"
    )

    assert units == [
        "Surah 1\n\n1 first verse",
        "Surah 2\nThe Cow\n1 new chapter",
    ]


def test_unverified_primary_anchor_does_not_enable_canonical_units():
    metadata = DomainMetadata(
        domain="quran",
        custom_json={
            "reference_schema": {"type": "chapter_verse"},
            "domain_structure": {
                "primary_anchor": {
                    "type": "chapter_verse",
                    "regex": r"\[(?P<chapter>\d+):(?P<verse>\d+)\]",
                    "unit": "verse",
                    "verified": False,
                },
            },
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
            },
        },
    )

    semantics = ReferenceSemantics.from_metadata(metadata)

    assert semantics.primary_anchor_pattern is None
    assert semantics.canonical_units_enabled is False


def test_reference_semantics_supports_book_hadith_schema():
    primary_regex = r"\bBook\s+(?P<book>\d+)\s*,?\s*Hadith\s+(?P<hadith>\d+)\b"
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(
            domain="hadith",
            document_type="collection",
            custom_json={
                "reference_schema": {
                    "type": "book_hadith",
                    "display": "Book {book}, Hadith {hadith}",
                    "canonical_ref_template": "book:{book}:hadith:{hadith}",
                    "fields": {"book": "book_number", "hadith": "hadith_number"},
                },
                "chunking": {"unit": "hadith", "include_neighbors": 1},
                "domain_structure": {
                    "primary_anchor": {
                        "type": "book_hadith",
                        "regex": primary_regex,
                        "unit": "hadith",
                        "verified": True,
                    },
                },
                "reference_resolution": {
                    "enabled": True,
                    "build_canonical_units": True,
                    "carry_forward_body_blocks": True,
                    "header_only_policy": "provenance_only",
                    "continuation_policy": "until_next_reference",
                    "max_page_gap": 2,
                    "require_single_reference_per_answerable_chunk": True,
                },
                "provenance": {
                    "preserve_original_blocks": True,
                    "block_preview_chars": 80,
                    "store_text_hash": True,
                },
                "reference_contract_validation": single_anchor_validation(primary_regex),
            },
        )
    )

    assert semantics.reference_type == "book_hadith"
    assert semantics.chunk_unit == "hadith"
    assert semantics.canonical_units_enabled is True
    assert semantics.carry_forward_body_blocks is True
    assert semantics.header_only_policy == "provenance_only"
    assert semantics.max_page_gap == 2
    assert semantics.require_single_reference_per_answerable_chunk is True
    assert semantics.preserve_original_blocks is True
    assert semantics.block_preview_chars == 80
    assert semantics.store_text_hash is True
    assert semantics.extract_chunk_references("Book 1, Hadith 2 text") == [
        {
            "raw": "Book 1, Hadith 2",
            "book": 1,
            "hadith": 2,
            "ref": "book:1:hadith:2",
        }
    ]
    assert semantics.extract_chunk_references("English cross reference [1:2] only") == []
    assert semantics.derive_reference_metadata("Book 1, Hadith 2 text") == {
        "reference_type": "book_hadith",
        "references": ["book:1:hadith:2"],
        "identity_ranges": {
            "book": {"start": 1, "end": 1},
            "hadith": {"start": 2, "end": 2},
        },
        "reference_identity_range": {
            "book": {"start": 1, "end": 1},
            "hadith": {"start": 2, "end": 2},
        },
        "reference_identity_fields": ["book", "hadith"],
        "reference_unit_field": "hadith",
        "previous_ref": "book:1:hadith:1",
        "next_ref": "book:1:hadith:3",
    }


def test_reference_semantics_stays_generic_without_reference_cues():
    metadata = DomainMetadata(domain="legal", document_type="brief", tags=["contract"])

    semantics = ReferenceSemantics.from_metadata(metadata)

    assert semantics.profile_name == "generic"
    assert semantics.reference_type is None
    assert semantics.chunk_unit == "section"
    assert semantics.exact_reference_top1 is False


def test_extract_query_reference_uses_model_declared_anchor_forms():
    semantics = ReferenceSemantics.from_metadata(verified_quran_metadata())

    assert semantics.extract_query_reference("What does Quran 1:4 say?") == {
        "chapter": 1,
        "ref": "1:4",
        "verse": 4,
        "raw": "Quran 1:4",
    }
    assert semantics.extract_query_reference("Find [2:17]") == {
        "chapter": 2,
        "ref": "2:17",
        "verse": 17,
        "raw": "[2:17]",
    }
    assert semantics.extract_query_reference("1:4") == {
        "chapter": 1,
        "ref": "1:4",
        "verse": 4,
        "raw": "1:4",
    }
    assert semantics.extract_query_reference("what is surah 113") is None


def test_extract_chunk_references_finds_multiple_markers():
    semantics = ReferenceSemantics.from_metadata(verified_quran_metadata())

    refs = semantics.extract_chunk_references(
        "Surah 1\n\n[1:1]\n\nPraise text\n\n[1:2]\n\nMerciful text"
    )

    assert refs == [
        {"chapter": 1, "ref": "1:1", "verse": 1, "raw": "[1:1]"},
        {"chapter": 1, "ref": "1:2", "verse": 2, "raw": "[1:2]"},
    ]


def test_extract_chunk_references_deduplicates_markers_in_order():
    semantics = ReferenceSemantics.from_metadata(verified_quran_metadata())

    refs = semantics.extract_chunk_references("[1:1] repeated [1:1] then [1:2]")

    assert refs == [
        {"chapter": 1, "ref": "1:1", "verse": 1, "raw": "[1:1]"},
        {"chapter": 1, "ref": "1:2", "verse": 2, "raw": "[1:2]"},
    ]


def test_derive_reference_metadata_records_range_pages_and_neighbors():
    semantics = ReferenceSemantics.from_metadata(verified_quran_metadata())

    metadata = semantics.derive_reference_metadata(
        "Surah 1\n\n[1:4]\n\nIt is You we worship.",
        {"page_start": 7, "page_end": 8},
    )

    assert metadata["reference_type"] == "surah_ayah"
    assert metadata["references"] == ["1:4"]
    assert metadata["reference_identity_range"] == {
        "chapter": {"start": 1, "end": 1},
        "verse": {"start": 4, "end": 4},
    }
    assert "chapter_start" not in metadata
    assert "verse_start" not in metadata
    assert metadata["page_start"] == 7
    assert metadata["page_end"] == 8
    assert metadata["previous_ref"] == "1:3"
    assert metadata["next_ref"] == "1:5"


def test_derive_reference_metadata_omits_neighbors_when_not_configured():
    primary_regex = r"\[(?P<chapter>\d{1,4}):(?P<verse>\d{1,4})\]"
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(
            custom_json={
                "reference_schema": {
                    "type": "chapter_verse",
                    "fields": {"chapter": "chapter", "verse": "verse"},
                    "canonical_ref_template": "{chapter}:{verse}",
                },
                "domain_structure": {
                    "primary_anchor": {
                        "regex": primary_regex,
                        "unit": "verse",
                        "verified": True,
                    }
                },
                "reference_resolution": {"enabled": True, "build_canonical_units": True},
                "reference_contract_validation": single_anchor_validation(primary_regex),
            }
        )
    )

    metadata = semantics.derive_reference_metadata("Text [3:9]", {"page": 12})

    assert metadata["reference_type"] == "chapter_verse"
    assert metadata["references"] == ["3:9"]
    assert metadata["page_start"] == 12
    assert metadata["page_end"] == 12
    assert "previous_ref" not in metadata
    assert "next_ref" not in metadata


def test_derive_reference_metadata_keeps_cross_reference_only_mentions_non_primary():
    primary_regex = r"\bVerse\s+(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})\b"
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(
            custom_json={
                "reference_schema": {
                    "type": "chapter_verse",
                    "canonical_ref_template": "{chapter}:{verse}",
                },
                "domain_structure": {
                    "primary_anchor": {
                        "regex": primary_regex,
                        "unit": "verse_section",
                        "verified": True,
                    },
                    "inline_references": {
                        "regex": r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})",
                        "policy": "cross_reference_only",
                        "verified": True,
                    },
                },
                "reference_resolution": {"enabled": True, "build_canonical_units": True},
                "reference_contract_validation": single_anchor_validation(primary_regex),
            }
        )
    )

    metadata = semantics.derive_reference_metadata(
        "Commentary heading\n\nVerse 18:30 body mentions 25:75-76.",
        {"page": 809},
    )

    assert semantics.extract_primary_anchor_references(
        "Commentary heading\n\nVerse 18:30 body."
    )[0]["ref"] == "18:30"
    assert metadata["references"] == ["18:30"]
    assert metadata["cross_references"] == ["25:75"]
    assert "chapter_start" not in metadata
    assert "verse_start" not in metadata


def test_builtin_quran_tafseer_profile_has_no_reference_capability_without_contract(tmp_path):
    profile = DomainMetadataService(tmp_path).get_profile("quran_tafseer")
    assert profile is not None
    semantics = ReferenceSemantics.from_metadata(profile.metadata)

    assert semantics.reference_capability == "none"
    assert semantics.canonical_units_enabled is False
    assert semantics.extract_primary_anchor_references("See also 69:18).") == []
    assert semantics.derive_reference_metadata("See also 69:18).") == {}
    assert semantics.derive_reference_metadata(
        "Verse 18:30 body mentions 25:75-76.",
        {"page": 809},
    ) == {}
    assert semantics.derive_reference_metadata(
        "[1:1]\n\nArabic text\n\nEnglish translation.",
        {"page": 2},
    ) == {}


def test_chunk_reference_metadata_aliases_derive_reference_metadata():
    semantics = ReferenceSemantics.from_metadata(verified_quran_metadata())

    assert semantics.chunk_reference_metadata("[1:4]") == semantics.derive_reference_metadata(
        "[1:4]"
    )


def test_reference_semantics_keeps_custom_schema_pattern_as_hint_without_execution():
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(
            domain="legal",
            document_type="statute",
            custom_json={
                "reference_schema": {
                    "type": "legal_section",
                    "pattern": r"Article\s+(?P<section>\d+(?:\.\d+)*)",
                },
                "chunking": {"unit": "section"},
                "retrieval": {"exact_reference_top1": True},
            },
        )
    )

    assert semantics.reference_capability == "hint"
    assert semantics.extract_query_reference("Explain Article 12.3") is None
    assert semantics.derive_reference_metadata("Article 12.3 text") == {}


def test_reference_semantics_does_not_infer_legal_section_from_standard_metadata():
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(domain="legal", document_type="statute", reference_pattern="section")
    )

    assert semantics.profile_name == "generic"
    assert semantics.reference_type is None
    assert semantics.extract_query_reference("Explain Section 12.3") is None


def test_reference_semantics_does_not_infer_page_line_from_standard_metadata():
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(domain="archive", reference_pattern="page line")
    )

    assert semantics.reference_type is None
    assert semantics.extract_query_reference("See page 5 line 8") is None


def test_reference_semantics_splits_text_into_reference_units():
    semantics = ReferenceSemantics.from_metadata(verified_quran_metadata())

    assert semantics.split_reference_units("Surah 1\n\n[1:1] One\n\n[1:2] Two") == [
        "Surah 1\n\n[1:1] One",
        "[1:2] Two",
    ]
