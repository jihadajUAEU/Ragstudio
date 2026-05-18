from pathlib import Path

import pytest
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.parser_normalization import (
    EQUATION_BLOCK_TYPES,
    TEXT_BLOCK_TYPES,
    ExpectedContentProfile,
    MinerUContentNormalizer,
    VisionRecoveryConfig,
    _parse_vision_recovery_text,
)

pytestmark = pytest.mark.asyncio


class FakeVisionRecoveryClient:
    def __init__(self, text: str):
        self.text = text
        self.calls = []

    async def recover_text(self, **kwargs):
        self.calls.append(kwargs)
        return self.text


async def test_text_blocks_preserved_by_page():
    data = [
        {"type": "text", "text": "Page one heading", "page_idx": 0},
        {"type": "paragraph", "content": "Page two body", "page_idx": 1},
    ]

    blocks = await MinerUContentNormalizer().normalize_content_list(data)

    assert [(block.text, block.page, block.block_type) for block in blocks] == [
        ("Page one heading", 1, "text"),
        ("Page two body", 2, "paragraph"),
    ]
    assert blocks[0].warning_metadata() == []


async def test_semantic_page_boundary_stitches_continuation_paragraph():
    data = [
        {
            "type": "paragraph",
            "text": "The runtime quality gate records parser warnings before retrieval",
            "page_idx": 0,
        },
        {
            "type": "paragraph",
            "text": "so reviewers can stop weak evidence before it reaches an answer.",
            "page_idx": 1,
        },
    ]

    blocks = await MinerUContentNormalizer().normalize_content_list(data)

    assert len(blocks) == 1
    assert blocks[0].text == (
        "The runtime quality gate records parser warnings before retrieval "
        "so reviewers can stop weak evidence before it reaches an answer."
    )
    assert blocks[0].page == 1
    assert blocks[0].block_type == "paragraph"
    assert blocks[0].warning_metadata() == []
    assert blocks[0].source_item["semantic_stitch"] == "page_boundary"
    assert blocks[0].source_item["page_start"] == 1
    assert blocks[0].source_item["page_end"] == 2
    assert blocks[0].source_item["stitched_pages"] == [1, 2]


async def test_semantic_page_boundary_does_not_stitch_complete_sentence():
    data = [
        {
            "type": "paragraph",
            "text": "The first page ends with a complete sentence.",
            "page_idx": 0,
        },
        {
            "type": "paragraph",
            "text": "The next page starts a new paragraph.",
            "page_idx": 1,
        },
    ]

    blocks = await MinerUContentNormalizer().normalize_content_list(data)

    assert [block.text for block in blocks] == [
        "The first page ends with a complete sentence.",
        "The next page starts a new paragraph.",
    ]


async def test_suspicious_arabic_prose_equation_is_quarantined_without_latex_insertion():
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

    blocks = await MinerUContentNormalizer().normalize_content_list(data, domain_metadata=metadata)

    assert [block.text for block in blocks] == ["Surah 1", "", "الحمد لله رب العالمين"]
    assert "$$" not in "\n".join(block.text for block in blocks)
    warning = blocks[1].warning_metadata()[0]
    assert warning["code"] == "suspected_text_misclassified_as_equation"
    assert warning["block_type"] == "equation_interline"
    assert warning["page"] == 1


async def test_recovered_text_is_used_with_recovery_warning():
    data = [
        {
            "type": "equation",
            "text": "$$ x = y $$",
            "recovered_text": "Recovered\x00 prose sentence.",
            "page_idx": 4,
        }
    ]
    metadata = DomainMetadata(domain="hadith", script="mixed", reference_pattern="Book N, Hadith N")

    blocks = await MinerUContentNormalizer().normalize_content_list(data, domain_metadata=metadata)

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


