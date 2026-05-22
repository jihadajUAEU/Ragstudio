import json
from pathlib import Path

import pytest
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_splitter import ChunkSplitter
from ragstudio.services.domain_metadata_quality_gate import DomainMetadataQualityGate
from ragstudio.services.domain_metadata_service import DomainMetadataService
from ragstudio.services.modal_preprocessor import MODAL_ROUTER_PROCESSED_FLAG


def words(count: int, prefix: str = "word") -> str:
    return " ".join(f"{prefix}{index}" for index in range(count))


def parser_warning_codes(chunk: AdapterChunk) -> list[str]:
    warnings = chunk.metadata.get("extraction_quality", {}).get("parser_warnings", [])
    return [warning["code"] for warning in warnings]


def parser_warnings(chunk: AdapterChunk) -> list[dict[str, str]]:
    return chunk.metadata.get("extraction_quality", {}).get("parser_warnings", [])


def tafseer_cross_reference_metadata() -> DomainMetadata:
    return DomainMetadata(
        domain="quran_tafseer",
        document_type="commentary",
        language="mixed",
        content_role="tafseer",
        tags=["quran", "tafseer", "english"],
        citation_style="surah_ayah",
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "canonical_ref_template": "{chapter}:{verse}",
            },
            "chunking": {"unit": "verse_section", "preserve_parallel_text": True},
            "domain_structure": {
                "primary_anchor": {
                    "type": "chapter_verse",
                    "regex": r"\bVerse\s+(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})\b",
                    "unit": "verse_section",
                },
                "inline_references": {
                    "type": "chapter_verse",
                    "regex": r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})",
                    "policy": "cross_reference_only",
                },
            },
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
                "carry_forward_body_blocks": True,
                "header_only_policy": "provenance_only",
                "continuation_policy": "until_next_reference",
                "max_page_gap": 1,
                "require_single_reference_per_answerable_chunk": True,
            },
        },
    )


def bukhari_hadith_metadata() -> DomainMetadata:
    return DomainMetadata(
        domain="hadith",
        document_type="collection",
        tags=["hadith", "arabic", "english"],
        script="arabic",
        custom_json={
            "reference_schema": {
                "type": "book_hadith",
                "canonical_ref_template": "book:{book}:hadith:{hadith}",
            },
            "chunking": {"unit": "hadith", "preserve_parallel_text": True},
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
                "carry_forward_body_blocks": True,
                "header_only_policy": "provenance_only",
                "continuation_policy": "until_next_reference",
                "max_page_gap": 1,
            },
            "provenance": {
                "preserve_original_blocks": True,
                "store_text_hash": True,
            },
        },
    )


def test_chunk_splitter_splits_tafseer_book_markdown_under_hard_cap():
    text = "\n\n".join(
        [
            "# Tafsir Ibn Kathir",
            "## Surah 1",
            f"Verse 1:1\n\n{words(900, 'alpha')}",
            f"Verse 1:2\n\n{words(900, 'beta')}",
            "## Surah 2",
            f"Verse 2:1\n\n{words(900, 'gamma')}",
        ]
    )
    chunk = AdapterChunk(
        text=text,
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "parser_mode": "mineru_strict",
                "artifact_ref": "source/auto/source.md",
                "chunk_index": 0,
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="tafseer", document_type="book"),
        parser_mode="mineru_strict",
    )

    assert len(split) == 3
    assert all(len(item.text.split()) <= 1500 for item in split)
    assert split[0].text.startswith("# Tafsir Ibn Kathir")
    assert split[1].text.startswith("Verse 1:2")
    parser_metadata = split[0].metadata["parser_metadata"]
    assert parser_metadata["backend"] == "mineru"
    assert parser_metadata["split_strategy"] == "metadata_profile"
    assert parser_metadata["split_profile"] == "tafseer_book"
    assert parser_metadata["parent_artifact_ref"] == "source/auto/source.md"
    assert parser_metadata["parent_chunk_index"] == 0
    assert parser_metadata["split_index"] == 0
    assert parser_metadata["split_count"] == 3


def test_chunk_splitter_hard_splits_single_oversized_paragraph():
    chunk = AdapterChunk(
        text=words(3100),
        source_location={"artifact": "plain.txt"},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 4}},
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="generic", document_type="document"),
        parser_mode="mineru_strict",
    )

    assert [len(item.text.split()) for item in split] == [1500, 1500, 100]
    assert split[2].metadata["parser_metadata"]["split_index"] == 2
    assert split[2].metadata["parser_metadata"]["split_count"] == 3
    assert split[2].metadata["parser_metadata"]["split_profile"] == "generic"


def test_chunk_splitter_splits_long_sentence_at_nearest_semantic_boundary():
    text = f"{words(39, 'lead')} boundary, {words(81, 'tail')}."

    split = ChunkSplitter(max_words=50)._hard_split_text(text, 50)

    assert split[0].endswith("boundary,")
    assert len(split[0].split()) == 40
    assert len(split[1].split()) == 50


def test_chunk_splitter_falls_back_to_word_cap_when_no_boundary_exists():
    split = ChunkSplitter(max_words=50)._hard_split_text(words(121), 50)

    assert [len(item.split()) for item in split] == [50, 50, 21]


def test_chunk_splitter_preserves_small_chunks_unchanged():
    chunk = AdapterChunk(
        text="short text",
        source_location={"page": 1},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 2}},
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="tafseer", document_type="book"),
        parser_mode="mineru_strict",
    )

    assert len(split) == 1
    assert split[0].text == "short text"
    assert split[0].source_location == {"page": 1}
    assert split[0].metadata["parser_metadata"]["chunk_index"] == 2
    assert "split_strategy" not in split[0].metadata["parser_metadata"]


@pytest.mark.asyncio
async def test_chunk_splitter_uses_mineru_content_list_when_available(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        """
        [
          {"type":"text","text":"Page one heading","page_idx":0},
          {"type":"text","text":"Page one body","page_idx":0},
          {"type":"text","text":"Page two heading","page_idx":1},
          {"type":"text","text":"Page two body","page_idx":1}
        ]
        """,
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_ref": "source/auto/source.md",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "chunk_index": 0,
            }
        },
    )

    split = await ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="tafseer", document_type="book"),
        parser_mode="mineru_strict",
    )

    assert [item.text for item in split] == [
        "Page one heading\n\nPage one body\n\nPage two heading\n\nPage two body",
    ]
    assert split[0].source_location["page_start"] == 1
    assert split[0].source_location["page_end"] == 2


