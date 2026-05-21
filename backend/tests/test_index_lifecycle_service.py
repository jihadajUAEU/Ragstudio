import json
import threading
from inspect import isawaitable
from pathlib import Path

import pytest
import pytest_asyncio
from ragstudio.db.models import Chunk, Document, GraphProjectionRecord, IndexRecord, SettingsProfile
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_persistence_service import ChunkPersistenceService
from ragstudio.services.graph_materialization_service import GraphMaterializationResult
from ragstudio.services.graph_projection_runner import (
    GraphProjectionCleanupError,
    GraphProjectionRunner,
)
from ragstudio.services.index_lifecycle_service import IndexLifecycleService
from ragstudio.services.layout_auto_repair import LayoutAutoRepairResult
from ragstudio.services.runtime_types import RuntimeChunk
from sqlalchemy import select


@pytest.fixture
def app(client):
    return client._transport.app


@pytest_asyncio.fixture
async def session(app):
    async with app.state.session_factory() as active_session:
        yield active_session


class FakeRuntime:
    def __init__(self, chunks: list[RuntimeChunk] | None = None):
        self.deleted: list[str] = []
        self.indexed_paths: list[str | Path] = []
        self.chunks = chunks or [
            RuntimeChunk(
                text="Runtime chunk",
                source_location={"page": 1},
                metadata={"score": 1.0},
                runtime_source_id="runtime-1",
                content_type="text",
                preview_ref="preview://runtime-1",
            )
        ]

    def capability_report(self):
        return {"active_backend": "runtime", "raganything_available": True}

    async def delete_document_index(self, document_id):
        self.deleted.append(document_id)

    async def index_document(self, artifact_path):
        self.indexed_paths.append(artifact_path)
        return self.chunks


class TransactionInspectingRuntime(FakeRuntime):
    def __init__(self, session):
        super().__init__()
        self.session = session
        self.in_transaction_during_delete: bool | None = None
        self.in_transaction_during_index: bool | None = None

    async def delete_document_index(self, document_id):
        self.in_transaction_during_delete = self.session.in_transaction()
        await super().delete_document_index(document_id)

    async def index_document(self, artifact_path):
        self.in_transaction_during_index = self.session.in_transaction()
        return await super().index_document(artifact_path)


class PreparsedRuntime(FakeRuntime):
    def __init__(self):
        super().__init__([])
        self.preparsed_paths: list[str | Path] = []
        self.preparsed_chunks = []

    async def index_document(self, artifact_path):
        raise AssertionError("runtime local parse must not be used for strict MinerU")

    async def index_preparsed_chunks(self, artifact_path, chunks, *, document_id):
        self.preparsed_paths.append(artifact_path)
        self.preparsed_chunks = chunks
        return [
            RuntimeChunk(
                text=chunks[0].text,
                source_location=chunks[0].source_location,
                metadata={"backend": "mineru", "document_id": document_id},
                runtime_source_id="mineru-preparsed-1",
                content_type="text",
            )
        ]


class FakeFactory:
    def __init__(self, runtime):
        self.runtime = runtime

    def build(self, profile):
        return self.runtime


class FakeHealthService:
    async def check(self, profile):
        return []

    def blocking_failures(self, checks):
        return []


class FakeDocumentParser:
    def __init__(
        self,
        chunks: list[AdapterChunk] | None = None,
        *,
        error: Exception | None = None,
        status_payload: dict | None = None,
    ):
        self.chunks = chunks or [
            AdapterChunk(
                text="Remote MinerU chunk",
                source_location={"page_start": 1, "page_end": 1},
                metadata={"parser_metadata": {"backend": "mineru"}},
            )
        ]
        self.error = error
        self.status_payload = status_payload
        self.calls = []

    async def parse(self, document, options, *, on_mineru_status=None):
        self.calls.append(
            {
                "document_id": document.id,
                "parser_mode": options.parser_mode,
                "has_status_callback": on_mineru_status is not None,
            }
        )
        if self.status_payload is not None and on_mineru_status is not None:
            await on_mineru_status(self.status_payload)
        if self.error is not None:
            raise self.error
        return self.chunks


class RecordingModalPreprocessor:
    def __init__(self) -> None:
        self.calls: list[list[AdapterChunk]] = []

    def preprocess(
        self,
        adapter_chunks: list[AdapterChunk],
        *,
        domain_metadata: DomainMetadata,
    ) -> list[AdapterChunk]:
        self.calls.append(adapter_chunks)
        return [
            AdapterChunk(
                text="router table text",
                source_location={
                    "artifact": "source_content_list.json",
                    "page_start": 1,
                    "page_end": 1,
                },
                metadata={
                    "modal_router_processed": True,
                    "modality": "table",
                    "structured_data": {"markdown": "| A |"},
                    "parser_metadata": {
                        "artifact_extract_dir": adapter_chunks[0].metadata["parser_metadata"][
                            "artifact_extract_dir"
                        ],
                        "content_list_ref": "source_content_list.json",
                    },
                },
                runtime_source_id=adapter_chunks[0].runtime_source_id,
            )
        ]


class RecordingLayoutAutoRepair:
    def __init__(self) -> None:
        self.calls: list[list[AdapterChunk]] = []

    def repair(self, adapter_chunks: list[AdapterChunk]) -> LayoutAutoRepairResult:
        self.calls.append(adapter_chunks)
        return LayoutAutoRepairResult(chunks=adapter_chunks, diagnostics=[])


class RecordingQualityGate:
    def __init__(self, report: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.report = report or {
            "index_quality_report": {
                "quality_report_version": 99,
                "preserved": {"nested": True},
            },
            "quality_repair": {
                "status": "preserved",
                "attempted": False,
            },
        }

    def validate_adapter_chunks(
        self,
        adapter_chunks: list[AdapterChunk],
        *,
        language: str,
        domain_metadata: DomainMetadata,
    ) -> dict:
        self.calls.append(
            {
                "chunks": adapter_chunks,
                "language": language,
                "domain_metadata": domain_metadata,
            }
        )
        return self.report


class SequenceQualityGate:
    def __init__(self, reports: list[dict]) -> None:
        self.reports = reports
        self.calls: list[list[AdapterChunk]] = []

    def validate_adapter_chunks(
        self,
        adapter_chunks: list[AdapterChunk],
        *,
        language: str,
        domain_metadata: DomainMetadata,
    ) -> dict:
        del language, domain_metadata
        self.calls.append(adapter_chunks)
        index = min(len(self.calls) - 1, len(self.reports) - 1)
        return self.reports[index]


class RecordingTargetedVisionRecovery:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def recover(self, chunks: list[AdapterChunk], *, config):
        self.calls.append({"chunks": chunks, "config": config})
        object.__setattr__(
            chunks[0],
            "text",
            f"{chunks[0].text}\n\nوحنانا من لدنا وزكاة وكان تقيا",
        )
        warning = chunks[0].metadata["extraction_quality"]["parser_warnings"][0]
        warning["severity"] = "info"
        warning["suppressed_from_counts"] = True
        warning["vision_recovery_status"] = "succeeded"
        warning["quality_gate_action"] = "accepted_recovery"
        request = chunks[0].metadata["quality_repair"]["targeted_vision_recovery_requests"][0]
        request["vision_recovery_status"] = "succeeded"
        return {
            "targeted_vision_recovery_requests": 1,
            "targeted_vision_recovery_attempted": 1,
            "targeted_vision_recovery_succeeded": 1,
            "targeted_vision_recovery_failed": 0,
            "targeted_vision_recovery_not_configured": 0,
            "targeted_vision_recovery_samples": [request],
        }



class FakeGraphMaterializationService:
    def __init__(
        self,
        *,
        result: GraphMaterializationResult | None = None,
        error: Exception | None = None,
    ):
        self.result = result or GraphMaterializationResult(
            status="succeeded",
            node_count=2,
            edge_count=1,
        )
        self.error = error
        self.calls = []
        self.delete_calls = []

    async def replace_document_graph(self, *, document_id, profile, chunks):
        call = {
            "document_id": document_id,
            "profile_id": profile.id,
            "neo4j_uri": getattr(profile, "neo4j_uri", None),
            "graph_workspace_label": getattr(profile, "graph_workspace_label", None),
            "chunk_count": len(chunks),
        }
        _add_auth_to_call(call, profile)
        self.calls.append(call)
        if self.error is not None:
            raise self.error
        return self.result

    async def delete_document_graph(self, *, document_id, profile):
        call = {
            "document_id": document_id,
            "profile_id": profile.id,
            "neo4j_uri": getattr(profile, "neo4j_uri", None),
            "graph_workspace_label": getattr(profile, "graph_workspace_label", None),
        }
        _add_auth_to_call(call, profile)
        self.delete_calls.append(call)
        if self.error is not None:
            raise self.error
        return self.result


class UriRoutedGraphMaterializationService(FakeGraphMaterializationService):
    def __init__(
        self,
        *,
        failed_uris: set[str] | None = None,
    ):
        super().__init__()
        self.failed_uris = failed_uris or set()

    async def delete_document_graph(self, *, document_id, profile):
        call = {
            "document_id": document_id,
            "profile_id": profile.id,
            "neo4j_uri": getattr(profile, "neo4j_uri", None),
            "graph_workspace_label": getattr(profile, "graph_workspace_label", None),
        }
        _add_auth_to_call(call, profile)
        self.delete_calls.append(call)
        if call["neo4j_uri"] in self.failed_uris:
            return GraphMaterializationResult(
                status="failed",
                node_count=0,
                edge_count=0,
                reason=f"{call['neo4j_uri']} unavailable",
            )
        return GraphMaterializationResult(
            status="succeeded",
            node_count=2,
            edge_count=1,
        )


class RunningStatusObservingGraphMaterializationService(FakeGraphMaterializationService):
    def __init__(self, session_factory, record_id: str):
        super().__init__()
        self.session_factory = session_factory
        self.record_id = record_id
        self.observed_cleanup_status: str | None = None

    async def delete_document_graph(self, *, document_id, profile):
        async with self.session_factory() as session:
            self.observed_cleanup_status = await session.scalar(
                select(GraphProjectionRecord.cleanup_status).where(
                    GraphProjectionRecord.id == self.record_id
                )
            )
        return await super().delete_document_graph(document_id=document_id, profile=profile)


def _add_auth_to_call(call: dict, profile) -> None:
    username = getattr(profile, "neo4j_username", None)
    password = getattr(profile, "neo4j_password", None)
    if username is not None:
        call["neo4j_username"] = username
    if password is not None:
        call["neo4j_password"] = password


def _quran_metadata() -> DomainMetadata:
    return DomainMetadata(
        domain="quran_tafseer",
        language="mixed",
        tags=["quran", "arabic", "english"],
        citation_style="surah_ayah",
        expected_structure="surah_ayah_sections",
        reference_pattern="surah_number:verse_number",
        script="arabic_english",
        custom_json={
            "reference_schema": {"type": "chapter_verse", "display": "{chapter}:{verse}"},
            "chunking": {"unit": "verse", "preserve_parallel_text": True},
        },
    )


@pytest.mark.asyncio
async def test_run_cpu_bound_offloads_sync_work_to_thread() -> None:
    service = IndexLifecycleService.__new__(IndexLifecycleService)
    event_loop_thread_id = threading.get_ident()

    def thread_id() -> int:
        return threading.get_ident()

    worker_thread_id = await service._run_cpu_bound(thread_id)

    assert worker_thread_id != event_loop_thread_id


@pytest.mark.asyncio
async def test_run_cpu_bound_awaits_awaitable_return() -> None:
    service = IndexLifecycleService.__new__(IndexLifecycleService)

    async def async_value() -> str:
        return "awaited"

    def returns_awaitable():
        return async_value()

    assert await service._run_cpu_bound(returns_awaitable) == "awaited"


@pytest.mark.asyncio
async def test_lifecycle_routes_layout_repair_and_quality_gate_through_cpu_helper(client):
    app = client._transport.app
    artifact_path = app.state.settings.data_dir / "cpu-helper-routing.pdf"
    artifact_path.write_text("runtime text", encoding="utf-8")
    parser_chunk = AdapterChunk(
        text="CPU helper routing chunk",
        source_location={"page_start": 1, "page_end": 1},
        metadata={"parser_metadata": {"backend": "mineru"}},
        runtime_source_id="runtime-cpu-helper",
    )
    layout_auto_repair = RecordingLayoutAutoRepair()
    quality_gate = RecordingQualityGate()
    runtime = PreparsedRuntime()

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="cpu-helper-routing.pdf",
            content_type="application/pdf",
            sha256="cpu-helper-routing",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()

        service = IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
            document_parser=FakeDocumentParser([parser_chunk]),
            layout_auto_repair=layout_auto_repair,
            quality_gate=quality_gate,
        )
        cpu_helper_calls: list[dict] = []

        async def recording_cpu_helper(func, *args, **kwargs):
            cpu_helper_calls.append({"func": func, "args": args, "kwargs": kwargs})
            result = func(*args, **kwargs)
            if isawaitable(result):
                return await result
            return result

        service._run_cpu_bound = recording_cpu_helper

        result = await service.reindex_document(
            document.id,
            options=IndexDocumentIn(parser_mode="mineru_strict"),
        )
        index_record = await session.scalar(
            select(IndexRecord).where(IndexRecord.document_id == document.id)
        )

    assert result is not None
    assert layout_auto_repair.calls
    assert quality_gate.calls
    assert any(call["func"] == layout_auto_repair.repair for call in cpu_helper_calls)
    assert any(call["func"] == quality_gate.validate_adapter_chunks for call in cpu_helper_calls)
    quality_call = next(
        call for call in cpu_helper_calls if call["func"] == quality_gate.validate_adapter_chunks
    )
    assert quality_call["kwargs"]["language"] == "unknown"
    assert isinstance(quality_call["kwargs"]["domain_metadata"], DomainMetadata)
    assert index_record is not None
    assert index_record.index_shape["index_quality_report"] == quality_gate.report[
        "index_quality_report"
    ]
    assert index_record.index_shape["quality_repair_report"] == quality_gate.report[
        "quality_repair"
    ]
    assert index_record.index_shape["quality_report_version"] == 99