async def test_image_only_equation_recovers_overlapping_pdf_text_layer(tmp_path: Path):
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "source_origin.pdf"
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((146, 420), "Recovered PDF text layer line", fontsize=12)
    document.save(pdf_path)
    document.close()

    content_list = tmp_path / "source_content_list.json"
    content_list.write_text("[]", encoding="utf-8")
    data = [
        {
            "type": "equation",
            "img_path": "images/ayah.jpg",
            "bbox": [232, 515, 903, 546],
            "page_idx": 0,
        }
    ]
    metadata = DomainMetadata(
        domain="quran_tafseer",
        script="mixed",
        tags=["quran", "arabic", "english"],
        reference_pattern="surah_number:verse_number",
    )

    blocks = await MinerUContentNormalizer().normalize_content_list(
        data,
        domain_metadata=metadata,
        artifact_root=tmp_path,
        content_list_path=content_list,
    )

    assert blocks[0].text == "Recovered PDF text layer line"
    assert blocks[0].recovery is not None
    assert blocks[0].recovery.source == "pdf_text_layer:source_origin.pdf"
    warning = blocks[0].warning_metadata()[0]
    assert warning["code"] == "recovered_text_from_misclassified_block"
    assert warning["recovery_source"] == "pdf_text_layer:source_origin.pdf"


async def test_image_block_recovers_overlapping_pdf_text_layer(tmp_path: Path):
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "source_origin.pdf"
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((206, 246), "Recovered PDF text layer image line", fontsize=12)
    document.save(pdf_path)
    document.close()

    content_list = tmp_path / "source_content_list.json"
    content_list.write_text("[]", encoding="utf-8")
    data = [
        {
            "type": "image",
            "img_path": "images/ayah.jpg",
            "bbox": [341, 284, 905, 318],
            "page_idx": 0,
        }
    ]
    metadata = DomainMetadata(
        domain="quran_tafseer",
        script="mixed",
        tags=["quran", "arabic", "english"],
        reference_pattern="surah_number:verse_number",
    )

    blocks = await MinerUContentNormalizer().normalize_content_list(
        data,
        domain_metadata=metadata,
        artifact_root=tmp_path,
        content_list_path=content_list,
    )

    assert blocks[0].text == "Recovered PDF text layer image line"
    assert blocks[0].recovery is not None
    assert blocks[0].recovery.source == "pdf_text_layer:source_origin.pdf"
    warning = blocks[0].warning_metadata()[0]
    assert warning["code"] == "recovered_text_from_disallowed_block"
    assert warning["block_type"] == "image"
    assert warning["recovery_source"] == "pdf_text_layer:source_origin.pdf"


async def test_image_block_uses_targeted_vision_recovery_when_text_layer_missing(tmp_path: Path):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    image_path = image_dir / "ayah.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-image")
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text("[]", encoding="utf-8")
    client = FakeVisionRecoveryClient("إنما التوبة على الله")
    config = VisionRecoveryConfig(
        base_url="http://vision.test/v1",
        model="vision-ocr",
        enabled=True,
        target_block_types=frozenset({"image", "equation"}),
        triggers=frozenset({"missing_pdf_text_layer", "missing_required_script"}),
        languages=frozenset({"arabic"}),
        max_blocks_per_page=2,
        max_total_blocks=4,
    )
    metadata = DomainMetadata(
        domain="quran_tafseer",
        script="mixed",
        tags=["arabic", "english"],
        custom_json={"quality_policy": {"required_scripts": ["arabic"]}},
    )
    data = [
        {
            "type": "image",
            "img_path": "images/ayah.png",
            "text": "The repentance accepted by Allah",
            "page_idx": 0,
        }
    ]

    blocks = await MinerUContentNormalizer(vision_recovery_client=client).normalize_content_list(
        data,
        domain_metadata=metadata,
        artifact_root=tmp_path,
        content_list_path=content_list,
        vision_recovery_config=config,
    )

    assert len(client.calls) == 1
    assert client.calls[0]["triggers"] == ["missing_required_script"]
    assert client.calls[0]["config"] is config
    assert blocks[0].text == "إنما التوبة على الله"
    assert blocks[0].recovery is not None
    assert blocks[0].recovery.source == "vision_model:vision-ocr"
    warning = blocks[0].warning_metadata()[0]
    assert warning["code"] == "recovered_text_from_disallowed_block"
    assert warning["recovery_source"] == "vision_model:vision-ocr"


