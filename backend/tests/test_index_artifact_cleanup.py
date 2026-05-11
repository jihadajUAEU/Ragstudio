import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document, GraphProjectionRecord, IndexRecord, Job
from ragstudio.services.index_artifact_cleanup import cleanup_document_index_artifacts
from sqlalchemy import func, select


@pytest.mark.asyncio
async def test_cleanup_removes_retrieval_artifacts_but_keeps_document_and_jobs(
    database_url,
    tmp_path,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        document = Document(
            id="doc-cleanup",
            filename="failed.pdf",
            content_type="application/pdf",
            sha256="failed-sha",
            artifact_path=str(tmp_path / "failed.pdf"),
            status="running",
        )
        job = Job(
            id="job-cleanup",
            type="index_document",
            target_id="doc-cleanup",
            status="failed",
            result={"error": "MinerU validation failed"},
        )
        session.add_all(
            [
                document,
                job,
                Chunk(
                    document_id="doc-cleanup",
                    text="stale",
                    source_location={},
                    metadata_json={},
                ),
                IndexRecord(
                    document_id="doc-cleanup",
                    runtime_profile_id="default",
                    status="failed",
                    chunk_count=1,
                ),
                GraphProjectionRecord(
                    document_id="doc-cleanup",
                    runtime_profile_id="default",
                    status="failed",
                    error="graph failed",
                ),
            ]
        )
        await session.commit()

        await cleanup_document_index_artifacts(session, "doc-cleanup", commit=True)

        chunk_count = (
            await session.execute(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == "doc-cleanup")
            )
        ).scalar_one()
        index_count = (
            await session.execute(
                select(func.count())
                .select_from(IndexRecord)
                .where(IndexRecord.document_id == "doc-cleanup")
            )
        ).scalar_one()
        graph_count = (
            await session.execute(
                select(func.count())
                .select_from(GraphProjectionRecord)
                .where(GraphProjectionRecord.document_id == "doc-cleanup")
            )
        ).scalar_one()
        kept_document = await session.get(Document, "doc-cleanup")
        kept_job = await session.get(Job, "job-cleanup")

    await engine.dispose()

    assert chunk_count == 0
    assert index_count == 0
    assert graph_count == 0
    assert kept_document is not None
    assert kept_job is not None
    assert kept_job.result["error"] == "MinerU validation failed"