@pytest.mark.asyncio
async def test_chunk_splitter_processes_shared_content_list_once(tmp_path, monkeypatch):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "First paragraph.", "page_idx": 0},
                {"type": "text", "text": "Second paragraph.", "page_idx": 0},
            ]
        ),
        encoding="utf-8",
    )
    parser_metadata = {
        "backend": "mineru",
        "artifact_extract_dir": str(tmp_path),
        "content_list_ref": "source_content_list.json",
    }
    chunks = [
        AdapterChunk(
            text=f"placeholder {index}",
            source_location={"artifact": "source.md"},
            metadata={"parser_metadata": parser_metadata},
        )
        for index in range(3)
    ]
    splitter = ChunkSplitter(max_words=1500)
    calls = 0
    original = splitter.content_normalizer.normalize_content_list

    async def counted_normalize(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(
        splitter.content_normalizer,
        "normalize_content_list",
        counted_normalize,
    )

    split = await splitter.split(
        chunks,
        domain_metadata=DomainMetadata(domain="general"),
        parser_mode="mineru_strict",
    )

    assert calls == 1
    assert [chunk.text for chunk in split] == ["First paragraph.\n\nSecond paragraph."]


def test_chunk_splitter_does_not_reparse_modal_router_processed_chunk(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps([{"type": "text", "text": "This should not be reread"}]),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="Table: Scores\n\n| Name | Score |\n| A | 10 |",
        source_location={"artifact": "source/auto/source.md", "block_index": 1},
        metadata={
            MODAL_ROUTER_PROCESSED_FLAG: True,
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "chunk_index": 1,
            },
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="generic", document_type="table"),
        parser_mode="mineru_strict",
    )

    assert split[0].text.startswith("Table: Scores")
    assert "This should not be reread" not in "\n".join(item.text for item in split)


@pytest.mark.asyncio
async def test_chunk_splitter_stitches_continuation_across_pages(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "text": "This paragraph starts on page one and",
                    "page_idx": 0,
                },
                {
                    "type": "text",
                    "text": "continues on page two before ending.",
                    "page_idx": 1,
                },
            ]
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source.md"},
        metadata={
            "parser_metadata": {
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "parser_mode": "mineru_strict",
            }
        },
    )

    split = await ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="general", document_type="report"),
        parser_mode="mineru_strict",
    )

    assert len(split) == 1
    assert "page one and continues" in split[0].text
    assert split[0].source_location["page_start"] == 1
    assert split[0].source_location["page_end"] == 2


@pytest.mark.asyncio
async def test_chunk_splitter_removes_stale_page_when_setting_page_range(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "text": "This paragraph starts on the first page and",
                    "page_idx": 0,
                },
                {
                    "type": "text",
                    "text": "continues onto the second page.",
                    "page_idx": 1,
                },
            ]
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source.md", "page": 1},
        metadata={
            "parser_metadata": {
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "parser_mode": "mineru_strict",
            }
        },
    )

    split = await ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="general", document_type="report"),
        parser_mode="mineru_strict",
    )

    assert len(split) == 1
    assert split[0].source_location["page_start"] == 1
    assert split[0].source_location["page_end"] == 2
    assert "page" not in split[0].source_location


@pytest.mark.asyncio
async def test_chunk_splitter_preserves_page_provenance_for_split_content_list_references(
    tmp_path: Path,
):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "[1:1] Page one reference text.", "page_idx": 0},
                {"type": "text", "text": "[1:2] Page two reference text.", "page_idx": 1},
            ]
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source.md", "page": 1},
        metadata={
            "parser_metadata": {
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "parser_mode": "mineru_strict",
            }
        },
    )

    split = await ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="religion",
            tags=["quran"],
            custom_json={
                "reference_schema": {"type": "surah_ayah"},
                "chunking": {"unit": "verse"},
            },
        ),
        parser_mode="mineru_strict",
    )

    assert [item.metadata["reference_metadata"]["references"] for item in split] == [
        ["1:1"],
        ["1:2"],
    ]
    assert split[0].source_location["page_start"] == 1
    assert split[0].source_location["page_end"] == 1
    assert split[1].source_location["page_start"] == 2
    assert split[1].source_location["page_end"] == 2
    assert "page" not in split[0].source_location
    assert "page" not in split[1].source_location


@pytest.mark.asyncio
async def test_chunk_splitter_scopes_hard_split_stitched_reference_warnings(
    tmp_path: Path,
):
    page_one_text = words(80, "pageone")
    page_two_text = words(80, "pagetwo")
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": f"[1:1] {page_one_text}", "page_idx": 0},
                {"type": "equation", "text": page_two_text, "page_idx": 1},
                {"type": "text", "text": "[1:2] Next reference.", "page_idx": 2},
            ]
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source.md", "page": 1},
        metadata={
            "parser_metadata": {
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "parser_mode": "mineru_strict",
            }
        },
    )

    split = await ChunkSplitter(max_words=50).split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="religion",
            tags=["quran"],
            custom_json={
                "reference_schema": {"type": "surah_ayah"},
                "chunking": {"unit": "verse"},
                "parser_normalization": {"recover_text_bearing_blocks_as_prose": True},
            },
        ),
        parser_mode="mineru_strict",
    )

    assert len(split) > 2
    first_child = split[0]
    assert "pageone0" in first_child.text
    assert "pagetwo0" not in first_child.text
    assert first_child.source_location["page_start"] == 1
    assert first_child.source_location["page_end"] == 1
    assert "page" not in first_child.source_location
    assert "recovered_text_from_misclassified_block" not in parser_warning_codes(first_child)
    assert all(warning.get("page") != 2 for warning in parser_warnings(first_child))


def test_chunk_splitter_invalid_content_list_falls_back_to_markdown(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text("{not json", encoding="utf-8")
    chunk = AdapterChunk(
        text=f"## Section\n\n{words(1600)}",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "chunk_index": 0,
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="tafseer", document_type="book"),
        parser_mode="mineru_strict",
    )

    assert len(split) == 2
    assert all(len(item.text.split()) <= 1500 for item in split)


def test_chunk_splitter_uses_scripture_profile_from_editable_metadata_json():
    chunk = AdapterChunk(
        text=(
            "Surah 1\n\n"
            "[1:1]\n\n[All] praise is [due] to Allah, Lord of the worlds -\n\n"
            "[1:2]\n\nThe Entirely Merciful, the Especially Merciful,"
        ),
        source_location={"artifact": "source/auto/source.md", "page_start": 2, "page_end": 2},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )
    metadata = DomainMetadata(
        domain="religion",
        document_type="religious_text",
        tags=["quran"],
        custom_json={
            "reference_schema": {"type": "surah_ayah"},
            "chunking": {"unit": "verse", "include_neighbors": 1, "preserve_parallel_text": True},
            "retrieval": {"exact_reference_top1": True},
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=metadata,
        parser_mode="mineru_strict",
    )

    assert [item.metadata["reference_metadata"]["references"] for item in split] == [
        ["1:1"],
        ["1:2"],
    ]
    assert split[0].metadata["parser_metadata"]["split_profile"] == "scripture_reference"
    assert split[0].metadata["reference_metadata"]["reference_type"] == "surah_ayah"
    assert split[0].metadata["reference_metadata"]["page_start"] == 2
    assert split[0].metadata["reference_metadata"]["page_end"] == 2
    assert "previous_ref" not in split[0].metadata["reference_metadata"]
    assert split[0].metadata["reference_metadata"]["next_ref"] == "1:2"


def test_chunk_splitter_selects_scripture_profile_from_standard_fields():
    chunk = AdapterChunk(
        text="Surah 2\n\n[2:2]\n\nThis is the Book about which there is no doubt.",
        source_location={"artifact": "source/auto/source.md", "page_start": 3, "page_end": 3},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="religion",
            document_type="religious_text",
            tags=["quran", "translation"],
            reference_pattern="surah_number:verse_number",
            expected_structure="parallel_text",
        ),
        parser_mode="mineru_strict",
    )

    assert split[0].metadata["parser_metadata"]["split_profile"] == "scripture_reference"
    assert split[0].metadata["reference_metadata"]["chapter_start"] == 2
    assert split[0].metadata["reference_metadata"]["verse_start"] == 2


