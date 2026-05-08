import json

import pytest


@pytest.mark.asyncio
async def test_upload_accepts_parser_mode_and_domain_metadata(client):
    response = await client.post(
        "/api/documents",
        data={
            "parser_mode": "local_fallback",
            "domain_metadata": json.dumps(
                {
                    "domain": "policy",
                    "document_type": "admin_document",
                    "tags": ["policy"],
                    "metadata_sources": ["user"],
                }
            ),
        },
        files={"file": ("policy.txt", b"Policy line\n", "text/plain")},
    )

    assert response.status_code == 201
    document_id = response.json()["id"]
    search_response = await client.post(
        "/api/chunks/search",
        json={"query": "Policy", "document_ids": [document_id], "limit": 10},
    )
    assert search_response.status_code == 200
    assert search_response.json()["items"][0]["metadata"]["domain_metadata"]["domain"] == "policy"


@pytest.mark.asyncio
async def test_upload_rejects_invalid_parser_options_before_reading_file(client):
    response = await client.post(
        "/api/documents",
        data={"parser_mode": "bogus", "domain_metadata": "{}"},
        files={"file": ("policy.txt", b"Policy line\n", "text/plain")},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["parser_mode"]


@pytest.mark.asyncio
async def test_upload_rejects_malformed_domain_metadata(client):
    response = await client.post(
        "/api/documents",
        data={"parser_mode": "local_fallback", "domain_metadata": "{not-json"},
        files={"file": ("policy.txt", b"Policy line\n", "text/plain")},
    )

    assert response.status_code == 400
    assert "domain_metadata" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_mineru_strict_failure_persists_failed_job(client, monkeypatch):
    async def fail_index(self, document_id, *, options, commit=True, on_mineru_status=None):
        raise RuntimeError("MinerU parse failed")

    monkeypatch.setattr(
        "ragstudio.services.document_service.ChunkService.index_document",
        fail_index,
    )

    response = await client.post(
        "/api/documents",
        data={"parser_mode": "mineru_strict", "domain_metadata": "{}"},
        files={"file": ("paper.pdf", b"%PDF fake", "application/pdf")},
    )
    jobs_response = await client.get("/api/jobs")

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    jobs = jobs_response.json()["items"]
    assert len(jobs) == 1
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["result"]["error"] == "MinerU parse failed"


@pytest.mark.asyncio
async def test_duplicate_upload_mineru_strict_failure_persists_failed_job(client, monkeypatch):
    first_response = await client.post(
        "/api/documents",
        files={"file": ("paper.pdf", b"%PDF fake", "application/pdf")},
    )

    async def fail_index(self, document_id, *, options, commit=True, on_mineru_status=None):
        raise RuntimeError("MinerU parse failed")

    monkeypatch.setattr(
        "ragstudio.services.document_service.ChunkService.index_document",
        fail_index,
    )

    second_response = await client.post(
        "/api/documents",
        data={"parser_mode": "mineru_strict", "domain_metadata": "{}"},
        files={"file": ("paper-copy.pdf", b"%PDF fake", "application/pdf")},
    )
    jobs_response = await client.get("/api/jobs")

    assert second_response.status_code == 201
    assert second_response.json()["id"] == first_response.json()["id"]
    assert second_response.json()["status"] == "failed"
    jobs = jobs_response.json()["items"]
    failed_jobs = [job for job in jobs if job["status"] == "failed"]
    succeeded_jobs = [job for job in jobs if job["status"] == "succeeded"]
    assert len(jobs) == 2
    assert succeeded_jobs
    assert failed_jobs
    assert failed_jobs[0]["result"]["error"] == "MinerU parse failed"


@pytest.mark.asyncio
async def test_duplicate_upload_with_explicit_default_options_creates_new_job(client):
    first_response = await client.post(
        "/api/documents",
        files={"file": ("notes.txt", b"same bytes", "text/plain")},
    )
    second_response = await client.post(
        "/api/documents",
        data={"parser_mode": "local_fallback", "domain_metadata": "{}"},
        files={"file": ("notes-copy.txt", b"same bytes", "text/plain")},
    )
    jobs_response = await client.get("/api/jobs")

    assert second_response.status_code == 201
    assert second_response.json()["id"] == first_response.json()["id"]
    jobs = [job for job in jobs_response.json()["items"] if job["type"] == "index_document"]
    assert len(jobs) == 2
    assert {job["status"] for job in jobs} == {"succeeded"}


@pytest.mark.asyncio
async def test_upload_local_fallback_index_failure_propagates(client, monkeypatch):
    async def fail_index(self, document_id, *, options, commit=True, on_mineru_status=None):
        raise RuntimeError("local index bug")

    monkeypatch.setattr(
        "ragstudio.services.document_service.ChunkService.index_document",
        fail_index,
    )

    with pytest.raises(RuntimeError, match="local index bug"):
        await client.post(
            "/api/documents",
            data={"parser_mode": "local_fallback", "domain_metadata": "{}"},
            files={"file": ("paper.txt", b"text", "text/plain")},
        )
