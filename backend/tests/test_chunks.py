import json

import pytest
import pytest_asyncio
from ragstudio.db.models import Chunk, Document, IndexRecord, SettingsProfile
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_sanitizer import sanitize_db_value
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.chunk_splitter import ChunkSplitter
from ragstudio.services.runtime_types import RuntimeChunk
from sqlalchemy import select


def words(count: int, prefix: str = "word"):
    return " ".join(f"{prefix}{index}" for index in range(count))


class FakeRuntime:
    async def delete_document_index(self, document_id):
        return None

    async def index_document(self, artifact_path):
        return [
            RuntimeChunk(
                text="runtime persisted chunk",
                source_location={"page": 1},
                metadata={"score": 1.0},
                runtime_source_id="runtime-source-1",
            )
        ]

    async def query(self, query, *, document_ids, query_config):
        raise NotImplementedError

    def capability_report(self):
        return {"active_backend": "runtime", "raganything_available": True}


class FakeRuntimeFactory:
    def build(self, profile):
        return FakeRuntime()


class NullByteAdapter:
    async def index_document(self, artifact_path):
        return [
            RuntimeChunk(
                text="alpha\x00 beta",
                source_location={"line": "1\x00"},
                metadata={
                    "backend": "fallback",
                    "artifact_ref": "nul.txt",
                    "nested": {"value": "bad\x00metadata"},
                    "items": ["ok\x00"],
                },
            )
        ]


class OversizedAdapter:
    async def index_document(self, artifact_path):
        return [
            AdapterChunk(
                text=words(3100),
                source_location={"artifact": "oversized.txt"},
                metadata={
                    "backend": "fallback",
                    "artifact_ref": "oversized.txt",
                    "chunk_index": 4,
                    "source_type": "text",
                },
            )
        ]


class ReferenceAdapter:
    async def index_document(self, artifact_path):
        return [
            AdapterChunk(
                text=(
                    "Surah 1\n\n"
                    "[1:3]\n\nSovereign of the Day of Recompense.\n\n"
                    "[1:4]\n\nIt is You we worship and You we ask for help.\n\n"
                    "[1:5]\n\nGuide us to the straight path.\n\n"
                    "Surah 2\n\n"
                    "[2:1]\n\nAlif, Lam, Meem."
                ),
                source_location={"artifact": "quran.txt", "page_start": 2, "page_end": 3},
                metadata={"backend": "fallback", "artifact_ref": "quran.txt", "chunk_index": 0},
            )
        ]


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
        parser_mode="mineru",
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


class PassingHealthService:
    async def check(self, profile):
        return []

    def blocking_failures(self, checks):
        return []


