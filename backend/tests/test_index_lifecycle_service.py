from pathlib import Path

import pytest
from ragstudio.db.models import Chunk, Document, IndexRecord, SettingsProfile
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.parsing import IndexDocumentIn
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
        await session.commit()

        chunks = await IndexLifecycleService(
            session,
            app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
        ).reindex_document(document.id, options=IndexDocumentIn())

        remaining = await session.execute(select(Chunk).where(Chunk.document_id == document.id))
        stored = remaining.scalars().all()
        records = (
            await session.execute(select(IndexRecord).where(IndexRecord.document_id == document.id))
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
    assert refreshed_document is not None
    assert refreshed_document.status == StageStatus.SUCCEEDED.value


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
        ).reindex_document(document.id, options=IndexDocumentIn())

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
async def test_lifecycle_missing_document_returns_none(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        result = await IndexLifecycleService(session, app.state.settings).reindex_document(
            "missing-document"
        )

    assert result is None