def test_chunk_splitter_preserves_title_as_small_metadata_chunk():
    chunk = AdapterChunk(
        text=(
            "The Holy Quran\n\n"
            "Arabic Text with English Translation\n\n"
            "Surah 1\n\n[1:1]\n\n[All] praise is [due] to Allah, Lord of the worlds -"
        ),
        source_location={"artifact": "source/auto/source.md", "page_start": 1, "page_end": 2},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="religion",
            tags=["quran"],
            reference_pattern="surah_number:verse_number",
        ),
        parser_mode="mineru_strict",
    )

    assert [item.text for item in split] == [
        "The Holy Quran\n\nArabic Text with English Translation",
        "Surah 1\n\n[1:1]\n\n[All] praise is [due] to Allah, Lord of the worlds -",
    ]
    title_chunk = split[0]
    assert title_chunk.metadata["parser_metadata"]["split_profile"] == "scripture_reference"
    assert title_chunk.metadata["document_metadata"]["title"] == (
        "The Holy Quran Arabic Text with English Translation"
    )


def test_chunk_splitter_cleans_obvious_mineru_noise_without_removing_text():
    arabic_text = "\u0627\u0644\u062d\u0645\u062f \u0644\u0644\u0647"
    chunk = AdapterChunk(
        text=(
            "Surah 1\n\n"
            "$$ \\theta = \\alpha \\beta $$\n\n"
            "[1:3]\n\n"
            f"Arabic text stays. {arabic_text}\n\n"
            "|\n\n"
            "English text stays."
        ),
        source_location={"artifact": "source/auto/source.md", "page_start": 4, "page_end": 4},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="religion",
            tags=["quran"],
            reference_pattern="surah_number:verse_number",
        ),
        parser_mode="mineru_strict",
    )

    assert "$$" not in split[0].text
    assert "\n|\n" not in split[0].text
    assert f"Arabic text stays. {arabic_text}" in split[0].text
    assert "English text stays." in split[0].text
    assert split[0].metadata["reference_metadata"]["references"] == ["1:3"]


def test_chunk_splitter_splits_reference_units_when_metadata_requests_verse_chunks():
    chunk = AdapterChunk(
        text="Surah 1\n\n[1:4]\n\nIt is You we worship.\n\n[1:5]\n\nGuide us.",
        source_location={"page_start": 2, "page_end": 2},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="religion",
            tags=["quran"],
            custom_json={
                "reference_schema": {"type": "surah_ayah"},
                "chunking": {"unit": "verse", "include_neighbors": 1},
            },
        ),
        parser_mode="mineru_strict",
    )

    assert [item.metadata["reference_metadata"]["references"] for item in split] == [
        ["1:4"],
        ["1:5"],
    ]
    assert split[0].text.startswith("Surah 1")
    assert split[1].text.startswith("[1:5]")


def test_chunk_splitter_uses_explicit_domain_metadata_for_content_list_normalization(
    tmp_path: Path,
):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        """
        [
          {"type":"equation","text":"$$ \\\\theta = \\\\alpha \\\\beta $$","page_idx":0},
          {"type":"text","text":"[1:1] English translation only.","page_idx":0}
        ]
        """,
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "chunk_index": 0,
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="religion",
            tags=["quran"],
            script="arabic",
            reference_pattern="surah_number:verse_number",
        ),
        parser_mode="mineru_strict",
    )

    warning_codes = {
        code for chunk in split for code in parser_warning_codes(chunk)
    }
    assert all("$$" not in chunk.text for chunk in split)
    assert "suspected_text_misclassified_as_equation" in warning_codes
    assert "reference_unit_missing_expected_script" in warning_codes


def test_chunk_splitter_quarantines_quran_like_equation_from_content_list(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        """
        [
          {"type":"text","text":"[1:2] The Entirely Merciful.","page_idx":0},
          {"type":"equation","text":"$$ \\\\theta = \\\\alpha \\\\beta $$","page_idx":0}
        ]
        """,
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="religion",
            tags=["quran"],
            script="arabic",
            reference_pattern="surah_number:verse_number",
        ),
        parser_mode="mineru_strict",
    )

    assert split[0].text == "[1:2] The Entirely Merciful."
    assert "$$" not in split[0].text
    assert "suspected_text_misclassified_as_equation" in parser_warning_codes(split[1])


def test_chunk_splitter_emits_warning_only_piece_for_quarantined_page(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        """
        [
          {"type":"equation","text":"$$ \\\\theta = \\\\alpha \\\\beta $$","page_idx":0},
          {"type":"text","text":"[1:2] The Entirely Merciful.","page_idx":1}
        ]
        """,
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="religion",
            tags=["quran"],
            script="arabic",
            reference_pattern="surah_number:verse_number",
        ),
        parser_mode="mineru_strict",
    )

    assert len(split) == 2
    assert "Parser quality gate quarantined" in split[0].text
    assert "$$" not in split[0].text
    assert "\\theta" not in split[0].text
    assert split[0].content_type == "parser_quality_warning"
    assert split[0].source_location["page_start"] == 1
    assert split[0].source_location["page_end"] == 1
    assert "suspected_text_misclassified_as_equation" in parser_warning_codes(split[0])
    assert split[1].text == "[1:2] The Entirely Merciful."
    assert split[1].source_location["page_start"] == 2
    assert parser_warning_codes(split[1]) == [
        "reference_unit_missing_expected_script",
    ]


def test_chunk_splitter_all_quarantined_content_list_does_not_fallback_to_parent_text(
    tmp_path: Path,
):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        """
        [
          {"type":"equation","text":"$$ \\\\theta = \\\\alpha \\\\beta $$","page_idx":0}
        ]
        """,
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown with $$ \\\\theta = \\\\alpha \\\\beta $$ should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="religion", tags=["quran"], script="arabic"),
        parser_mode="mineru_strict",
    )

    assert len(split) == 1
    assert "fallback markdown" not in split[0].text
    assert "$$" not in split[0].text
    assert split[0].content_type == "parser_quality_warning"
    assert split[0].metadata["parser_metadata"]["parser_quality_only"] is True
    assert "suspected_text_misclassified_as_equation" in parser_warning_codes(split[0])


def test_chunk_splitter_inserts_recovered_text_with_parser_warning(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    recovered_text = (
        "[1:3] "
        "\u0645\u0627\u0644\u0643 "
        "\u064a\u0648\u0645 "
        "\u0627\u0644\u062f\u064a\u0646"
    )
    content_list.write_text(
        f"""
        [
          {{
            "type":"equation",
            "text":"$$ bad mineru equation $$",
            "recovered_text":"{recovered_text}",
            "page_idx":0
          }}
        ]
        """,
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="religion", tags=["quran"], script="arabic"),
        parser_mode="mineru_strict",
    )

    assert split[0].text == recovered_text
    assert "recovered_text_from_misclassified_block" in parser_warning_codes(split[0])


