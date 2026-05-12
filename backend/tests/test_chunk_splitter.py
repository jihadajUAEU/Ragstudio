import json
from pathlib import Path

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_splitter import ChunkSplitter


def words(count: int, prefix: str = "word") -> str:
    return " ".join(f"{prefix}{index}" for index in range(count))


def parser_warning_codes(chunk: AdapterChunk) -> list[str]:
    warnings = chunk.metadata.get("extraction_quality", {}).get("parser_warnings", [])
    return [warning["code"] for warning in warnings]


def parser_warnings(chunk: AdapterChunk) -> list[dict[str, str]]:
    return chunk.metadata.get("extraction_quality", {}).get("parser_warnings", [])


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


def test_chunk_splitter_uses_mineru_content_list_when_available(tmp_path: Path):
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

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="tafseer", document_type="book"),
        parser_mode="mineru_strict",
    )

    assert [item.text for item in split] == [
        "Page one heading\n\nPage one body",
        "Page two heading\n\nPage two body",
    ]
    assert split[0].source_location["page_start"] == 1
    assert split[0].source_location["page_end"] == 1
    assert split[1].source_location["page_start"] == 2
    assert split[1].source_location["page_end"] == 2


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

    assert "$$" not in split[0].text
    assert "suspected_text_misclassified_as_equation" in parser_warning_codes(split[0])
    assert "reference_unit_missing_expected_script" in parser_warning_codes(split[0])


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
    assert "suspected_text_misclassified_as_equation" in parser_warning_codes(split[0])


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


def test_chunk_splitter_dedupes_existing_quality_gate_warning():
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

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="religion", tags=["quran"], script="arabic"),
        parser_mode="mineru_strict",
    )

    warnings = parser_warnings(split[0])
    assert warnings == [warning]


def test_chunk_splitter_allows_mixed_arabic_english_reference_chunk():
    arabic_text = (
        "\u0625\u064a\u0627\u0643 \u0646\u0639\u0628\u062f "
        "\u0648\u0625\u064a\u0627\u0643 \u0646\u0633\u062a\u0639\u064a\u0646"
    )
    chunk = AdapterChunk(
        text=f"[1:4]\n\n{arabic_text}\n\nYou alone we worship.",
        source_location={"page_start": 1, "page_end": 1},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="religion", tags=["quran"], script="arabic"),
        parser_mode="mineru_strict",
    )

    assert "reference_unit_missing_expected_script" not in parser_warning_codes(split[0])


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
