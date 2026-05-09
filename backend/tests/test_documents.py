import asyncio
import json
from pathlib import Path

import pytest
from ragstudio.db.models import Document, IndexRecord, Job, SettingsProfile
from ragstudio.schemas.common import StageStatus
from ragstudio.services.document_service import DocumentService
from ragstudio.services.runtime_types import RuntimeChunk
from sqlalchemy import select


class FakeRuntime:
    async def delete_document_index(self, document_id):
        return None

    async def index_document(self, artifact_path):
        return [
            RuntimeChunk(
                text="upload runtime chunk",
                source_location={"page": 1},
                metadata={},
                runtime_source_id="upload-runtime-1",
            )
        ]

    async def query(self, query, *, document_ids, query_config):
        raise NotImplementedError

    def capability_report(self):
        return {"active_backend": "runtime", "raganything_available": True}


class FakeRuntimeFactory:
    def build(self, profile):
        return FakeRuntime()


class PassingHealthService:
    async def check(self, profile):
        return []

    def blocking_failures(self, checks):
        return []


async def wait_for_jobs(client, expected_count: int, terminal: bool = True) -> list[dict]:
    for _ in range(50):
        response = await client.get("/api/jobs")
        jobs = response.json()["items"]
        if len(jobs) >= expected_count:
            if not terminal or all(job["status"] in {"succeeded", "failed"} for job in jobs):
                return jobs
        await asyncio.sleep(0.01)
    return jobs


async def wait_for_chunks(client, document_id: str, expected_total: int) -> dict:
    payload = {"query": "", "document_ids": [document_id], "limit": 20}
    for _ in range(50):
        response = await client.post("/api/chunks/search", json=payload)
        body = response.json()
        if body["total"] >= expected_total:
            return body
        await asyncio.sleep(0.01)
    return body


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
    await wait_for_chunks(client, document_id, 1)
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
    jobs = await wait_for_jobs(client, 1)

    assert response.status_code == 201
    assert response.json()["status"] == "running"
    assert len(jobs) == 1
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["result"]["error"] == "MinerU parse failed"


@pytest.mark.asyncio
async def test_duplicate_upload_mineru_strict_failure_persists_failed_job(client, monkeypatch):
    first_response = await client.post(
        "/api/documents",
        files={"file": ("paper.pdf", b"%PDF fake", "application/pdf")},
    )
    await wait_for_jobs(client, 1)

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
    jobs = await wait_for_jobs(client, 2)

    assert second_response.status_code == 201
    assert second_response.json()["id"] == first_response.json()["id"]
    assert second_response.json()["status"] == "running"
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
    jobs = await wait_for_jobs(client, 2)

    assert second_response.status_code == 201
    assert second_response.json()["id"] == first_response.json()["id"]
    jobs = [job for job in jobs if job["type"] == "index_document"]
    assert len(jobs) == 2
    assert {job["status"] for job in jobs} == {"succeeded"}


@pytest.mark.asyncio
async def test_duplicate_upload_schedules_each_created_job_id(client, monkeypatch):
    scheduled = []

    async def fake_run_index_job(settings, document_id, job_id, options):
        scheduled.append(
            {
                "document_id": document_id,
                "job_id": job_id,
                "parser_mode": options.parser_mode,
            }
        )

    monkeypatch.setattr("ragstudio.api.routes.documents._run_index_job", fake_run_index_job)

    first_response = await client.post(
        "/api/documents",
        data={"parser_mode": "local_fallback", "domain_metadata": "{}"},
        files={"file": ("notes.txt", b"same bytes", "text/plain")},
    )
    second_response = await client.post(
        "/api/documents",
        data={"parser_mode": "mineru_with_fallback", "domain_metadata": "{}"},
        files={"file": ("notes-copy.txt", b"same bytes", "text/plain")},
    )

    for _ in range(20):
        if len(scheduled) == 2:
            break
        await asyncio.sleep(0.01)
    jobs = await wait_for_jobs(client, 2, terminal=False)
    job_ids = {job["id"] for job in jobs}

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert first_response.json()["id"] == second_response.json()["id"]
    assert len(scheduled) == 2
    assert {item["job_id"] for item in scheduled} == job_ids
    assert scheduled[0]["job_id"] != scheduled[1]["job_id"]
    assert [item["parser_mode"] for item in scheduled] == [
        "local_fallback",
        "mineru_with_fallback",
    ]


