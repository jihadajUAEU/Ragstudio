from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.parser_normalization import (
    EQUATION_BLOCK_TYPES,
    TEXT_BLOCK_TYPES,
    ExpectedContentProfile,
    MinerUContentNormalizer,
)


def test_text_blocks_preserved_by_page():
    data = [
        {"type": "text", "text": "Page one heading", "page_idx": 0},
        {"type": "paragraph", "content": "Page two body", "page_idx": 1},
    ]

    blocks = MinerUContentNormalizer().normalize_content_list(data)

    assert [(block.text, block.page, block.block_type) for block in blocks] == [
        ("Page one heading", 1, "text"),
        ("Page two body", 2, "paragraph"),
    ]
    assert blocks[0].warning_metadata() == []


def test_suspicious_arabic_prose_equation_is_quarantined_without_latex_insertion():
    data = [
        {"type": "text", "text": "Surah 1", "page_idx": 0},
        {"type": "equation_interline", "text": "$$ \\theta = \\alpha \\beta $$", "page_idx": 0},
        {"type": "text", "text": "الحمد لله رب العالمين", "page_idx": 0},
    ]
    metadata = DomainMetadata(
        domain="quran_tafseer",
        language="mixed",
        script="mixed",
        reference_pattern="surah_number:verse_number",
        expected_structure="surah_ayah_sections",
        tags=["quran", "arabic", "english"],
    )

    blocks = MinerUContentNormalizer().normalize_content_list(data, domain_metadata=metadata)

    assert [block.text for block in blocks] == ["Surah 1", "", "الحمد لله رب العالمين"]
    assert "$$" not in "\n".join(block.text for block in blocks)
    warning = blocks[1].warning_metadata()[0]
    assert warning["code"] == "suspected_text_misclassified_as_equation"
    assert warning["block_type"] == "equation_interline"
    assert warning["page"] == 1


def test_recovered_text_is_used_with_recovery_warning():
    data = [
        {
            "type": "equation",
            "text": "$$ x = y $$",
            "recovered_text": "Recovered\x00 prose sentence.",
            "page_idx": 4,
        }
    ]
    metadata = DomainMetadata(domain="hadith", script="mixed", reference_pattern="Book N, Hadith N")

    blocks = MinerUContentNormalizer().normalize_content_list(data, domain_metadata=metadata)

    assert blocks[0].text == "Recovered prose sentence."
    assert blocks[0].recovery is not None
    assert blocks[0].recovery.text == "Recovered prose sentence."
    assert blocks[0].recovery.source == "recovered_text"
    assert blocks[0].warning_metadata() == [
        {
            "code": "recovered_text_from_misclassified_block",
            "message": (
                "Used parser-provided recovered text for a block misclassified as an equation."
            ),
            "block_type": "equation",
            "page": 5,
            "recovery_source": "recovered_text",
        }
    ]


def test_arabic_hadith_misclassified_as_equation_is_flagged_outside_quran_examples():
    data = [
        {
            "type": "equation",
            "content": "حدثنا عبد الله قال سمعت رسول الله صلى الله عليه وسلم",
            "page_idx": 2,
        }
    ]
    metadata = DomainMetadata(
        domain="hadith",
        language="arabic",
        script="arabic",
        reference_pattern="Book N, Hadith N",
        expected_structure="book_chapter_hadith",
        tags=["hadith", "arabic"],
    )

    blocks = MinerUContentNormalizer().normalize_content_list(data, domain_metadata=metadata)

    assert blocks[0].text == ""
    assert blocks[0].warning_metadata()[0]["code"] == "suspected_text_misclassified_as_equation"


def test_mixed_arabic_english_paragraph_text_is_preserved():
    data = [
        {
            "type": "paragraph",
            "content": "In the name of Allah الرحمن الرحيم",
            "page_idx": 8,
        }
    ]
    metadata = DomainMetadata(language="mixed", script="mixed", tags=["arabic", "english"])

    blocks = MinerUContentNormalizer().normalize_content_list(data, domain_metadata=metadata)

    assert blocks[0].text == "In the name of Allah الرحمن الرحيم"
    assert blocks[0].page == 9
    assert blocks[0].warning_metadata() == []


def test_math_science_equation_blocks_remain_valid_and_warning_free():
    profile = ExpectedContentProfile(
        expected_scripts=frozenset({"latin"}),
        allowed_block_types=TEXT_BLOCK_TYPES | EQUATION_BLOCK_TYPES,
        content_domain="physics",
        parser_strictness="normal",
    )
    data = [{"type": "equation_interline", "text": "E = mc^2", "page_idx": 0}]

    blocks = MinerUContentNormalizer().normalize_content_list(data, expected_profile=profile)

    assert blocks[0].text == "E = mc^2"
    assert blocks[0].block_type == "equation_interline"
    assert blocks[0].warning_metadata() == []