@pytest_asyncio.fixture(autouse=True)
async def fallback_runtime_profile(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="fallback",
                llm_model="fallback",
                embedding_model="fallback",
                storage_backend="fallback_local",
                runtime_mode="fallback",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_index_uploaded_document_creates_line_chunks(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("notes.txt", b"alpha beta\n\ngamma delta\n", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    index_response = await client.post(f"/api/chunks/index/{document_id}")

    assert index_response.status_code == 200
    chunks = index_response.json()
    assert [chunk["text"] for chunk in chunks] == ["alpha beta", "gamma delta"]
    assert chunks[0]["document_id"] == document_id
    assert chunks[0]["source_location"] == {"line": 1}
    assert chunks[1]["source_location"] == {"line": 3}
    assert chunks[0]["metadata"]["document_id"] == document_id
    assert chunks[0]["metadata"]["parser_metadata"]["backend"] == "fallback"
    assert chunks[0]["metadata"]["parser_metadata"]["artifact_ref"]
    assert chunks[0]["runtime_profile_id"] is None
    assert "artifact_path" not in chunks[0]["metadata"]
    assert not chunks[0]["metadata"]["parser_metadata"]["artifact_ref"].startswith("/")
    app = client._transport.app
    async with app.state.session_factory() as session:
        record = await session.scalar(
            select(IndexRecord).where(IndexRecord.document_id == document_id)
        )
    assert record is None


@pytest.mark.asyncio
async def test_index_document_strips_null_bytes_before_persisting(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("nul.txt", b"ignored", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    app = client._transport.app
    async with app.state.session_factory() as session:
        chunks = await ChunkService(
            session,
            app.state.settings.data_dir,
            adapter=NullByteAdapter(),
        ).index_document(
            document_id,
            options=IndexDocumentIn(parser_mode="local_fallback"),
        )

        assert chunks is not None
        assert chunks[0].text == "alpha beta"
        persisted = await session.scalar(select(Chunk).where(Chunk.document_id == document_id))

    assert persisted is not None
    assert persisted.text == "alpha beta"
    assert persisted.source_location == {"line": "1"}
    assert persisted.metadata_json["nested"] == {"value": "badmetadata"}
    assert persisted.metadata_json["items"] == ["ok"]


def test_sanitize_db_value_converts_json_unsafe_values(tmp_path):
    class CustomValue:
        def __str__(self):
            return "custom\x00value"

    payload = {
        "nan": float("nan"),
        "inf": float("inf"),
        "bytes": b"hello\x00world",
        "path": tmp_path / "artifact.txt",
        "custom": CustomValue(),
        "nested": ("ok\x00", {"bad\x00key": b"value\x00"}),
    }

    sanitized = sanitize_db_value(payload)

    assert sanitized["nan"] is None
    assert sanitized["inf"] is None
    assert sanitized["bytes"] == "helloworld"
    assert sanitized["path"].endswith("artifact.txt")
    assert sanitized["custom"] == "customvalue"
    assert sanitized["nested"] == ["ok", {"badkey": "value"}]


@pytest.mark.asyncio
async def test_search_chunks_returns_ranked_matches(client):
    upload_response = await client.post(
        "/api/documents",
        files={
            "file": (
                "ranked.txt",
                b"apple banana\nbanana carrot\nzebra only\napple banana carrot\n",
                "text/plain",
            )
        },
    )
    document_id = upload_response.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")

    search_response = await client.post(
        "/api/chunks/search",
        json={"query": "apple banana", "document_ids": [document_id], "limit": 2},
    )

    assert search_response.status_code == 200
    payload = search_response.json()
    assert payload["total"] == 2
    assert [item["text"] for item in payload["items"]] == [
        "apple banana",
        "apple banana carrot",
    ]
    assert payload["items"][0]["metadata"]["score"] > payload["items"][1]["metadata"]["score"]


@pytest.mark.asyncio
async def test_search_chunks_preserves_source_order_for_ties_and_empty_query(client):
    upload_response = await client.post(
        "/api/documents",
        files={
            "file": (
                "ties.txt",
                b"same match first\nsame match second\nsame match third\n",
                "text/plain",
            )
        },
    )
    document_id = upload_response.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")

    tie_response = await client.post(
        "/api/chunks/search",
        json={"query": "same match", "document_ids": [document_id], "limit": 10},
    )
    empty_response = await client.post(
        "/api/chunks/search",
        json={"query": "", "document_ids": [document_id], "limit": 10},
    )

    assert tie_response.status_code == 200
    assert empty_response.status_code == 200
    expected = ["same match first", "same match second", "same match third"]
    assert [item["text"] for item in tie_response.json()["items"]] == expected
    assert [item["text"] for item in empty_response.json()["items"]] == expected


@pytest.mark.asyncio
async def test_search_chunks_boosts_collection_count_title(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("bukhari.pdf", b"%PDF fake", "application/pdf")},
    )
    document_id = upload_response.json()["id"]

    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add_all(
            [
                Chunk(
                    document_id=document_id,
                    text="Book 65, Hadith 201 mentions truthfulness.",
                    source_location={"page": 65},
                    metadata_json={"domain_metadata": {"domain": "hadith"}},
                ),
                Chunk(
                    document_id=document_id,
                    text="Sahih al-Bukhari\n\n7277 Hadith Collection",
                    source_location={"page": 1},
                    metadata_json={
                        "document_metadata": {
                            "title": "Sahih al-Bukhari 7277 Hadith Collection"
                        },
                        "domain_metadata": {
                            "domain": "hadith",
                            "document_type": "collection",
                            "collection": "Sahih al-Bukhari",
                        },
                    },
                ),
            ]
        )
        await session.commit()

    search_response = await client.post(
        "/api/chunks/search",
        json={"query": "how many hadith in bukhari", "document_ids": [document_id], "limit": 2},
    )

    assert search_response.status_code == 200
    result = search_response.json()
    assert result["items"][0]["text"] == "Sahih al-Bukhari\n\n7277 Hadith Collection"
    assert result["items"][0]["metadata"]["score_breakdown"]["answer_bearing_count"] > 0


@pytest.mark.asyncio
async def test_search_chunks_exact_reference_returns_matching_verse_top_one(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("quran.txt", b"surah sample", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add_all(
            [
                Chunk(
                    document_id=document_id,
                    text="[1:3]\n\nSovereign of the Day of Recompense.",
                    source_location={"page_start": 2, "page_end": 2},
                    metadata_json={
                        "domain_metadata": {
                            "tags": ["quran"],
                            "reference_pattern": "surah_number:verse_number",
                        },
                        "reference_metadata": {
                            "reference_type": "surah_ayah",
                            "chapter_start": 1,
                            "chapter_end": 1,
                            "verse_start": 3,
                            "verse_end": 3,
                            "references": ["1:3"],
                            "next_ref": "1:4",
                        },
                    },
                ),
                Chunk(
                    document_id=document_id,
                    text="[1:4]\n\nIt is You we worship and You we ask for help.",
                    source_location={"page_start": 2, "page_end": 2},
                    metadata_json={
                        "domain_metadata": {
                            "tags": ["quran"],
                            "reference_pattern": "surah_number:verse_number",
                        },
                        "reference_metadata": {
                            "reference_type": "surah_ayah",
                            "chapter_start": 1,
                            "chapter_end": 1,
                            "verse_start": 4,
                            "verse_end": 4,
                            "references": ["1:4"],
                            "previous_ref": "1:3",
                            "next_ref": "1:5",
                        },
                    },
                ),
                Chunk(
                    document_id=document_id,
                    text="[2:4]\n\nAnd who believe in what has been revealed to you.",
                    source_location={"page_start": 3, "page_end": 3},
                    metadata_json={
                        "domain_metadata": {
                            "tags": ["quran"],
                            "reference_pattern": "surah_number:verse_number",
                        },
                        "reference_metadata": {
                            "reference_type": "surah_ayah",
                            "chapter_start": 2,
                            "chapter_end": 2,
                            "verse_start": 4,
                            "verse_end": 4,
                            "references": ["2:4"],
                        },
                    },
                ),
            ]
        )
        await session.commit()

    response = await client.post(
        "/api/chunks/search",
        json={"query": "What does Quran 1:4 say?", "document_ids": [document_id], "limit": 3},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["text"].startswith("[1:4]")
    assert items[0]["metadata"]["score_breakdown"]["reference_exact"] == 100.0
    assert items[0]["metadata"]["retrieval_explain"]["query_reference"] == "1:4"
    assert items[0]["metadata"]["retrieval_explain"]["matched_references"] == ["1:4"]
    assert items[0]["retrieval_explain"]["matched_references"] == ["1:4"]


@pytest.mark.asyncio
async def test_search_chunks_natural_language_returns_exact_phrase_in_top_five(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("quran.txt", b"surah sample", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    app = client._transport.app
    async with app.state.session_factory() as session:
        for index in range(8):
            session.add(
                Chunk(
                    document_id=document_id,
                    text=f"Generic Allah guidance chunk {index}",
                    source_location={"page_start": index + 10},
                    metadata_json={"domain_metadata": {"tags": ["quran"]}},
                )
            )
        session.add(
            Chunk(
                document_id=document_id,
                text="[1:5]\n\nGuide us to the straight path.",
                source_location={"page_start": 2, "page_end": 2},
                metadata_json={
                    "domain_metadata": {
                        "tags": ["quran"],
                        "reference_pattern": "surah_number:verse_number",
                    },
                    "reference_metadata": {
                        "reference_type": "surah_ayah",
                        "chapter_start": 1,
                        "chapter_end": 1,
                        "verse_start": 5,
                        "verse_end": 5,
                        "references": ["1:5"],
                    },
                },
            )
        )
        await session.commit()

    response = await client.post(
        "/api/chunks/search",
        json={
            "query": "What guidance is requested in Quran 1:5?",
            "document_ids": [document_id],
            "limit": 5,
        },
    )

    assert response.status_code == 200
    texts = [item["text"] for item in response.json()["items"]]
    assert any(text.startswith("[1:5]") for text in texts)


@pytest.mark.asyncio
async def test_exact_reference_search_includes_previous_and_next_relationships(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("quran.txt", b"surah sample", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    app = client._transport.app
    async with app.state.session_factory() as session:
        for verse in (3, 4, 5):
            session.add(
                Chunk(
                    document_id=document_id,
                    text=f"[1:{verse}]\n\nVerse {verse}",
                    source_location={"page_start": 2},
                    metadata_json={
                        "domain_metadata": {
                            "tags": ["quran"],
                            "reference_pattern": "surah_number:verse_number",
                        },
                        "reference_metadata": {
                            "chapter_start": 1,
                            "chapter_end": 1,
                            "verse_start": verse,
                            "verse_end": verse,
                            "references": [f"1:{verse}"],
                            "previous_ref": f"1:{verse - 1}" if verse > 1 else None,
                            "next_ref": f"1:{verse + 1}",
                        },
                    },
                )
            )
        await session.commit()

    response = await client.post(
        "/api/chunks/search",
        json={"query": "Quran 1:4", "document_ids": [document_id], "limit": 3},
    )

    texts = [item["text"] for item in response.json()["items"]]
    assert texts[0].startswith("[1:4]")
    assert any(text.startswith("[1:3]") for text in texts)
    assert any(text.startswith("[1:5]") for text in texts)
    assert response.json()["items"][0]["relationship_refs"] == {
        "previous": "1:3",
        "next": "1:5",
    }


@pytest.mark.asyncio
async def test_search_exact_reference_uses_explicit_reference_list_across_chapters(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("quran.txt", b"surah sample", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            Chunk(
                document_id=document_id,
                text="[1:7]\n\nLast verse.\n\n[2:1]\n\nAlif Lam Meem.",
                source_location={"page_start": 2},
                metadata_json={
                    "domain_metadata": {
                        "custom_json": {
                            "reference_schema": {"type": "surah_ayah"},
                            "retrieval": {"exact_reference_top1": True},
                        }
                    },
                    "reference_metadata": {
                        "reference_type": "surah_ayah",
                        "chapter_start": 1,
                        "chapter_end": 2,
                        "verse_start": 7,
                        "verse_end": 1,
                        "references": ["1:7", "2:1"],
                    },
                },
            )
        )
        await session.commit()

    response = await client.post(
        "/api/chunks/search",
        json={"query": "Quran 2:1", "document_ids": [document_id], "limit": 1},
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["text"].startswith("[1:7]")
    assert item["metadata"]["score_breakdown"]["reference_exact"] == 100.0


@pytest.mark.asyncio
async def test_search_chapter_only_reference_returns_requested_surah(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("quran.txt", b"surah sample", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add_all(
            [
                Chunk(
                    document_id=document_id,
                    text="Surah 109\n\n[109:2]\n\nI do not worship what you worship.",
                    source_location={"page_start": 602},
                    metadata_json={
                        "domain_metadata": {
                            "custom_json": {
                                "reference_schema": {"type": "surah_ayah"},
                                "retrieval": {"boost_same_chapter": True},
                            }
                        },
                        "reference_metadata": {
                            "chapter_start": 109,
                            "chapter_end": 109,
                            "verse_start": 1,
                            "verse_end": 6,
                            "references": ["109:1", "109:2"],
                        },
                    },
                ),
                Chunk(
                    document_id=document_id,
                    text=(
                        "Surah 113\n\n"
                        "[113:1]\n\nSay, I seek refuge in the Lord of daybreak.\n\n"
                        "[113:2]\n\nFrom the evil of that which He created."
                    ),
                    source_location={"page_start": 605},
                    metadata_json={
                        "domain_metadata": {
                            "custom_json": {
                                "reference_schema": {"type": "surah_ayah"},
                                "retrieval": {"boost_same_chapter": True},
                            }
                        },
                        "reference_metadata": {
                            "chapter_start": 113,
                            "chapter_end": 113,
                            "verse_start": 1,
                            "verse_end": 5,
                            "references": ["113:1", "113:2"],
                        },
                    },
                ),
            ]
        )
        await session.commit()

    response = await client.post(
        "/api/chunks/search",
        json={"query": "what is surah 113", "document_ids": [document_id], "limit": 2},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["text"].startswith("Surah 113")
    assert items[0]["metadata"]["score_breakdown"]["same_chapter"] == 60.0
    assert items[0]["metadata"]["retrieval_explain"]["query_reference"] == "chapter:113"


@pytest.mark.asyncio
async def test_search_respects_disabled_reference_boosts(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("quran.txt", b"surah sample", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            Chunk(
                document_id=document_id,
                text="[1:4]\n\nIt is You we worship and You we ask for help.",
                source_location={"page_start": 2},
                metadata_json={
                    "domain_metadata": {
                        "custom_json": {
                            "reference_schema": {"type": "surah_ayah"},
                            "retrieval": {
                                "exact_reference_top1": False,
                                "boost_same_chapter": False,
                                "boost_neighbor_verses": False,
                            },
                        }
                    },
                    "reference_metadata": {
                        "chapter_start": 1,
                        "chapter_end": 1,
                        "verse_start": 4,
                        "verse_end": 4,
                        "references": ["1:4"],
                        "previous_ref": "1:3",
                        "next_ref": "1:5",
                    },
                },
            )
        )
        await session.commit()

    response = await client.post(
        "/api/chunks/search",
        json={"query": "Quran 1:4", "document_ids": [document_id], "limit": 1},
    )

    assert response.status_code == 200
    breakdown = response.json()["items"][0]["metadata"]["score_breakdown"]
    assert breakdown["reference_exact"] == 0.0
    assert breakdown["same_chapter"] == 0.0
    assert breakdown["neighbor_match"] == 0.0


@pytest.mark.asyncio
async def test_index_and_search_derives_reference_metadata_from_uploaded_text(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("quran.txt", b"surah sample", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    app = client._transport.app
    async with app.state.session_factory() as session:
        chunks = await ChunkService(
            session,
            app.state.settings.data_dir,
            adapter=ReferenceAdapter(),
        ).index_document(
            document_id,
            options=IndexDocumentIn(
                parser_mode="local_fallback",
                domain_metadata={
                    "domain": "religion",
                    "document_type": "religious_text",
                    "tags": ["quran"],
                    "custom_json": {
                        "reference_schema": {"type": "surah_ayah"},
                        "chunking": {"unit": "verse", "include_neighbors": 1},
                        "retrieval": {
                            "exact_reference_top1": True,
                            "boost_same_chapter": True,
                            "boost_neighbor_verses": True,
                        },
                    },
                },
            ),
        )

    assert chunks is not None
    assert [chunk.metadata["reference_metadata"]["references"] for chunk in chunks] == [
        ["1:3"],
        ["1:4"],
        ["1:5"],
        ["2:1"],
    ]

    response = await client.post(
        "/api/chunks/search",
        json={"query": "What does Quran 1:4 say?", "document_ids": [document_id], "limit": 5},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["text"].startswith("[1:4]")
    assert items[0]["metadata"]["retrieval_explain"]["matched_references"] == ["1:4"]


@pytest.mark.asyncio
async def test_index_document_persists_relationship_aware_chunk_metadata(client):
    upload_response = await client.post(
        "/api/documents",
        files={
            "file": (
                "quran.txt",
                b"[113:1] Say, I seek refuge in the Lord of daybreak.\n"
                b"[113:2] From the evil of that which He created.",
                "text/plain",
            )
        },
    )
    document_id = upload_response.json()["id"]

    index_response = await client.post(
        f"/api/chunks/index/{document_id}",
        json={
            "parser_mode": "local_fallback",
            "domain_metadata": {
                "domain": "quran_tafseer",
                "document_type": "commentary",
                "citation_style": "surah_ayah",
                "expected_structure": "surah_ayah_sections",
                "tags": ["quran", "religious_text"],
                "custom_json": {
                    "reference_schema": {
                        "type": "chapter_verse",
                        "display": "{chapter}:{verse}",
                        "fields": {
                            "chapter": "surah_number",
                            "verse": "ayah_number",
                        },
                    },
                    "chunking": {"unit": "verse", "include_neighbors": 1},
                    "graph": {
                        "node_types": ["surah", "ayah", "chunk"],
                        "edge_types": ["contains", "next_ayah", "references"],
                        "materialize_from": [
                            "mineru_structure",
                            "reference_metadata",
                        ],
                        "confidence_policy": "evidence_required",
                    },
                },
            },
        },
    )

    assert index_response.status_code == 200
    chunks = index_response.json()
    assert chunks[0]["metadata"]["relationship_metadata"]["references"] == ["113:1"]
    assert {
        "type": "next_ayah",
        "source": "ref:113:1",
        "target": "ref:113:2",
        "evidence": "reference_metadata",
    } in chunks[0]["metadata"]["relationship_metadata"]["graph_relationships"]
    assert all(
        relationship["evidence"] == "reference_metadata"
        for relationship in chunks[0]["metadata"]["relationship_metadata"][
            "graph_relationships"
        ]
    )


@pytest.mark.asyncio
async def test_index_missing_document_returns_404(client):
    response = await client.post("/api/chunks/index/missing-document")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reindex_replaces_existing_chunks(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("replace.txt", b"first line\nsecond line\n", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    first_index_response = await client.post(f"/api/chunks/index/{document_id}")
    second_index_response = await client.post(f"/api/chunks/index/{document_id}")

    assert first_index_response.status_code == 200
    assert second_index_response.status_code == 200
    assert [chunk["text"] for chunk in second_index_response.json()] == [
        "first line",
        "second line",
    ]

    search_response = await client.post(
        "/api/chunks/search",
        json={"query": "line", "document_ids": [document_id], "limit": 10},
    )

    assert search_response.status_code == 200
    assert search_response.json()["total"] == 2


@pytest.mark.asyncio
async def test_index_local_chunks_copies_domain_metadata(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("hadith.txt", b"Book 1, Hadith 1\n", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    response = await client.post(
        f"/api/chunks/index/{document_id}",
        json={
            "parser_mode": "local_fallback",
            "domain_metadata": {
                "domain": "hadith",
                "document_type": "collection",
                "language": "mixed",
                "tags": ["hadith"],
                "collection": "Sahih al-Bukhari",
                "metadata_sources": ["profile", "user"],
            },
        },
    )

    assert response.status_code == 200
    metadata = response.json()[0]["metadata"]
    assert metadata["domain_metadata"]["domain"] == "hadith"
    assert metadata["domain_metadata"]["collection"] == "Sahih al-Bukhari"
    assert metadata["parser_metadata"]["backend"] == "fallback"
    assert metadata["parser_metadata"]["parser_mode"] == "local_fallback"


@pytest.mark.asyncio
async def test_index_document_splits_oversized_adapter_chunk(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("oversized.txt", b"ignored", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    app = client._transport.app
    async with app.state.session_factory() as session:
        chunks = await ChunkService(
            session,
            app.state.settings.data_dir,
            adapter=OversizedAdapter(),
        ).index_document(
            document_id,
            options=IndexDocumentIn(
                parser_mode="local_fallback",
                domain_metadata={
                    "domain": "generic",
                    "document_type": "document",
                    "collection": "Adapter regression",
                },
            ),
        )

        persisted = (
            await session.execute(
                select(Chunk)
                .where(Chunk.document_id == document_id)
                .order_by(Chunk.created_at.asc(), Chunk.id.asc())
            )
        ).scalars().all()

    assert chunks is not None
    assert [len(chunk.text.split()) for chunk in chunks] == [1500, 1500, 100]
    assert [len(chunk.text.split()) for chunk in persisted] == [1500, 1500, 100]
    metadata = chunks[0].metadata
    assert metadata["domain_metadata"]["collection"] == "Adapter regression"
    assert metadata["parser_metadata"]["backend"] == "fallback"
    assert metadata["parser_metadata"]["split_strategy"] == "metadata_profile"
    assert metadata["parser_metadata"]["split_profile"] == "generic"
    assert metadata["parser_metadata"]["parent_artifact_ref"] == "oversized.txt"
    assert metadata["parser_metadata"]["parent_chunk_index"] == 4
    assert metadata["parser_metadata"]["split_count"] == 3


@pytest.mark.asyncio
async def test_index_mineru_strict_uses_adapter_chunks(client, monkeypatch):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("paper.pdf", b"%PDF fake", "application/pdf")},
    )
    document_id = upload_response.json()["id"]

    async def fake_index_document(self, document_id, *, options, on_mineru_status=None):
        from ragstudio.services.adapter import AdapterChunk

        return [
            AdapterChunk(
                text="MinerU text",
                source_location={"page": 1, "artifact": "pages/page-1.md"},
                metadata={
                    "parser_metadata": {
                        "backend": "mineru",
                        "parser_mode": "mineru_strict",
                        "parse_job_id": "job-1",
                        "content_type": "text",
                    }
                },
            )
        ]

    monkeypatch.setattr(
        "ragstudio.services.chunk_service.ChunkService._mineru_adapter_chunks",
        fake_index_document,
    )

    app = client._transport.app
    async with app.state.session_factory() as session:
        chunks = await ChunkService(session, app.state.settings.data_dir).index_document(
            document_id,
            options=IndexDocumentIn(
                parser_mode="mineru_strict",
                domain_metadata={"domain": "research", "document_type": "paper"},
            ),
        )

    assert chunks is not None
    chunk = chunks[0]
    assert chunk.text == "MinerU text"
    assert chunk.metadata["domain_metadata"]["domain"] == "research"
    assert chunk.metadata["parser_metadata"]["backend"] == "mineru"


@pytest.mark.asyncio
async def test_index_mineru_strict_splits_huge_markdown_adapter_chunk(client, monkeypatch):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("huge-tafseer.pdf", b"%PDF fake", "application/pdf")},
    )
    document_id = upload_response.json()["id"]

    async def fake_mineru_adapter_chunks(self, document_id, *, options, on_mineru_status=None):
        return [
            AdapterChunk(
                text="\n\n".join(
                    [
                        "# Tafsir",
                        "## Surah 1",
                        f"Verse 1:1\n\n{words(900, 'alpha')}",
                        f"Verse 1:2\n\n{words(900, 'beta')}",
                        "## Surah 2",
                        f"Verse 2:1\n\n{words(900, 'gamma')}",
                    ]
                ),
                source_location={"artifact": "source/auto/source.md"},
                metadata={
                    "parser_metadata": {
                        "backend": "mineru",
                        "parser_mode": "mineru_strict",
                        "parse_job_id": "job-huge",
                        "artifact_ref": "source/auto/source.md",
                        "chunk_index": 0,
                    }
                },
            )
        ]

    monkeypatch.setattr(
        "ragstudio.services.chunk_service.ChunkService._mineru_adapter_chunks",
        fake_mineru_adapter_chunks,
    )

    app = client._transport.app
    async with app.state.session_factory() as session:
        chunks = await ChunkService(session, app.state.settings.data_dir).index_document(
            document_id,
            options=IndexDocumentIn(
                parser_mode="mineru_strict",
                domain_metadata={"domain": "tafseer", "document_type": "book"},
            ),
        )

        persisted = (
            await session.execute(
                select(Chunk)
                .where(Chunk.document_id == document_id)
                .order_by(Chunk.created_at.asc(), Chunk.id.asc())
            )
        ).scalars().all()

    assert chunks is not None
    assert len(chunks) == 3
    assert all(len(chunk.text.split()) <= 1500 for chunk in chunks)
    assert len(persisted) == 3
    assert chunks[0].text.startswith("# Tafsir")
    assert chunks[1].text.startswith("Verse 1:2")
    metadata = chunks[0].metadata
    assert metadata["domain_metadata"]["domain"] == "tafseer"
    assert metadata["parser_metadata"]["backend"] == "mineru"
    assert metadata["parser_metadata"]["split_strategy"] == "metadata_profile"
    assert metadata["parser_metadata"]["split_profile"] == "tafseer_book"
    assert metadata["parser_metadata"]["parent_artifact_ref"] == "source/auto/source.md"
    assert metadata["parser_metadata"]["split_count"] == 3


@pytest.mark.asyncio
async def test_runtime_index_route_persists_chunks_and_index_record(client, monkeypatch):
    monkeypatch.setattr(
        "ragstudio.services.index_lifecycle_service.RAGAnythingRuntimeFactory",
        FakeRuntimeFactory,
    )
    monkeypatch.setattr(
        "ragstudio.services.index_lifecycle_service.RuntimeHealthService",
        PassingHealthService,
    )
    app = client._transport.app
    artifact_path = app.state.settings.data_dir / "runtime-index.txt"
    artifact_path.write_text("runtime text", encoding="utf-8")
    async with app.state.session_factory() as session:
        profile = await session.get(SettingsProfile, "default")
        assert profile is not None
        profile.provider = "openai-compatible"
        profile.llm_model = "gpt-4o"
        profile.llm_base_url = "http://127.0.0.1:8004/v1"
        profile.embedding_model = "text-embedding-3-large"
        profile.embedding_base_url = "http://127.0.0.1:8001/v1"
        profile.storage_backend = "postgres_pgvector_neo4j"
        profile.runtime_mode = "runtime"
        document = Document(
            filename="runtime-index.txt",
            content_type="text/plain",
            sha256="runtime-index-route",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()
        document_id = document.id

    response = await client.post(f"/api/chunks/index/{document_id}")

    assert response.status_code == 200
    assert response.json()[0]["runtime_profile_id"] == "default"
    async with app.state.session_factory() as session:
        chunks = (
            await session.execute(select(Chunk).where(Chunk.document_id == document_id))
        ).scalars().all()
        records = (
            await session.execute(
                select(IndexRecord).where(IndexRecord.document_id == document_id)
            )
        ).scalars().all()

    assert [chunk.text for chunk in chunks] == ["runtime persisted chunk"]
    assert chunks[0].runtime_source_id == "runtime-source-1"
    assert len(records) == 1
    assert records[0].runtime_profile_id == "default"
    assert records[0].chunk_count == 1


@pytest.mark.asyncio
async def test_runtime_index_route_reports_blocking_health_as_conflict(client):
    app = client._transport.app
    artifact_path = app.state.settings.data_dir / "runtime-blocked.txt"
    artifact_path.write_text("runtime text", encoding="utf-8")
    async with app.state.session_factory() as session:
        profile = await session.get(SettingsProfile, "default")
        assert profile is not None
        profile.provider = "openai-compatible"
        profile.llm_model = "gpt-4o"
        profile.llm_base_url = "http://127.0.0.1:8004/v1"
        profile.embedding_model = "text-embedding-3-large"
        profile.embedding_base_url = "http://127.0.0.1:8001/v1"
        profile.storage_backend = "postgres_pgvector_neo4j"
        profile.runtime_mode = "runtime"
        document = Document(
            filename="runtime-blocked.txt",
            content_type="text/plain",
            sha256="runtime-blocked-route",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()
        document_id = document.id

    response = await client.post(f"/api/chunks/index/{document_id}")

    assert response.status_code == 409
    detail = response.json()["detail"].lower()
    assert "raganything" in detail or "lightrag" in detail or "neo4j" in detail


@pytest.mark.asyncio
async def test_saved_fallback_profile_uses_legacy_chunk_indexing(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("saved-fallback.txt", b"fallback profile text\n", "text/plain")},
    )
    document_id = upload_response.json()["id"]

    response = await client.post(f"/api/chunks/index/{document_id}")

    assert response.status_code == 200
    chunk = response.json()[0]
    assert chunk["runtime_profile_id"] is None
    assert chunk["metadata"]["parser_metadata"]["backend"] == "fallback"
    async with client._transport.app.state.session_factory() as session:
        record = await session.scalar(
            select(IndexRecord).where(IndexRecord.document_id == document_id)
        )
    assert record is None