@pytest.mark.asyncio
async def test_lifecycle_deletes_existing_chunks_and_mirrors_runtime_chunks(client):
    app = client._transport.app
    runtime = FakeRuntime()
    artifact_path = app.state.settings.data_dir / "doc.txt"
    artifact_path.write_text("runtime text", encoding="utf-8")

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="doc.txt",
            content_type="text/plain",
            sha256="abc",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="old",
                source_location={},
                metadata_json={},
            )
        )
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id="old-profile",
                status=StageStatus.SUCCEEDED.value,
                index_shape={},
                chunk_count=1,
            )
        )
        session.add(
            GraphProjectionRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status="succeeded",
                graph_workspace_label="ragstudio_default",
                graph_storage_uri="bolt://neo4j.test:7687",
                node_count=2,
                edge_count=1,
            )
        )
        await session.commit()

        chunks = await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
        ).reindex_document(
            document.id,
            options=IndexDocumentIn(parser_mode="mineru_strict"),
        )

        remaining = await session.execute(select(Chunk).where(Chunk.document_id == document.id))
        stored = remaining.scalars().all()
        records = (
            await session.execute(select(IndexRecord).where(IndexRecord.document_id == document.id))
        ).scalars().all()
        projection_records = (
            await session.execute(
                select(GraphProjectionRecord).where(
                    GraphProjectionRecord.document_id == document.id
                )
            )
        ).scalars().all()
        refreshed_document = await session.get(Document, document.id)

    assert runtime.deleted == [document.id]
    assert runtime.indexed_paths == [str(artifact_path)]
    assert chunks is not None
    assert [chunk.text for chunk in chunks] == ["Runtime chunk"]
    assert len(stored) == 1
    assert stored[0].metadata_json["mirrored_snapshot"] is True
    assert stored[0].metadata_json["document_id"] == document.id
    assert stored[0].runtime_profile_id == "default"
    assert stored[0].runtime_source_id == "runtime-1"
    assert stored[0].content_type == "text"
    assert stored[0].preview_ref == "preview://runtime-1"
    assert stored[0].indexed_at is not None
    assert len(records) == 1
    assert records[0].runtime_profile_id == "default"
    assert records[0].chunk_count == 1
    assert len(projection_records) == 2
    projection_by_id = {record.id: record for record in projection_records}
    pending_projection = projection_by_id[chunks.graph_projection_record_id]
    assert pending_projection.runtime_profile_id == "default"
    assert pending_projection.status == "pending"
    assert pending_projection.graph_workspace_label == "ragstudio_default"
    assert pending_projection.node_count == 0
    assert pending_projection.edge_count == 0
    assert chunks.graph_materialization == {
        "status": "pending",
        "node_count": 0,
        "edge_count": 0,
        "reason": None,
    }
    assert refreshed_document is not None
    assert refreshed_document.status == StageStatus.SUCCEEDED.value


@pytest.mark.asyncio
async def test_lifecycle_does_not_snapshot_neo4j_password(client):
    app = client._transport.app
    runtime = FakeRuntime()
    artifact_path = app.state.settings.data_dir / "graph-no-password.txt"
    artifact_path.write_text("Graph password snapshot", encoding="utf-8")

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
                neo4j_username="neo4j",
                neo4j_password="do-not-copy",
            )
        )
        document = Document(
            filename="graph-no-password.txt",
            content_type="text/plain",
            sha256="graph-no-password",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.flush()

        result = await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
        ).reindex_document(document.id)

        projection_record = await session.scalar(
            select(GraphProjectionRecord).where(GraphProjectionRecord.document_id == document.id)
        )

    assert result is not None
    assert projection_record is not None
    assert projection_record.graph_storage_uri == "bolt://neo4j.test:7687"
    assert projection_record.graph_storage_username == "neo4j"
    assert projection_record.graph_storage_password is None


@pytest.mark.asyncio
async def test_lifecycle_releases_studio_transaction_before_runtime_storage_work(client):
    app = client._transport.app
    artifact_path = app.state.settings.data_dir / "transaction-release.txt"
    artifact_path.write_text("runtime text", encoding="utf-8")

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="transaction-release.txt",
            content_type="text/plain",
            sha256="transaction-release",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()

        runtime = TransactionInspectingRuntime(session)

        await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
        ).reindex_document(
            document.id,
            options=IndexDocumentIn(parser_mode="mineru_strict"),
        )

    assert runtime.in_transaction_during_delete is False
    assert runtime.in_transaction_during_index is False


@pytest.mark.asyncio
async def test_lifecycle_falls_back_to_runtime_index_when_preparse_is_unsupported(client):
    app = client._transport.app
    runtime = FakeRuntime()
    artifact_path = app.state.settings.data_dir / "unsupported-preparse-runtime.pdf"
    artifact_path.write_text("runtime text", encoding="utf-8")

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="unsupported-preparse-runtime.pdf",
            content_type="application/pdf",
            sha256="unsupported-preparse-runtime",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()

        chunks = await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
        ).reindex_document(
            document.id,
            options=IndexDocumentIn(parser_mode="mineru_strict"),
        )

    assert runtime.deleted == [document.id]
    assert runtime.indexed_paths == [str(artifact_path)]
    assert chunks is not None
    assert [chunk.text for chunk in chunks] == ["Runtime chunk"]


@pytest.mark.asyncio
async def test_lifecycle_uses_preparsed_mineru_chunks_for_strict_runtime_reindex(
    client,
    monkeypatch,
):
    app = client._transport.app
    artifact_path = app.state.settings.data_dir / "strict-mineru-runtime.pdf"
    artifact_path.write_text("runtime text", encoding="utf-8")

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="strict-mineru-runtime.pdf",
            content_type="application/pdf",
            sha256="strict-mineru-runtime",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()

        document_parser = FakeDocumentParser()
        runtime = PreparsedRuntime()

        chunks = await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
            document_parser=document_parser,
        ).reindex_document(
            document.id,
            options=IndexDocumentIn(parser_mode="mineru_strict"),
        )

    assert runtime.preparsed_paths == [str(artifact_path)]
    assert document_parser.calls == [
        {
            "document_id": document.id,
            "parser_mode": "mineru_strict",
            "has_status_callback": False,
        }
    ]
    assert chunks is not None
    assert [chunk.text for chunk in chunks] == ["Remote MinerU chunk"]