@pytest.mark.asyncio
async def test_reindex_document_queues_job_with_updated_metadata(client, monkeypatch, tmp_path):
    scheduled = []

    async def fake_run_index_job(settings, document_id, job_id, options):
        scheduled.append(
            {
                "document_id": document_id,
                "job_id": job_id,
                "parser_mode": options.parser_mode,
                "domain_metadata": options.domain_metadata.model_dump(exclude_none=True),
            }
        )

    monkeypatch.setattr("ragstudio.api.routes.documents._run_index_job", fake_run_index_job)
    session_factory = client._transport.app.state.session_factory
    artifact = tmp_path / "uploads" / "reindex-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with session_factory() as session:
        document = Document(
            filename="quran.pdf",
            content_type="application/pdf",
            sha256="reindex-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.commit()
        document_id = document.id

    response = await client.post(
        f"/api/documents/{document_id}/reindex",
        json={
            "parser_mode": "local_fallback",
            "domain_metadata": {
                "domain": "religion",
                "document_type": "religious_text",
                "tags": ["quran"],
                "custom_json": {
                    "reference_schema": {"type": "surah_ayah"},
                    "retrieval": {"exact_reference_top1": True},
                },
            },
        },
    )

    for _ in range(20):
        if scheduled:
            break
        await asyncio.sleep(0.01)

    assert response.status_code == 202
    body = response.json()
    assert body["document_id"] == document_id
    assert body["job_id"]
    assert body["status"] == "ready"
    assert scheduled[0]["document_id"] == document_id
    assert scheduled[0]["job_id"] == body["job_id"]
    assert scheduled[0]["parser_mode"] == "local_fallback"
    assert scheduled[0]["domain_metadata"]["domain"] == "religion"
    assert scheduled[0]["domain_metadata"]["document_type"] == "religious_text"
    assert scheduled[0]["domain_metadata"]["tags"] == ["quran"]
    assert scheduled[0]["domain_metadata"]["custom_json"] == {
        "reference_schema": {"type": "surah_ayah"},
        "retrieval": {"exact_reference_top1": True},
    }


@pytest.mark.asyncio
async def test_reindex_missing_document_returns_404(client):
    response = await client.post(
        "/api/documents/missing-document/reindex",
        json={"parser_mode": "local_fallback", "domain_metadata": {}},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


@pytest.mark.asyncio
async def test_upload_uses_runtime_index_lifecycle_when_profile_exists(client, monkeypatch):
    monkeypatch.setattr(
        "ragstudio.services.index_lifecycle_service.RAGAnythingRuntimeFactory",
        FakeRuntimeFactory,
    )
    monkeypatch.setattr(
        "ragstudio.services.index_lifecycle_service.RuntimeHealthService",
        PassingHealthService,
    )
    monkeypatch.setattr(
        "ragstudio.api.routes.documents.RuntimeHealthService",
        PassingHealthService,
    )
    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://127.0.0.1:8004/v1",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://127.0.0.1:8001/v1",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        await session.commit()

    response = await client.post(
        "/api/documents",
        files={"file": ("runtime-upload.txt", b"runtime upload", "text/plain")},
    )

    assert response.status_code == 201
    document_id = response.json()["id"]
    await wait_for_jobs(client, 1)
    async with app.state.session_factory() as session:
        record = await session.scalar(
            select(IndexRecord).where(IndexRecord.document_id == document_id)
        )

    assert record is not None
    assert record.runtime_profile_id == "default"
    assert record.chunk_count == 1


@pytest.mark.asyncio
async def test_duplicate_upload_requires_runtime_index_when_profile_changes(client):
    first_response = await client.post(
        "/api/documents",
        files={"file": ("runtime-change.txt", b"same runtime bytes", "text/plain")},
    )
    assert first_response.status_code == 201
    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://127.0.0.1:8004/v1",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://127.0.0.1:8001/v1",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        await session.commit()

    second_response = await client.post(
        "/api/documents",
        files={"file": ("runtime-change-copy.txt", b"same runtime bytes", "text/plain")},
    )

    assert second_response.status_code == 409
    assert "native_runtime_adapter" in second_response.json()["detail"]


@pytest.mark.asyncio
async def test_runtime_blocked_mineru_strict_upload_returns_conflict(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://127.0.0.1:8004/v1",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://127.0.0.1:8001/v1",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        await session.commit()

    response = await client.post(
        "/api/documents",
        data={"parser_mode": "mineru_strict", "domain_metadata": "{}"},
        files={"file": ("runtime-strict.pdf", b"%PDF fake", "application/pdf")},
    )

    assert response.status_code == 409
    assert "native_runtime_adapter" in response.json()["detail"]


@pytest.mark.asyncio
async def test_duplicate_runtime_blocked_mineru_strict_upload_returns_conflict(client):
    first_response = await client.post(
        "/api/documents",
        files={"file": ("runtime-strict.pdf", b"%PDF fake", "application/pdf")},
    )
    assert first_response.status_code == 201

    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://127.0.0.1:8004/v1",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://127.0.0.1:8001/v1",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        await session.commit()

    second_response = await client.post(
        "/api/documents",
        data={"parser_mode": "mineru_strict", "domain_metadata": "{}"},
        files={"file": ("runtime-strict-copy.pdf", b"%PDF fake", "application/pdf")},
    )

    assert second_response.status_code == 409
    assert "native_runtime_adapter" in second_response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_local_fallback_index_failure_propagates(client, monkeypatch):
    async def fail_index(self, document_id, *, options, commit=True, on_mineru_status=None):
        raise RuntimeError("local index bug")

    monkeypatch.setattr(
        "ragstudio.services.document_service.ChunkService.index_document",
        fail_index,
    )

    response = await client.post(
        "/api/documents",
        data={"parser_mode": "local_fallback", "domain_metadata": "{}"},
        files={"file": ("paper.txt", b"text", "text/plain")},
    )
    jobs = await wait_for_jobs(client, 1)

    assert response.status_code == 201
    assert response.json()["status"] == "running"
    assert len(jobs) == 1
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["result"]["error"] == "local index bug"


@pytest.mark.asyncio
async def test_delete_document_removes_document_chunks_jobs_and_artifact(client):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("delete-me.txt", b"alpha beta\ngamma delta", "text/plain")},
    )
    assert upload_response.status_code == 201
    document_id = upload_response.json()["id"]
    await wait_for_chunks(client, document_id, 2)
    session_factory = client._transport.app.state.session_factory
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        assert document is not None
        artifact_path = Path(document.artifact_path)

    search_before = await client.post(
        "/api/chunks/search",
        json={"query": "", "document_ids": [document_id], "limit": 10},
    )
    assert search_before.status_code == 200
    assert search_before.json()["total"] == 2
    assert artifact_path.exists()

    delete_response = await client.delete(f"/api/documents/{document_id}")

    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert not artifact_path.exists()

    documents_response = await client.get("/api/documents")
    assert documents_response.status_code == 200
    assert documents_response.json()["items"] == []

    jobs_response = await client.get("/api/jobs")
    assert jobs_response.status_code == 200
    assert jobs_response.json()["items"] == []

    search_after = await client.post(
        "/api/chunks/search",
        json={"query": "", "document_ids": [document_id], "limit": 10},
    )
    assert search_after.status_code == 200
    assert search_after.json()["total"] == 0


@pytest.mark.asyncio
async def test_delete_document_removes_runtime_index_records(client, tmp_path):
    session_factory = client._transport.app.state.session_factory
    artifact = tmp_path / "uploads" / "indexed-delete-sha"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("alpha", encoding="utf-8")
    async with session_factory() as session:
        document = Document(
            filename="runtime-delete.txt",
            content_type="text/plain",
            sha256="indexed-delete-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status=StageStatus.SUCCEEDED.value,
                index_shape={},
                chunk_count=1,
            )
        )
        await session.commit()
        document_id = document.id

    response = await client.delete(f"/api/documents/{document_id}")

    assert response.status_code == 204
    async with session_factory() as session:
        record = await session.scalar(
            select(IndexRecord).where(IndexRecord.document_id == document_id)
        )
    assert record is None


