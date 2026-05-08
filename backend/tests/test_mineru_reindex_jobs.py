import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document, Job
from ragstudio.schemas.chunks import ChunkSearchIn
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.document_service import DocumentService


class FailingIndexService(DocumentService):
    async def _index_document_for_job(
        self, document, job, options=None, on_mineru_status=None
    ):
        job.status = "running"
        job.progress = 25
        job.logs = [*job.logs, "MinerU parsing on HPC."]
        raise RuntimeError("MinerU parse timed out for job remote-123.")


@pytest.mark.asyncio
async def test_arabic_phrase_search_matches_indexed_chunk(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'studio.sqlite3'}")
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
async def test_run_index_job_marks_strict_mineru_failure(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'studio.sqlite3'}")
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
async def test_create_strict_reindex_job_returns_immediately(client, monkeypatch):
    upload_response = await client.post(
        "/api/documents",
        files={"file": ("quran_arabic_english.pdf", b"%PDF-1.4", "application/pdf")},
    )
    document_id = upload_response.json()["id"]
    scheduled = {}

    def fake_add_task(self, fn, *args, **kwargs):
        scheduled["fn"] = fn
        scheduled["args"] = args
        scheduled["kwargs"] = kwargs

    monkeypatch.setattr("fastapi.BackgroundTasks.add_task", fake_add_task)

    response = await client.post(
        f"/api/chunks/index/{document_id}/jobs",
        json={
            "parser_mode": "mineru_strict",
            "domain_metadata": {
                "domain": "religious_text",
                "document_type": "scripture_translation",
                "language": "arabic_english",
                "tags": ["quran", "arabic", "english", "translation"],
                "collection": "quran_arabic_english",
            },
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["type"] == "index_document"
    assert body["target_id"] == document_id
    assert body["status"] == "ready"
    assert scheduled["args"][1] == document_id
    assert scheduled["args"][2] == body["id"]
