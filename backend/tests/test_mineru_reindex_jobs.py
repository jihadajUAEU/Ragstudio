import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document, Job, SettingsProfile
from ragstudio.schemas.chunks import ChunkSearchIn
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.schemas.runtime import RuntimeHealthCheck
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.document_service import DocumentService
from ragstudio.services.mineru_client import MinerUSidecarHealth


class FailingIndexService(DocumentService):
    async def _index_document_for_job(
        self, document, job, options=None, on_mineru_status=None
    ):
        job.status = "running"
        job.progress = 25
        job.logs = [*job.logs, "MinerU parsing on HPC."]
        raise RuntimeError("MinerU parse timed out for job remote-123.")


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


@pytest.mark.asyncio
async def test_arabic_phrase_search_matches_indexed_chunk(tmp_path, database_url):
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine)

    async with session_factory() as session:
        document = Document(
            filename="quran_arabic_english.pdf",
            content_type="application/pdf",
            sha256="arabic-search-sha",
            artifact_path=str(tmp_path / "quran.pdf"),
            status="succeeded",
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="الذين يؤمنون بما أنزل إليك وما أنزل من قبلك",
                source_location={"page": 2},
                metadata_json={
                    "domain_metadata": {"domain": "religious_text"},
                    "parser_metadata": {"backend": "mineru", "parser_mode": "mineru_strict"},
                },
            )
        )
        await session.commit()

        result = await ChunkService(session, tmp_path).search(
            ChunkSearchIn(
                query="الذين يؤمنون بما أنزل",
                document_ids=[document.id],
                limit=5,
            )
        )

    await engine.dispose()

    assert result.total == 1
    assert "بما أنزل" in result.items[0].text
    assert result.items[0].metadata["parser_metadata"]["backend"] == "mineru"


@pytest.mark.asyncio
async def test_run_index_job_marks_strict_mineru_failure(tmp_path, database_url):
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine)

    async with session_factory() as session:
        artifact = tmp_path / "quran.pdf"
        artifact.write_bytes(b"%PDF-1.4")
        document = Document(
            filename="quran_arabic_english.pdf",
            content_type="application/pdf",
            sha256="strict-failure-sha",
            artifact_path=str(artifact),
            status="ready",
        )
        session.add(document)
        await session.flush()
        job = Job(type="index_document", target_id=document.id, status="ready", progress=0)
        session.add(job)
        await session.commit()

        service = FailingIndexService(session, tmp_path)
        await service.run_index_job(
            document.id,
            job.id,
            IndexDocumentIn(parser_mode="mineru_strict"),
        )

        refreshed_doc = await session.get(Document, document.id)
        refreshed_job = await session.get(Job, job.id)

    await engine.dispose()

    assert refreshed_doc is not None
    assert refreshed_job is not None
    assert refreshed_doc.status == "failed"
    assert refreshed_job.status == "failed"
    assert refreshed_job.progress == 100
    assert "MinerU parse timed out" in refreshed_job.logs[-1]


@pytest.mark.asyncio
async def test_run_index_job_preserves_mineru_status_on_success(
    tmp_path,
    database_url,
    monkeypatch,
):
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine)

    async with session_factory() as session:
        artifact = tmp_path / "quran.pdf"
        artifact.write_bytes(b"%PDF-1.4")
        document = Document(
            filename="quran_arabic_english.pdf",
            content_type="application/pdf",
            sha256="strict-success-sha",
            artifact_path=str(artifact),
            status="ready",
        )
        session.add(document)
        await session.flush()
        job = Job(type="index_document", target_id=document.id, status="ready", progress=0)
        session.add(job)
        await session.commit()

        async def fake_index_document(
            self,
            document_id,
            *,
            options=None,
            commit=True,
            on_mineru_status=None,
        ):
            if on_mineru_status is not None:
                await on_mineru_status(
                    {
                        "jobId": "remote-ready",
                        "status": "ready",
                        "progress": 100,
                        "detail": "MinerU artifacts ready.",
                        "updatedAt": "2026-05-08T09:00:00Z",
                    }
                )
            return [object(), object(), object()]

        monkeypatch.setattr(ChunkService, "index_document", fake_index_document)

        service = DocumentService(session, tmp_path)
        await service.run_index_job(
            document.id,
            job.id,
            IndexDocumentIn(parser_mode="mineru_strict"),
        )

        refreshed_job = await session.get(Job, job.id)

    await engine.dispose()

    assert refreshed_job is not None
    assert refreshed_job.status == "succeeded"
    assert refreshed_job.result["chunk_count"] == 3
    assert refreshed_job.result["mineru"]["job_id"] == "remote-ready"
    assert refreshed_job.result["mineru"]["status"] == "ready"