def test_chunk_splitter_preserves_content_list_metadata_when_text_matches_parent(
    tmp_path: Path,
):
    content_list = tmp_path / "source_content_list.json"
    recovered_text = (
        "\u0647\u0630\u0627 "
        "\u0646\u0635 "
        "\u0639\u0631\u0628\u064a "
        "\u0645\u0633\u062a\u0639\u0627\u062f"
    )
    content_list.write_text(
        f"""
        [
          {{
            "type":"equation",
            "text":"$$ bad mineru equation $$",
            "recovered_text":"{recovered_text}",
            "page_idx":2
          }}
        ]
        """,
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text=recovered_text,
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="religion", tags=["quran"], script="arabic"),
        parser_mode="mineru_strict",
    )

    assert split[0].text == recovered_text
    assert split[0].source_location["page_start"] == 3
    assert split[0].source_location["page_end"] == 3
    assert "recovered_text_from_misclassified_block" in parser_warning_codes(split[0])


def test_chunk_splitter_flags_hadith_reference_missing_expected_arabic():
    chunk = AdapterChunk(
        text="Book 1, Hadith 7\n\nThe Prophet said this in English translation only.",
        source_location={"page_start": 1, "page_end": 1},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="hadith", script="arabic"),
        parser_mode="mineru_strict",
    )

    assert "reference_unit_missing_expected_script" in parser_warning_codes(split[0])


def test_chunk_splitter_builds_canonical_hadith_units_from_header_body_blocks(
    tmp_path: Path,
):
    arabic_body = "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644 \u0627\u0644\u0644\u0647"
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "Book 1, Hadith 3", "page_idx": 3},
                {"type": "text", "text": arabic_body, "page_idx": 3},
                {
                    "type": "text",
                    "text": "The Messenger of Allah said this in translation.",
                    "page_idx": 4,
                },
                {"type": "text", "text": "Book 1, Hadith 4", "page_idx": 4},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "chunk_index": 0,
            }
        },
    )
    metadata = DomainMetadata(
        domain="hadith",
        document_type="collection",
        tags=["hadith", "arabic", "english"],
        script="arabic",
        custom_json={
            "reference_schema": {
                "type": "book_hadith",
                "display": "Book {book}, Hadith {hadith}",
                "canonical_ref_template": "book:{book}:hadith:{hadith}",
            },
            "chunking": {"unit": "hadith", "preserve_parallel_text": True},
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

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=metadata,
        parser_mode="mineru_strict",
    )

    assert len(split) == 2
    canonical = split[0]
    assert canonical.content_type == "text"
    assert "Book 1, Hadith 3" in canonical.text
    assert arabic_body in canonical.text
    assert "The Messenger of Allah" in canonical.text
    assert canonical.source_location["page_start"] == 4
    assert canonical.source_location["page_end"] == 5
    assert canonical.metadata["reference_metadata"]["references"] == ["book:1:hadith:3"]
    assert canonical.metadata["canonical_reference_unit"]["answerable"] is True
    assert canonical.metadata["canonical_reference_unit"]["body_status"] == "assembled"
    provenance_blocks = canonical.metadata["provenance"]["blocks"]
    assert [block["role"] for block in provenance_blocks] == [
        "reference_header",
        "reference_body",
        "reference_continuation",
    ]
    assert all("text_hash" in block for block in provenance_blocks)
    assert "reference_unit_missing_expected_script" not in parser_warning_codes(canonical)

    header_only = split[1]
    assert header_only.text == "Book 1, Hadith 4"
    assert header_only.content_type == "reference_provenance"
    assert header_only.metadata["parser_metadata"]["provenance_only"] is True
    assert header_only.metadata["canonical_reference_unit"]["answerable"] is False
    assert header_only.metadata["quality_action_policy"]["index_vector"] is False
    assert parser_warning_codes(header_only) == []


def test_chunk_splitter_uses_layout_aware_hadith_strategy_for_late_header(
    tmp_path: Path,
):
    arabic_body = (
        "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644 \u0627\u0644\u0644\u0647 "
        "\u0635\u0644\u0649 \u0627\u0644\u0644\u0647 \u0639\u0644\u064a\u0647 "
        "\u0648\u0633\u0644\u0645"
    )
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": arabic_body, "page_idx": 126},
                {
                    "type": "text",
                    "text": "It was narrated that Anas said...",
                    "page_idx": 126,
                },
                {
                    "type": "header",
                    "recovered_text": "Book 2, Hadith 29 - Grade: Sahih",
                    "page_idx": 126,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "chunk_index": 0,
            }
        },
    )
    metadata = DomainMetadata(
        domain="hadith",
        document_type="collection",
        tags=["hadith", "arabic", "english"],
        script="arabic",
        custom_json={
            "reference_schema": {
                "type": "book_hadith",
                "canonical_ref_template": "book:{book}:hadith:{hadith}",
            },
            "chunking": {"unit": "hadith", "preserve_parallel_text": True},
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
                "carry_forward_body_blocks": True,
                "header_only_policy": "provenance_only",
                "max_page_gap": 1,
            },
            "provenance": {
                "preserve_original_blocks": True,
                "store_text_hash": True,
            },
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=metadata,
        parser_mode="mineru_strict",
    )

    assert len(split) == 1
    canonical = split[0]
    assert canonical.preview_ref == "book:2:hadith:29"
    assert "Book 2, Hadith 29" in canonical.text
    assert arabic_body in canonical.text
    assert "It was narrated" in canonical.text
    assert canonical.metadata["canonical_reference_unit"]["assembly_strategy"] == (
        "domain_evidence_graph"
    )
    warnings = parser_warnings(canonical)
    assert [warning["code"] for warning in warnings] == [
        "recovered_text_from_disallowed_block"
    ]
    provenance_blocks = canonical.metadata["provenance"]["blocks"]
    assert [block["role"] for block in provenance_blocks] == [
        "reference_header",
        "reference_body",
        "reference_continuation",
    ]
    assert provenance_blocks[0]["warning_codes"] == [
        "recovered_text_from_disallowed_block"
    ]
    assert all("text_hash" in block for block in provenance_blocks)
    assert "reference_unit_missing_expected_script" not in parser_warning_codes(canonical)


