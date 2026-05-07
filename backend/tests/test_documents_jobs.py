import asyncio
from hashlib import sha256

import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Document
from ragstudio.services import document_service
from ragstudio.services.document_service import DocumentService
from sqlalchemy import select


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
    assert any(
        job["type"] == "index_document" and job["target_id"] == document["id"] for job in jobs
    )


@pytest.mark.asyncio
async def test_upload_document_is_idempotent_by_content_hash(client):
    files = {"file": ("sample.txt", b"same bytes", "text/plain")}

    first_response = await client.post("/api/documents", files=files)
    second_response = await client.post(
        "/api/documents",
        files={"file": ("copy.txt", b"same bytes", "text/plain")},
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert second_response.json()["id"] == first_response.json()["id"]

    documents_response = await client.get("/api/documents")
    assert documents_response.status_code == 200
    documents = documents_response.json()["items"]
    assert len(documents) == 1

    jobs_response = await client.get("/api/jobs")
    assert jobs_response.status_code == 200
    index_jobs = [job for job in jobs_response.json()["items"] if job["type"] == "index_document"]
    assert len(index_jobs) == 1
    assert index_jobs[0]["target_id"] == first_response.json()["id"]


@pytest.mark.asyncio
async def test_duplicate_uploads_with_different_filenames_share_one_artifact(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'studio.sqlite3'}")
    session_factory = make_session_factory(engine)
    await init_db(engine)

    content = b"same artifact bytes"
    digest = sha256(content).hexdigest()

    async with session_factory() as session:
        service = DocumentService(session, tmp_path)
        first_document = await service.upload("first.txt", "text/plain", content)
        second_document = await service.upload("second.txt", "text/plain", content)
        documents = (await session.execute(select(Document))).scalars().all()

    await engine.dispose()

    upload_files = [path for path in (tmp_path / "uploads").iterdir() if path.is_file()]
    assert second_document.id == first_document.id
    assert len(documents) == 1
    assert upload_files == [tmp_path / "uploads" / digest]


@pytest.mark.asyncio
async def test_concurrent_duplicate_uploads_are_idempotent(client):
    async def upload_copy(index: int):
        return await client.post(
            "/api/documents",
            files={"file": (f"copy-{index}.txt", b"concurrent bytes", "text/plain")},
        )

    responses = await asyncio.gather(*(upload_copy(index) for index in range(8)))

    assert {response.status_code for response in responses} == {201}
    document_ids = {response.json()["id"] for response in responses}
    assert len(document_ids) == 1

    documents_response = await client.get("/api/documents")
    assert documents_response.status_code == 200
    documents = documents_response.json()["items"]
    assert len(documents) == 1

    jobs_response = await client.get("/api/jobs")
    assert jobs_response.status_code == 200
    index_jobs = [job for job in jobs_response.json()["items"] if job["type"] == "index_document"]
    assert len(index_jobs) == 1
    assert index_jobs[0]["target_id"] == responses[0].json()["id"]


@pytest.mark.asyncio
async def test_upload_failure_preserves_content_addressed_artifact(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'studio.sqlite3'}")
    session_factory = make_session_factory(engine)
    await init_db(engine)

    content = b"preserve canonical artifact"
    digest = sha256(content).hexdigest()

    def fail_build(job_type, target_id):
        raise RuntimeError("job enqueue failed")

    monkeypatch.setattr(document_service.JobWorker, "build", fail_build)

    async with session_factory() as session:
        with pytest.raises(RuntimeError, match="job enqueue failed"):
            await DocumentService(session, tmp_path).upload("sample.txt", "text/plain", content)
        documents = (await session.execute(select(Document))).scalars().all()

    await engine.dispose()

    assert documents == []
    assert (tmp_path / "uploads" / digest).read_bytes() == content


@pytest.mark.asyncio
async def test_upload_document_sanitizes_artifact_path_for_unsafe_filename(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'studio.sqlite3'}")
    session_factory = make_session_factory(engine)
    await init_db(engine)

    async with session_factory() as session:
        document_out = await DocumentService(session, tmp_path).upload(
            filename="../sample.txt",
            content_type="text/plain",
            content=b"traversal check",
        )
        document = await session.scalar(select(Document).where(Document.id == document_out.id))

    await engine.dispose()

    assert document is not None
    artifact_name = document.artifact_path.split("/")[-1]
    assert "/" not in artifact_name
    assert ".." not in artifact_name
