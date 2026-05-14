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
                "boost_same_chapter": True,
                "boost_neighbor_verses": True,
            },
        },
    )


def test_reference_semantics_detects_scripture_profile_from_metadata_json():
    semantics = ReferenceSemantics.from_metadata(quran_metadata())

    assert semantics.profile_name == "scripture_reference"
    assert semantics.reference_type == "surah_ayah"
    assert semantics.chunk_unit == "verse"
    assert semantics.include_neighbors == 1
    assert semantics.exact_reference_top1 is True
    assert semantics.preserve_parallel_text is True
    assert semantics.boost_same_chapter is True
    assert semantics.boost_neighbor_verses is True
    assert semantics.relationships["previous"] == ["same_chapter", "verse - 1"]


def test_reference_semantics_falls_back_from_standard_metadata_fields():
    metadata = DomainMetadata(
        domain="religion",
        document_type="religious_text",
        tags=["quran"],
        reference_pattern="surah_number:verse_number",
        expected_structure="parallel_text",
    )

    semantics = ReferenceSemantics.from_metadata(metadata)

    assert semantics.profile_name == "scripture_reference"
    assert semantics.reference_type == "surah_ayah"
    assert semantics.chunk_unit == "verse"
    assert semantics.exact_reference_top1 is True
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

    assert semantics.profile_name == "scripture_reference"
    assert semantics.reference_type == "chapter_verse"
    assert semantics.chunk_unit == "stanza"
    assert semantics.include_neighbors == 2
    assert semantics.exact_reference_top1 is False


def test_reference_semantics_supports_book_hadith_schema():
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
    assert semantics.derive_reference_metadata("Book 1, Hadith 2 text") == {
        "reference_type": "book_hadith",
        "references": ["book:1:hadith:2"],
        "book_start": 1,
        "book_end": 1,
        "hadith_start": 2,
        "hadith_end": 2,
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


def test_extract_query_reference_supports_quran_bracket_and_bare_forms():
    semantics = ReferenceSemantics.from_metadata(quran_metadata())

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
    assert semantics.extract_query_reference("what is surah 113") == {
        "chapter": 113,
        "ref": "surah 113",
        "raw": "surah 113",
    }


def test_extract_chunk_references_finds_multiple_markers():
    semantics = ReferenceSemantics.from_metadata(quran_metadata())

    refs = semantics.extract_chunk_references(
        "Surah 1\n\n[1:1]\n\nPraise text\n\n[1:2]\n\nMerciful text"
    )

    assert refs == [
        {"chapter": 1, "ref": "1:1", "verse": 1, "raw": "[1:1]"},
        {"chapter": 1, "ref": "1:2", "verse": 2, "raw": "[1:2]"},
    ]


def test_extract_chunk_references_deduplicates_markers_in_order():
    semantics = ReferenceSemantics.from_metadata(quran_metadata())

    refs = semantics.extract_chunk_references("[1:1] repeated [1:1] then [1:2]")

    assert refs == [
        {"chapter": 1, "ref": "1:1", "verse": 1, "raw": "[1:1]"},
        {"chapter": 1, "ref": "1:2", "verse": 2, "raw": "[1:2]"},
    ]


def test_derive_reference_metadata_records_range_pages_and_neighbors():
    semantics = ReferenceSemantics.from_metadata(quran_metadata())

    metadata = semantics.derive_reference_metadata(
        "Surah 1\n\n[1:4]\n\nIt is You we worship.",
        {"page_start": 7, "page_end": 8},
    )

    assert metadata["reference_type"] == "surah_ayah"
    assert metadata["chapter_start"] == 1
    assert metadata["chapter_end"] == 1
    assert metadata["verse_start"] == 4
    assert metadata["verse_end"] == 4
    assert metadata["references"] == ["1:4"]
    assert metadata["page_start"] == 7
    assert metadata["page_end"] == 8
    assert metadata["previous_ref"] == "1:3"
    assert metadata["next_ref"] == "1:5"


def test_derive_reference_metadata_omits_neighbors_when_not_configured():
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(
            reference_pattern="chapter_number:verse_number",
            custom_json={"reference_schema": {"type": "chapter_verse"}},
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
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(
            custom_json={
                "reference_schema": {
                    "type": "chapter_verse",
                    "canonical_ref_template": "{chapter}:{verse}",
                },
                "domain_structure": {
                    "primary_anchor": {
                        "regex": r"\bVerse\s+(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})\b",
                        "unit": "verse_section",
                    },
                    "inline_references": {
                        "regex": r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})",
                        "policy": "cross_reference_only",
                    },
                },
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
    assert metadata["chapter_start"] == 18
    assert metadata["chapter_end"] == 18
    assert metadata["verse_start"] == 30
    assert metadata["verse_end"] == 30


def test_builtin_quran_tafseer_defaults_inline_references_to_cross_references(tmp_path):
    profile = DomainMetadataService(tmp_path).get_profile("quran_tafseer")
    assert profile is not None
    semantics = ReferenceSemantics.from_metadata(profile.metadata)

    assert semantics.inline_reference_policy == "cross_reference_only"
    assert semantics.extract_primary_anchor_references("See also 69:18).") == []
    assert semantics.derive_reference_metadata("See also 69:18).") == {}
    assert semantics.derive_reference_metadata(
        "Verse 18:30 body mentions 25:75-76.",
        {"page": 809},
    )["references"] == ["18:30"]


def test_chunk_reference_metadata_aliases_derive_reference_metadata():
    semantics = ReferenceSemantics.from_metadata(quran_metadata())

    assert semantics.chunk_reference_metadata("[1:4]") == semantics.derive_reference_metadata(
        "[1:4]"
    )


def test_reference_semantics_uses_custom_schema_pattern_for_legal_sections():
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

    assert semantics.extract_query_reference("Explain Article 12.3") == {
        "raw": "Article 12.3",
        "section": "12.3",
        "ref": "section:12.3",
    }
    assert semantics.derive_reference_metadata("Article 12.3 text")["references"] == [
        "section:12.3"
    ]


def test_reference_semantics_infers_legal_section_from_standard_metadata():
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(domain="legal", document_type="statute", reference_pattern="section")
    )

    assert semantics.profile_name == "scripture_reference"
    assert semantics.reference_type == "legal_section"
    assert semantics.extract_query_reference("Explain Section 12.3") == {
        "raw": "Section 12.3",
        "section": "12.3",
        "ref": "section:12.3",
    }


def test_reference_semantics_infers_page_line_from_standard_metadata():
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(domain="archive", reference_pattern="page line")
    )

    assert semantics.reference_type == "page_line"
    assert semantics.extract_query_reference("See page 5 line 8") == {
        "raw": "page 5 line 8",
        "page": 5,
        "line": 8,
        "ref": "page:5:line:8",
    }


def test_reference_semantics_splits_text_into_reference_units():
    semantics = ReferenceSemantics.from_metadata(quran_metadata())

    assert semantics.split_reference_units("Surah 1\n\n[1:1] One\n\n[1:2] Two") == [
        "Surah 1\n\n[1:1] One",
        "[1:2] Two",
    ]
