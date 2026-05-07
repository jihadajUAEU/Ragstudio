import pytest


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
    assert chunks[0]["metadata"]["backend"] == "fallback"
    assert chunks[0]["metadata"]["artifact_ref"]
    assert "artifact_path" not in chunks[0]["metadata"]
    assert not chunks[0]["metadata"]["artifact_ref"].startswith("/")


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
    assert [chunk["text"] for chunk in second_index_response.json()] == ["first line", "second line"]

    search_response = await client.post(
        "/api/chunks/search",
        json={"query": "line", "document_ids": [document_id], "limit": 10},
    )

    assert search_response.status_code == 200
    assert search_response.json()["total"] == 2
