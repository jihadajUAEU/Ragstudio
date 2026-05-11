from pathlib import Path

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_splitter import ChunkSplitter


def words(count: int, prefix: str = "word") -> str:
    return " ".join(f"{prefix}{index}" for index in range(count))


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
