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
    async def fail_index(self, document_id, *, options, commit=True):
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