@pytest.mark.asyncio
async def test_reindex_document_runs_targeted_recovery_before_persisting_chunks(
    session,
    app,
    tmp_path,
):
    artifact_path = tmp_path / "targeted-recovery.pdf"
    artifact_path.write_bytes(b"%PDF-1.4\n")
    document = Document(
        id="doc-targeted-recovery",
        filename="targeted-recovery.pdf",
        content_type="application/pdf",
        artifact_path=str(artifact_path),
        sha256="targeted-recovery",
        status=StageStatus.SUCCEEDED.value,
    )
    session.add_all(
        [
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                mineru_enabled=True,
                mineru_base_url="http://mineru.test",
                vision_model="vision-ocr",
                vision_base_url="http://vision.test/v1",
            ),
            document,
        ]
    )
    await session.commit()

    parser_chunk = AdapterChunk(
        text="[19:13] And affection from Us and purity.",
        source_location={"page_start": 1, "page_end": 1},
        metadata={
            "extraction_quality": {
                "parser_warnings": [
                    {
                        "code": "reference_unit_missing_expected_script",
                        "reference": "19:13",
                        "expected_script": "arabic",
                    }
                ]
            },
            "quality_repair": {
                "targeted_vision_recovery_requests": [
                    {
                        "reference": "19:13",
                        "missing_scripts": ["arabic"],
                        "page_start": 1,
                        "page_end": 1,
                    }
                ]
            },
        },
    )
    quality_gate = SequenceQualityGate(
        [
            {
                "index_quality_report": {"status": "ready_with_warnings"},
                "quality_repair": {"targeted_vision_recovery_requests": 1},
            },
            {
                "index_quality_report": {"status": "passed"},
                "quality_repair": {"targeted_vision_recovery_requests": 1},
            },
        ]
    )
    targeted_recovery = RecordingTargetedVisionRecovery()

    result = await IndexLifecycleService(
        session,
        app.state.settings,
        runtime_factory=FakeFactory(PreparsedRuntime()),
        health_service=FakeHealthService(),
        document_parser=FakeDocumentParser([parser_chunk]),
        quality_gate=quality_gate,
        targeted_vision_recovery=targeted_recovery,
    ).reindex_document(
        document.id,
        options=IndexDocumentIn(
            domain_metadata=DomainMetadata(
                custom_json={"vision_recovery_policy": {"enabled": True}}
            )
        ),
    )

    assert result is not None
    assert len(quality_gate.calls) == 2
    assert targeted_recovery.calls
    assert targeted_recovery.calls[0]["config"].model == "vision-ocr"
    stored_chunks = (
        await session.execute(select(Chunk).where(Chunk.document_id == document.id))
    ).scalars().all()
    assert len(stored_chunks) == 1
    assert "وحنانا من لدنا" in stored_chunks[0].text
    index_record = (
        await session.execute(select(IndexRecord).where(IndexRecord.document_id == document.id))
    ).scalar_one()
    quality_report = index_record.index_shape["quality_repair_report"]
    assert quality_report["targeted_vision_recovery_succeeded"] == 1


@pytest.mark.asyncio
async def test_reindex_document_applies_modal_preprocessor(session, app, tmp_path):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "type": "table",
                    "table_caption": ["Scores"],
                    "table_body": [["Name", "Score"], ["A", "9"]],
                    "page_idx": 0,
                }
            ]
        ),
        encoding="utf-8",
    )
    artifact_path = tmp_path / "modal.pdf"
    artifact_path.write_bytes(b"%PDF-1.4\n")

    document = Document(
        id="doc-modal-production",
        filename="modal.pdf",
        content_type="application/pdf",
        artifact_path=str(artifact_path),
        sha256="abc123",
        status=StageStatus.SUCCEEDED.value,
    )
    session.add_all(
        [
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                mineru_enabled=True,
                mineru_base_url="http://mineru.test",
            ),
            document,
        ]
    )
    await session.commit()

    parser_chunk = AdapterChunk(
        text="raw parser placeholder",
        source_location={"artifact": "source.md"},
        metadata={
            "parser_metadata": {
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "parser_mode": "mineru_strict",
            }
        },
        runtime_source_id="runtime-modal",
    )
    runtime = PreparsedRuntime()

    result = await IndexLifecycleService(
        session,
        app.state.settings,
        runtime_factory=FakeFactory(runtime),
        health_service=FakeHealthService(),
        document_parser=FakeDocumentParser([parser_chunk]),
    ).reindex_document(
        document.id,
        options=IndexDocumentIn(domain_metadata=DomainMetadata(domain="general")),
    )

    assert result is not None
    assert runtime.preparsed_chunks
    first_chunk = runtime.preparsed_chunks[0]
    assert first_chunk.metadata["modal_router_processed"] is True
    assert first_chunk.metadata["modality"] == "table"
    assert first_chunk.metadata["page"] == 1
    assert first_chunk.source_location["page_start"] == 1
    assert first_chunk.source_location["page_end"] == 1


@pytest.mark.asyncio
async def test_reindex_document_uses_injected_modal_preprocessor(session, app, tmp_path):
    artifact_path = tmp_path / "modal.pdf"
    artifact_path.write_bytes(b"%PDF-1.4\n")
    document = Document(
        id="doc-modal-injected",
        filename="modal.pdf",
        content_type="application/pdf",
        artifact_path=str(artifact_path),
        sha256="modal-injected",
        status=StageStatus.SUCCEEDED.value,
    )
    session.add_all(
        [
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                mineru_enabled=True,
                mineru_base_url="http://mineru.test",
            ),
            document,
        ]
    )
    await session.commit()

    parser_chunk = AdapterChunk(
        text="raw parser placeholder",
        source_location={"artifact": "source.md"},
        metadata={
            "parser_metadata": {
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "parser_mode": "mineru_strict",
            }
        },
        runtime_source_id="runtime-modal",
    )
    modal_preprocessor = RecordingModalPreprocessor()
    runtime = PreparsedRuntime()

    result = await IndexLifecycleService(
        session,
        app.state.settings,
        runtime_factory=FakeFactory(runtime),
        health_service=FakeHealthService(),
        document_parser=FakeDocumentParser([parser_chunk]),
        modal_preprocessor=modal_preprocessor,
    ).reindex_document(
        document.id,
        options=IndexDocumentIn(domain_metadata=DomainMetadata(domain="general")),
    )

    assert result is not None
    assert len(modal_preprocessor.calls) == 1
    assert runtime.preparsed_chunks[0].metadata["modal_router_processed"] is True
    assert runtime.preparsed_chunks[0].metadata["modality"] == "table"


@pytest.mark.asyncio
async def test_reindex_document_applies_layout_auto_repair_before_runtime_materialization(
    session,
    app,
    tmp_path,
):
    artifact_path = tmp_path / "layout-repair.pdf"
    artifact_path.write_bytes(b"%PDF-1.4\n")
    document = Document(
        id="doc-layout-repair",
        filename="layout-repair.pdf",
        content_type="application/pdf",
        artifact_path=str(artifact_path),
        sha256="layout-repair",
        status=StageStatus.SUCCEEDED.value,
    )
    session.add_all(
        [
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            ),
            document,
        ]
    )
    await session.commit()

    parser_chunk = AdapterChunk(
        text="Layout repair chunk",
        source_location={"page_start": 3, "page_end": 2, "page": 3},
        metadata={"parser_metadata": {"backend": "mineru"}},
        runtime_source_id="runtime-layout-repair",
    )
    runtime = PreparsedRuntime()

    result = await IndexLifecycleService(
        session,
        app.state.settings,
        runtime_factory=FakeFactory(runtime),
        health_service=FakeHealthService(),
        document_parser=FakeDocumentParser([parser_chunk]),
    ).reindex_document(
        document.id,
        options=IndexDocumentIn(parser_mode="mineru_strict"),
    )

    index_record = await session.scalar(
        select(IndexRecord).where(IndexRecord.document_id == document.id)
    )

    assert result is not None
    assert runtime.preparsed_chunks[0].source_location == {"page_start": 2, "page_end": 3}
    assert runtime.preparsed_chunks[0].metadata["layout_auto_repair"]["diagnostics"][0][
        "code"
    ] == "page_range_reordered"
    assert index_record is not None
    assert index_record.index_shape["layout_auto_repair_report"]["repaired_count"] == 1


@pytest.mark.asyncio
async def test_reindex_document_assembles_canonical_references_before_modal_preprocessing(
    session,
    app,
    tmp_path,
):
    arabic_body = "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644 \u0627\u0644\u0644\u0647"
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "Sunan Ibn Majah", "page_idx": 0},
                {"type": "text", "text": "Book 1, Hadith 1", "page_idx": 1},
                {"type": "text", "text": arabic_body, "page_idx": 1},
                {
                    "type": "text",
                    "text": "The Messenger of Allah said a short narration.",
                    "page_idx": 1,
                },
                {"type": "text", "text": "Book 1, Hadith 2", "page_idx": 1},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    artifact_path = tmp_path / "hadith.pdf"
    artifact_path.write_bytes(b"%PDF-1.4\n")

    document = Document(
        id="doc-canonical-lifecycle",
        filename="hadith.pdf",
        content_type="application/pdf",
        artifact_path=str(artifact_path),
        sha256="canonical-lifecycle",
        status=StageStatus.SUCCEEDED.value,
    )
    session.add_all(
        [
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                mineru_enabled=True,
                mineru_base_url="http://mineru.test",
            ),
            document,
        ]
    )
    await session.commit()

    parser_chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "parser_mode": "mineru_strict",
            }
        },
        runtime_source_id="runtime-canonical",
    )
    runtime = PreparsedRuntime()
    metadata = DomainMetadata(
        domain="hadith",
        document_type="collection",
        tags=["hadith", "arabic", "english"],
        script="mixed",
        custom_json={
            "reference_schema": {
                "type": "book_hadith",
                "display": "Book {book}, Hadith {hadith}",
                "canonical_ref_template": "book:{book}:hadith:{hadith}",
            },
            "chunking": {"unit": "hadith", "preserve_parallel_text": True},
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
                "carry_forward_body_blocks": True,
                "header_only_policy": "provenance_only",
                "continuation_policy": "until_next_reference",
                "max_page_gap": 2,
                "require_single_reference_per_answerable_chunk": True,
            },
            "provenance": {"preserve_original_blocks": True},
            "quality_policy": {
                "required_scripts": ["arabic"],
                "optional_scripts": ["latin"],
                "required_scripts_by_unit_role": {"hadith": ["arabic"]},
                "optional_scripts_by_unit_role": {"hadith": ["latin"]},
                "missing_optional_script_action": "no_warning",
                "missing_required_script_action": "warn",
                "materialization_policy": "allow_if_required_scripts_present",
            },
        },
    )

    result = await IndexLifecycleService(
        session,
        app.state.settings,
        runtime_factory=FakeFactory(runtime),
        health_service=FakeHealthService(),
        document_parser=FakeDocumentParser([parser_chunk]),
    ).reindex_document(
        document.id,
        options=IndexDocumentIn(parser_mode="mineru_strict", domain_metadata=metadata),
    )

    assert result is not None
    assert runtime.preparsed_chunks
    first_chunk = runtime.preparsed_chunks[0]
    assert "Book 1, Hadith 1" in first_chunk.text
    assert arabic_body in first_chunk.text
    assert "The Messenger of Allah" in first_chunk.text
    assert first_chunk.metadata["reference_metadata"]["references"] == [
        "book:1:hadith:1"
    ]
    assert first_chunk.metadata.get("modal_router_processed") is None
    assert "reference_unit_missing_expected_script" not in {
        warning["code"]
        for warning in first_chunk.metadata.get("extraction_quality", {}).get(
            "parser_warnings", []
        )
    }


