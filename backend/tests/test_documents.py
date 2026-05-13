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
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.schemas.runtime import RuntimeHealthCheck
from ragstudio.services.document_service import DocumentService
from ragstudio.services.graph_materialization_service import GraphMaterializationResult
from ragstudio.services.graph_projection_runner import GraphProjectionCleanupError
from ragstudio.services.runtime_profile_service import RuntimeProfileService
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


async def seed_product_runtime_profile(client) -> None:
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


def allow_product_readiness(monkeypatch) -> None:
    async def validate_sidecar(self, options):
        return None

    monkeypatch.setattr(
        "ragstudio.api.routes.documents.RuntimeHealthService",
        PassingHealthService,
    )
    monkeypatch.setattr(
        "ragstudio.services.chunk_service.ChunkService.validate_strict_mineru_sidecar",
        validate_sidecar,
    )


@pytest.mark.asyncio
async def test_upload_rejects_local_fallback_parser_mode(client):
    response = await client.post(
        "/api/documents",
        data={
            "parser_mode": "local_fallback",
            "domain_metadata": "{}",
        },
        files={"file": ("policy.txt", b"Policy line\n", "text/plain")},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_upload_reports_legacy_runtime_profile_without_crashing(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="legacy",
                llm_model="legacy-llm",
                embedding_model="legacy-embedding",
                storage_backend="fallback_local",
                runtime_mode="fallback",
                embedding_provider="fallback",
            )
        )
        await session.commit()

    response = await client.post(
        "/api/documents",
        data={"parser_mode": "mineru_strict", "domain_metadata": "{}"},
        files={"file": ("legacy-profile.pdf", b"%PDF fake", "application/pdf")},
    )

    assert response.status_code == 409
    assert "Configure a product runtime profile" in response.json()["detail"]