def test_chunk_splitter_reassociates_recovered_hadith_header_on_dense_visual_page(
    tmp_path: Path,
):
    arabic_12 = (
        "\u0627\u0644\u0645\u0633\u0644\u0645 \u063a\u0646\u0645 "
        "\u064a\u062a\u0628\u0639 \u0628\u0647\u0627 \u0634\u0639\u0641 "
        "\u0627\u0644\u062c\u0628\u0627\u0644 \u0648\u0645\u0648\u0627\u0642\u0639 "
        "\u0627\u0644\u0642\u0637\u0631\u060c \u064a\u0641\u0631 "
        "\u0628\u062f\u064a\u0646\u0647 \u0645\u0646 \u0627\u0644\u0641\u062a\u0646"
    )
    english_12 = (
        "Narrated Abu Said Al-Khudri: Allah's Messenger (■) said, "
        '"A time will soon come when the best property of a Muslim will be sheep."'
    )
    arabic_13 = (
        "\u062d\u062a\u0649 \u064a\u0639\u0631\u0641 \u0627\u0644\u063a\u0636\u0628 "
        "\u0641\u064a \u0648\u062c\u0647\u0647 \u062b\u0645 \u064a\u0642\u0648\u0644 "
        "\u0625\u0646 \u0623\u062a\u0642\u0627\u0643\u0645 "
        "\u0648\u0623\u0639\u0644\u0645\u0643\u0645 \u0628\u0627\u0644\u0644\u0647 "
        "\u0623\u0646\u0627"
    )
    english_13 = "Narrated 'Aisha: Whenever Allah's Messenger ordered the Muslims."
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "text": arabic_12,
                    "bbox": [101, 103, 906, 229],
                    "page_idx": 14,
                },
                {
                    "type": "text",
                    "text": english_12,
                    "bbox": [89, 239, 900, 291],
                    "page_idx": 14,
                },
                {
                    "type": "text",
                    "text": "Book 2, Hadith 13",
                    "bbox": [91, 309, 218, 324],
                    "page_idx": 14,
                },
                {
                    "type": "text",
                    "text": arabic_13,
                    "bbox": [91, 334, 905, 496],
                    "page_idx": 14,
                },
                {
                    "type": "text",
                    "text": english_13,
                    "bbox": [89, 506, 803, 613],
                    "page_idx": 14,
                },
                {
                    "type": "header",
                    "recovered_text": "Book 2, Hadith 12",
                    "bbox": [93, 75, 217, 89],
                    "page_idx": 14,
                },
                {
                    "type": "footer",
                    "recovered_text": "Book 2, Hadith 14",
                    "bbox": [93, 901, 217, 915],
                    "page_idx": 14,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "chunk_index": 0,
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=bukhari_hadith_metadata(),
        parser_mode="mineru_strict",
    )

    by_ref = {piece.preview_ref: piece for piece in split if piece.preview_ref}
    hadith_12 = by_ref["book:2:hadith:12"]
    assert set(by_ref) == {
        "book:2:hadith:12",
        "book:2:hadith:13",
        "book:2:hadith:14",
    }
    assert "Book 2, Hadith 12" in hadith_12.text
    assert arabic_12 in hadith_12.text
    assert english_12 in hadith_12.text
    assert "Book 2, Hadith 13" not in hadith_12.text
    assert arabic_13 in by_ref["book:2:hadith:13"].text
    assert english_13 in by_ref["book:2:hadith:13"].text
    assert by_ref["book:2:hadith:14"].content_type == "reference_provenance"
    assert hadith_12.metadata["canonical_reference_unit"]["assembly_strategy"] == (
        "domain_evidence_graph"
    )
    assert hadith_12.source_location["page_start"] == 15
    assert hadith_12.source_location["page_end"] == 15
    assert "reference_unit_missing_expected_script" not in parser_warning_codes(hadith_12)
    assert "recovered_text_from_disallowed_block" in parser_warning_codes(hadith_12)


def test_chunk_splitter_keeps_next_hadith_footer_as_provenance_boundary(
    tmp_path: Path,
):
    arabic_14 = (
        "\u0648\u0645\u0646 \u064a\u0643\u0631\u0647 \u0623\u0646 "
        "\u064a\u0639\u0648\u062f \u0641\u064a \u0627\u0644\u0643\u0641\u0631 "
        "\u0628\u0639\u062f \u0625\u0630 \u0623\u0646\u0642\u0630\u0647 "
        "\u0627\u0644\u0644\u0647"
    )
    english_14 = "Narrated Anas: The Prophet said whoever possesses three qualities."
    arabic_15 = (
        "\u0635\u0641\u0631\u0627\u0621 \u0645\u0644\u062a\u0648\u064a\u0629 "
        "\u0642\u0627\u0644 \u0648\u0647\u064a\u0628 \u062d\u062f\u062b\u0646\u0627 "
        "\u0639\u0645\u0631\u0648"
    )
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "text": "Book 2, Hadith 14",
                    "bbox": [91, 631, 218, 645],
                    "page_idx": 14,
                },
                {
                    "type": "text",
                    "text": arabic_14,
                    "bbox": [99, 655, 905, 784],
                    "page_idx": 14,
                },
                {
                    "type": "text",
                    "text": english_14,
                    "bbox": [89, 795, 905, 866],
                    "page_idx": 14,
                },
                {
                    "type": "footer",
                    "recovered_text": "Book 2, Hadith 15",
                    "bbox": [93, 901, 217, 915],
                    "page_idx": 14,
                },
                {
                    "type": "text",
                    "text": arabic_15,
                    "bbox": [96, 75, 906, 299],
                    "page_idx": 15,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=bukhari_hadith_metadata(),
        parser_mode="mineru_strict",
    )

    by_ref = {piece.preview_ref: piece for piece in split if piece.preview_ref}
    assert arabic_14 in by_ref["book:2:hadith:14"].text
    assert arabic_15 not in by_ref["book:2:hadith:14"].text
    assert arabic_15 in by_ref["book:2:hadith:15"].text
    assert by_ref["book:2:hadith:15"].content_type == "text"
    assert "recovered_text_from_disallowed_block" in parser_warning_codes(
        by_ref["book:2:hadith:15"]
    )


def test_chunk_splitter_keeps_missing_arabic_warning_when_visual_unit_has_no_arabic(
    tmp_path: Path,
):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "text": "Book 2, Hadith 20",
                    "bbox": [91, 100, 218, 116],
                    "page_idx": 20,
                },
                {
                    "type": "text",
                    "text": "Narrated Abu Huraira: English translation only.",
                    "bbox": [91, 130, 900, 160],
                    "page_idx": 20,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=bukhari_hadith_metadata(),
        parser_mode="mineru_strict",
    )

    assert "reference_unit_missing_expected_script" in parser_warning_codes(split[0])


def test_chunk_splitter_keeps_hadith_body_across_page_until_next_anchor(
    tmp_path: Path,
):
    arabic = (
        "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644 \u0627\u0644\u0644\u0647 "
        "\u0635\u0644\u0649 \u0627\u0644\u0644\u0647 \u0639\u0644\u064a\u0647 "
        "\u0648\u0633\u0644\u0645"
    )
    english_page_two = "The translation continues on the next page before a new hadith."
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "text": "Book 3, Hadith 4",
                    "bbox": [91, 880, 218, 896],
                    "page_idx": 30,
                },
                {
                    "type": "text",
                    "text": arabic,
                    "bbox": [91, 904, 906, 940],
                    "page_idx": 30,
                },
                {
                    "type": "text",
                    "text": english_page_two,
                    "bbox": [91, 74, 900, 120],
                    "page_idx": 31,
                },
                {
                    "type": "text",
                    "text": "Book 3, Hadith 5",
                    "bbox": [91, 140, 218, 156],
                    "page_idx": 31,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=bukhari_hadith_metadata(),
        parser_mode="mineru_strict",
    )

    by_ref = {piece.preview_ref: piece for piece in split if piece.preview_ref}
    assert arabic in by_ref["book:3:hadith:4"].text
    assert english_page_two in by_ref["book:3:hadith:4"].text
    assert "Book 3, Hadith 5" not in by_ref["book:3:hadith:4"].text
    assert by_ref["book:3:hadith:4"].source_location["page_start"] == 31
    assert by_ref["book:3:hadith:4"].source_location["page_end"] == 32
    assert "reference_unit_missing_expected_script" not in parser_warning_codes(
        by_ref["book:3:hadith:4"]
    )


