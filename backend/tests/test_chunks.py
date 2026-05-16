import json

import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_sanitizer import sanitize_db_value
from ragstudio.services.chunk_service import ChunkService
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


@pytest.mark.asyncio
async def test_domain_metadata_for_documents_dedupes_and_copies(
    database_url,
    tmp_path,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    repeated_metadata = {
        "domain": "quran_tafseer",
        "language": "arabic",
        "nested": {"reference_schema": "chapter_verse"},
    }
    different_metadata = {
        "domain": "hadith",
        "language": "arabic",
        "nested": {"reference_schema": "book_hadith"},
    }

    async with factory() as session:
        session.add_all(
            [
                Document(
                    id="doc-a",
                    filename="a.pdf",
                    content_type="application/pdf",
                    sha256="sha-a",
                    artifact_path=str(tmp_path / "a.pdf"),
                ),
                Document(
                    id="doc-b",
                    filename="b.pdf",
                    content_type="application/pdf",
                    sha256="sha-b",
                    artifact_path=str(tmp_path / "b.pdf"),
                ),
                Chunk(
                    id="chunk-a-1",
                    document_id="doc-a",
                    text="A first chunk",
                    metadata_json={"domain_metadata": repeated_metadata},
                ),
                Chunk(
                    id="chunk-a-2",
                    document_id="doc-a",
                    text="A repeated metadata chunk",
                    metadata_json={"domain_metadata": dict(repeated_metadata)},
                ),
                Chunk(
                    id="chunk-b-1",
                    document_id="doc-b",
                    text="B different metadata chunk",
                    metadata_json={"domain_metadata": different_metadata},
                ),
                Chunk(
                    id="chunk-b-2",
                    document_id="doc-b",
                    text="B no metadata chunk",
                    metadata_json={"parser_metadata": {"backend": "mineru"}},
                ),
            ]
        )
        await session.commit()

        assert await ChunkService(session, tmp_path).domain_metadata_for_documents([]) == []

        result = await ChunkService(session, tmp_path).domain_metadata_for_documents(
            ["doc-b", "doc-a", "doc-b"]
        )

        assert result == [
            {
                **different_metadata,
                "document_id": "doc-b",
            },
            {
                **repeated_metadata,
                "document_id": "doc-a",
            },
        ]

        result[1]["nested"]["reference_schema"] = "mutated"
        stored = await session.get(Chunk, "chunk-a-1")

    await engine.dispose()

    assert stored is not None
    assert (
        stored.metadata_json["domain_metadata"]["nested"]["reference_schema"]
        == "chapter_verse"
    )
