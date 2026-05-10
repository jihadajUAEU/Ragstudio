from pathlib import Path
from types import SimpleNamespace

import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Document, SettingsProfile
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.document_parser_service import DocumentParserService
from ragstudio.services.mineru_client import MinerUJobResult, MinerUSidecarHealth


class LocalParser:
    async def index_document(self, artifact_path):
        return [
            AdapterChunk(
                text="Local fallback text",
                source_location={"line": 1},
                metadata={"backend": "fallback", "chunk_index": 0},
                runtime_source_id="local-runtime-1",
                content_type="application/x-local-preview",
                preview_ref="preview://local-runtime-1",
            )
        ]


class FailingMinerUClient:
    def __init__(self, base_url, timeout_ms, poll_interval_ms):
        self.base_url = base_url
        self.timeout_ms = timeout_ms
        self.poll_interval_ms = poll_interval_ms

    async def health(self):
        return MinerUSidecarHealth(
            ready=True,
            detail="RAG-Anything sidecar ready",
            version="hybrid",
            hpc_enabled=True,
            hpc_mode="coordinator",
            raw={"hpcMineru": {"enabled": True, "mode": "coordinator"}},
        )

    async def parse_document(self, **kwargs):
        raise RuntimeError("remote MinerU failed")


class EventSession:
    def __init__(self):
        self.events = []
        self.settings = SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="gpt-4o",
            embedding_model="fallback",
            storage_backend="fallback_local",
            runtime_mode="fallback",
            mineru_enabled=True,
            mineru_base_url="http://10.10.9.19:8765",
            mineru_require_hpc=True,
        )

    async def get(self, model, key):
        self.events.append(f"get:{model.__name__}:{key}")
        return self.settings

    async def commit(self):
        self.events.append("commit")


class EventMinerUClient:
    def __init__(self, base_url, timeout_ms, poll_interval_ms, *, events):
        self.events = events

    async def health(self):
        self.events.append("health")
        return MinerUSidecarHealth(
            ready=True,
            detail="RAG-Anything sidecar ready",
            version="hybrid",
            hpc_enabled=True,
            hpc_mode="coordinator",
            raw={"hpcMineru": {"enabled": True, "mode": "coordinator"}},
        )

    async def parse_document(self, **kwargs):
        self.events.append("parse")
        return MinerUJobResult(parse_job_id="job-1", artifact_zip=Path("artifact.zip"))

    def normalize_artifact_zip(self, **kwargs):
        self.events.append("normalize")
        return [
            AdapterChunk(
                text="Remote MinerU chunk",
                source_location={"page": 1},
                metadata={"parser_metadata": {"backend": "mineru"}},
            )
        ]


@pytest.mark.asyncio
async def test_mineru_with_fallback_uses_local_chunks_and_records_error(
    tmp_path,
    database_url,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        artifact = tmp_path / "document.pdf"
        artifact.write_bytes(b"%PDF-1.4")
        document = Document(
            filename="document.pdf",
            content_type="application/pdf",
            sha256="fallback-sha",
            artifact_path=str(artifact),
            status="ready",
        )
        settings = SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="gpt-4o",
            embedding_model="fallback",
            storage_backend="fallback_local",
            runtime_mode="fallback",
            mineru_enabled=True,
            mineru_base_url="http://10.10.9.19:8765",
            mineru_require_hpc=True,
        )
        session.add_all([document, settings])
        await session.commit()

        chunks = await DocumentParserService(
            session,
            tmp_path,
            local_parser=LocalParser(),
            mineru_client_factory=FailingMinerUClient,
        ).parse(
            document,
            IndexDocumentIn(parser_mode="mineru_with_fallback"),
        )

    await engine.dispose()

    assert [chunk.text for chunk in chunks] == ["Local fallback text"]
    parser_metadata = chunks[0].metadata["parser_metadata"]
    assert parser_metadata["backend"] == "fallback"
    assert parser_metadata["parser_mode"] == "mineru_with_fallback"
    assert parser_metadata["fallback_used"] is True
    assert parser_metadata["mineru_error"] == "remote MinerU failed"
    assert chunks[0].runtime_source_id == "local-runtime-1"
    assert chunks[0].content_type == "application/x-local-preview"
    assert chunks[0].preview_ref == "preview://local-runtime-1"


@pytest.mark.asyncio
async def test_commit_before_remote_parse_releases_session_before_parse(tmp_path):
    session = EventSession()

    def mineru_client_factory(base_url, timeout_ms, poll_interval_ms):
        return EventMinerUClient(
            base_url,
            timeout_ms,
            poll_interval_ms,
            events=session.events,
        )

    document = SimpleNamespace(
        id="doc-1",
        artifact_path=str(tmp_path / "document.pdf"),
        content_type="application/pdf",
        sha256="sha",
    )

    chunks = await DocumentParserService(
        session,
        tmp_path,
        mineru_client_factory=mineru_client_factory,
        commit_before_remote_parse=True,
    ).mineru_parse(
        document,
        IndexDocumentIn(parser_mode="mineru_strict"),
    )

    assert [chunk.text for chunk in chunks] == ["Remote MinerU chunk"]
    assert session.events == [
        "get:SettingsProfile:default",
        "health",
        "commit",
        "parse",
        "normalize",
    ]