async def test_vision_recovery_does_not_replace_existing_required_script_text(tmp_path: Path):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    (image_dir / "ayah.png").write_bytes(b"\x89PNG\r\n\x1a\nfake-image")
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text("[]", encoding="utf-8")
    client = FakeVisionRecoveryClient("Wrong replacement")
    config = VisionRecoveryConfig(
        base_url="http://vision.test/v1",
        model="vision-ocr",
        enabled=True,
    )
    metadata = DomainMetadata(
        custom_json={"quality_policy": {"required_scripts": ["arabic"]}}
    )
    data = [
        {
            "type": "image",
            "img_path": "images/ayah.png",
            "text": "إنما التوبة على الله",
            "page_idx": 0,
        }
    ]

    blocks = await MinerUContentNormalizer(vision_recovery_client=client).normalize_content_list(
        data,
        domain_metadata=metadata,
        artifact_root=tmp_path,
        content_list_path=content_list,
        vision_recovery_config=config,
    )

    assert client.calls == []
    assert blocks[0].text == ""
    assert blocks[0].warning_metadata()[0]["code"] == "disallowed_block_type_quarantined"


async def test_vision_recovery_keeps_pdf_text_layer_when_required_script_present(tmp_path: Path):
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "source_origin.pdf"
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((206, 246), "Recovered PDF text layer image line", fontsize=12)
    document.save(pdf_path)
    document.close()
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text("[]", encoding="utf-8")
    client = FakeVisionRecoveryClient("Wrong replacement")
    config = VisionRecoveryConfig(
        base_url="http://vision.test/v1",
        model="vision-ocr",
        enabled=True,
    )
    metadata = DomainMetadata(
        custom_json={"quality_policy": {"required_scripts": ["latin"]}}
    )
    data = [
        {
            "type": "image",
            "img_path": "images/ayah.jpg",
            "bbox": [341, 284, 905, 318],
            "page_idx": 0,
        }
    ]

    blocks = await MinerUContentNormalizer(vision_recovery_client=client).normalize_content_list(
        data,
        domain_metadata=metadata,
        artifact_root=tmp_path,
        content_list_path=content_list,
        vision_recovery_config=config,
    )

    assert client.calls == []
    assert blocks[0].text == "Recovered PDF text layer image line"
    assert blocks[0].recovery is not None
    assert blocks[0].recovery.source == "pdf_text_layer:source_origin.pdf"


async def test_vision_recovery_rejects_plain_text_or_refusal_payloads():
    assert (
        _parse_vision_recovery_text(
            {"choices": [{"message": {"content": "I cannot read this image."}}]}
        )
        is None
    )
    assert (
        _parse_vision_recovery_text(
            {"choices": [{"message": {"content": '{"text": "Recovered"}'}}]}
        )
        == "Recovered"
    )


async def test_vision_recovery_respects_total_and_per_page_caps(tmp_path: Path):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    for index in range(3):
        (image_dir / f"block-{index}.png").write_bytes(b"\x89PNG\r\n\x1a\nfake-image")
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text("[]", encoding="utf-8")
    client = FakeVisionRecoveryClient("إنما التوبة على الله")
    config = VisionRecoveryConfig(
        base_url="http://vision.test/v1",
        model="vision-ocr",
        enabled=True,
        max_blocks_per_page=1,
        max_total_blocks=1,
    )
    metadata = DomainMetadata(
        custom_json={"quality_policy": {"required_scripts": ["arabic"]}}
    )
    data = [
        {
            "type": "image",
            "img_path": f"images/block-{index}.png",
            "text": "English only",
            "page_idx": 0,
        }
        for index in range(3)
    ]

    blocks = await MinerUContentNormalizer(vision_recovery_client=client).normalize_content_list(
        data,
        domain_metadata=metadata,
        artifact_root=tmp_path,
        content_list_path=content_list,
        vision_recovery_config=config,
    )

    assert len(client.calls) == 1
    assert [block.text for block in blocks] == ["إنما التوبة على الله", "", ""]
    assert blocks[1].warning_metadata()[0]["code"] == "disallowed_block_type_quarantined"