def test_chunk_splitter_stops_hadith_body_at_competing_recovered_anchor(
    tmp_path: Path,
):
    arabic_20 = (
        "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644 \u0627\u0644\u0644\u0647 "
        "\u0635\u0644\u0649 \u0627\u0644\u0644\u0647 \u0639\u0644\u064a\u0647 "
        "\u0648\u0633\u0644\u0645 \u0641\u064a \u0627\u0644\u062d\u062f\u064a\u062b "
        "\u0627\u0644\u0623\u0648\u0644"
    )
    english_20 = "Narrated first companion: first translation."
    arabic_21 = (
        "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644 \u0627\u0644\u0644\u0647 "
        "\u0635\u0644\u0649 \u0627\u0644\u0644\u0647 \u0639\u0644\u064a\u0647 "
        "\u0648\u0633\u0644\u0645 \u0641\u064a \u0627\u0644\u062d\u062f\u064a\u062b "
        "\u0627\u0644\u062b\u0627\u0646\u064a"
    )
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "type": "header",
                    "recovered_text": "Book 5, Hadith 20",
                    "bbox": [91, 80, 220, 96],
                    "page_idx": 50,
                },
                {
                    "type": "text",
                    "text": arabic_20,
                    "bbox": [91, 110, 906, 170],
                    "page_idx": 50,
                },
                {
                    "type": "text",
                    "text": english_20,
                    "bbox": [91, 180, 906, 230],
                    "page_idx": 50,
                },
                {
                    "type": "header",
                    "recovered_text": "Book 5, Hadith 21",
                    "bbox": [91, 240, 220, 256],
                    "page_idx": 50,
                },
                {
                    "type": "text",
                    "text": arabic_21,
                    "bbox": [91, 270, 906, 330],
                    "page_idx": 50,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=bukhari_hadith_metadata(),
        parser_mode="mineru_strict",
    )

    by_ref = {piece.preview_ref: piece for piece in split if piece.preview_ref}
    assert arabic_20 in by_ref["book:5:hadith:20"].text
    assert english_20 in by_ref["book:5:hadith:20"].text
    assert arabic_21 not in by_ref["book:5:hadith:20"].text
    assert arabic_21 in by_ref["book:5:hadith:21"].text
    assert by_ref["book:5:hadith:20"].metadata["reference_metadata"]["references"] == [
        "book:5:hadith:20"
    ]
    assert by_ref["book:5:hadith:21"].metadata["reference_metadata"]["references"] == [
        "book:5:hadith:21"
    ]


def test_chunk_splitter_preserves_genuine_warning_when_dense_page_has_partial_success(
    tmp_path: Path,
):
    arabic_12 = "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644 \u0627\u0644\u0644\u0647"
    english_12 = "Narrated first companion: Arabic-backed translation."
    english_13 = "Narrated second companion: English translation only."
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "type": "header",
                    "recovered_text": "Book 2, Hadith 12",
                    "bbox": [93, 75, 217, 89],
                    "page_idx": 14,
                },
                {
                    "type": "text",
                    "text": arabic_12,
                    "bbox": [101, 103, 906, 229],
                    "page_idx": 14,
                },
                {
                    "type": "text",
                    "text": english_12,
                    "bbox": [89, 239, 900, 291],
                    "page_idx": 14,
                },
                {
                    "type": "text",
                    "text": "Book 2, Hadith 13",
                    "bbox": [91, 309, 218, 324],
                    "page_idx": 14,
                },
                {
                    "type": "text",
                    "text": english_13,
                    "bbox": [89, 506, 803, 613],
                    "page_idx": 14,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=bukhari_hadith_metadata(),
        parser_mode="mineru_strict",
    )

    by_ref = {piece.preview_ref: piece for piece in split if piece.preview_ref}
    assert arabic_12 in by_ref["book:2:hadith:12"].text
    assert "reference_unit_missing_expected_script" not in parser_warning_codes(
        by_ref["book:2:hadith:12"]
    )
    assert english_13 in by_ref["book:2:hadith:13"].text
    assert "reference_unit_missing_expected_script" in parser_warning_codes(
        by_ref["book:2:hadith:13"]
    )


def test_chunk_splitter_preserves_unassigned_canonical_blocks_as_provenance(
    tmp_path: Path,
):
    arabic_body = "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644 \u0627\u0644\u0644\u0647"
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "Collection Preface", "page_idx": 0},
                {"type": "equation_interline", "page_idx": 0},
                {"type": "text", "text": "Book 1, Hadith 3", "page_idx": 3},
                {"type": "text", "text": arabic_body, "page_idx": 3},
                {"type": "text", "text": "Detached commentary", "page_idx": 8},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "chunk_index": 0,
            }
        },
    )
    metadata = DomainMetadata(
        domain="hadith",
        document_type="collection",
        tags=["hadith", "arabic"],
        script="arabic",
        custom_json={
            "reference_schema": {
                "type": "book_hadith",
                "canonical_ref_template": "book:{book}:hadith:{hadith}",
            },
            "chunking": {"unit": "hadith", "preserve_parallel_text": True},
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
                "carry_forward_body_blocks": True,
                "header_only_policy": "provenance_only",
                "max_page_gap": 2,
            },
            "provenance": {"preserve_original_blocks": True},
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=metadata,
        parser_mode="mineru_strict",
    )

    assert len(split) == 4
    preface, warning_only, canonical, detached = split
    assert preface.content_type == "reference_provenance"
    assert preface.text == "Collection Preface"
    assert preface.metadata["parser_metadata"]["provenance_reason"] == (
        "unassigned_before_first_reference"
    )
    assert preface.metadata["quality_action_policy"]["index_vector"] is False

    assert warning_only.content_type == "reference_provenance"
    assert warning_only.text.startswith("[Parser quality provenance retained")
    assert parser_warning_codes(warning_only) == [
        "suspected_text_misclassified_as_equation"
    ]

    assert canonical.metadata["reference_metadata"]["references"] == [
        "book:1:hadith:3"
    ]
    assert arabic_body in canonical.text

    assert detached.content_type == "reference_provenance"
    assert detached.text == "Detached commentary"
    assert detached.metadata["parser_metadata"]["provenance_reason"] == (
        "max_page_gap_exceeded"
    )
    assert detached.metadata["quality_action_policy"]["project_graph"] is False


def test_chunk_splitter_builds_canonical_quran_verse_from_header_body_blocks(
    tmp_path: Path,
):
    arabic_body = "\u0648\u062d\u0646\u0627\u0646\u0627 \u0645\u0646 \u0644\u062f\u0646\u0627"
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "[19:13]", "page_idx": 311},
                {"type": "text", "text": arabic_body, "page_idx": 311},
                {
                    "type": "text",
                    "text": "And affection from Us and purity.",
                    "page_idx": 311,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )
    metadata = DomainMetadata(
        domain="quran_tafseer",
        tags=["quran", "arabic", "english"],
        script="arabic",
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "canonical_ref_template": "{chapter}:{verse}",
            },
            "chunking": {"unit": "verse", "preserve_parallel_text": True},
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
                "carry_forward_body_blocks": True,
                "header_only_policy": "provenance_only",
                "continuation_policy": "until_next_reference",
                "max_page_gap": 1,
                "require_single_reference_per_answerable_chunk": True,
            },
            "provenance": {"preserve_original_blocks": True},
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=metadata,
        parser_mode="mineru_strict",
    )

    assert len(split) == 1
    assert split[0].metadata["reference_metadata"]["references"] == ["19:13"]
    assert split[0].source_location["page_start"] == 312
    assert arabic_body in split[0].text
    assert "reference_unit_missing_expected_script" not in parser_warning_codes(split[0])