@pytest.mark.asyncio
async def test_lifecycle_filters_quarantined_reference_from_preparsed_runtime_index(client):
    app = client._transport.app
    artifact_path = app.state.settings.data_dir / "quality-filter-runtime.pdf"
    artifact_path.write_text("runtime text", encoding="utf-8")

    parser_chunks = [
        AdapterChunk(
            text=(
                "[19:12] \u064a\u0627 \u064a\u062d\u064a\u0649 "
                "\u062e\u0630 \u0627\u0644\u0643\u062a\u0627\u0628 "
                "O John, take the Scripture."
            ),
            source_location={"page": 312},
            metadata={"reference_metadata": {"references": ["19:12"]}},
        ),
        AdapterChunk(
            text="[19:13] And affection from Us and purity, and he was fearing of Allah.",
            source_location={"page": 312},
            metadata={"reference_metadata": {"references": ["19:13"]}},
        ),
    ]

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="quality-filter-runtime.pdf",
            content_type="application/pdf",
            sha256="quality-filter-runtime",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()

        runtime = PreparsedRuntime()
        result = await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
            document_parser=FakeDocumentParser(parser_chunks),
        ).reindex_document(
            document.id,
            options=IndexDocumentIn(
                parser_mode="mineru_strict",
                domain_metadata=_quran_metadata(),
            ),
        )

        stored_chunks = (
            await session.execute(select(Chunk).where(Chunk.document_id == document.id))
        ).scalars().all()
        index_record = await session.scalar(
            select(IndexRecord).where(IndexRecord.document_id == document.id)
        )

    assert result is not None
    assert [chunk.text for chunk in runtime.preparsed_chunks] == [parser_chunks[0].text]
    assert len(stored_chunks) == 2
    blocked = next(chunk for chunk in stored_chunks if "19:13" in chunk.text)
    assert blocked.metadata_json["quality_action_policy"]["index_vector"] is False
    assert blocked.tokens_ar == []
    assert index_record is not None
    report = index_record.index_shape["index_quality_report"]
    references = {item["reference"]: item for item in report["references"]}
    assert references["19:13"]["materialization"]["index_vector"] is False


@pytest.mark.asyncio
async def test_lifecycle_marks_runtime_failed_when_all_references_are_quarantined(client):
    app = client._transport.app
    artifact_path = app.state.settings.data_dir / "quality-all-blocked-runtime.pdf"
    artifact_path.write_text("runtime text", encoding="utf-8")

    parser_chunks = [
        AdapterChunk(
            text=(
                "[19:13] \u0648\u062d\u0646\u0627\u0646\u0627 "
                "\u0645\u0646 \u0644\u062f\u0646\u0627"
            ),
            source_location={"page": 312},
            metadata={"reference_metadata": {"references": ["19:13"]}},
        )
    ]

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="quality-all-blocked-runtime.pdf",
            content_type="application/pdf",
            sha256="quality-all-blocked-runtime",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()

        runtime = PreparsedRuntime()
        result = await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
            document_parser=FakeDocumentParser(parser_chunks),
        ).reindex_document(
            document.id,
            options=IndexDocumentIn(
                parser_mode="mineru_strict",
                domain_metadata=_quran_metadata(),
            ),
        )
        index_record = await session.scalar(
            select(IndexRecord).where(IndexRecord.document_id == document.id)
        )
        projection_record = await session.get(
            GraphProjectionRecord,
            result.graph_projection_record_id,
        )

    assert runtime.preparsed_paths == []
    assert index_record is not None
    assert index_record.status == StageStatus.FAILED.value
    assert index_record.error == "No chunks passed the runtime materialization quality gate."
    assert projection_record is not None
    assert projection_record.status == "skipped"
    assert result.graph_materialization == {
        "status": "skipped",
        "node_count": 0,
        "edge_count": 0,
        "reason": "No chunks passed the runtime materialization quality gate.",
    }


@pytest.mark.asyncio
async def test_lifecycle_cleans_nonpreparsed_native_index_when_quality_blocks_all(client):
    app = client._transport.app
    artifact_path = app.state.settings.data_dir / "quality-native-cleanup.pdf"
    artifact_path.write_text("runtime text", encoding="utf-8")

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="quality-native-cleanup.pdf",
            content_type="application/pdf",
            sha256="quality-native-cleanup",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()

        runtime = FakeRuntime(
            [
                RuntimeChunk(
                    text=(
                        "[19:13] \u0648\u062d\u0646\u0627\u0646\u0627 "
                        "\u0645\u0646 \u0644\u062f\u0646\u0627"
                    ),
                    source_location={"page": 312},
                    metadata={
                        "quality_action_policy": {
                            "persist_chunk": True,
                            "index_vector": False,
                            "index_exact_arabic": False,
                            "project_graph": False,
                            "graph_confidence": "blocked",
                            "quality_flags": ["missing_expected_script:arabic"],
                        },
                        "reference_metadata": {"references": ["19:13"]},
                    },
                    runtime_source_id="runtime-blocked",
                    content_type="text",
                )
            ]
        )
        result = await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
        ).reindex_document(
            document.id,
            options=IndexDocumentIn(
                parser_mode="mineru_strict",
                domain_metadata=_quran_metadata(),
            ),
        )
        index_record = await session.scalar(
            select(IndexRecord).where(IndexRecord.document_id == document.id)
        )

    assert runtime.indexed_paths == [str(artifact_path)]
    assert runtime.deleted == [document.id, document.id]
    assert index_record is not None
    assert index_record.status == StageStatus.FAILED.value
    assert index_record.error == "No chunks passed the runtime materialization quality gate."
    assert result.graph_materialization == {
        "status": "skipped",
        "node_count": 0,
        "edge_count": 0,
        "reason": "No chunks passed the runtime materialization quality gate.",
    }


@pytest.mark.asyncio
async def test_lifecycle_creates_pending_graph_projection_before_runtime_enrichment(client):
    app = client._transport.app
    artifact_path = app.state.settings.data_dir / "pending-before-runtime.pdf"
    artifact_path.write_text("runtime text", encoding="utf-8")

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="pending-before-runtime.pdf",
            content_type="application/pdf",
            sha256="pending-before-runtime",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()

        runtime = PreparsedRuntime()
        result = await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
            document_parser=FakeDocumentParser(),
        ).reindex_document(
            document.id,
            options=IndexDocumentIn(parser_mode="mineru_strict"),
        )

        projection_record = await session.get(
            GraphProjectionRecord,
            result.graph_projection_record_id,
        )

    assert result is not None
    assert runtime.preparsed_paths == [str(artifact_path)]
    assert runtime.preparsed_chunks
    assert projection_record is not None
    assert projection_record.status == "pending"
    assert result.graph_materialization == {
        "status": "pending",
        "node_count": 0,
        "edge_count": 0,
        "reason": None,
    }


@pytest.mark.asyncio
async def test_lifecycle_marks_pending_graph_projection_skipped_when_persistence_fails(
    client,
    monkeypatch,
):
    app = client._transport.app
    artifact_path = app.state.settings.data_dir / "pending-persist-fails.pdf"
    artifact_path.write_text("runtime text", encoding="utf-8")
    runtime = PreparsedRuntime()

    async def failing_persist(self, *args, **kwargs):
        raise RuntimeError("canonical chunk write failed")

    monkeypatch.setattr(ChunkPersistenceService, "persist", failing_persist)

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="pending-persist-fails.pdf",
            content_type="application/pdf",
            sha256="pending-persist-fails",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()
        document_id = document.id

        with pytest.raises(RuntimeError, match="canonical chunk write failed"):
            await IndexLifecycleService(
                session,
                app.state.settings,
                runtime_factory=FakeFactory(runtime),
                health_service=FakeHealthService(),
                document_parser=FakeDocumentParser(),
            ).reindex_document(
                document_id,
                options=IndexDocumentIn(parser_mode="mineru_strict"),
            )

    async with app.state.session_factory() as session:
        projection_record = await session.scalar(
            select(GraphProjectionRecord).where(
                GraphProjectionRecord.document_id == document_id
            )
        )

    assert projection_record is not None
    assert projection_record.status == "skipped"
    assert projection_record.node_count == 0
    assert projection_record.edge_count == 0
    assert runtime.preparsed_paths == []
    assert runtime.deleted == [document_id]
    assert "Canonical chunk persistence failed: canonical chunk write failed" in (
        projection_record.error or ""
    )


@pytest.mark.asyncio
async def test_lifecycle_cleans_preparsed_runtime_index_when_runtime_branch_skips(client):
    app = client._transport.app
    artifact_path = app.state.settings.data_dir / "preparsed-runtime-skips.pdf"
    artifact_path.write_text("runtime text", encoding="utf-8")

    class FailingPreparsedRuntime(PreparsedRuntime):
        async def index_preparsed_chunks(self, artifact_path, chunks, *, document_id):
            self.preparsed_paths.append(artifact_path)
            self.preparsed_chunks = chunks
            raise RuntimeError("native partial write failed")

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="preparsed-runtime-skips.pdf",
            content_type="application/pdf",
            sha256="preparsed-runtime-skips",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()

        runtime = FailingPreparsedRuntime()
        result = await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
            document_parser=FakeDocumentParser(),
        ).reindex_document(
            document.id,
            options=IndexDocumentIn(parser_mode="mineru_strict"),
        )
        index_record = await session.scalar(
            select(IndexRecord).where(IndexRecord.document_id == document.id)
        )
        projection_record = await session.get(
            GraphProjectionRecord,
            result.graph_projection_record_id,
        )

    assert runtime.preparsed_paths == [str(artifact_path)]
    assert runtime.deleted == [document.id, document.id]
    assert index_record is not None
    assert index_record.status == StageStatus.FAILED.value
    assert index_record.error == "native partial write failed"
    assert projection_record is not None
    assert projection_record.status == "skipped"
    assert result.graph_materialization == {
        "status": "skipped",
        "node_count": 0,
        "edge_count": 0,
        "reason": "native partial write failed",
    }


