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
        metadata={"parser_metadata": {"backend": "fallback", "chunk_index": 4}},
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=DomainMetadata(domain="generic", document_type="document"),
        parser_mode="local_fallback",
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
