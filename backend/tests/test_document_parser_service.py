from pathlib import Path
from types import SimpleNamespace

import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Document, SettingsProfile
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn
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


class LocalParserShouldNotRun:
    async def index_document(self, artifact_path):
        raise AssertionError("local parser must not run in product indexing")


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
            parser="mineru",
            parse_method="auto",
            mineru_backend="pipeline",
            mineru_device="cuda:0",
            mineru_lang="en",
            mineru_formula=True,
            mineru_table=True,
            mineru_source="huggingface",
            mineru_max_concurrent_files=2,
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
        self.events.append(("parse", kwargs["parse_options"].to_metadata()))
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
async def test_mineru_with_fallback_is_rejected_without_running_local_parser(
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

        DocumentParserService(
            session,
            tmp_path,
            local_parser=LocalParserShouldNotRun(),
            mineru_client_factory=FailingMinerUClient,
        )
        with pytest.raises(ValueError, match="mineru_with_fallback"):
            IndexDocumentIn(parser_mode="mineru_with_fallback")

    await engine.dispose()


@pytest.mark.asyncio
async def test_mineru_strict_requires_configured_mineru_base_url(tmp_path, database_url):
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
            storage_backend="postgres_pgvector_neo4j",
            runtime_mode="runtime",
            mineru_enabled=True,
            mineru_base_url=None,
            mineru_require_hpc=True,
        )
        session.add_all([document, settings])
        await session.commit()

        service = DocumentParserService(
            session,
            tmp_path,
            local_parser=LocalParserShouldNotRun(),
            mineru_client_factory=FailingMinerUClient,
        )
        with pytest.raises(RuntimeError, match="MinerU base URL is not configured"):
            await service.parse(document, IndexDocumentIn(parser_mode="mineru_strict"))

    await engine.dispose()


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

    from ragstudio.services.mineru_extraction_validator import MinerUExtractionValidator

    chunks = await DocumentParserService(
        session,
        tmp_path,
        mineru_client_factory=mineru_client_factory,
        commit_before_remote_parse=True,
        extraction_validator=MinerUExtractionValidator(min_text_chars=8),
    ).mineru_parse(
        document,
        IndexDocumentIn(parser_mode="mineru_strict"),
    )

    assert [chunk.text for chunk in chunks] == ["Remote MinerU chunk"]
    assert session.events == [
        "get:SettingsProfile:default",
        "health",
        "commit",
        (
            "parse",
            {
                "parser": "mineru",
                "parseMethod": "auto",
                "parserKwargs": {
                    "backend": "pipeline",
                    "device": "cuda:0",
                    "formula": True,
                    "table": True,
                    "lang": "en",
                    "source": "huggingface",
                },
                "maxConcurrentFiles": 2,
            },
        ),
        "normalize",
    ]


def test_index_document_options_accept_document_mineru_parse_options():
    options = IndexDocumentIn.model_validate(
        {
            "parser_mode": "mineru_strict",
            "domain_metadata": {"domain": "quran_tafseer"},
            "mineru_parse_options": {
                "parse_method": "ocr",
                "backend": "pipeline",
                "device": "cuda:0",
                "lang": "arabic",
                "formula": False,
                "table": False,
                "source": "huggingface",
                "max_concurrent_files": 2,
            },
        }
    )

    assert options.mineru_parse_options is not None
    assert options.mineru_parse_options.parse_method == "ocr"
    assert options.mineru_parse_options.backend == "pipeline"
    assert options.mineru_parse_options.device == "cuda:0"
    assert options.mineru_parse_options.max_concurrent_files == 2


def test_mineru_parse_options_ignore_hidden_domain_metadata_overrides(tmp_path):
    settings = SettingsProfile(
        id="default",
        provider="openai-compatible",
        llm_model="gpt-4o",
        embedding_model="fallback",
        storage_backend="postgres_pgvector_neo4j",
        runtime_mode="runtime",
        mineru_enabled=True,
        mineru_base_url="http://10.10.9.19:8765",
        mineru_backend="pipeline",
        mineru_device="cuda:1",
        mineru_lang="en",
        mineru_formula=True,
        mineru_table=True,
        mineru_source="huggingface",
        mineru_max_concurrent_files=2,
    )
    metadata = DomainMetadata(
        domain="quran_tafseer",
        document_type="commentary",
        language="mixed",
        script="mixed",
        tags=["quran", "arabic", "tafseer"],
        custom_json={
            "parser_normalization": {
                "allow_equations_as_content": False,
                "recover_text_bearing_blocks_as_prose": True,
                "preserve_original_block_type": True,
            },
            "mineru_parse_options": {
                "parse_method": "ocr",
                "lang": "arabic",
                "formula": False,
                "table": False,
                "device": "cuda:0",
                "max_concurrent_files": 1,
            },
        },
    )

    parse_options = DocumentParserService(EventSession(), tmp_path)._mineru_parse_options(
        settings,
        metadata,
    )

    assert parse_options.to_metadata() == {
        "parser": "mineru",
        "parseMethod": "auto",
        "parserKwargs": {
            "backend": "pipeline",
            "device": "cuda:1",
            "formula": True,
            "table": True,
            "lang": "en",
            "source": "huggingface",
        },
        "maxConcurrentFiles": 2,
    }


@pytest.mark.asyncio
async def test_mineru_parse_allows_missing_arabic_for_downstream_recovery(tmp_path):
    from ragstudio.services.mineru_extraction_validator import MinerUExtractionValidator

    session = EventSession()

    class EnglishOnlyMinerUClient(EventMinerUClient):
        def normalize_artifact_zip(self, **kwargs):
            self.events.append("normalize")
            return [
                AdapterChunk(
                    text="[2:28]\nHow can you disbelieve in Allah?",
                    source_location={"page": 1},
                    metadata={"parser_metadata": {"backend": "mineru"}},
                )
            ]

    def mineru_client_factory(base_url, timeout_ms, poll_interval_ms):
        return EnglishOnlyMinerUClient(
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
        extraction_validator=MinerUExtractionValidator(min_text_chars=8),
    ).mineru_parse(
        document,
        IndexDocumentIn(
            parser_mode="mineru_strict",
            domain_metadata=DomainMetadata(domain="quran", script="arabic"),
        ),
    )

    assert [chunk.text for chunk in chunks] == [
        "[2:28]\nHow can you disbelieve in Allah?"
    ]