@pytest.mark.asyncio
async def test_lifecycle_preserves_runtime_index_when_strict_mineru_parse_fails(
    client,
    monkeypatch,
):
    app = client._transport.app
    artifact_path = app.state.settings.data_dir / "strict-mineru-fails.pdf"
    artifact_path.write_text("runtime text", encoding="utf-8")

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="strict-mineru-fails.pdf",
            content_type="application/pdf",
            sha256="strict-mineru-fails",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()

        document_parser = FakeDocumentParser(error=RuntimeError("remote MinerU failed"))
        runtime = PreparsedRuntime()

        with pytest.raises(RuntimeError, match="remote MinerU failed"):
            await IndexLifecycleService(
                session,
                app.state.settings,
                runtime_factory=FakeFactory(runtime),
                health_service=FakeHealthService(),
                document_parser=document_parser,
            ).reindex_document(
                document.id,
                options=IndexDocumentIn(parser_mode="mineru_strict"),
            )

    assert runtime.deleted == []
    assert runtime.preparsed_paths == []


@pytest.mark.asyncio
async def test_lifecycle_forwards_runtime_mineru_status_callback(client, monkeypatch):
    app = client._transport.app
    artifact_path = app.state.settings.data_dir / "strict-mineru-progress.pdf"
    artifact_path.write_text("runtime text", encoding="utf-8")
    statuses = []

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="strict-mineru-progress.pdf",
            content_type="application/pdf",
            sha256="strict-mineru-progress",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()

        async def collect_status(status):
            statuses.append(status)

        document_parser = FakeDocumentParser(
            status_payload={"status": "running", "progress": 42},
        )

        await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(PreparsedRuntime()),
            health_service=FakeHealthService(),
            document_parser=document_parser,
        ).reindex_document(
            document.id,
            options=IndexDocumentIn(parser_mode="mineru_strict"),
            on_mineru_status=collect_status,
        )

    assert statuses == [{"status": "running", "progress": 42}]


@pytest.mark.asyncio
async def test_lifecycle_splits_oversized_runtime_chunks(client):
    app = client._transport.app
    runtime = FakeRuntime(
        [
            RuntimeChunk(
                text=" ".join(f"runtime{index}" for index in range(3100)),
                source_location={"artifact": "runtime.md"},
                metadata={"backend": "runtime", "chunk_index": 0},
                runtime_source_id="runtime-large",
                content_type="text",
                preview_ref="preview://runtime-large",
            )
        ]
    )
    artifact_path = app.state.settings.data_dir / "large-runtime.txt"
    artifact_path.write_text("runtime text", encoding="utf-8")

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="large-runtime.txt",
            content_type="text/plain",
            sha256="runtime-large",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()

        chunks = await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
        ).reindex_document(
            document.id,
            options=IndexDocumentIn(
                parser_mode="mineru_strict",
                domain_metadata={"domain": "generic", "document_type": "document"},
            ),
        )

        stored = (
            await session.execute(select(Chunk).where(Chunk.document_id == document.id))
        ).scalars().all()
        record = (
            await session.execute(select(IndexRecord).where(IndexRecord.document_id == document.id))
        ).scalar_one()

    assert chunks is not None
    assert len(chunks) == 3
    assert len(stored) == 3
    assert record.chunk_count == 3
    assert [len(chunk.text.split()) for chunk in chunks] == [1500, 1500, 100]
    assert chunks[0].metadata["domain_metadata"]["domain"] == "generic"
    assert chunks[0].metadata["parser_metadata"]["split_strategy"] == "metadata_profile"


@pytest.mark.asyncio
async def test_lifecycle_strips_null_bytes_from_runtime_chunks(client):
    app = client._transport.app
    runtime = FakeRuntime(
        [
            RuntimeChunk(
                text="Runtime\x00 chunk",
                source_location={"page\x00": "1\x00"},
                metadata={"score\x00": "1.0\x00"},
                runtime_source_id="runtime-\x001",
                content_type="text/\x00plain",
                preview_ref="preview://runtime-\x001",
            )
        ]
    )
    artifact_path = app.state.settings.data_dir / "doc-with-nuls.txt"
    artifact_path.write_text("runtime text", encoding="utf-8")

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        document = Document(
            filename="doc-with-nuls.txt",
            content_type="text/plain",
            sha256="def",
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        session.add(document)
        await session.commit()

        chunks = await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
        ).reindex_document(
            document.id,
            options=IndexDocumentIn(parser_mode="mineru_strict"),
        )

        stored = (
            await session.execute(select(Chunk).where(Chunk.document_id == document.id))
        ).scalar_one()

    assert chunks is not None
    assert chunks[0].text == "Runtime chunk"
    assert stored.text == "Runtime chunk"
    assert stored.source_location == {"page": "1"}
    assert stored.metadata_json["score"] == "1.0"
    assert stored.runtime_source_id == "runtime-1"
    assert stored.content_type == "text/plain"
    assert stored.preview_ref == "preview://runtime-1"


@pytest.mark.asyncio
async def test_graph_projection_runner_materializes_pending_record(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
            )
        )
        document = Document(
            filename="graph-runner.txt",
            content_type="text/plain",
            sha256="graph-runner",
            artifact_path=str(app.state.settings.data_dir / "graph-runner.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="Graph runner chunk",
                source_location={"page": 1},
                metadata_json={"relationship_metadata": {"references": ["Bukhari 1"]}},
                runtime_profile_id="default",
            )
        )
        projection_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="default",
            status="pending",
        )
        session.add(projection_record)
        await session.flush()

        fake = FakeGraphMaterializationService()
        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=fake,
        ).materialize_pending(document.id)
        refreshed_record = await session.get(GraphProjectionRecord, projection_record.id)

    assert fake.calls == [
        {
            "document_id": document.id,
            "profile_id": "default",
            "neo4j_uri": "bolt://neo4j.test:7687",
            "neo4j_username": "neo4j",
            "neo4j_password": "ragstudio-password",
            "graph_workspace_label": "ragstudio_default",
            "chunk_count": 1,
        }
    ]
    assert result == {
        "status": "succeeded",
        "node_count": 2,
        "edge_count": 1,
        "reason": None,
    }
    assert refreshed_record is not None
    assert refreshed_record.status == "succeeded"
    assert refreshed_record.node_count == 2
    assert refreshed_record.edge_count == 1
    assert refreshed_record.error is None
    assert refreshed_record.projection_run_id is not None
    assert refreshed_record.graph_storage_password is None


@pytest.mark.asyncio
async def test_graph_projection_runner_skips_blocked_quality_policy_chunks(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
            )
        )
        document = Document(
            filename="graph-quality-policy.txt",
            content_type="text/plain",
            sha256="graph-quality-policy",
            artifact_path=str(app.state.settings.data_dir / "graph-quality-policy.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add_all(
            [
                Chunk(
                    document_id=document.id,
                    text="Allowed graph runner chunk",
                    source_location={"page": 1},
                    metadata_json={"relationship_metadata": {"references": ["19:12"]}},
                    runtime_profile_id="default",
                ),
                Chunk(
                    document_id=document.id,
                    text="Blocked graph runner chunk",
                    source_location={"page": 1},
                    metadata_json={
                        "relationship_metadata": {"references": ["19:13"]},
                        "quality_action_policy": {
                            "project_graph": False,
                            "graph_confidence": "blocked",
                        },
                    },
                    runtime_profile_id="default",
                ),
            ]
        )
        session.add(
            GraphProjectionRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status="pending",
            )
        )
        await session.flush()

        fake = FakeGraphMaterializationService()
        await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=fake,
        ).materialize_pending(document.id)

    assert fake.calls[0]["chunk_count"] == 1


@pytest.mark.asyncio
async def test_graph_projection_runner_uses_record_runtime_profile(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add_all(
            [
                SettingsProfile(
                    id="default",
                    provider="openai-compatible",
                    llm_model="gpt-4o",
                    llm_base_url="http://default-llm.test",
                    embedding_model="text-embedding-3-large",
                    embedding_base_url="http://default-embedding.test",
                    storage_backend="postgres_pgvector_neo4j",
                    runtime_mode="runtime",
                    neo4j_uri="bolt://default-neo4j.test:7687",
                ),
                SettingsProfile(
                    id="archived",
                    provider="openai-compatible",
                    llm_model="gpt-4o",
                    llm_base_url="http://archived-llm.test",
                    embedding_model="text-embedding-3-large",
                    embedding_base_url="http://archived-embedding.test",
                    storage_backend="postgres_pgvector_neo4j",
                    runtime_mode="runtime",
                    neo4j_uri="bolt://archived-neo4j.test:7687",
                ),
            ]
        )
        document = Document(
            filename="graph-runner-profile.txt",
            content_type="text/plain",
            sha256="graph-runner-profile",
            artifact_path=str(app.state.settings.data_dir / "graph-runner-profile.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="Graph runner profile chunk",
                source_location={},
                metadata_json={},
                runtime_profile_id="archived",
            )
        )
        session.add(
            GraphProjectionRecord(
                document_id=document.id,
                runtime_profile_id="archived",
                status="pending",
            )
        )
        await session.flush()

        fake = FakeGraphMaterializationService()
        await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=fake,
        ).materialize_pending(document.id)

    assert fake.calls == [
        {
            "document_id": document.id,
            "profile_id": "archived",
            "neo4j_uri": "bolt://archived-neo4j.test:7687",
            "neo4j_username": "neo4j",
            "neo4j_password": "ragstudio-password",
            "graph_workspace_label": "ragstudio_archived",
            "chunk_count": 1,
        }
    ]


@pytest.mark.asyncio
async def test_graph_projection_runner_records_non_blocking_failure(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
            )
        )
        document = Document(
            filename="graph-runner-failure.txt",
            content_type="text/plain",
            sha256="graph-runner-failure",
            artifact_path=str(app.state.settings.data_dir / "graph-runner-failure.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="Graph runner failure chunk",
                source_location={},
                metadata_json={},
                runtime_profile_id="default",
            )
        )
        projection_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="default",
            status="pending",
        )
        session.add(projection_record)
        await session.flush()

        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=FakeGraphMaterializationService(
                error=RuntimeError("neo4j unavailable")
            ),
        ).materialize_pending(document.id)
        refreshed_record = await session.get(GraphProjectionRecord, projection_record.id)

    assert result == {
        "status": "failed",
        "node_count": 0,
        "edge_count": 0,
        "reason": "neo4j unavailable",
    }
    assert refreshed_record is not None
    assert refreshed_record.status == "failed"
    assert refreshed_record.error == "neo4j unavailable"
    assert refreshed_record.projection_run_id is not None