async def test_image_block_recovers_multiline_pdf_text_layer_band(tmp_path: Path):
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "source_origin.pdf"
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((206, 220), "Verse 4:17", fontsize=12)
    page.insert_text((206, 246), "Recovered first text layer line", fontsize=12)
    page.insert_text((206, 266), "Recovered second text layer line", fontsize=12)
    document.save(pdf_path)
    document.close()

    content_list = tmp_path / "source_content_list.json"
    content_list.write_text("[]", encoding="utf-8")
    data = [
        {
            "type": "image",
            "img_path": "images/ayah.jpg",
            "bbox": [341, 284, 905, 350],
            "page_idx": 0,
        }
    ]
    metadata = DomainMetadata(
        domain="quran_tafseer",
        script="mixed",
        tags=["quran", "arabic", "english"],
        reference_pattern="surah_number:verse_number",
    )

    blocks = await MinerUContentNormalizer().normalize_content_list(
        data,
        domain_metadata=metadata,
        artifact_root=tmp_path,
        content_list_path=content_list,
    )

    assert blocks[0].text == (
        "Recovered first text layer line\nRecovered second text layer line"
    )
    assert "Verse 4:17" not in blocks[0].text
    assert blocks[0].recovery is not None
    assert blocks[0].recovery.source == "pdf_text_layer:source_origin.pdf"


async def test_reference_header_gap_recovers_pdf_text_layer_between_header_and_translation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fitz = pytest.importorskip("fitz")
    from ragstudio.services import parser_normalization

    arabic_text = "كمثل الذي استوقد نارا فلما أضاءت ما حوله"
    monkeypatch.setattr(
        parser_normalization,
        "_pdf_arabic_lines_text_in_region",
        lambda context, *, page_number, content_bbox: arabic_text,
    )
    pdf_path = tmp_path / "source_origin.pdf"
    document = fitz.open()
    document.new_page(width=612, height=792)
    document.save(pdf_path)
    document.close()

    content_list = tmp_path / "source_content_list.json"
    content_list.write_text("[]", encoding="utf-8")
    data = [
        {"type": "text", "text": "Verse 2:17", "bbox": [93, 444, 179, 459], "page_idx": 0},
        {
            "type": "text",
            "text": "Their example is that of one who kindled a fire.",
            "bbox": [89, 535, 887, 569],
            "page_idx": 0,
        },
    ]
    metadata = DomainMetadata(
        domain="quran_tafseer",
        script="mixed",
        tags=["quran", "arabic", "english"],
        reference_pattern="surah_number:verse_number",
    )

    blocks = await MinerUContentNormalizer().normalize_content_list(
        data,
        domain_metadata=metadata,
        artifact_root=tmp_path,
        content_list_path=content_list,
    )

    assert [block.text for block in blocks] == [
        "Verse 2:17",
        arabic_text,
        "Their example is that of one who kindled a fire.",
    ]
    assert blocks[1].block_type == "pdf_text_gap"
    assert blocks[1].recovery is not None
    assert blocks[1].recovery.source == "pdf_text_layer:source_origin.pdf"
    warning = blocks[1].warning_metadata()[0]
    assert warning["code"] == "recovered_text_from_disallowed_block"
    assert warning["block_type"] == "pdf_text_gap"


async def test_arabic_hadith_misclassified_as_equation_is_flagged_outside_quran_examples():
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

    blocks = await MinerUContentNormalizer().normalize_content_list(data, domain_metadata=metadata)

    assert blocks[0].text == ""
    assert blocks[0].warning_metadata()[0]["code"] == "suspected_text_misclassified_as_equation"