@pytest.mark.asyncio
async def test_chunk_splitter_dedupes_existing_quality_gate_warning():
    warning = {
        "code": "reference_unit_missing_expected_script",
        "message": (
            "Reference-bearing chunk is expected to contain Arabic script, "
            "but no Arabic letters were detected."
        ),
        "expected_script": "arabic",
    }
    chunk = AdapterChunk(
        text="[1:1] English translation only.",
        source_location={"page_start": 1, "page_end": 1},
        metadata={
            "parser_metadata": {"backend": "mineru", "chunk_index": 0},
            "extraction_quality": {"parser_warnings": [warning]},
        },
    )

    split = await ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="religion", tags=["quran"], script="arabic"),
        parser_mode="mineru_strict",
    )

    warnings = parser_warnings(split[0])
    assert warnings == [warning]
    assert "parser_warnings" not in split[0].metadata


@pytest.mark.asyncio
async def test_chunk_splitter_writes_quality_gate_warnings_to_extraction_quality():
    chunk = AdapterChunk(
        text="[1:1] English translation only.",
        source_location={"page_start": 1, "page_end": 1},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    split = await ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="religion", tags=["quran"], script="arabic"),
        parser_mode="mineru_strict",
    )

    warnings = parser_warnings(split[0])
    assert [warning["code"] for warning in warnings] == [
        "reference_unit_missing_expected_script"
    ]
    assert "parser_warnings" not in split[0].metadata
    assert DomainMetadataQualityGate().parser_warnings_for_chunk(split[0]) == warnings


@pytest.mark.asyncio
async def test_chunk_splitter_does_not_enrich_unchanged_piece_for_info_only_warning():
    chunk = AdapterChunk(
        text="Verse 18:30 Indeed, those who have believed.",
        source_location={"page_start": 809, "page_end": 809},
        metadata={
            "parser_metadata": {"backend": "mineru", "chunk_index": 0},
            "extraction_quality": {
                "parser_warnings": [
                    {
                        "code": "recovered_text_from_misclassified_block",
                        "block_type": "equation",
                        "message": "Used parser-provided recovered text.",
                    }
                ]
            },
        },
    )

    metadata = DomainMetadata(
        domain="general",
        custom_json={
            "layout_quality_policy": {
                "misclassified_block_policy": {
                    "equation_with_recovered_text": {
                        "action": "recover_as_text",
                        "warning_level": "info",
                    }
                },
            },
        },
    )

    split = await ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=metadata,
        parser_mode="mineru_strict",
    )

    assert split == [chunk]


@pytest.mark.asyncio
async def test_chunk_splitter_allows_mixed_arabic_english_reference_chunk():
    arabic_text = (
        "\u0625\u064a\u0627\u0643 \u0646\u0639\u0628\u062f "
        "\u0648\u0625\u064a\u0627\u0643 \u0646\u0633\u062a\u0639\u064a\u0646"
    )
    chunk = AdapterChunk(
        text=f"[1:4]\n\n{arabic_text}\n\nYou alone we worship.",
        source_location={"page_start": 1, "page_end": 1},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    split = await ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="religion", tags=["quran"], script="arabic"),
        parser_mode="mineru_strict",
    )

    assert "reference_unit_missing_expected_script" not in parser_warning_codes(split[0])


@pytest.mark.asyncio
async def test_chunk_splitter_keeps_tafseer_inline_cross_references_inside_primary_anchor(
    tmp_path: Path,
):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "Verse 18:30", "page_idx": 808},
                {
                    "type": "text",
                    "text": "Indeed, those who have believed and done righteous deeds.",
                    "page_idx": 808,
                },
                {
                    "type": "text",
                    "text": (
                        "The Reward of those Who believe and do Righteous Deeds. "
                        "In a similar way, He contrasts the two in 25:75-76."
                    ),
                    "page_idx": 808,
                },
                {"type": "text", "text": "Verse 18:32", "page_idx": 808},
                {
                    "type": "text",
                    "text": "And present to them an example of two men.",
                    "page_idx": 808,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/ocr/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )
    metadata = tafseer_cross_reference_metadata()

    split = await ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=metadata,
        parser_mode="mineru_strict",
    )

    answerable = [piece for piece in split if piece.content_type != "reference_provenance"]
    assert [piece.preview_ref for piece in answerable] == ["18:30", "18:32"]
    assert "25:75-76" in answerable[0].text
    assert "The Reward of those Who believe" in answerable[0].text
    assert answerable[0].metadata["reference_metadata"]["references"] == ["18:30"]
    assert answerable[0].metadata["reference_metadata"]["cross_references"] == ["25:75"]
    assert not any(piece.preview_ref == "25:75" for piece in split)


def test_chunk_splitter_recovers_tafseer_verse_image_text_from_pdf_layer(
    tmp_path: Path,
    monkeypatch,
):
    fitz = pytest.importorskip("fitz")
    from ragstudio.services import parser_normalization

    arabic_text = "إن الذين ءامنوا وعملوا الصالحات إنا لا نضيع أجر من أحسن عملا"
    pdf_path = tmp_path / "source_origin.pdf"
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((206, 246), "placeholder text layer", fontsize=12)
    document.save(pdf_path)
    document.close()
    monkeypatch.setattr(
        parser_normalization,
        "_overlapping_pdf_line_text",
        lambda page, target, fitz_module: arabic_text,
    )

    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "Verse 18:30", "page_idx": 0},
                {
                    "type": "image",
                    "img_path": "images/ayah.jpg",
                    "bbox": [341, 284, 905, 318],
                    "page_idx": 0,
                },
                {
                    "type": "text",
                    "text": (
                        "Indeed, those who have believed and done righteous deeds - "
                        "indeed, We will not allow to be lost the reward of any who "
                        "did well in deeds."
                    ),
                    "page_idx": 0,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/ocr/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )
    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=tafseer_cross_reference_metadata(),
        parser_mode="mineru_strict",
    )

    assert len(split) == 1
    assert split[0].preview_ref == "18:30"
    assert arabic_text in split[0].text
    assert "Indeed, those who have believed" in split[0].text
    assert split[0].metadata["reference_metadata"]["references"] == ["18:30"]
    warnings = parser_warnings(split[0])
    assert [warning["code"] for warning in warnings] == [
        "recovered_text_from_disallowed_block"
    ]
    assert warnings[0]["block_type"] == "image"
    assert warnings[0]["recovery_source"] == "pdf_text_layer:source_origin.pdf"
    assert "reference_unit_missing_expected_script" not in parser_warning_codes(split[0])


