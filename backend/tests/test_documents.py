import asyncio
import json
from pathlib import Path

import httpx
import pytest
from ragstudio.db.models import (
    Chunk,
    Document,
    GraphProjectionRecord,
    IndexRecord,
    Job,
    SettingsProfile,
)
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.runtime import RuntimeHealthCheck
from ragstudio.services.document_service import DocumentService
from ragstudio.services.graph_materialization_service import GraphMaterializationResult
from ragstudio.services.graph_projection_runner import GraphProjectionCleanupError
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
    def __init__(self, *_args, **_kwargs):
        pass

    def build(self, profile):
        return FakeRuntime()


class PassingHealthService:
    def __init__(self, *_args, **_kwargs):
        pass

    async def check(self, profile):
        return []

    def blocking_failures(self, checks):
        return []


class BlockingHealthService:
    def __init__(self, *_args, **_kwargs):
        pass

    async def check(self, profile):
        return [
            RuntimeHealthCheck(
                name="raganything",
                status="failed",
                severity="blocking",
                detail="RAG-Anything package is not importable in this test.",
            )
        ]

    def blocking_failures(self, checks):
        return checks


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
async def test_upload_uses_default_parser_mode_when_omitted(client, monkeypatch):
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

    response = await client.post(
        "/api/documents",
        data={
            "domain_metadata": json.dumps(
                {"domain": "policy", "document_type": "admin_document"}
            ),
        },
        files={"file": ("policy.txt", b"Policy line\n", "text/plain")},
    )

    for _ in range(20):
        if scheduled:
            break
        await asyncio.sleep(0.01)

    assert response.status_code == 201
    assert scheduled[0]["parser_mode"] == "mineru_strict"
    assert scheduled[0]["domain_metadata"]["domain"] == "policy"


@pytest.mark.asyncio
async def test_documents_list_includes_latest_index_options(client, tmp_path):
    session_factory = client._transport.app.state.session_factory
    artifact = tmp_path / "uploads" / "indexed-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with session_factory() as session:
        document = Document(
            filename="quran.pdf",
            content_type="application/pdf",
            sha256="indexed-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="[1:4] It is You we worship and You we ask for help.",
                source_location={"page": 2},
                metadata_json={
                    "parser_metadata": {
                        "backend": "mineru",
                        "parser_mode": "mineru_strict",
                    },
                    "domain_metadata": {
                        "domain": "quran_tafseer",
                        "document_type": "commentary",
                        "tags": ["quran"],
                        "custom_json": {
                            "reference_schema": {"type": "chapter_verse"},
                        },
                    },
                },
            )
        )
        await session.commit()

    response = await client.get("/api/documents")

    assert response.status_code == 200
    document = response.json()["items"][0]
    assert document["latest_index_options"]["parser_mode"] == "mineru_strict"
    assert document["latest_index_options"]["domain_metadata"]["domain"] == "quran_tafseer"
    assert document["latest_index_options"]["domain_metadata"]["custom_json"] == {
        "reference_schema": {"type": "chapter_verse"},
    }


@pytest.mark.asyncio
async def test_documents_list_infers_mineru_index_options_without_parser_mode(client, tmp_path):
    session_factory = client._transport.app.state.session_factory
    artifact = tmp_path / "uploads" / "legacy-mineru-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with session_factory() as session:
        document = Document(
            filename="legacy-quran.pdf",
            content_type="application/pdf",
            sha256="legacy-mineru-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="[1:4] It is You we worship and You we ask for help.",
                source_location={"page": 2},
                metadata_json={
                    "parser_metadata": {"backend": "mineru"},
                    "domain_metadata": {
                        "domain": "quran_tafseer",
                        "document_type": "commentary",
                    },
                },
            )
        )
        await session.commit()

    response = await client.get("/api/documents")

    document = response.json()["items"][0]
    assert document["latest_index_options"]["parser_mode"] == "mineru_strict"
    assert document["latest_index_options"]["domain_metadata"]["domain"] == "quran_tafseer"