@pytest.mark.asyncio
async def test_graph_projection_runner_preserves_old_projection_when_replacement_skips(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
            )
        )
        document = Document(
            filename="graph-replacement-skips.txt",
            content_type="text/plain",
            sha256="graph-replacement-skips",
            artifact_path=str(app.state.settings.data_dir / "graph-replacement-skips.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        old_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="default",
            status="succeeded",
            graph_workspace_label="ragstudio_default",
            graph_storage_uri="bolt://neo4j.test:7687",
            node_count=2,
            edge_count=1,
        )
        new_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="default",
            status="pending",
            graph_workspace_label="ragstudio_default",
            graph_storage_uri="bolt://neo4j.test:7687",
        )
        session.add_all([old_record, new_record])
        await session.flush()

        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=FakeGraphMaterializationService(
                result=GraphMaterializationResult(
                    status="skipped",
                    node_count=0,
                    edge_count=0,
                    reason="driver_unavailable",
                )
            ),
        ).materialize_pending(document.id)
        records = (
            await session.execute(
                select(GraphProjectionRecord).where(
                    GraphProjectionRecord.document_id == document.id
                )
            )
        ).scalars().all()

    assert result["status"] == "skipped"
    assert {record.id for record in records} == {old_record.id, new_record.id}
    assert {record.id: record.status for record in records} == {
        old_record.id: "succeeded",
        new_record.id: "skipped",
    }


@pytest.mark.asyncio
async def test_graph_projection_runner_rematerializes_from_mirrored_chunks(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
            )
        )
        document = Document(
            filename="graph-rematerialize.txt",
            content_type="text/plain",
            sha256="graph-rematerialize",
            artifact_path=str(app.state.settings.data_dir / "graph-rematerialize.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="Graph rematerialize chunk",
                source_location={},
                metadata_json={"relationship_metadata": {"references": ["Bukhari 2"]}},
                runtime_profile_id="default",
            )
        )
        await session.flush()

        fake = FakeGraphMaterializationService()
        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=fake,
        ).rematerialize_document(document.id)
        projection_record = await session.scalar(
            select(GraphProjectionRecord).where(GraphProjectionRecord.document_id == document.id)
        )

    assert fake.calls == [
        {
            "document_id": document.id,
            "profile_id": "default",
            "neo4j_uri": "bolt://neo4j.test:7687",
            "neo4j_username": "neo4j",
            "neo4j_password": "ragstudio-password",
            "graph_workspace_label": "ragstudio_default",
            "chunk_count": 1,
        }
    ]
    assert result["status"] == "succeeded"
    assert projection_record is not None
    assert projection_record.status == "succeeded"
    assert projection_record.node_count == 2
    assert projection_record.edge_count == 1
    assert projection_record.graph_storage_password is None


@pytest.mark.asyncio
async def test_graph_projection_runner_rematerialize_does_not_snapshot_neo4j_password(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
                neo4j_username="neo4j",
                neo4j_password="do-not-copy",
            )
        )
        document = Document(
            filename="graph-rematerialize-no-password.txt",
            content_type="text/plain",
            sha256="graph-rematerialize-no-password",
            artifact_path=str(app.state.settings.data_dir / "graph-rematerialize-no-password.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="Graph rematerialize no password chunk",
                source_location={},
                metadata_json={},
                runtime_profile_id="default",
            )
        )
        await session.flush()

        fake = FakeGraphMaterializationService()
        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=fake,
        ).rematerialize_document(document.id)
        projection_record = await session.scalar(
            select(GraphProjectionRecord).where(GraphProjectionRecord.document_id == document.id)
        )

    assert result["status"] == "succeeded"
    assert fake.calls == [
        {
            "document_id": document.id,
            "profile_id": "default",
            "neo4j_uri": "bolt://neo4j.test:7687",
            "neo4j_username": "neo4j",
            "neo4j_password": "do-not-copy",
            "graph_workspace_label": "ragstudio_default",
            "chunk_count": 1,
        }
    ]
    assert projection_record is not None
    assert projection_record.graph_storage_uri == "bolt://neo4j.test:7687"
    assert projection_record.graph_storage_username == "neo4j"
    assert projection_record.graph_storage_password is None


@pytest.mark.asyncio
async def test_graph_projection_runner_deletes_projection_records_with_graph(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
            )
        )
        document = Document(
            filename="graph-delete.txt",
            content_type="text/plain",
            sha256="graph-delete",
            artifact_path=str(app.state.settings.data_dir / "graph-delete.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        projection_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="default",
            status="succeeded",
            node_count=2,
            edge_count=1,
        )
        session.add(projection_record)
        await session.flush()

        fake = FakeGraphMaterializationService()
        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=fake,
        ).delete_document_graph(document.id)
        deleted_record_id = await session.scalar(
            select(GraphProjectionRecord.id).where(GraphProjectionRecord.id == projection_record.id)
        )

    assert fake.delete_calls == [
        {
            "document_id": document.id,
            "profile_id": "default",
            "neo4j_uri": "bolt://neo4j.test:7687",
            "neo4j_username": "neo4j",
            "neo4j_password": "ragstudio-password",
            "graph_workspace_label": "ragstudio_default",
        }
    ]
    assert result["status"] == "succeeded"
    assert deleted_record_id is None


@pytest.mark.asyncio
async def test_graph_projection_runner_delete_uses_profile_password_for_passwordless_target(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://profile-neo4j.test:7687",
                neo4j_username="profile-user",
                neo4j_password="profile-password",
            )
        )
        document = Document(
            filename="graph-delete-passwordless-target.txt",
            content_type="text/plain",
            sha256="graph-delete-passwordless-target",
            artifact_path=str(app.state.settings.data_dir / "graph-delete-passwordless-target.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        projection_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="default",
            status="succeeded",
            graph_workspace_label="ragstudio_default",
            graph_storage_uri="bolt://stored-neo4j.test:7687",
            graph_storage_username="stored-user",
            graph_storage_password=None,
            node_count=2,
            edge_count=1,
        )
        session.add(projection_record)
        await session.flush()

        fake = FakeGraphMaterializationService(
            result=GraphMaterializationResult(
                status="failed",
                node_count=0,
                edge_count=0,
                reason="stop-before-delete",
            )
        )
        with pytest.raises(GraphProjectionCleanupError, match="stop-before-delete"):
            await GraphProjectionRunner(
                session,
                app.state.settings,
                materialization_service=fake,
            ).delete_document_graph(document.id)
        refreshed_record = await session.get(GraphProjectionRecord, projection_record.id)

    assert fake.delete_calls == [
        {
            "document_id": document.id,
            "profile_id": "default",
            "neo4j_uri": "bolt://stored-neo4j.test:7687",
            "neo4j_username": "stored-user",
            "neo4j_password": "profile-password",
            "graph_workspace_label": "ragstudio_default",
        }
    ]
    assert refreshed_record is not None
    assert refreshed_record.graph_storage_password is None


@pytest.mark.asyncio
async def test_graph_projection_runner_deletes_using_recorded_target_after_profile_drift(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://new-neo4j.test:7687",
                neo4j_username="new-user",
                neo4j_password="new-password",
            )
        )
        document = Document(
            filename="graph-delete-profile-drift.txt",
            content_type="text/plain",
            sha256="graph-delete-profile-drift",
            artifact_path=str(app.state.settings.data_dir / "graph-delete-profile-drift.txt"),
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
                graph_storage_uri="bolt://old-neo4j.test:7687",
                graph_storage_username="old-user",
                graph_storage_password="old-password",
                node_count=2,
                edge_count=1,
            )
        )
        await session.flush()

        fake = FakeGraphMaterializationService()
        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=fake,
        ).delete_document_graph(document.id)

    assert fake.delete_calls == [
        {
            "document_id": document.id,
            "profile_id": "default",
            "neo4j_uri": "bolt://old-neo4j.test:7687",
            "neo4j_username": "old-user",
            "neo4j_password": "old-password",
            "graph_workspace_label": "ragstudio_default",
        }
    ]
    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_graph_projection_runner_uses_settings_auth_for_stored_target_without_password(
    client,
):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
                neo4j_username=None,
                neo4j_password=None,
            )
        )
        document = Document(
            filename="graph-delete-settings-auth.txt",
            content_type="text/plain",
            sha256="graph-delete-settings-auth",
            artifact_path=str(app.state.settings.data_dir / "graph-delete-settings-auth.txt"),
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
                graph_storage_username=None,
                graph_storage_password=None,
                node_count=2,
                edge_count=1,
            )
        )
        await session.flush()

        fake = FakeGraphMaterializationService()
        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=fake,
        ).delete_document_graph(document.id)

    assert result["status"] == "succeeded"
    assert fake.delete_calls == [
        {
            "document_id": document.id,
            "profile_id": "default",
            "neo4j_uri": "bolt://neo4j.test:7687",
            "neo4j_username": app.state.settings.neo4j_username,
            "neo4j_password": app.state.settings.neo4j_password,
            "graph_workspace_label": "ragstudio_default",
        }
    ]


@pytest.mark.asyncio
async def test_graph_projection_runner_deletes_using_recorded_target_without_live_profile(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        document = Document(
            filename="graph-delete-profile-removed.txt",
            content_type="text/plain",
            sha256="graph-delete-profile-removed",
            artifact_path=str(app.state.settings.data_dir / "graph-delete-profile-removed.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            GraphProjectionRecord(
                document_id=document.id,
                runtime_profile_id="removed-profile",
                status="succeeded",
                graph_workspace_label="ragstudio_removed_profile",
                graph_storage_uri="bolt://old-neo4j.test:7687",
                graph_storage_username="old-user",
                graph_storage_password="old-password",
                node_count=2,
                edge_count=1,
            )
        )
        await session.flush()

        fake = FakeGraphMaterializationService()
        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=fake,
        ).delete_document_graph(document.id)

    assert fake.delete_calls == [
        {
            "document_id": document.id,
            "profile_id": "removed-profile",
            "neo4j_uri": "bolt://old-neo4j.test:7687",
            "neo4j_username": "old-user",
            "neo4j_password": "old-password",
            "graph_workspace_label": "ragstudio_removed_profile",
        }
    ]
    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_graph_projection_runner_marks_cleanup_succeeded(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
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
            filename="graph-cleanup-state.txt",
            content_type="text/plain",
            sha256="graph-cleanup-state",
            artifact_path=str(app.state.settings.data_dir / "graph-cleanup-state.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        projection_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="default",
            status="succeeded",
            graph_workspace_label="ragstudio_default",
            graph_storage_uri="bolt://neo4j.test:7687",
            node_count=2,
            edge_count=1,
        )
        session.add(projection_record)
        await session.flush()

        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=FakeGraphMaterializationService(),
        ).delete_document_graph(document.id)
        refreshed = await session.get(GraphProjectionRecord, projection_record.id)

    assert result["status"] == "succeeded"
    assert refreshed is None


