import pytest


@pytest.mark.asyncio
async def test_upload_document_creates_document_and_index_job(client):
    files = {"file": ("sample.txt", b"alpha beta gamma", "text/plain")}

    upload_response = await client.post("/api/documents", files=files)

    assert upload_response.status_code == 201
    document = upload_response.json()
    assert document["filename"] == "sample.txt"
    assert document["status"] == "ready"

    jobs_response = await client.get("/api/jobs")
    assert jobs_response.status_code == 200
    jobs = jobs_response.json()["items"]
    assert any(job["type"] == "index_document" and job["target_id"] == document["id"] for job in jobs)
