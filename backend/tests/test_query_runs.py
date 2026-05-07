import pytest


@pytest.mark.asyncio
async def test_query_creates_run_with_answer_and_chunk_trace(client):
    upload = await client.post(
        "/api/documents",
        files={"file": ("sample.txt", b"alpha answer source", "text/plain")},
    )
    document_id = upload.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")
    variant = await client.post(
        "/api/variants",
        json={"name": "Balanced", "preset": "balanced", "parameters": {}},
    )

    response = await client.post(
        "/api/query",
        json={"query": "alpha?", "document_ids": [document_id], "variant_ids": [variant.json()["id"]]},
    )

    assert response.status_code == 200
    run = response.json()["runs"][0]
    assert run["status"] == "succeeded"
    assert "alpha" in run["answer"]
    assert run["sources"][0]["document_id"] == document_id
    assert run["chunk_traces"][0]["inclusion_status"] == "prompt-included"
    assert run["timings"]["search_ms"] >= 0


@pytest.mark.asyncio
async def test_list_runs_returns_persisted_query_runs(client):
    upload = await client.post(
        "/api/documents",
        files={"file": ("history.txt", b"history answer", "text/plain")},
    )
    document_id = upload.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")
    variant = await client.post(
        "/api/variants",
        json={"name": "History", "preset": "balanced", "parameters": {}},
    )
    query = await client.post(
        "/api/query",
        json={"query": "history", "document_ids": [document_id], "variant_ids": [variant.json()["id"]]},
    )
    run_id = query.json()["runs"][0]["id"]

    response = await client.get("/api/runs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == run_id
    assert payload["items"][0]["answer"]


@pytest.mark.asyncio
async def test_query_invalid_variant_id_returns_error_without_persisting_runs(client):
    upload = await client.post(
        "/api/documents",
        files={"file": ("variant-missing.txt", b"variant missing", "text/plain")},
    )
    document_id = upload.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")

    response = await client.post(
        "/api/query",
        json={"query": "missing variant", "document_ids": [document_id], "variant_ids": ["missing-variant"]},
    )

    assert response.status_code == 404
    runs = await client.get("/api/runs")
    assert runs.json()["total"] == 0


@pytest.mark.asyncio
async def test_query_invalid_document_id_returns_error_without_persisting_runs(client):
    variant = await client.post(
        "/api/variants",
        json={"name": "Document Missing", "preset": "balanced", "parameters": {}},
    )

    response = await client.post(
        "/api/query",
        json={"query": "missing document", "document_ids": ["missing-document"], "variant_ids": [variant.json()["id"]]},
    )

    assert response.status_code == 404
    runs = await client.get("/api/runs")
    assert runs.json()["total"] == 0


@pytest.mark.asyncio
async def test_query_creates_one_run_per_variant(client):
    upload = await client.post(
        "/api/documents",
        files={"file": ("multi.txt", b"shared answer", "text/plain")},
    )
    document_id = upload.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")
    first = await client.post("/api/variants", json={"name": "First", "preset": "balanced", "parameters": {}})
    second = await client.post("/api/variants", json={"name": "Second", "preset": "balanced", "parameters": {}})
    variant_ids = [first.json()["id"], second.json()["id"]]

    response = await client.post(
        "/api/query",
        json={"query": "shared", "document_ids": [document_id], "variant_ids": variant_ids},
    )

    assert response.status_code == 200
    runs = response.json()["runs"]
    assert [run["variant_id"] for run in runs] == variant_ids
    assert all(run["status"] == "succeeded" for run in runs)

    persisted_runs = await client.get("/api/runs")
    assert persisted_runs.json()["total"] == 2