@pytest.mark.asyncio
async def test_documents_list_preserves_parser_mode_when_domain_metadata_is_invalid(
    client,
    tmp_path,
):
    session_factory = client._transport.app.state.session_factory
    artifact = tmp_path / "uploads" / "invalid-domain-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with session_factory() as session:
        document = Document(
            filename="invalid-domain.pdf",
            content_type="application/pdf",
            sha256="invalid-domain-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="[1:4] It is You we worship and You we ask for help.",
                source_location={"page": 2},
                metadata_json={
                    "parser_metadata": {
                        "backend": "mineru",
                        "parser_mode": "mineru_strict",
                    },
                    "domain_metadata": {"domain": 123, "tags": "quran"},
                },
            )
        )
        await session.commit()

    response = await client.get("/api/documents")

    document = response.json()["items"][0]
    assert document["latest_index_options"]["parser_mode"] == "mineru_strict"
    assert document["latest_index_options"]["domain_metadata"]["domain"] == "generic"


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
        data={"parser_mode": "local_fallback", "domain_metadata": "{}"},
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
async def test_duplicate_upload_with_explicit_default_options_reuses_active_job(client):
    first_response = await client.post(
        "/api/documents",
        files={"file": ("notes.txt", b"same bytes", "text/plain")},
    )
    second_response = await client.post(
        "/api/documents",
        data={"parser_mode": "local_fallback", "domain_metadata": "{}"},
        files={"file": ("notes-copy.txt", b"same bytes", "text/plain")},
    )
    jobs = await wait_for_jobs(client, 1, terminal=False)

    assert second_response.status_code == 201
    assert second_response.json()["id"] == first_response.json()["id"]
    jobs = [job for job in jobs if job["type"] == "index_document"]
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_duplicate_upload_does_not_schedule_second_active_job(client, monkeypatch):
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
        if len(scheduled) == 1:
            break
        await asyncio.sleep(0.01)
    jobs = await wait_for_jobs(client, 1, terminal=False)

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert first_response.json()["id"] == second_response.json()["id"]
    assert len(scheduled) == 1
    assert scheduled[0]["job_id"] == jobs[0]["id"]
    assert scheduled[0]["parser_mode"] == "local_fallback"


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
async def test_rematerialize_document_graph_route_retries_projection(client, monkeypatch):
    calls = []

    async def fake_rematerialize_document(self, document_id):
        calls.append(document_id)
        return {
            "status": "succeeded",
            "node_count": 2,
            "edge_count": 1,
            "reason": None,
        }

    monkeypatch.setattr(
        "ragstudio.api.routes.documents.GraphProjectionRunner.rematerialize_document",
        fake_rematerialize_document,
    )
    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="graph-rematerialize-route.txt",
            content_type="text/plain",
            sha256="graph-rematerialize-route",
            artifact_path=str(app.state.settings.data_dir / "graph-rematerialize-route.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.commit()
        document_id = document.id

    response = await client.post(f"/api/documents/{document_id}/graph/rematerialize")

    assert response.status_code == 200
    assert response.json() == {
        "document_id": document_id,
        "status": "succeeded",
        "node_count": 2,
        "edge_count": 1,
        "reason": None,
    }
    assert calls == [document_id]


@pytest.mark.asyncio
async def test_rematerialize_missing_document_graph_returns_404(client):
    response = await client.post("/api/documents/missing-document/graph/rematerialize")

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


@pytest.mark.asyncio
async def test_rematerialize_document_graph_rejects_active_index_job(client, monkeypatch):
    calls = []

    async def fake_rematerialize_document(self, document_id):
        calls.append(document_id)
        return {
            "status": "succeeded",
            "node_count": 2,
            "edge_count": 1,
            "reason": None,
        }

    monkeypatch.setattr(
        "ragstudio.api.routes.documents.GraphProjectionRunner.rematerialize_document",
        fake_rematerialize_document,
    )
    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="graph-rematerialize-active-job.txt",
            content_type="text/plain",
            sha256="graph-rematerialize-active-job",
            artifact_path=str(app.state.settings.data_dir / "graph-rematerialize-active-job.txt"),
            status=StageStatus.RUNNING.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Job(
                type="index_document",
                target_id=document.id,
                status=StageStatus.RUNNING.value,
                progress=50,
            )
        )
        await session.commit()
        document_id = document.id

    response = await client.post(f"/api/documents/{document_id}/graph/rematerialize")

    assert response.status_code == 409
    assert "active indexing job" in response.json()["detail"]
    assert calls == []