def test_allowed_math_equation_extracts_latex_payload():
    profile = ExpectedContentProfile(
        expected_scripts=frozenset({"latin"}),
        allowed_block_types=TEXT_BLOCK_TYPES | EQUATION_BLOCK_TYPES,
        content_domain="physics",
    )
    data = [{"type": "equation", "latex": "E = mc^2", "page_idx": 0}]

    blocks = MinerUContentNormalizer().normalize_content_list(data, expected_profile=profile)

    assert blocks[0].text == "E = mc^2"
    assert blocks[0].warning_metadata() == []


def test_expected_structure_can_allow_equation_blocks_without_warning():
    data = [{"type": "equation", "text": "a^2 + b^2 = c^2", "page_idx": 2}]
    metadata = DomainMetadata(expected_structure="math_equation_sections")

    blocks = MinerUContentNormalizer().normalize_content_list(data, domain_metadata=metadata)

    assert blocks[0].text == "a^2 + b^2 = c^2"
    assert blocks[0].block_type == "equation"
    assert blocks[0].warning_metadata() == []


def test_text_bearing_disallowed_block_type_is_quarantined_with_warning():
    profile = ExpectedContentProfile(allowed_block_types=frozenset({"paragraph"}))
    data = [
        {"type": "heading", "text": "Excluded title", "page_idx": 0},
        {"type": "paragraph", "text": "Included body", "page_idx": 0},
    ]

    blocks = MinerUContentNormalizer().normalize_content_list(data, expected_profile=profile)

    assert [block.text for block in blocks] == ["", "Included body"]
    assert blocks[0].warning_metadata()[0]["code"] == "disallowed_block_type_quarantined"
    assert blocks[0].warning_metadata()[0]["block_type"] == "heading"
    assert blocks[1].warning_metadata() == []


def test_disallowed_block_type_uses_recovered_text_when_available():
    profile = ExpectedContentProfile(allowed_block_types=frozenset({"paragraph"}))
    data = [
        {
            "type": "image",
            "text": "raw OCR damage",
            "recovery": {"text": "Recovered caption text.", "source": "ocr_repair"},
            "page_idx": 0,
        }
    ]

    blocks = MinerUContentNormalizer().normalize_content_list(data, expected_profile=profile)

    assert blocks[0].text == "Recovered caption text."
    assert blocks[0].warning_metadata()[0]["code"] == "recovered_text_from_disallowed_block"
    assert blocks[0].warning_metadata()[0]["recovery_source"] == "ocr_repair"


def test_top_level_table_body_is_extracted_for_table_blocks():
    data = [{"type": "table", "table_body": "Column A | Column B", "page_idx": 1}]

    blocks = MinerUContentNormalizer().normalize_content_list(data)

    assert blocks[0].text == "Column A | Column B"
    assert blocks[0].block_type == "table"
    assert blocks[0].page == 2


def test_reference_patterns_are_preserved_exactly_and_in_order():
    metadata = DomainMetadata(
        reference_pattern=r"Book\s+\d+, Hadith\s+\d+",
        custom_json={
            "parser_normalization": {
                "reference_patterns": [r"Surah[A-Z]+:\d+", "CaseSensitiveRef"]
            }
        },
    )

    profile = ExpectedContentProfile.from_domain_metadata(metadata)

    assert profile.reference_patterns == (
        r"Book\s+\d+, Hadith\s+\d+",
        r"Surah[A-Z]+:\d+",
        "CaseSensitiveRef",
    )


def test_custom_json_content_profile_configures_allowed_block_types_and_scripts():
    metadata = DomainMetadata(
        custom_json={
            "content_profile": {
                "allowed_block_types": ["paragraph"],
                "expected_scripts": ["Arabic", "Latin"],
            }
        }
    )
    data = [
        {"type": "text", "text": "Excluded text"},
        {"type": "paragraph", "text": "Included paragraph"},
    ]

    profile = ExpectedContentProfile.from_domain_metadata(metadata)
    blocks = MinerUContentNormalizer().normalize_content_list(data, expected_profile=profile)

    assert profile.expected_scripts == frozenset({"arabic", "latin"})
    assert profile.allowed_block_types == frozenset({"paragraph"})
    assert [block.text for block in blocks] == ["", "Included paragraph"]
    assert blocks[0].warning_metadata()[0]["code"] == "disallowed_block_type_quarantined"


def test_bool_page_values_are_not_treated_as_page_numbers():
    data = [
        {"type": "text", "text": "No page", "page_idx": True},
        {"type": "paragraph", "text": "Still no page", "page": False},
    ]

    blocks = MinerUContentNormalizer().normalize_content_list(data)

    assert [block.page for block in blocks] == [None, None]


def test_nested_content_paragraph_content_and_null_character_cleanup():
    data = [
        {
            "type": "paragraph",
            "content": {"paragraph_content": ["First\x00", {"text": "second"}, ["third\x00"]]},
            "page_idx": 0,
        },
        {
            "type": "text",
            "content": {"content": "Nested\x00 text"},
            "page_idx": 1,
        },
    ]

    blocks = MinerUContentNormalizer().normalize_content_list(data)

    assert [block.text for block in blocks] == ["First second third", "Nested text"]
    assert [block.page for block in blocks] == [1, 2]
