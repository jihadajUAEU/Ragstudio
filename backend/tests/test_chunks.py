import pytest
import pytest_asyncio
from ragstudio.db.models import SettingsProfile
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.chunk_service import ChunkService


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
    assert "artifact_path" not in chunks[0]["metadata"]
    assert not chunks[0]["metadata"]["parser_metadata"]["artifact_ref"].startswith("/")


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