@pytest.mark.asyncio
async def test_rematerialize_document_graph_serializes_with_reindex_job_creation(
    client,
    monkeypatch,
):
    entered_rematerialize = asyncio.Event()
    release_rematerialize = asyncio.Event()

    async def fake_rematerialize_document(self, document_id):
        entered_rematerialize.set()
        await release_rematerialize.wait()
        return {
            "status": "succeeded",
            "node_count": 2,
            "edge_count": 1,
            "reason": None,
        }

    async def fake_run_index_job(settings, document_id, job_id, options):
        return None

    monkeypatch.setattr(
        "ragstudio.api.routes.documents.GraphProjectionRunner.rematerialize_document",
        fake_rematerialize_document,
    )
    monkeypatch.setattr("ragstudio.api.routes.documents._run_index_job", fake_run_index_job)
    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="graph-rematerialize-lock.txt",
            content_type="text/plain",
            sha256="graph-rematerialize-lock",
            artifact_path=str(app.state.settings.data_dir / "graph-rematerialize-lock.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.commit()
        document_id = document.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        rematerialize_task = asyncio.create_task(
            async_client.post(f"/api/documents/{document_id}/graph/rematerialize")
        )
        await entered_rematerialize.wait()

        reindex_task = asyncio.create_task(
            async_client.post(
                f"/api/documents/{document_id}/reindex",
                json={"parser_mode": "local_fallback", "domain_metadata": {}},
            )
        )
        await asyncio.sleep(0.05)
        assert reindex_task.done() is False

        release_rematerialize.set()
        rematerialize_response, reindex_response = await asyncio.gather(
            rematerialize_task,
            reindex_task,
        )

    assert rematerialize_response.status_code == 200
    assert reindex_response.status_code == 202


@pytest.mark.asyncio
async def test_reindex_document_validates_custom_json(client, tmp_path):
    session_factory = client._transport.app.state.session_factory
    artifact = tmp_path / "uploads" / "invalid-json-reindex-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with session_factory() as session:
        document = Document(
            filename="quran.pdf",
            content_type="application/pdf",
            sha256="invalid-json-reindex-sha",
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
            "domain_metadata": {"custom_json": {"retrieval": {"exact_reference_top1": "yes"}}},
        },
    )

    assert response.status_code == 422
    assert "retrieval values" in response.json()["detail"]


@pytest.mark.asyncio
async def test_reindex_document_rejects_active_index_job(client, tmp_path):
    session_factory = client._transport.app.state.session_factory
    artifact = tmp_path / "uploads" / "active-reindex-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with session_factory() as session:
        document = Document(
            filename="quran.pdf",
            content_type="application/pdf",
            sha256="active-reindex-sha",
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
                progress=50,
            )
        )
        await session.commit()
        document_id = document.id

    response = await client.post(
        f"/api/documents/{document_id}/reindex",
        json={"parser_mode": "local_fallback", "domain_metadata": {}},
    )

    assert response.status_code == 409
    assert "active indexing job" in response.json()["detail"]


