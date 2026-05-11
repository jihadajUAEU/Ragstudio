import json

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_sanitizer import sanitize_db_value
from ragstudio.services.chunk_splitter import ChunkSplitter


def test_chunk_splitter_splits_mineru_content_list_by_reference_units(tmp_path):
    content_list = tmp_path / "content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "page_idx": 0,
                    "text": "[113:1] Say, I seek refuge in the Lord of daybreak.",
                },
                {
                    "page_idx": 0,
                    "text": "[113:2] From the evil of that which He created.",
                },
            ]
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="ignored when content_list_ref is available",
        source_location={"artifact": "quran.pdf"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "content_list.json",
                "chunk_index": 0,
            }
        },
    )

    chunks = ChunkSplitter().split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="quran_tafseer",
            document_type="commentary",
            custom_json={
                "reference_schema": {"type": "chapter_verse"},
                "chunking": {"unit": "verse"},
            },
        ),
        parser_mode="mineru_strict",
    )

    assert [item.text for item in chunks] == [
        "[113:1] Say, I seek refuge in the Lord of daybreak.",
        "[113:2] From the evil of that which He created.",
    ]
    assert [item.metadata["reference_metadata"]["references"] for item in chunks] == [
        ["113:1"],
        ["113:2"],
    ]
    assert all(item.source_location["page_start"] == 1 for item in chunks)


def test_sanitize_db_value_converts_json_unsafe_values(tmp_path):
    payload = {
        "path": tmp_path / "artifact.txt",
        "set": {"a", "b"},
        "tuple": ("x", 1),
        "nested": {"bytes": b"abc"},
    }

    sanitized = sanitize_db_value(payload)

    assert sanitized["path"] == str(tmp_path / "artifact.txt")
    assert sanitized["set"] in {"{'a', 'b'}", "{'b', 'a'}"}
    assert sanitized["tuple"] == ["x", 1]
    assert sanitized["nested"]["bytes"] == "abc"
