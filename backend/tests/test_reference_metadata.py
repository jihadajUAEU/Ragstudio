from ragstudio.schemas.parsing import DomainMetadata
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


def test_chunk_reference_metadata_aliases_derive_reference_metadata():
    semantics = ReferenceSemantics.from_metadata(quran_metadata())

    assert semantics.chunk_reference_metadata("[1:4]") == semantics.derive_reference_metadata("[1:4]")


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


def test_reference_semantics_splits_text_into_reference_units():
    semantics = ReferenceSemantics.from_metadata(quran_metadata())

    assert semantics.split_reference_units("Surah 1\n\n[1:1] One\n\n[1:2] Two") == [
        "Surah 1\n\n[1:1] One",
        "[1:2] Two",
    ]