@pytest.mark.asyncio
async def test_graph_projection_runner_skips_already_cleaned_record(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        document = Document(
            filename="graph-cleaned-skip.txt",
            content_type="text/plain",
            sha256="graph-cleaned-skip",
            artifact_path=str(app.state.settings.data_dir / "graph-cleaned-skip.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        projection_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="removed-profile",
            status="succeeded",
            graph_workspace_label="ragstudio_removed_profile",
            graph_storage_uri="bolt://old-neo4j.test:7687",
            node_count=2,
            edge_count=1,
            cleanup_status="succeeded",
        )
        session.add(projection_record)
        await session.flush()
        document_id = document.id
        projection_record_id = projection_record.id
        await session.commit()

    async with app.state.session_factory() as session:
        fake = FakeGraphMaterializationService()
        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=fake,
        ).delete_document_graph(document_id)
        deleted_record = await session.get(GraphProjectionRecord, projection_record_id)

    assert fake.delete_calls == []
    assert result == {
        "status": "succeeded",
        "node_count": 0,
        "edge_count": 0,
        "reason": None,
    }
    assert deleted_record is None


@pytest.mark.asyncio
async def test_graph_projection_runner_reports_default_profile_message_for_incomplete_target(
    client,
):
    app = client._transport.app

    async with app.state.session_factory() as session:
        document = Document(
            filename="graph-delete-default-missing.txt",
            content_type="text/plain",
            sha256="graph-delete-default-missing",
            artifact_path=str(app.state.settings.data_dir / "graph-delete-default-missing.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            GraphProjectionRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status="succeeded",
                graph_workspace_label=None,
                graph_storage_uri=None,
                graph_storage_username=None,
                graph_storage_password=None,
                node_count=2,
                edge_count=1,
            )
        )
        await session.flush()

        with pytest.raises(
            GraphProjectionCleanupError,
            match=r"Default runtime profile is not configured\.",
        ):
            await GraphProjectionRunner(
                session,
                app.state.settings,
                materialization_service=FakeGraphMaterializationService(),
            ).delete_document_graph(document.id)


@pytest.mark.asyncio
async def test_graph_projection_runner_removes_failed_zero_count_record_without_graph_cleanup(
    client,
):
    app = client._transport.app

    async with app.state.session_factory() as session:
        document = Document(
            filename="graph-delete-failed-zero.txt",
            content_type="text/plain",
            sha256="graph-delete-failed-zero",
            artifact_path=str(app.state.settings.data_dir / "graph-delete-failed-zero.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        projection_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="missing-profile",
            status="failed",
            node_count=0,
            edge_count=0,
            error="neo4j write failed before commit",
        )
        session.add(projection_record)
        await session.flush()

        fake = FakeGraphMaterializationService()
        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=fake,
        ).delete_document_graph(document.id)
        deleted_record_id = await session.scalar(
            select(GraphProjectionRecord.id).where(GraphProjectionRecord.id == projection_record.id)
        )

    assert fake.delete_calls == []
    assert result["status"] == "skipped"
    assert result["reason"] == "no_materialized_projection"
    assert deleted_record_id is None


@pytest.mark.asyncio
async def test_graph_projection_runner_preserves_records_when_graph_delete_fails(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
            )
        )
        document = Document(
            filename="graph-delete-fails.txt",
            content_type="text/plain",
            sha256="graph-delete-fails",
            artifact_path=str(app.state.settings.data_dir / "graph-delete-fails.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        projection_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="default",
            status="succeeded",
            node_count=2,
            edge_count=1,
        )
        session.add(projection_record)
        await session.flush()
        projection_record_id = projection_record.id
        await session.commit()

        with pytest.raises(GraphProjectionCleanupError, match="Graph projection cleanup failed"):
            await GraphProjectionRunner(
                session,
                app.state.settings,
                materialization_service=FakeGraphMaterializationService(
                    result=GraphMaterializationResult(
                        status="failed",
                        node_count=0,
                        edge_count=0,
                        reason="neo4j unavailable",
                    )
                ),
            ).delete_document_graph(document.id)
        preserved_record_id = await session.scalar(
            select(GraphProjectionRecord.id).where(GraphProjectionRecord.id == projection_record_id)
        )

    assert preserved_record_id == projection_record.id
    async with app.state.session_factory() as session:
        refreshed = await session.get(GraphProjectionRecord, projection_record_id)

    assert refreshed is not None
    assert refreshed.cleanup_status == "failed"
    assert refreshed.cleanup_error == "Graph projection cleanup failed: neo4j unavailable"
    assert refreshed.cleanup_attempted_at is not None


@pytest.mark.asyncio
async def test_graph_projection_runner_marks_cleanup_failed_when_delete_raises(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
            )
        )
        document = Document(
            filename="graph-delete-raises.txt",
            content_type="text/plain",
            sha256="graph-delete-raises",
            artifact_path=str(app.state.settings.data_dir / "graph-delete-raises.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        projection_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="default",
            status="succeeded",
            graph_workspace_label="ragstudio_default",
            graph_storage_uri="bolt://neo4j.test:7687",
            node_count=2,
            edge_count=1,
        )
        session.add(projection_record)
        await session.flush()
        projection_record_id = projection_record.id
        await session.commit()

        with pytest.raises(GraphProjectionCleanupError, match="neo4j connection reset"):
            await GraphProjectionRunner(
                session,
                app.state.settings,
                materialization_service=FakeGraphMaterializationService(
                    error=RuntimeError("neo4j connection reset")
                ),
            ).delete_document_graph(document.id)

    async with app.state.session_factory() as session:
        refreshed = await session.get(GraphProjectionRecord, projection_record_id)

    assert refreshed is not None
    assert refreshed.cleanup_status == "failed"
    assert refreshed.cleanup_error == "Graph projection cleanup failed: neo4j connection reset"
    assert refreshed.cleanup_attempted_at is not None


@pytest.mark.asyncio
async def test_graph_projection_runner_persists_running_state_before_external_delete(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
            )
        )
        document = Document(
            filename="graph-delete-running-visible.txt",
            content_type="text/plain",
            sha256="graph-delete-running-visible",
            artifact_path=str(app.state.settings.data_dir / "graph-delete-running-visible.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        projection_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="default",
            status="succeeded",
            graph_workspace_label="ragstudio_default",
            graph_storage_uri="bolt://neo4j.test:7687",
            node_count=2,
            edge_count=1,
        )
        session.add(projection_record)
        await session.flush()
        projection_record_id = projection_record.id
        await session.commit()

        fake = RunningStatusObservingGraphMaterializationService(
            app.state.session_factory,
            projection_record_id,
        )
        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=fake,
        ).delete_document_graph(document.id)

    assert result["status"] == "succeeded"
    assert fake.observed_cleanup_status == "running"


