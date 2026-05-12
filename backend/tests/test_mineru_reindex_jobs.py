import pytest
from ragstudio.config import AppSettings
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import (
    Chunk,
    Document,
    GraphProjectionRecord,
    IndexRecord,
    Job,
    SettingsProfile,
)
from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.schemas.runtime import RuntimeHealthCheck
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.document_service import DocumentService
from ragstudio.services.index_lifecycle_service import IndexLifecycleService
from ragstudio.services.mineru_client import MinerUSidecarHealth
from sqlalchemy import func, select


class FailingIndexService(DocumentService):
    async def _index_document_for_job(
        self, document, job, options=None, on_mineru_status=None
    ):
        if on_mineru_status is not None:
            await on_mineru_status(
                {
                    "jobId": "remote-123",
                    "status": "running",
                    "progress": 42,
                    "detail": "MinerU parsing on HPC.",
                    "updatedAt": "2026-05-11T08:00:00Z",
                }
            )
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
async def test_runtime_enrichment_failure_keeps_persisted_chunks(
    tmp_path,
    database_url,
):
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine)

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

    async with session_factory() as session:
        artifact = tmp_path / "bukhari.pdf"
        artifact.write_bytes(b"%PDF-1.4")
        document = Document(
            id="doc-bukhari-partial",
            filename="hadith_bukhari.pdf",
            content_type="application/pdf",
            sha256="bukhari-partial-sha",
            artifact_path=str(artifact),
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

        result = await IndexLifecycleService(
            session,
            AppSettings(data_dir=tmp_path),
            runtime_factory=FakeRuntimeFactory(),
            health_service=PassingHealthService(),
            document_parser=FakeDocumentParser(),
        ).reindex_document(
            "doc-bukhari-partial",
            options=IndexDocumentIn(parser_mode="mineru_strict"),
        )

        refreshed_doc = await session.get(Document, "doc-bukhari-partial")
        chunk_count = (
            await session.execute(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.document_id == "doc-bukhari-partial")
            )
        ).scalar_one()

    await engine.dispose()

    assert result is not None
    assert len(result.chunks) == 1
    assert refreshed_doc is not None
    assert refreshed_doc.status == "succeeded"
    assert chunk_count == 1
    assert result.graph_materialization["status"] == "skipped"
    assert "runtime enrichment unavailable" in result.graph_materialization["reason"]


@pytest.mark.asyncio
async def test_runtime_enrichment_empty_output_marks_index_failed(
    tmp_path,
    database_url,
):
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine)

    class FakeDocumentParser:
        async def parse(self, document, options, *, on_mineru_status=None):
            return [
                AdapterChunk(
                    text="Sahih al-Bukhari contains 7277 hadith.",
                    source_location={"page": 1},
                    metadata={"parser_metadata": {"backend": "mineru"}},
                )
            ]

    class EmptyRuntime:
        async def delete_document_index(self, document_id):
            return None

        async def index_preparsed_chunks(self, artifact_path, preparsed_chunks, *, document_id):
            return []

    class FakeRuntimeFactory:
        def build(self, profile):
            return EmptyRuntime()

    class PassingHealthService:
        async def check(self, profile):
            return []

        def blocking_failures(self, checks):
            return []

    async with session_factory() as session:
        artifact = tmp_path / "bukhari-empty-runtime.pdf"
        artifact.write_bytes(b"%PDF-1.4")
        document = Document(
            id="doc-bukhari-empty-runtime",
            filename="hadith_bukhari_empty_runtime.pdf",
            content_type="application/pdf",
            sha256="bukhari-empty-runtime-sha",
            artifact_path=str(artifact),
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

        result = await IndexLifecycleService(
            session,
            AppSettings(data_dir=tmp_path),
            runtime_factory=FakeRuntimeFactory(),
            health_service=PassingHealthService(),
            document_parser=FakeDocumentParser(),
        ).reindex_document(
            "doc-bukhari-empty-runtime",
            options=IndexDocumentIn(parser_mode="mineru_strict"),
        )

        refreshed_doc = await session.get(Document, "doc-bukhari-empty-runtime")
        chunk_count = (
            await session.execute(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.document_id == "doc-bukhari-empty-runtime")
            )
        ).scalar_one()
        index_record = (
            await session.execute(
                select(IndexRecord).where(
                    IndexRecord.document_id == "doc-bukhari-empty-runtime"
                )
            )
        ).scalar_one()
        graph_record = await session.get(
            GraphProjectionRecord,
            result.graph_projection_record_id,
        )

    async with session_factory() as session:
        separately_loaded_graph_record = await session.get(
            GraphProjectionRecord,
            result.graph_projection_record_id,
        )

    await engine.dispose()

    assert result is not None
    assert refreshed_doc is not None
    assert refreshed_doc.status == "succeeded"
    assert chunk_count == 1
    assert index_record.status == StageStatus.FAILED.value
    assert "produced 0 chunks for 1 quality-approved chunks" in index_record.error
    assert result.graph_materialization["status"] == "skipped"
    assert (
        "produced 0 chunks for 1 quality-approved chunks"
        in result.graph_materialization["reason"]
    )
    assert result.graph_projection_record_id is not None
    assert graph_record is not None
    assert graph_record.status in {"skipped", "failed"}
    assert "produced 0 chunks for 1 quality-approved chunks" in graph_record.error
    assert separately_loaded_graph_record is not None
    assert separately_loaded_graph_record.status == "skipped"
    assert "produced 0 chunks for 1 quality-approved chunks" in separately_loaded_graph_record.error


