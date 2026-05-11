import pytest
from ragstudio.config import AppSettings
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document, IndexRecord, Job, SettingsProfile
from ragstudio.schemas.chunks import ChunkSearchIn
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.index_lifecycle_service import IndexLifecycleService
from sqlalchemy import func, select


class FakeDocumentParser:
    async def parse(self, document, options, *, on_mineru_status=None):
        if on_mineru_status is not None:
            await on_mineru_status(
                {
                    "jobId": "remote-ready",
                    "status": "ready",
                    "progress": 100,
                    "detail": "MinerU artifacts ready.",
                    "updatedAt": "2026-05-11T07:18:50Z",
                }
            )
        return [
            AdapterChunk(
                text="Sahih al-Bukhari contains 7277 hadith.",
                source_location={"page": 1},
                metadata={
                    "parser_metadata": {"backend": "mineru"},
                    "document_metadata": {
                        "title": "Sahih al-Bukhari 7277 Hadith Collection"
                    },
                    "extraction_quality": {"validated": True},
                },
            )
        ]


class FailingRuntime:
    async def delete_document_index(self, document_id):
        return None

    async def index_preparsed_chunks(self, artifact_path, preparsed_chunks, *, document_id):
        raise RuntimeError("runtime enrichment unavailable")


class FakeRuntimeFactory:
    def build(self, profile):
        return FailingRuntime()


class PassingHealthService:
    async def check(self, profile):
        return []

    def blocking_failures(self, checks):
        return []


@pytest.mark.asyncio
async def test_chunks_are_searchable_when_runtime_enrichment_fails(database_url, tmp_path):
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine)

    async with session_factory() as session:
        artifact = tmp_path / "bukhari.pdf"
        artifact.write_bytes(b"%PDF-1.4")
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
        session.add(
            Document(
                id="doc-e2e-durable",
                filename="hadith_bukhari.pdf",
                content_type="application/pdf",
                sha256="e2e-durable-sha",
                artifact_path=str(artifact),
                status=StageStatus.READY.value,
            )
        )
        session.add(
            Job(
                id="job-e2e-durable",
                type="index_document",
                target_id="doc-e2e-durable",
                status=StageStatus.READY.value,
                progress=0,
            )
        )
        await session.commit()

        result = await IndexLifecycleService(
            session,
            AppSettings(data_dir=tmp_path),
            runtime_factory=FakeRuntimeFactory(),
            health_service=PassingHealthService(),
            document_parser=FakeDocumentParser(),
        ).reindex_document(
            "doc-e2e-durable",
            options=IndexDocumentIn(parser_mode="mineru_strict"),
        )

        search_result = await ChunkService(session, tmp_path).search(
            ChunkSearchIn(query="Bukhari 7277", document_ids=["doc-e2e-durable"], limit=5)
        )
        chunk_count = (
            await session.execute(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.document_id == "doc-e2e-durable")
            )
        ).scalar_one()
        index_records = (
            await session.execute(
                select(IndexRecord).where(IndexRecord.document_id == "doc-e2e-durable")
            )
        ).scalars().all()
        refreshed_doc = await session.get(Document, "doc-e2e-durable")

    await engine.dispose()

    assert result is not None
    assert len(result.chunks) == 1
    assert result.graph_materialization["status"] == "skipped"
    assert "runtime enrichment unavailable" in result.graph_materialization["reason"]
    assert refreshed_doc is not None
    assert refreshed_doc.status == StageStatus.SUCCEEDED.value
    assert chunk_count == 1
    assert search_result.total == 1
    assert search_result.items[0].text == "Sahih al-Bukhari contains 7277 hadith."
    assert len(index_records) == 1
    assert index_records[0].status == StageStatus.FAILED.value
    assert index_records[0].chunk_count == 1
    assert "runtime enrichment unavailable" in (index_records[0].error or "")