@pytest.mark.asyncio
async def test_delete_missing_document_returns_404(client):
    response = await client.delete("/api/documents/missing-document")

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


@pytest.mark.asyncio
async def test_delete_document_with_active_index_job_removes_document_job_and_artifact(
    client,
    tmp_path,
):
    session_factory = client._transport.app.state.session_factory
    async with session_factory() as session:
        artifact = tmp_path / "uploads" / "active-delete-sha"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("alpha", encoding="utf-8")
        document = Document(
            filename="active.txt",
            content_type="text/plain",
            sha256="active-delete-sha",
            artifact_path=str(artifact),
            status=StageStatus.RUNNING.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Job(
                type="index_document",
                target_id=document.id,
                status=StageStatus.RUNNING.value,
                progress=10,
            )
        )
        await session.commit()
        document_id = document.id

    response = await client.delete(f"/api/documents/{document_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert not artifact.exists()
    async with session_factory() as session:
        assert await session.get(Document, document_id) is None
        job_id = await session.scalar(select(Job.id).where(Job.target_id == document_id))
    assert job_id is None


@pytest.mark.asyncio
async def test_delete_document_rolls_back_when_artifact_cleanup_fails(client, tmp_path):
    session_factory = client._transport.app.state.session_factory
    artifact = tmp_path / "uploads" / "artifact-directory"
    artifact.mkdir(parents=True)
    async with session_factory() as session:
        document = Document(
            filename="cleanup-fails.txt",
            content_type="text/plain",
            sha256="cleanup-fails-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Job(
                type="index_document",
                target_id=document.id,
                status=StageStatus.SUCCEEDED.value,
                progress=100,
            )
        )
        await session.commit()
        document_id = document.id

    async with session_factory() as session:
        with pytest.raises(OSError):
            await DocumentService(session, tmp_path).delete_document(document_id)

    async with session_factory() as session:
        assert await session.get(Document, document_id) is not None
        job_id = await session.scalar(select(Job.id).where(Job.target_id == document_id))

    assert artifact.exists()
    assert job_id is not None