@pytest.mark.asyncio
async def test_graph_projection_cleanup_marker_does_not_commit_unrelated_session_changes(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://llm.test",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://embedding.test",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://neo4j.test:7687",
            )
        )
        unrelated_document = Document(
            filename="unrelated-original.txt",
            content_type="text/plain",
            sha256="unrelated-original",
            artifact_path=str(app.state.settings.data_dir / "unrelated-original.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        cleanup_document = Document(
            filename="graph-delete-isolated-marker.txt",
            content_type="text/plain",
            sha256="graph-delete-isolated-marker",
            artifact_path=str(app.state.settings.data_dir / "graph-delete-isolated-marker.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add_all([unrelated_document, cleanup_document])
        await session.flush()
        projection_record = GraphProjectionRecord(
            document_id=cleanup_document.id,
            runtime_profile_id="default",
            status="succeeded",
            graph_workspace_label="ragstudio_default",
            graph_storage_uri="bolt://neo4j.test:7687",
            node_count=2,
            edge_count=1,
        )
        session.add(projection_record)
        await session.flush()
        unrelated_document_id = unrelated_document.id
        cleanup_document_id = cleanup_document.id
        projection_record_id = projection_record.id
        await session.commit()

    async with app.state.session_factory() as session:
        unrelated_document = await session.get(Document, unrelated_document_id)
        assert unrelated_document is not None
        unrelated_document.filename = "unrelated-dirty.txt"

        with pytest.raises(GraphProjectionCleanupError, match="neo4j connection reset"):
            await GraphProjectionRunner(
                session,
                app.state.settings,
                materialization_service=FakeGraphMaterializationService(
                    error=RuntimeError("neo4j connection reset")
                ),
            ).delete_document_graph(cleanup_document_id)
        await session.rollback()

    async with app.state.session_factory() as session:
        unrelated_document = await session.get(Document, unrelated_document_id)
        refreshed = await session.get(GraphProjectionRecord, projection_record_id)

    assert unrelated_document is not None
    assert unrelated_document.filename == "unrelated-original.txt"
    assert refreshed is not None
    assert refreshed.cleanup_status == "failed"
    assert refreshed.cleanup_error == "Graph projection cleanup failed: neo4j connection reset"


@pytest.mark.asyncio
async def test_graph_projection_runner_marks_duplicate_target_records_cleaned_before_later_failure(
    client,
):
    app = client._transport.app

    async with app.state.session_factory() as session:
        document = Document(
            filename="graph-duplicate-target-retry.txt",
            content_type="text/plain",
            sha256="graph-duplicate-target-retry",
            artifact_path=str(app.state.settings.data_dir / "graph-duplicate-target-retry.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        duplicate_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="a-profile",
            status="succeeded",
            graph_workspace_label="ragstudio_a",
            graph_storage_uri="bolt://target-a.test:7687",
            node_count=2,
            edge_count=1,
        )
        duplicate_retry_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="x-profile",
            status="succeeded",
            graph_workspace_label="ragstudio_a",
            graph_storage_uri="bolt://target-a.test:7687",
            node_count=3,
            edge_count=2,
        )
        failing_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="b-profile",
            status="succeeded",
            graph_workspace_label="ragstudio_b",
            graph_storage_uri="bolt://target-b.test:7687",
            node_count=5,
            edge_count=4,
        )
        session.add_all([duplicate_record, duplicate_retry_record, failing_record])
        await session.flush()
        document_id = document.id
        duplicate_record_ids = [duplicate_record.id, duplicate_retry_record.id]
        failing_record_id = failing_record.id
        await session.commit()

    first_delete = UriRoutedGraphMaterializationService(
        failed_uris={"bolt://target-b.test:7687"}
    )
    async with app.state.session_factory() as session:
        with pytest.raises(GraphProjectionCleanupError, match=r"target-b\.test:7687 unavailable"):
            await GraphProjectionRunner(
                session,
                app.state.settings,
                materialization_service=first_delete,
            ).delete_document_graph(document_id)

    assert [call["neo4j_uri"] for call in first_delete.delete_calls] == [
        "bolt://target-a.test:7687",
        "bolt://target-b.test:7687",
    ]
    async with app.state.session_factory() as session:
        duplicate_statuses = (
            (
                await session.execute(
                    select(GraphProjectionRecord.cleanup_status)
                    .where(GraphProjectionRecord.id.in_(duplicate_record_ids))
                    .order_by(GraphProjectionRecord.id.asc())
                )
            )
            .scalars()
            .all()
        )
        failing_status = await session.scalar(
            select(GraphProjectionRecord.cleanup_status).where(
                GraphProjectionRecord.id == failing_record_id
            )
        )

    assert duplicate_statuses == ["succeeded", "succeeded"]
    assert failing_status == "failed"

    retry_delete = UriRoutedGraphMaterializationService()
    async with app.state.session_factory() as session:
        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=retry_delete,
        ).delete_document_graph(document_id)

    assert result["status"] == "succeeded"
    assert [call["neo4j_uri"] for call in retry_delete.delete_calls] == [
        "bolt://target-b.test:7687"
    ]


@pytest.mark.asyncio
async def test_graph_projection_runner_groups_stored_and_partial_records_after_target_fill(
    client,
):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://target-a.test:7687",
            )
        )
        document = Document(
            filename="graph-mixed-target-retry.txt",
            content_type="text/plain",
            sha256="graph-mixed-target-retry",
            artifact_path=str(app.state.settings.data_dir / "graph-mixed-target-retry.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        stored_target_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="default",
            status="succeeded",
            graph_workspace_label="ragstudio_default",
            graph_storage_uri="bolt://target-a.test:7687",
            node_count=2,
            edge_count=1,
        )
        partial_legacy_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="default",
            status="succeeded",
            graph_workspace_label=None,
            graph_storage_uri=None,
            node_count=3,
            edge_count=2,
        )
        failing_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="z-profile",
            status="succeeded",
            graph_workspace_label="ragstudio_z",
            graph_storage_uri="bolt://target-z.test:7687",
            node_count=5,
            edge_count=4,
        )
        session.add_all([stored_target_record, partial_legacy_record, failing_record])
        await session.flush()
        document_id = document.id
        duplicate_record_ids = [stored_target_record.id, partial_legacy_record.id]
        await session.commit()

    first_delete = UriRoutedGraphMaterializationService(
        failed_uris={"bolt://target-z.test:7687"}
    )
    async with app.state.session_factory() as session:
        with pytest.raises(GraphProjectionCleanupError, match=r"target-z\.test:7687 unavailable"):
            await GraphProjectionRunner(
                session,
                app.state.settings,
                materialization_service=first_delete,
            ).delete_document_graph(document_id)

    assert [call["neo4j_uri"] for call in first_delete.delete_calls] == [
        "bolt://target-a.test:7687",
        "bolt://target-z.test:7687",
    ]
    async with app.state.session_factory() as session:
        duplicate_records = (
            (
                await session.execute(
                    select(GraphProjectionRecord)
                    .where(GraphProjectionRecord.id.in_(duplicate_record_ids))
                    .order_by(GraphProjectionRecord.id.asc())
                )
            )
            .scalars()
            .all()
        )

    assert [record.cleanup_status for record in duplicate_records] == [
        "succeeded",
        "succeeded",
    ]
    assert [record.graph_storage_uri for record in duplicate_records] == [
        "bolt://target-a.test:7687",
        "bolt://target-a.test:7687",
    ]
    assert [record.graph_workspace_label for record in duplicate_records] == [
        "ragstudio_default",
        "ragstudio_default",
    ]


@pytest.mark.asyncio
async def test_graph_projection_runner_prefers_live_profile_credentials_for_target_group(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://target-auth.test:7687",
                neo4j_username="neo4j-user",
                neo4j_password="live-password",
            )
        )
        document = Document(
            filename="graph-live-profile-credentials.txt",
            content_type="text/plain",
            sha256="graph-live-profile-credentials",
            artifact_path=str(app.state.settings.data_dir / "graph-live-profile-credentials.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        removed_profile_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="removed-profile",
            status="succeeded",
            graph_workspace_label="ragstudio_default",
            graph_storage_uri="bolt://target-auth.test:7687",
            graph_storage_username="neo4j-user",
            graph_storage_password=None,
            node_count=2,
            edge_count=1,
        )
        live_profile_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="default",
            status="succeeded",
            graph_workspace_label=None,
            graph_storage_uri=None,
            graph_storage_username=None,
            graph_storage_password=None,
            node_count=3,
            edge_count=2,
        )
        session.add_all([removed_profile_record, live_profile_record])
        await session.flush()
        document_id = document.id
        await session.commit()

    fake = FakeGraphMaterializationService()
    async with app.state.session_factory() as session:
        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=fake,
        ).delete_document_graph(document_id)

    assert result["status"] == "succeeded"
    assert fake.delete_calls == [
        {
            "document_id": document_id,
            "profile_id": "default",
            "neo4j_uri": "bolt://target-auth.test:7687",
            "neo4j_username": "neo4j-user",
            "neo4j_password": "live-password",
            "graph_workspace_label": "ragstudio_default",
        }
    ]


@pytest.mark.asyncio
async def test_graph_projection_runner_groups_same_target_with_different_stored_passwords(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        document = Document(
            filename="graph-stored-password-group.txt",
            content_type="text/plain",
            sha256="graph-stored-password-group",
            artifact_path=str(app.state.settings.data_dir / "graph-stored-password-group.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        passwordless_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="removed-profile",
            status="succeeded",
            graph_workspace_label="ragstudio_removed_profile",
            graph_storage_uri="bolt://stored-target.test:7687",
            graph_storage_username="neo4j-user",
            graph_storage_password=None,
            node_count=2,
            edge_count=1,
        )
        credential_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="removed-profile",
            status="succeeded",
            graph_workspace_label="ragstudio_removed_profile",
            graph_storage_uri="bolt://stored-target.test:7687",
            graph_storage_username="neo4j-user",
            graph_storage_password="stored-password",
            node_count=3,
            edge_count=2,
        )
        session.add_all([passwordless_record, credential_record])
        await session.flush()
        document_id = document.id
        await session.commit()

    fake = FakeGraphMaterializationService()
    async with app.state.session_factory() as session:
        result = await GraphProjectionRunner(
            session,
            app.state.settings,
            materialization_service=fake,
        ).delete_document_graph(document_id)

    assert result["status"] == "succeeded"
    assert fake.delete_calls == [
        {
            "document_id": document_id,
            "profile_id": "removed-profile",
            "neo4j_uri": "bolt://stored-target.test:7687",
            "neo4j_username": "neo4j-user",
            "neo4j_password": "stored-password",
            "graph_workspace_label": "ragstudio_removed_profile",
        }
    ]


@pytest.mark.asyncio
async def test_graph_projection_runner_skips_retry_when_duplicate_target_already_cleaned(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                embedding_model="text-embedding-3-large",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
                neo4j_uri="bolt://target-a.test:7687",
            )
        )
        document = Document(
            filename="graph-duplicate-target-already-cleaned.txt",
            content_type="text/plain",
            sha256="graph-duplicate-target-already-cleaned",
            artifact_path=str(
                app.state.settings.data_dir / "graph-duplicate-target-already-cleaned.txt"
            ),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        cleaned_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="default",
            status="succeeded",
            graph_workspace_label="ragstudio_default",
            graph_storage_uri="bolt://target-a.test:7687",
            node_count=2,
            edge_count=1,
            cleanup_status="succeeded",
        )
        partial_retry_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="default",
            status="succeeded",
            graph_workspace_label=None,
            graph_storage_uri=None,
            node_count=3,
            edge_count=2,
            cleanup_status="failed",
            cleanup_error="previous interruption",
        )
        failing_record = GraphProjectionRecord(
            document_id=document.id,
            runtime_profile_id="z-profile",
            status="succeeded",
            graph_workspace_label="ragstudio_z",
            graph_storage_uri="bolt://target-z.test:7687",
            node_count=5,
            edge_count=4,
        )
        session.add_all([cleaned_record, partial_retry_record, failing_record])
        await session.flush()
        document_id = document.id
        duplicate_record_ids = [cleaned_record.id, partial_retry_record.id]
        await session.commit()

    fake = UriRoutedGraphMaterializationService(failed_uris={"bolt://target-z.test:7687"})
    async with app.state.session_factory() as session:
        with pytest.raises(GraphProjectionCleanupError, match=r"target-z\.test:7687 unavailable"):
            await GraphProjectionRunner(
                session,
                app.state.settings,
                materialization_service=fake,
            ).delete_document_graph(document_id)

    assert [call["neo4j_uri"] for call in fake.delete_calls] == ["bolt://target-z.test:7687"]
    async with app.state.session_factory() as session:
        duplicate_records = (
            (
                await session.execute(
                    select(GraphProjectionRecord)
                    .where(GraphProjectionRecord.id.in_(duplicate_record_ids))
                    .order_by(GraphProjectionRecord.id.asc())
                )
            )
            .scalars()
            .all()
        )

    assert [record.cleanup_status for record in duplicate_records] == [
        "succeeded",
        "succeeded",
    ]
    assert [record.cleanup_error for record in duplicate_records] == [None, None]
    assert [record.graph_storage_uri for record in duplicate_records] == [
        "bolt://target-a.test:7687",
        "bolt://target-a.test:7687",
    ]


@pytest.mark.asyncio
async def test_lifecycle_missing_document_returns_none(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        result = await IndexLifecycleService(session, app.state.settings).reindex_document(
            "missing-document"
        )

    assert result is None