async def test_mixed_arabic_english_paragraph_text_is_preserved():
    data = [
        {
            "type": "paragraph",
            "content": "In the name of Allah الرحمن الرحيم",
            "page_idx": 8,
        }
    ]
    metadata = DomainMetadata(language="mixed", script="mixed", tags=["arabic", "english"])

    blocks = await MinerUContentNormalizer().normalize_content_list(data, domain_metadata=metadata)

    assert blocks[0].text == "In the name of Allah الرحمن الرحيم"
    assert blocks[0].page == 9
    assert blocks[0].warning_metadata() == []


async def test_math_science_equation_blocks_remain_valid_and_warning_free():
    profile = ExpectedContentProfile(
        expected_scripts=frozenset({"latin"}),
        allowed_block_types=TEXT_BLOCK_TYPES | EQUATION_BLOCK_TYPES,
        content_domain="physics",
        parser_strictness="normal",
    )
    data = [{"type": "equation_interline", "text": "E = mc^2", "page_idx": 0}]

    blocks = await MinerUContentNormalizer().normalize_content_list(data, expected_profile=profile)

    assert blocks[0].text == "E = mc^2"
    assert blocks[0].block_type == "equation_interline"
    assert blocks[0].warning_metadata() == []


async def test_allowed_math_equation_extracts_latex_payload():
    profile = ExpectedContentProfile(
        expected_scripts=frozenset({"latin"}),
        allowed_block_types=TEXT_BLOCK_TYPES | EQUATION_BLOCK_TYPES,
        content_domain="physics",
    )
    data = [{"type": "equation", "latex": "E = mc^2", "page_idx": 0}]

    blocks = await MinerUContentNormalizer().normalize_content_list(data, expected_profile=profile)

    assert blocks[0].text == "E = mc^2"
    assert blocks[0].warning_metadata() == []


async def test_expected_structure_can_allow_equation_blocks_without_warning():
    data = [{"type": "equation", "text": "a^2 + b^2 = c^2", "page_idx": 2}]
    metadata = DomainMetadata(expected_structure="math_equation_sections")

    blocks = await MinerUContentNormalizer().normalize_content_list(data, domain_metadata=metadata)

    assert blocks[0].text == "a^2 + b^2 = c^2"
    assert blocks[0].block_type == "equation"
    assert blocks[0].warning_metadata() == []


async def test_text_bearing_disallowed_block_type_is_quarantined_with_warning():
    profile = ExpectedContentProfile(allowed_block_types=frozenset({"paragraph"}))
    data = [
        {"type": "heading", "text": "Excluded title", "page_idx": 0},
        {"type": "paragraph", "text": "Included body", "page_idx": 0},
    ]

    blocks = await MinerUContentNormalizer().normalize_content_list(data, expected_profile=profile)

    assert [block.text for block in blocks] == ["", "Included body"]
    assert blocks[0].warning_metadata()[0]["code"] == "disallowed_block_type_quarantined"
    assert blocks[0].warning_metadata()[0]["block_type"] == "heading"
    assert blocks[1].warning_metadata() == []


async def test_disallowed_block_type_uses_recovered_text_when_available():
    profile = ExpectedContentProfile(allowed_block_types=frozenset({"paragraph"}))
    data = [
        {
            "type": "image",
            "text": "raw OCR damage",
            "recovery": {"text": "Recovered caption text.", "source": "ocr_repair"},
            "page_idx": 0,
        }
    ]

    blocks = await MinerUContentNormalizer().normalize_content_list(data, expected_profile=profile)

    assert blocks[0].text == "Recovered caption text."
    assert blocks[0].warning_metadata()[0]["code"] == "recovered_text_from_disallowed_block"


async def test_repair_metadata_recovers_text_bearing_disallowed_block_as_prose():
    metadata = DomainMetadata(
        custom_json={
            "parser_normalization": {
                "allowed_block_types": ["paragraph"],
                "recover_text_bearing_blocks_as_prose": True,
            }
        }
    )
    data = [
        {"type": "heading", "text": "Hadith text misclassified as heading", "page_idx": 0}
    ]

    blocks = await MinerUContentNormalizer().normalize_content_list(data, domain_metadata=metadata)

    assert blocks[0].text == "Hadith text misclassified as heading"
    assert blocks[0].warning_metadata()[0]["code"] == "recovered_text_from_disallowed_block"