def test_chunk_splitter_preserves_mixed_geometry_order_for_recovered_image_text(
    tmp_path: Path,
):
    arabic_text = "للذين يعملون السوء بجهالة ثم يتوبون من قريب"
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "Verse 4:15", "page_idx": 0},
                {
                    "type": "image",
                    "recovered_text": arabic_text,
                    "bbox": [102, 724, 906, 790],
                    "page_idx": 0,
                },
                {
                    "type": "text",
                    "text": "Those who commit unlawful sexual intercourse of your women.",
                    "page_idx": 0,
                },
                {"type": "text", "text": "Verse 4:17", "page_idx": 0},
                {
                    "type": "text",
                    "text": "The repentance accepted by Allah is only for those who do wrong.",
                    "page_idx": 0,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/ocr/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=tafseer_cross_reference_metadata(),
        parser_mode="mineru_strict",
    )

    by_ref = {piece.preview_ref: piece for piece in split if piece.preview_ref}
    assert arabic_text in by_ref["4:15"].text
    assert arabic_text not in by_ref["4:17"].text
    assert "reference_unit_missing_expected_script" not in parser_warning_codes(by_ref["4:15"])


def test_chunk_splitter_reorders_recovered_verse_image_by_page_geometry(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    arabic_text = "للذين يعملون السوء بجهالة ثم يتوبون من قريب"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "Verse 4:15", "bbox": [91, 120, 179, 140], "page_idx": 0},
                {
                    "type": "text",
                    "text": "Those who commit unlawful sexual intercourse of your women.",
                    "bbox": [91, 150, 864, 180],
                    "page_idx": 0,
                },
                {
                    "type": "image",
                    "recovered_text": arabic_text,
                    "bbox": [102, 724, 906, 790],
                    "page_idx": 1,
                },
                {
                    "type": "text",
                    "text": "The previous verse commentary continues on this page.",
                    "bbox": [89, 74, 908, 678],
                    "page_idx": 1,
                },
                {
                    "type": "text",
                    "text": "Verse 4:17",
                    "bbox": [91, 708, 179, 724],
                    "page_idx": 1,
                },
                {
                    "type": "text",
                    "text": "The repentance accepted by Allah is only for those who do wrong.",
                    "bbox": [91, 799, 864, 835],
                    "page_idx": 1,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/ocr/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )
    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=tafseer_cross_reference_metadata(),
        parser_mode="mineru_strict",
    )

    by_ref = {piece.preview_ref: piece for piece in split if piece.preview_ref}
    assert arabic_text not in by_ref["4:15"].text
    assert arabic_text in by_ref["4:17"].text
    assert "The repentance accepted by Allah" in by_ref["4:17"].text
    assert "reference_unit_missing_expected_script" not in parser_warning_codes(by_ref["4:17"])


def test_chunk_splitter_downgrades_builtin_tafseer_dangling_inline_refs(
    tmp_path: Path,
):
    arabic_text = "إن الذين آمنوا وعملوا الصالحات إنا لا نضيع أجر من أحسن عملا"
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "69:18).", "page_idx": 0},
                {"type": "text", "text": "Verse 18:30", "page_idx": 0},
                {"type": "text", "text": arabic_text, "page_idx": 0},
                {
                    "type": "text",
                    "text": "Indeed, those who have believed and done righteous deeds.",
                    "page_idx": 0,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/ocr/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )
    profile = DomainMetadataService(tmp_path).get_profile("quran_tafseer")
    assert profile is not None

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=profile.metadata,
        parser_mode="mineru_strict",
    )

    answerable = [piece for piece in split if piece.content_type != "reference_provenance"]
    provenance = [piece for piece in split if piece.content_type == "reference_provenance"]
    assert [piece.preview_ref for piece in answerable] == ["18:30"]
    assert not any(piece.preview_ref == "69:18" for piece in split)
    assert provenance[0].text == "69:18)."
    assert provenance[0].metadata["canonical_reference_unit"]["answerable"] is False


def test_chunk_splitter_recovers_cross_page_verse_header_gap_from_pdf_layer(
    tmp_path: Path,
    monkeypatch,
):
    fitz = pytest.importorskip("fitz")
    from ragstudio.services import parser_normalization

    arabic_text = "أو كصيب من السماء فيه ظلمات ورعد وبرق"
    monkeypatch.setattr(
        parser_normalization,
        "_pdf_arabic_lines_text_in_region",
        lambda context, *, page_number, content_bbox: arabic_text if page_number == 1 else "",
    )
    pdf_path = tmp_path / "source_origin.pdf"
    document = fitz.open()
    document.new_page(width=612, height=792)
    document.new_page(width=612, height=792)
    document.save(pdf_path)
    document.close()

    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "type": "footer",
                    "text": "Verse 2:19",
                    "bbox": [93, 896, 178, 911],
                    "page_idx": 0,
                },
                {
                    "type": "text",
                    "text": (
                        "Or it is like a rainstorm from the sky within which is "
                        "darkness, thunder and lightning."
                    ),
                    "bbox": [89, 145, 888, 181],
                    "page_idx": 1,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/ocr/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    metadata = tafseer_cross_reference_metadata()
    metadata = metadata.model_copy(
        update={
            "custom_json": {
                **metadata.custom_json,
                "parser_normalization": {
                    "recover_text_bearing_blocks_as_prose": True,
                },
            }
        }
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=metadata,
        parser_mode="mineru_strict",
    )

    assert len(split) == 1
    assert split[0].preview_ref == "2:19"
    assert arabic_text in split[0].text
    assert "rainstorm from the sky" in split[0].text
    assert "reference_unit_missing_expected_script" not in parser_warning_codes(split[0])


def test_chunk_splitter_keeps_primary_anchor_after_heading_in_content_list(
    tmp_path: Path,
):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "text": (
                        "Commentary heading\n\n"
                        "Verse 18:30 Indeed, those who believe are rewarded. "
                        "The commentary mentions 25:75-76."
                    ),
                    "page_idx": 808,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/ocr/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=tafseer_cross_reference_metadata(),
        parser_mode="mineru_strict",
    )

    assert len(split) == 1
    assert split[0].content_type != "reference_provenance"
    assert split[0].preview_ref == "18:30"
    assert split[0].metadata["reference_metadata"]["references"] == ["18:30"]
    assert split[0].metadata["reference_metadata"]["cross_references"] == ["25:75"]
    assert split[0].text.startswith("Commentary heading")


def test_chunk_splitter_fallback_uses_primary_anchor_policy_for_inline_references():
    chunk = AdapterChunk(
        text=(
            "Commentary heading\n\n"
            "Verse 18:30 Indeed, those who believe are rewarded. "
            "The commentary mentions 25:75-76.\n\n"
            "Verse 18:32 And present to them an example of two men."
        ),
        source_location={"artifact": "source/auto/source.md", "page_start": 809},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=tafseer_cross_reference_metadata(),
        parser_mode="mineru_strict",
    )

    assert [item.metadata["reference_metadata"]["references"] for item in split] == [
        ["18:30"],
        ["18:32"],
    ]
    assert split[0].metadata["reference_metadata"]["cross_references"] == ["25:75"]
    assert "25:75" not in split[1].metadata["reference_metadata"]["references"]


def test_chunk_splitter_preserves_real_math_content_list_equation(tmp_path: Path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        """
        [
          {"type":"text","text":"Physics derivation","page_idx":0},
          {"type":"equation","text":"$$ E = mc^2 $$","page_idx":0}
        ]
        """,
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="science", document_type="paper", tags=["physics"]),
        parser_mode="mineru_strict",
    )

    assert split[0].text == "Physics derivation\n\n$$ E = mc^2 $$"
    assert parser_warning_codes(split[0]) == []