@pytest.mark.asyncio
async def test_create_strict_reindex_job_returns_not_found_before_sidecar_check(
    client,
    monkeypatch,
):
    runtime_checked = {"value": False}

    class FailingHealthClient:
        def __init__(self, base_url, timeout_ms, poll_interval_ms):
            self.base_url = base_url
            self.timeout_ms = timeout_ms
            self.poll_interval_ms = poll_interval_ms

        async def health(self):
            raise AssertionError("health must not be checked for a missing document")

    async def fail_runtime_check(self, profile):
        runtime_checked["value"] = True
        raise AssertionError("runtime health must not be checked for a missing document")

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
                mineru_enabled=True,
                mineru_base_url="http://10.10.9.19:8765",
                mineru_require_hpc=True,
            )
        )
        await session.commit()

    before = (await client.get("/api/jobs")).json()["total"]
    monkeypatch.setattr("ragstudio.services.chunk_service.MinerUClient", FailingHealthClient)
    monkeypatch.setattr(
        "ragstudio.api.routes.documents.RuntimeHealthService.check",
        fail_runtime_check,
    )

    response = await client.post(
        "/api/documents/missing-document/reindex",
        json={"parser_mode": "mineru_strict", "domain_metadata": {}},
    )

    after = (await client.get("/api/jobs")).json()["total"]
    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"
    assert after == before
    assert runtime_checked["value"] is False


@pytest.mark.asyncio
async def test_create_reindex_job_returns_conflict_when_runtime_health_blocks(
    client, monkeypatch
):
    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="runtime-job.pdf",
            content_type="application/pdf",
            sha256="runtime-job",
            artifact_path=str(app.state.settings.data_dir / "runtime-job.pdf"),
            status="ready",
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
        await session.commit()
        document_id = document.id

    monkeypatch.setattr(
        "ragstudio.api.routes.documents.RuntimeHealthService",
        BlockingHealthService,
    )

    response = await client.post(
        f"/api/documents/{document_id}/reindex",
        json={"parser_mode": "mineru_strict", "domain_metadata": {}},
    )

    assert response.status_code == 409
    detail = response.json()["detail"].lower()
    assert "raganything" in detail or "lightrag" in detail or "neo4j" in detail


@pytest.mark.asyncio
async def test_mineru_strict_blocks_when_sidecar_is_local_only(tmp_path, database_url):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    class LocalHealthClient:
        def __init__(self, base_url, timeout_ms, poll_interval_ms):
            self.base_url = base_url
            self.timeout_ms = timeout_ms
            self.poll_interval_ms = poll_interval_ms

        async def health(self):
            return MinerUSidecarHealth(
                ready=True,
                detail="RAG-Anything sidecar ready",
                version="hybrid",
                hpc_enabled=False,
                hpc_mode="local",
                raw={"hpcMineru": {"enabled": False, "mode": "local"}},
            )

        async def parse_document(self, **kwargs):
            raise AssertionError("parse_document must not be called when HPC is required")

    async with factory() as session:
        artifact = tmp_path / "quran.pdf"
        artifact.write_bytes(b"%PDF-1.4")
        document = Document(
            filename="quran.pdf",
            content_type="application/pdf",
            sha256="sha",
            artifact_path=str(artifact),
            status="ready",
        )
        settings = SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="gpt-4o",
            llm_base_url="http://127.0.0.1:8004/v1",
            embedding_model="text-embedding-3-large",
            embedding_base_url="http://127.0.0.1:8001/v1",
            storage_backend="postgres_pgvector_neo4j",
            runtime_mode="runtime",
            mineru_enabled=True,
            mineru_base_url="http://10.10.9.19:8765",
            mineru_require_hpc=True,
        )
        session.add_all([document, settings])
        await session.commit()

        with pytest.raises(RuntimeError, match="MinerU sidecar is not in HPC coordinator mode"):
            await ChunkService(
                session,
                tmp_path,
                mineru_client_factory=LocalHealthClient,
            ).index_document(
                document.id,
                options=IndexDocumentIn(parser_mode="mineru_strict"),
            )

    await engine.dispose()