@pytest.mark.asyncio
async def test_reindex_document_concurrent_requests_create_one_active_job(
    client,
    monkeypatch,
    tmp_path,
):
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_run_index_job(settings, document_id, job_id, options):
        started.set()
        await release.wait()

    monkeypatch.setattr("ragstudio.api.routes.documents._run_index_job", fake_run_index_job)
    session_factory = client._transport.app.state.session_factory
    artifact = tmp_path / "uploads" / "concurrent-reindex-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with session_factory() as session:
        document = Document(
            filename="quran.pdf",
            content_type="application/pdf",
            sha256="concurrent-reindex-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.commit()
        document_id = document.id

    transport = httpx.ASGITransport(app=client._transport.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        responses = await asyncio.gather(
            async_client.post(
                f"/api/documents/{document_id}/reindex",
                json={"parser_mode": "local_fallback", "domain_metadata": {}},
            ),
            async_client.post(
                f"/api/documents/{document_id}/reindex",
                json={"parser_mode": "local_fallback", "domain_metadata": {}},
            ),
        )

    release.set()
    statuses = sorted(response.status_code for response in responses)
    assert statuses == [202, 409]
    async with session_factory() as session:
        active_jobs = (
            await session.execute(
                select(Job).where(
                    Job.type == "index_document",
                    Job.target_id == document_id,
                    Job.status.in_([StageStatus.READY.value, StageStatus.RUNNING.value]),
                )
            )
        ).scalars().all()
    assert len(active_jobs) == 1


@pytest.mark.asyncio
async def test_reindex_document_validates_strict_mineru_before_queueing(client, tmp_path):
    session_factory = client._transport.app.state.session_factory
    artifact = tmp_path / "uploads" / "strict-reindex-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with session_factory() as session:
        document = Document(
            filename="quran.pdf",
            content_type="application/pdf",
            sha256="strict-reindex-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.commit()
        document_id = document.id

    response = await client.post(
        f"/api/documents/{document_id}/reindex",
        json={"parser_mode": "mineru_strict", "domain_metadata": {}},
    )

    assert response.status_code == 409
    assert "MinerU" in response.json()["detail"]
    async with session_factory() as session:
        job_count = len(
            (
                await session.execute(
                    select(Job).where(Job.type == "index_document", Job.target_id == document_id)
                )
            ).scalars().all()
        )
    assert job_count == 0


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
        data={"parser_mode": "local_fallback", "domain_metadata": "{}"},
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
async def test_duplicate_upload_requires_runtime_index_when_profile_changes(client, monkeypatch):
    monkeypatch.setattr(
        "ragstudio.api.routes.documents.RuntimeHealthService",
        BlockingHealthService,
    )
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
    detail = second_response.json()["detail"].lower()
    assert "raganything" in detail or "lightrag" in detail or "neo4j" in detail


@pytest.mark.asyncio
async def test_runtime_blocked_mineru_strict_upload_returns_conflict(client, monkeypatch):
    monkeypatch.setattr(
        "ragstudio.api.routes.documents.RuntimeHealthService",
        BlockingHealthService,
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
        data={"parser_mode": "mineru_strict", "domain_metadata": "{}"},
        files={"file": ("runtime-strict.pdf", b"%PDF fake", "application/pdf")},
    )

    assert response.status_code == 409
    detail = response.json()["detail"].lower()
    assert "raganything" in detail or "lightrag" in detail or "neo4j" in detail


@pytest.mark.asyncio
async def test_duplicate_runtime_blocked_mineru_strict_upload_returns_conflict(
    client, monkeypatch
):
    monkeypatch.setattr(
        "ragstudio.api.routes.documents.RuntimeHealthService",
        BlockingHealthService,
    )
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
    detail = second_response.json()["detail"].lower()
    assert "raganything" in detail or "lightrag" in detail or "neo4j" in detail


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
        data={"parser_mode": "local_fallback", "domain_metadata": "{}"},
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
        session.add(
            GraphProjectionRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status="skipped",
                node_count=0,
                edge_count=0,
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
        projection_record = await session.scalar(
            select(GraphProjectionRecord).where(GraphProjectionRecord.document_id == document_id)
        )
    assert record is None
    assert projection_record is None


@pytest.mark.asyncio
async def test_delete_document_blocks_when_graph_projection_cleanup_fails(client, tmp_path):
    session_factory = client._transport.app.state.session_factory
    artifact = tmp_path / "uploads" / "graph-delete-cleanup-fails"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("alpha", encoding="utf-8")
    async with session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="graph-delete-cleanup-fails.txt",
            content_type="text/plain",
            sha256="graph-delete-cleanup-fails",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            GraphProjectionRecord(
                document_id=document.id,
                runtime_profile_id="missing-profile",
                status="succeeded",
                node_count=1,
                edge_count=0,
            )
        )
        await session.commit()
        document_id = document.id

    response = await client.delete(f"/api/documents/{document_id}")

    assert response.status_code == 409
    assert "Runtime profile 'missing-profile' is not configured" in response.json()["detail"]
    assert artifact.exists()
    async with session_factory() as session:
        assert await session.get(Document, document_id) is not None
        projection_record = await session.scalar(
            select(GraphProjectionRecord).where(GraphProjectionRecord.document_id == document_id)
        )
    assert projection_record is not None


@pytest.mark.asyncio
async def test_delete_document_does_not_repeat_graph_cleanup_after_artifact_unlink_failure(
    client,
    tmp_path,
    monkeypatch,
):
    app = client._transport.app
    session_factory = app.state.session_factory
    artifact = tmp_path / "uploads" / "graph-delete-unlink-fails"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("alpha", encoding="utf-8")
    async with session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
            )
        )
        document = Document(
            filename="graph-delete-unlink-fails.txt",
            content_type="text/plain",
            sha256="graph-delete-unlink-fails",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            GraphProjectionRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status="succeeded",
                graph_workspace_label="ragstudio_default",
                graph_storage_uri="bolt://neo4j.test:7687",
                node_count=1,
                edge_count=0,
            )
        )
        await session.commit()
        document_id = document.id

    graph_cleanup_calls = []

    async def fake_delete_document_graph(self, *, document_id, profile):
        graph_cleanup_calls.append(document_id)
        return GraphMaterializationResult(status="succeeded", node_count=1, edge_count=0)

    monkeypatch.setattr(
        "ragstudio.services.graph_materialization_service.GraphMaterializationService.delete_document_graph",
        fake_delete_document_graph,
    )

    original_unlink = Path.unlink
    calls = {"count": 0}

    def flaky_unlink(self, *args, **kwargs):
        if self == artifact and calls["count"] == 0:
            calls["count"] += 1
            raise OSError("unlink failed once")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as retry_client:
        first_response = await retry_client.delete(f"/api/documents/{document_id}")

        assert first_response.status_code == 500
        async with session_factory() as session:
            projection_record = await session.scalar(
                select(GraphProjectionRecord).where(
                    GraphProjectionRecord.document_id == document_id
                )
            )
        assert projection_record is not None
        assert projection_record.cleanup_status == "succeeded"

        second_response = await retry_client.delete(f"/api/documents/{document_id}")

    assert second_response.status_code == 204
    assert not artifact.exists()
    assert graph_cleanup_calls == [document_id]


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