@pytest.mark.asyncio
async def test_reindex_reports_legacy_runtime_profile_without_crashing(client, tmp_path):
    app = client._transport.app
    artifact = tmp_path / "uploads" / "legacy-profile-reindex"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="legacy",
                llm_model="legacy-llm",
                embedding_model="legacy-embedding",
                storage_backend="fallback_local",
                runtime_mode="fallback",
                embedding_provider="fallback",
            )
        )
        document = Document(
            filename="legacy-profile.pdf",
            content_type="application/pdf",
            sha256="legacy-profile-reindex",
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
    assert "Configure a product runtime profile" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_uses_default_parser_mode_when_omitted(client, monkeypatch):
    await seed_product_runtime_profile(client)
    allow_product_readiness(monkeypatch)

    response = await client.post(
        "/api/documents",
        data={
            "domain_metadata": json.dumps(
                {"domain": "policy", "document_type": "admin_document"}
            ),
        },
        files={"file": ("policy.txt", b"Policy line\n", "text/plain")},
    )

    assert response.status_code == 201
    document_id = response.json()["id"]
    jobs = await wait_for_jobs(client, 1, terminal=False)
    job_summary = next(job for job in jobs if job["target_id"] == document_id)
    async with client._transport.app.state.session_factory() as session:
        job = await session.get(Job, job_summary["id"])
    assert job is not None
    assert job.job_options["parser_mode"] == "mineru_strict"
    assert job.job_options["domain_metadata"]["domain"] == "policy"


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
async def test_duplicate_upload_with_explicit_default_options_reuses_active_job(
    client,
    monkeypatch,
):
    await seed_product_runtime_profile(client)
    allow_product_readiness(monkeypatch)
    first_response = await client.post(
        "/api/documents",
        files={"file": ("notes.txt", b"same bytes", "text/plain")},
    )
    second_response = await client.post(
        "/api/documents",
        data={"parser_mode": "mineru_strict", "domain_metadata": "{}"},
        files={"file": ("notes-copy.txt", b"same bytes", "text/plain")},
    )
    jobs = await wait_for_jobs(client, 1, terminal=False)

    assert second_response.status_code == 201
    assert second_response.json()["id"] == first_response.json()["id"]
    jobs = [job for job in jobs if job["type"] == "index_document"]
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_duplicate_upload_does_not_schedule_second_active_job(client, monkeypatch):
    await seed_product_runtime_profile(client)
    allow_product_readiness(monkeypatch)

    first_response = await client.post(
        "/api/documents",
        data={"parser_mode": "mineru_strict", "domain_metadata": "{}"},
        files={"file": ("notes.txt", b"same bytes", "text/plain")},
    )
    second_response = await client.post(
        "/api/documents",
        data={"parser_mode": "mineru_strict", "domain_metadata": "{}"},
        files={"file": ("notes-copy.txt", b"same bytes", "text/plain")},
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    document_id = first_response.json()["id"]
    assert document_id == second_response.json()["id"]
    await wait_for_jobs(client, 1, terminal=False)
    async with client._transport.app.state.session_factory() as session:
        result = await session.execute(
            select(Job).where(
                Job.type == "index_document",
                Job.target_id == document_id,
                Job.status.in_([StageStatus.READY.value, StageStatus.RUNNING.value]),
            )
        )
        active_jobs = result.scalars().all()
    assert len(active_jobs) == 1
    assert active_jobs[0].job_options["parser_mode"] == "mineru_strict"


@pytest.mark.asyncio
async def test_upload_persists_document_specific_mineru_parse_options(
    client,
    monkeypatch,
):
    await seed_product_runtime_profile(client)
    allow_product_readiness(monkeypatch)
    mineru_parse_options = {
        "parse_method": "ocr",
        "backend": "pipeline",
        "device": "cuda:0",
        "lang": "arabic",
        "formula": False,
        "table": False,
        "source": "huggingface",
        "max_concurrent_files": 2,
    }

    response = await client.post(
        "/api/documents",
        data={
            "parser_mode": "mineru_strict",
            "domain_metadata": "{}",
            "mineru_parse_options": json.dumps(mineru_parse_options),
        },
        files={"file": ("tafseer.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 201
    document_id = response.json()["id"]
    await wait_for_jobs(client, 1, terminal=False)
    async with client._transport.app.state.session_factory() as session:
        result = await session.execute(
            select(Job).where(Job.type == "index_document", Job.target_id == document_id)
        )
        job = result.scalars().one()
    assert job.job_options["mineru_parse_options"] == mineru_parse_options


@pytest.mark.asyncio
async def test_reindex_document_queues_job_with_updated_metadata(client, monkeypatch, tmp_path):
    await seed_product_runtime_profile(client)
    allow_product_readiness(monkeypatch)

    async def validate_sidecar(self, options):
        return None

    monkeypatch.setattr(
        "ragstudio.services.chunk_service.ChunkService.validate_strict_mineru_sidecar",
        validate_sidecar,
    )
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
            "parser_mode": "mineru_strict",
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

    assert response.status_code == 202
    body = response.json()
    assert body["document_id"] == document_id
    assert body["job_id"]
    assert body["status"] == "ready"
    async with session_factory() as session:
        job = await session.get(Job, body["job_id"])
    assert job is not None
    assert job.target_id == document_id
    assert job.job_options["parser_mode"] == "mineru_strict"
    assert job.job_options["domain_metadata"]["domain"] == "religion"
    assert job.job_options["domain_metadata"]["document_type"] == "religious_text"
    assert job.job_options["domain_metadata"]["tags"] == ["quran"]
    assert job.job_options["domain_metadata"]["custom_json"] == {
        "reference_schema": {"type": "surah_ayah"},
        "retrieval": {"exact_reference_top1": True},
    }


@pytest.mark.asyncio
async def test_reindex_persists_document_specific_mineru_parse_options(
    client,
    tmp_path,
    monkeypatch,
):
    await seed_product_runtime_profile(client)
    allow_product_readiness(monkeypatch)
    app = client._transport.app
    mineru_parse_options = {
        "parse_method": "ocr",
        "backend": "pipeline",
        "device": "cuda:0",
        "lang": "arabic",
        "formula": False,
        "table": False,
        "source": "huggingface",
        "max_concurrent_files": 2,
    }
    artifact = tmp_path / "uploads" / "reindex-mineru-options-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with app.state.session_factory() as session:
        document = Document(
            filename="tafseer.pdf",
            content_type="application/pdf",
            sha256="reindex-mineru-options-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.commit()
        document_id = document.id

    response = await client.post(
        f"/api/documents/{document_id}/reindex",
        json={
            "parser_mode": "mineru_strict",
            "domain_metadata": {"domain": "quran_tafseer"},
            "mineru_parse_options": mineru_parse_options,
        },
    )

    assert response.status_code == 202
    async with app.state.session_factory() as session:
        job = await session.get(Job, response.json()["job_id"])
    assert job is not None
    assert job.job_options["mineru_parse_options"] == mineru_parse_options


@pytest.mark.asyncio
async def test_reindex_persists_job_options_for_worker(client, tmp_path, monkeypatch):
    await seed_product_runtime_profile(client)
    allow_product_readiness(monkeypatch)
    app = client._transport.app
    index_options = {
        "parser_mode": "mineru_strict",
        "domain_metadata": {"domain": "quran", "tags": ["arabic"]},
    }
    expected_options = IndexDocumentIn.model_validate(index_options).model_dump(
        mode="json",
        exclude_none=True,
    )

    artifact = tmp_path / "uploads" / "durable-worker-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with app.state.session_factory() as session:
        document = Document(
            filename="worker-quran.pdf",
            content_type="application/pdf",
            sha256="durable-worker-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.commit()
        document_id = document.id

    response = await client.post(
        f"/api/documents/{document_id}/reindex",
        json=index_options,
    )

    assert response.status_code == 202
    async with app.state.session_factory() as session:
        job = await session.get(Job, response.json()["job_id"])

    assert job is not None
    assert job.status == StageStatus.READY.value
    assert job.job_options == expected_options
    assert job.result["index_options"] == job.job_options


@pytest.mark.asyncio
async def test_reindex_does_not_schedule_in_process_background_task(client, tmp_path, monkeypatch):
    await seed_product_runtime_profile(client)
    allow_product_readiness(monkeypatch)
    app = client._transport.app
    artifact = tmp_path / "uploads" / "no-background-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with app.state.session_factory() as session:
        document = Document(
            filename="no-background.pdf",
            content_type="application/pdf",
            sha256="no-background-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.commit()
        document_id = document.id

    called = False

    def fail_background_task(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("route must not create an in-process indexing task")

    import ragstudio.api.routes.documents as document_routes

    monkeypatch.setattr(
        document_routes,
        "create_background_task",
        fail_background_task,
        raising=False,
    )

    response = await client.post(
        f"/api/documents/{document_id}/reindex",
        json={"parser_mode": "mineru_strict", "domain_metadata": {}},
    )

    assert response.status_code == 202
    assert called is False


@pytest.mark.asyncio
async def test_reindex_rejects_mineru_with_fallback(client, tmp_path):
    session_factory = client._transport.app.state.session_factory
    artifact = tmp_path / "uploads" / "reindex-policy-sha"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Quran 1:4", encoding="utf-8")
    async with session_factory() as session:
        document = Document(
            filename="quran.pdf",
            content_type="application/pdf",
            sha256="reindex-policy-sha",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.commit()
        document_id = document.id

    response = await client.post(
        f"/api/documents/{document_id}/reindex",
        json={"parser_mode": "mineru_with_fallback", "domain_metadata": {}},
    )

    assert response.status_code == 422
    assert "mineru_strict" in str(response.json()["detail"])


@pytest.mark.asyncio
async def test_reindex_missing_document_returns_404(client):
    response = await client.post(
        "/api/documents/missing-document/reindex",
        json={"parser_mode": "mineru_strict", "domain_metadata": {}},
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
    await seed_product_runtime_profile(client)
    allow_product_readiness(monkeypatch)
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

    async def validate_sidecar(self, options):
        return None

    monkeypatch.setattr(
        "ragstudio.api.routes.documents.GraphProjectionRunner.rematerialize_document",
        fake_rematerialize_document,
    )
    monkeypatch.setattr(
        "ragstudio.services.chunk_service.ChunkService.validate_strict_mineru_sidecar",
        validate_sidecar,
    )
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
                json={"parser_mode": "mineru_strict", "domain_metadata": {}},
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
            "parser_mode": "mineru_strict",
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
        json={"parser_mode": "mineru_strict", "domain_metadata": {}},
    )

    assert response.status_code == 409
    assert "active indexing job" in response.json()["detail"]


@pytest.mark.asyncio
async def test_reindex_document_concurrent_requests_create_one_active_job(
    client,
    monkeypatch,
    tmp_path,
):
    await seed_product_runtime_profile(client)
    allow_product_readiness(monkeypatch)

    async def validate_sidecar(self, options):
        return None

    monkeypatch.setattr(
        "ragstudio.services.chunk_service.ChunkService.validate_strict_mineru_sidecar",
        validate_sidecar,
    )
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
                json={"parser_mode": "mineru_strict", "domain_metadata": {}},
            ),
            async_client.post(
                f"/api/documents/{document_id}/reindex",
                json={"parser_mode": "mineru_strict", "domain_metadata": {}},
            ),
        )

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
async def test_upload_queues_runtime_index_job_when_profile_exists(client, monkeypatch):
    async def validate_sidecar(self, options):
        return None

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
    monkeypatch.setattr(
        "ragstudio.services.chunk_service.ChunkService.validate_strict_mineru_sidecar",
        validate_sidecar,
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
        files={"file": ("runtime-upload.txt", b"runtime upload", "text/plain")},
    )

    assert response.status_code == 201
    document_id = response.json()["id"]
    jobs = await wait_for_jobs(client, 1, terminal=False)
    async with app.state.session_factory() as session:
        record = await session.scalar(
            select(IndexRecord).where(IndexRecord.document_id == document_id)
        )
        job = await session.get(Job, jobs[0]["id"])

    assert record is None
    assert job is not None
    assert jobs[0]["target_id"] == document_id
    assert jobs[0]["status"] == StageStatus.READY.value
    assert job.job_options["parser_mode"] == "mineru_strict"


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
async def test_delete_document_removes_document_chunks_jobs_and_artifact(client):
    session_factory = client._transport.app.state.session_factory
    artifact_path = client._transport.app.state.settings.data_dir / "uploads" / "delete-me-sha"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("alpha beta\ngamma delta", encoding="utf-8")
    async with session_factory() as session:
        document = Document(
            filename="delete-me.txt",
            content_type="text/plain",
            sha256="delete-me-sha",
            artifact_path=str(artifact_path),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        document_id = document.id
        session.add_all(
            [
                Chunk(
                    document_id=document_id,
                    text="alpha beta",
                    source_location={"line": 1},
                    metadata_json={},
                ),
                Chunk(
                    document_id=document_id,
                    text="gamma delta",
                    source_location={"line": 2},
                    metadata_json={},
                ),
                Job(
                    type="index_document",
                    target_id=document_id,
                    status=StageStatus.SUCCEEDED.value,
                    progress=100,
                ),
            ]
        )
        await session.commit()

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
async def test_ready_runtime_index_allows_enriched_index_shape(client, tmp_path):
    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="runtime-indexed.txt",
            content_type="text/plain",
            sha256="runtime-indexed-enriched-sha",
            artifact_path=str(tmp_path / "runtime-indexed.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
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
        session.add(document)
        await session.flush()
        profile = await RuntimeProfileService(session, app.state.settings).get_active_profile()
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id=profile.id,
                status=StageStatus.SUCCEEDED.value,
                index_shape={
                    **profile.index_shape,
                    "parser_mode": "mineru_strict",
                    "canonical_chunk_count": 1,
                    "runtime_chunk_count": 1,
                },
                chunk_count=1,
            )
        )
        await session.commit()

        ready = await DocumentService(
            session,
            app.state.settings.data_dir,
            app.state.settings,
        )._has_ready_runtime_index(document.id, profile)

    assert ready is True


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
async def test_delete_document_rejects_active_index_job_and_preserves_state(
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

    assert response.status_code == 409
    assert "active indexing job" in response.json()["detail"]
    assert artifact.exists()
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        job_id = await session.scalar(select(Job.id).where(Job.target_id == document_id))
    assert document is not None
    assert document.status == StageStatus.RUNNING.value
    assert job_id is not None


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