async def test_repair_metadata_recovers_text_bearing_equation_as_prose():
    metadata = DomainMetadata(
        custom_json={
            "parser_normalization": {
                "recover_text_bearing_blocks_as_prose": True,
            }
        }
    )
    data = [{"type": "equation", "text": "Arabic prose misclassified as equation", "page_idx": 0}]

    blocks = await MinerUContentNormalizer().normalize_content_list(data, domain_metadata=metadata)

    assert blocks[0].text == "Arabic prose misclassified as equation"
    assert blocks[0].warning_metadata()[0]["code"] == "recovered_text_from_misclassified_block"


async def test_top_level_table_body_is_extracted_for_table_blocks():
    data = [{"type": "table", "table_body": "Column A | Column B", "page_idx": 1}]

    blocks = await MinerUContentNormalizer().normalize_content_list(data)

    assert blocks[0].text == "Column A | Column B"
    assert blocks[0].block_type == "table"
    assert blocks[0].page == 2


async def test_reference_patterns_are_preserved_exactly_and_in_order():
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


async def test_custom_json_content_profile_configures_allowed_block_types_and_scripts():
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
    blocks = await MinerUContentNormalizer().normalize_content_list(data, expected_profile=profile)

    assert profile.expected_scripts == frozenset({"arabic", "latin"})
    assert profile.allowed_block_types == frozenset({"paragraph"})
    assert [block.text for block in blocks] == ["", "Included paragraph"]
    assert blocks[0].warning_metadata()[0]["code"] == "disallowed_block_type_quarantined"


async def test_bool_page_values_are_not_treated_as_page_numbers():
    data = [
        {"type": "text", "text": "No page", "page_idx": True},
        {"type": "paragraph", "text": "Still no page", "page": False},
    ]

    blocks = await MinerUContentNormalizer().normalize_content_list(data)

    assert [block.page for block in blocks] == [None, None]


async def test_nested_content_paragraph_content_and_null_character_cleanup():
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

    blocks = await MinerUContentNormalizer().normalize_content_list(data)

    assert [block.text for block in blocks] == ["First second third", "Nested text"]
    assert [block.page for block in blocks] == [1, 2]


async def test_reference_header_gap_recovery_stays_inside_header_column(
    tmp_path: Path,
    monkeypatch,
):
    fitz = pytest.importorskip("fitz")
    from ragstudio.services import parser_normalization

    pdf_path = tmp_path / "source_origin.pdf"
    document = fitz.open()
    document.new_page(width=612, height=792)
    document.save(pdf_path)
    document.close()

    recovered_text = "إنما التوبة على الله"

    def fake_pdf_recovery(context, *, page_number, content_bbox):
        del context, page_number
        assert content_bbox[0] < 80
        assert content_bbox[2] < 540
        return recovered_text

    monkeypatch.setattr(
        parser_normalization,
        "_pdf_arabic_lines_text_in_region",
        fake_pdf_recovery,
    )
    content_list = tmp_path / "source_content_list.json"
    data = [
        {
            "type": "text",
            "text": "Verse 4:17",
            "bbox": [90, 100, 175, 120],
            "page_idx": 0,
        },
        {
            "type": "text",
            "text": "The repentance accepted by Allah is only for those who do wrong.",
            "bbox": [90, 200, 470, 235],
            "page_idx": 0,
        },
    ]

    blocks = await MinerUContentNormalizer().normalize_content_list(
        data,
        domain_metadata=DomainMetadata(domain="quran_tafseer"),
        artifact_root=tmp_path,
        content_list_path=content_list,
    )

    assert [block.text for block in blocks] == [
        "Verse 4:17",
        recovered_text,
        "The repentance accepted by Allah is only for those who do wrong.",
    ]