@pytest.mark.asyncio
async def test_delete_document_preserves_job_and_index_record_when_graph_cleanup_fails(
    client,
    tmp_path,
    monkeypatch,
):
    app = client._transport.app
    session_factory = app.state.session_factory
    artifact = tmp_path / "uploads" / "graph-cleanup-fails.txt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("alpha", encoding="utf-8")

    async with session_factory() as session:
        document = Document(
            filename="graph-cleanup-fails.txt",
            content_type="text/plain",
            sha256="graph-cleanup-fails-sha",
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
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status=StageStatus.SUCCEEDED.value,
                chunk_count=1,
            )
        )
        await session.commit()
        document_id = document.id

    async def fail_after_cleanup_state_commit(self, document_id):
        await self.session.commit()
        raise GraphProjectionCleanupError("Graph projection cleanup failed: neo4j unavailable")

    monkeypatch.setattr(
        "ragstudio.services.document_service.GraphProjectionRunner.delete_document_graph",
        fail_after_cleanup_state_commit,
    )

    async with session_factory() as session:
        with pytest.raises(GraphProjectionCleanupError, match="neo4j unavailable"):
            await DocumentService(
                session,
                tmp_path,
                settings=app.state.settings,
            ).delete_document(document_id)

    async with session_factory() as session:
        document_exists = await session.get(Document, document_id)
        job_id = await session.scalar(select(Job.id).where(Job.target_id == document_id))
        index_record_id = await session.scalar(
            select(IndexRecord.id).where(IndexRecord.document_id == document_id)
        )

    assert artifact.exists()
    assert document_exists is not None
    assert job_id is not None
    assert index_record_id is not None
