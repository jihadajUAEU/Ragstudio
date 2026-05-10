from pathlib import Path

import pytest
from ragstudio.db.models import Chunk, Document, GraphProjectionRecord, IndexRecord, SettingsProfile
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.graph_materialization_service import GraphMaterializationResult
from ragstudio.services.graph_projection_runner import (
    GraphProjectionCleanupError,
    GraphProjectionRunner,
)
from ragstudio.services.index_lifecycle_service import IndexLifecycleService
from ragstudio.services.runtime_types import RuntimeChunk
from sqlalchemy import select


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


def _add_auth_to_call(call: dict, profile) -> None:
    username = getattr(profile, "neo4j_username", None)
    password = getattr(profile, "neo4j_password", None)
    if username is not None:
        call["neo4j_username"] = username
    if password is not None:
        call["neo4j_password"] = password


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
            options=IndexDocumentIn(parser_mode="local_fallback"),
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
            options=IndexDocumentIn(parser_mode="local_fallback"),
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
                parser_mode="local_fallback",
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
            options=IndexDocumentIn(parser_mode="local_fallback"),
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
            match="Default runtime profile is not configured.",
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
            select(GraphProjectionRecord.id).where(GraphProjectionRecord.id == projection_record.id)
        )

    assert preserved_record_id == projection_record.id


@pytest.mark.asyncio
async def test_lifecycle_missing_document_returns_none(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        result = await IndexLifecycleService(session, app.state.settings).reindex_document(
            "missing-document"
        )

    assert result is None