@pytest.mark.asyncio
async def test_runtime_enrichment_failure_records_current_skipped_graph_state(
    tmp_path,
    database_url,
):
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine)

    class FakeDocumentParser:
        async def parse(self, document, options, *, on_mineru_status=None):
            return [
                AdapterChunk(
                    text="Sahih al-Bukhari contains 7277 hadith.",
                    source_location={"page": 1},
                    metadata={"parser_metadata": {"backend": "mineru"}},
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

    async with session_factory() as session:
        artifact = tmp_path / "bukhari-stale-graph.pdf"
        artifact.write_bytes(b"%PDF-1.4")
        document = Document(
            id="doc-bukhari-stale-graph",
            filename="hadith_bukhari_stale_graph.pdf",
            content_type="application/pdf",
            sha256="bukhari-stale-graph-sha",
            artifact_path=str(artifact),
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
        session.add(
            GraphProjectionRecord(
                document_id="doc-bukhari-stale-graph",
                runtime_profile_id="default",
                status="succeeded",
                graph_workspace_label="ragstudio_default",
                graph_storage_uri="bolt://old.example:7687",
                graph_storage_username="neo4j",
                node_count=7,
                edge_count=6,
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
            "doc-bukhari-stale-graph",
            options=IndexDocumentIn(parser_mode="mineru_strict"),
        )

        graph_records = (
            await session.execute(
                select(GraphProjectionRecord).where(
                    GraphProjectionRecord.document_id == "doc-bukhari-stale-graph"
                )
            )
        ).scalars().all()
        current_graph_record = await session.get(
            GraphProjectionRecord,
            result.graph_projection_record_id,
        )

    await engine.dispose()

    old_records = [
        record
        for record in graph_records
        if record.status == "stale" and record.node_count == 7 and record.edge_count == 6
    ]
    assert result is not None
    assert result.graph_projection_record_id is not None
    assert len(graph_records) == 2
    assert len(old_records) == 1
    assert current_graph_record is not None
    assert current_graph_record.id != old_records[0].id
    assert old_records[0].error == "Superseded by a newer indexing attempt."
    assert current_graph_record.status in {"skipped", "failed"}
    assert current_graph_record.node_count == 0
    assert current_graph_record.edge_count == 0
    assert "runtime enrichment unavailable" in current_graph_record.error


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
        session.add(
            Chunk(
                document_id=document.id,
                text="stale searchable chunk",
                source_location={"page": 1},
                metadata_json={},
            )
        )
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status="succeeded",
                index_shape={"kind": "stale"},
                chunk_count=1,
            )
        )
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
        chunk_count = (
            await session.execute(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == document.id)
            )
        ).scalar_one()
        index_count = (
            await session.execute(
                select(func.count())
                .select_from(IndexRecord)
                .where(IndexRecord.document_id == document.id)
            )
        ).scalar_one()

    await engine.dispose()

    assert refreshed_doc is not None
    assert refreshed_job is not None
    assert refreshed_doc.status == "failed"
    assert refreshed_job.status == "failed"
    assert refreshed_job.progress == 100
    assert "MinerU parse timed out" in refreshed_job.logs[-1]
    assert chunk_count == 0
    assert index_count == 0
    assert refreshed_job.result["mineru"]["job_id"] == "remote-123"
    assert refreshed_job.result["mineru"]["status"] == "running"
    assert refreshed_job.result["indexing_stage"] == {
        "stage": "failed",
        "label": "Failed",
        "detail": "MinerU parse timed out for job remote-123.",
        "progress": 100,
    }


@pytest.mark.asyncio
async def test_index_document_for_job_records_warning_when_graph_materialization_skips(
    tmp_path,
    database_url,
    monkeypatch,
):
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine)

    class LifecycleResult:
        chunks = [object()]
        graph_materialization = {
            "status": "skipped",
            "reason": "runtime enrichment unavailable",
        }

    async def fake_reindex_document(
        self,
        document_id,
        *,
        options=None,
        on_mineru_status=None,
        on_stage=None,
    ):
        return LifecycleResult()

    async with session_factory() as session:
        artifact = tmp_path / "quran.pdf"
        artifact.write_bytes(b"%PDF-1.4")
        document = Document(
            filename="quran_arabic_english.pdf",
            content_type="application/pdf",
            sha256="strict-skipped-warning-sha",
            artifact_path=str(artifact),
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
        await session.flush()
        job = Job(type="index_document", target_id=document.id, status="ready", progress=0)
        session.add(job)
        await session.commit()

        monkeypatch.setattr(
            IndexLifecycleService,
            "reindex_document",
            fake_reindex_document,
        )

        service = DocumentService(session, tmp_path, AppSettings(data_dir=tmp_path))
        await service._index_document_for_job(
            document,
            job,
            IndexDocumentIn(parser_mode="mineru_strict"),
        )
        await session.commit()

        refreshed_doc = await session.get(Document, document.id)
        refreshed_job = await session.get(Job, job.id)

    await engine.dispose()

    assert refreshed_doc is not None
    assert refreshed_job is not None
    assert refreshed_doc.status == "succeeded"
    assert refreshed_job.status == "succeeded"
    assert refreshed_job.result["warnings"] == ["runtime enrichment unavailable"]
    assert refreshed_job.result["indexing_stage"] == {
        "stage": "ready_with_warnings",
        "label": "Ready with warnings",
        "detail": "Indexed 1 chunks with warnings.",
        "progress": 100,
        "chunk_count": 1,
        "warning": "runtime enrichment unavailable",
    }
    assert "Ready with warnings: runtime enrichment unavailable" in refreshed_job.logs


@pytest.mark.asyncio
async def test_index_document_for_job_records_parser_quality_warning_summary(
    tmp_path,
    database_url,
    monkeypatch,
):
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine)

    warning = {
        "code": "reference_unit_missing_expected_script",
        "message": "Expected Arabic text in reference unit.",
        "block_type": "paragraph",
        "page": 1,
    }

    class OrmLikeChunk:
        extraction_quality = {"parser_warnings": [warning]}

    class LifecycleResult:
        chunks = [
            ChunkOut(
                id="chunk-parser-quality",
                document_id="doc-parser-quality-job",
                text="Chunk with parser quality warning.",
                source_location={"page": 1},
                metadata={"extraction_quality": {"parser_warnings": [warning]}},
            ),
            OrmLikeChunk(),
        ]
        graph_materialization = {
            "status": "pending",
            "node_count": 0,
            "edge_count": 0,
            "reason": None,
        }

    async def fake_reindex_document(
        self,
        document_id,
        *,
        options=None,
        on_mineru_status=None,
        on_stage=None,
    ):
        return LifecycleResult()

    async def fake_materialize_pending(self, document_id):
        return {
            "status": "succeeded",
            "node_count": 1,
            "edge_count": 0,
            "reason": None,
        }

    async with session_factory() as session:
        artifact = tmp_path / "parser-quality.pdf"
        artifact.write_bytes(b"%PDF-1.4")
        document = Document(
            id="doc-parser-quality-job",
            filename="parser-quality.pdf",
            content_type="application/pdf",
            sha256="parser-quality-job-sha",
            artifact_path=str(artifact),
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
        await session.flush()
        job = Job(type="index_document", target_id=document.id, status="ready", progress=0)
        session.add(job)
        await session.commit()

        monkeypatch.setattr(
            IndexLifecycleService,
            "reindex_document",
            fake_reindex_document,
        )
        monkeypatch.setattr(
            "ragstudio.services.document_service.GraphProjectionRunner.materialize_pending",
            fake_materialize_pending,
        )

        service = DocumentService(session, tmp_path, AppSettings(data_dir=tmp_path))
        await service._index_document_for_job(
            document,
            job,
            IndexDocumentIn(parser_mode="mineru_strict"),
        )
        await session.commit()

        refreshed_job = await session.get(Job, job.id)

    await engine.dispose()

    assert refreshed_job is not None
    assert refreshed_job.result["parser_quality"] == {
        "warning_counts": {"reference_unit_missing_expected_script": 2},
        "affected_chunks": 2,
    }
    parser_quality_details = refreshed_job.result["parser_quality_details"]
    assert parser_quality_details["groups"][0]["code"] == "reference_unit_missing_expected_script"
    assert parser_quality_details["groups"][0]["chunk_count"] == 2
    assert parser_quality_details["groups"][0]["warning_count"] == 2
    assert parser_quality_details["groups"][0]["block_types"] == {"paragraph": 2}
    assert parser_quality_details["groups"][0]["examples"][0] == {
        "chunk_id": "chunk-parser-quality",
        "page": 1,
        "reference": None,
        "block_type": "paragraph",
        "expected_script": None,
        "action": None,
        "message": "Expected Arabic text in reference unit.",
        "text_preview": "Chunk with parser quality warning.",
    }
    assert refreshed_job.result["indexing_stage"]["stage"] == "ready_with_warnings"
    assert refreshed_job.result["indexing_stage"]["warning"] == (
        "reference_unit_missing_expected_script=2"
    )
    assert (
        "Parser quality warnings: reference_unit_missing_expected_script=2"
        in refreshed_job.logs
    )


@pytest.mark.asyncio
async def test_index_document_for_job_keeps_combined_warning_entries_unique(
    tmp_path,
    database_url,
    monkeypatch,
):
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine)

    warning = {
        "code": "reference_unit_missing_expected_script",
        "message": "Expected Arabic text in reference unit.",
        "block_type": "paragraph",
        "page": 1,
    }

    class LifecycleResult:
        chunks = [
            ChunkOut(
                id="chunk-parser-quality-combined",
                document_id="doc-parser-quality-combined",
                text="Chunk with duplicate parser quality warnings.",
                source_location={"page": 1},
                metadata={
                    "extraction_quality": {
                        "parser_warnings": [
                            warning,
                            {**warning, "message": "Same warning code repeated."},
                        ]
                    }
                },
            )
        ]
        graph_materialization = {
            "status": "skipped",
            "node_count": 0,
            "edge_count": 0,
            "reason": "runtime enrichment unavailable",
        }

    async def fake_reindex_document(
        self,
        document_id,
        *,
        options=None,
        on_mineru_status=None,
        on_stage=None,
    ):
        return LifecycleResult()

    async with session_factory() as session:
        artifact = tmp_path / "parser-quality-combined.pdf"
        artifact.write_bytes(b"%PDF-1.4")
        document = Document(
            id="doc-parser-quality-combined",
            filename="parser-quality-combined.pdf",
            content_type="application/pdf",
            sha256="parser-quality-combined-sha",
            artifact_path=str(artifact),
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
        await session.flush()
        job = Job(type="index_document", target_id=document.id, status="ready", progress=0)
        session.add(job)
        await session.commit()

        monkeypatch.setattr(
            IndexLifecycleService,
            "reindex_document",
            fake_reindex_document,
        )

        service = DocumentService(session, tmp_path, AppSettings(data_dir=tmp_path))
        await service._index_document_for_job(
            document,
            job,
            IndexDocumentIn(parser_mode="mineru_strict"),
        )
        await session.commit()

        refreshed_job = await session.get(Job, job.id)

    await engine.dispose()

    parser_warning = "reference_unit_missing_expected_script=1"
    assert refreshed_job is not None
    assert refreshed_job.result["parser_quality"] == {
        "warning_counts": {"reference_unit_missing_expected_script": 1},
        "affected_chunks": 1,
    }
    assert refreshed_job.result["warnings"] == [
        "runtime enrichment unavailable",
        parser_warning,
    ]
    assert refreshed_job.result["indexing_stage"]["warning"] == (
        f"runtime enrichment unavailable; {parser_warning}"
    )
    assert refreshed_job.result["warnings"].count("runtime enrichment unavailable") == 1
    assert all(";" not in warning for warning in refreshed_job.result["warnings"])


@pytest.mark.asyncio
async def test_index_document_for_job_promotes_failed_graph_materialization_warning(
    tmp_path,
    database_url,
    monkeypatch,
):
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine)

    class LifecycleResult:
        chunks = [object()]
        graph_materialization = {
            "status": "pending",
            "node_count": 0,
            "edge_count": 0,
            "reason": None,
        }

    async def fake_reindex_document(
        self,
        document_id,
        *,
        options=None,
        on_mineru_status=None,
        on_stage=None,
    ):
        return LifecycleResult()

    async def fake_materialize_pending(self, document_id):
        return {
            "status": "failed",
            "node_count": 0,
            "edge_count": 0,
            "reason": "Neo4j projection failed",
        }

    async with session_factory() as session:
        artifact = tmp_path / "graph-failed.pdf"
        artifact.write_bytes(b"%PDF-1.4")
        document = Document(
            id="doc-graph-failed",
            filename="graph-failed.pdf",
            content_type="application/pdf",
            sha256="graph-failed-sha",
            artifact_path=str(artifact),
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
        await session.flush()
        job = Job(type="index_document", target_id=document.id, status="ready", progress=0)
        session.add(job)
        await session.commit()

        monkeypatch.setattr(
            IndexLifecycleService,
            "reindex_document",
            fake_reindex_document,
        )
        monkeypatch.setattr(
            "ragstudio.services.document_service.GraphProjectionRunner.materialize_pending",
            fake_materialize_pending,
        )

        service = DocumentService(session, tmp_path, AppSettings(data_dir=tmp_path))
        await service._index_document_for_job(
            document,
            job,
            IndexDocumentIn(parser_mode="mineru_strict"),
        )
        await session.commit()

        refreshed_job = await session.get(Job, job.id)

    await engine.dispose()

    assert refreshed_job is not None
    assert refreshed_job.result["warnings"] == ["Neo4j projection failed"]
    assert refreshed_job.result["indexing_stage"] == {
        "stage": "ready_with_warnings",
        "label": "Ready with warnings",
        "detail": "Indexed 1 chunks with warnings.",
        "progress": 100,
        "chunk_count": 1,
        "warning": "Neo4j projection failed",
    }
    assert "Ready with warnings: Neo4j projection failed" in refreshed_job.logs


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
    assert refreshed_job.result["indexing_stage"] == {
        "stage": "ready",
        "label": "Ready",
        "detail": "Indexed 3 chunks.",
        "progress": 100,
        "chunk_count": 3,
    }
    assert refreshed_job.result["mineru"]["job_id"] == "remote-ready"
    assert refreshed_job.result["mineru"]["status"] == "ready"


@pytest.mark.asyncio
async def test_run_index_job_merges_mineru_status_diagnostics(
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
            sha256="strict-merged-diagnostics-sha",
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
                        "jobId": "remote-validated",
                        "status": "processing",
                        "progress": 45,
                        "detail": "MinerU artifacts received.",
                        "updatedAt": "2026-05-11T08:30:00Z",
                    }
                )
                await on_mineru_status(
                    {
                        "jobId": "remote-validated",
                        "status": "validated",
                        "progress": 80,
                        "detail": "MinerU artifacts validated.",
                        "chunkCount": 12,
                        "characterCount": 34567,
                        "pageCount": 9,
                    }
                )
            return [object(), object()]

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
    assert refreshed_job.result["chunk_count"] == 2
    assert refreshed_job.result["mineru"] == {
        "job_id": "remote-validated",
        "status": "validated",
        "progress": 80,
        "detail": "MinerU artifacts validated.",
        "updated_at": "2026-05-11T08:30:00Z",
        "chunk_count": 12,
        "character_count": 34567,
        "page_count": 9,
    }


@pytest.mark.asyncio
async def test_run_index_job_marks_searchable_document_succeeded_when_enrichment_skips(
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
            sha256="strict-skipped-enrichment-sha",
            artifact_path=str(artifact),
            status="ready",
        )
        session.add(document)
        await session.flush()
        job = Job(type="index_document", target_id=document.id, status="ready", progress=0)
        session.add(job)
        await session.commit()

        async def fake_index_document_for_job(
            self,
            document,
            job,
            options=None,
            on_mineru_status=None,
        ):
            document.status = "succeeded"
            job.status = "succeeded"
            job.progress = 100
            job.result = {
                **job.result,
                "document_id": document.id,
                "chunk_count": 1,
                "graph_materialization": {
                    "status": "skipped",
                    "reason": "runtime enrichment unavailable",
                },
            }
            job.logs = [*job.logs, "Indexed 1 chunks."]

        monkeypatch.setattr(
            DocumentService,
            "_index_document_for_job",
            fake_index_document_for_job,
        )

        service = DocumentService(session, tmp_path)
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
    assert refreshed_doc.status == "succeeded"
    assert refreshed_job.status == "succeeded"
    assert refreshed_job.progress == 100
    assert refreshed_job.result["graph_materialization"]["status"] == "skipped"


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
