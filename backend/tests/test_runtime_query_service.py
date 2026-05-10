import pytest
from ragstudio.db.models import Chunk, Document, IndexRecord, SettingsProfile, Variant
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.query import QueryIn
from ragstudio.schemas.runtime import RuntimeHealthCheck
from ragstudio.services.query_service import QueryResourceNotFoundError, QueryService
from ragstudio.services.retrieval_evidence import OrchestratedAnswer
from ragstudio.services.retrieval_orchestrator import NativeScopedQueryUnsupported
from ragstudio.services.runtime_profile_service import RuntimeProfileService
from ragstudio.services.runtime_types import RuntimeQueryResult


class FakeRuntime:
    def __init__(self, result: RuntimeQueryResult | None = None):
        self.result = result

    def capability_report(self):
        return {"active_backend": "runtime", "raganything_available": True}

    async def delete_document_index(self, document_id):
        return None

    async def index_document(self, artifact_path):
        return []

    async def query(self, query, *, document_ids, query_config):
        if self.result is not None:
            return self.result
        return RuntimeQueryResult(
            answer=f"runtime answer: {query}",
            sources=(
                [{"document_id": document_ids[0], "text": "source"}] if document_ids else []
            ),
            chunk_traces=[{"rank": 1, "inclusion_status": "prompt-included"}],
            reranker_traces=[{"rank": 1, "score": 0.9}],
            timings={"runtime_query_ms": 5},
            token_metadata={"prompt_tokens": 11},
        )


class FakeFactory:
    def __init__(self, runtime: FakeRuntime | None = None):
        self.runtime = runtime or FakeRuntime()

    def build(self, profile):
        return self.runtime


class FakeHealthService:
    def __init__(self, checks: list[RuntimeHealthCheck] | None = None):
        self.checks = checks or []

    async def check(self, profile):
        return self.checks

    def blocking_failures(self, checks):
        return [
            item
            for item in checks
            if item.status == "failed" and item.severity == "blocking"
        ]


class FakeOrchestrator:
    def __init__(
        self,
        *,
        answer: str | None = None,
        sources: list[dict] | None = None,
        chunk_traces: list[dict] | None = None,
        reranker_traces: list[dict] | None = None,
        token_metadata: dict | None = None,
        timings: dict | None = None,
        error: str | None = None,
        error_type: str | None = None,
        raise_native_scope_unsupported: bool = False,
    ):
        self.answer = answer
        self.sources = sources
        self.chunk_traces = chunk_traces
        self.reranker_traces = reranker_traces
        self.token_metadata = token_metadata
        self.timings = timings
        self.error = error
        self.error_type = error_type
        self.raise_native_scope_unsupported = raise_native_scope_unsupported
        self.calls = []

    async def query(self, query, *, runtime, profile, document_ids, variant_id, query_config):
        self.calls.append(
            {
                "query": query,
                "document_ids": document_ids,
                "variant_id": variant_id,
                "query_config": query_config,
            }
        )
        if self.raise_native_scope_unsupported:
            raise NativeScopedQueryUnsupported("native scoped query unsupported")
        return OrchestratedAnswer(
            answer=self.answer if self.answer is not None else f"runtime answer: {query}",
            sources=self.sources
            if self.sources is not None
            else ([{"document_id": document_ids[0], "text": "source"}] if document_ids else []),
            chunk_traces=self.chunk_traces
            if self.chunk_traces is not None
            else [{"rank": 1, "inclusion_status": "prompt-included"}],
            reranker_traces=self.reranker_traces
            if self.reranker_traces is not None
            else [{"rank": 1, "score": 0.9}],
            timings=self.timings if self.timings is not None else {"orchestrated_query": True},
            token_metadata=self.token_metadata
            if self.token_metadata is not None
            else {"prompt_tokens": 11},
            error=self.error,
            error_type=self.error_type,
        )


async def _create_runtime_records(
    session,
    app,
    *,
    indexed: bool = True,
    index_shape: dict | None = None,
):
    settings = SettingsProfile(
        id="default",
        provider="openai-compatible",
        llm_model="gpt-4o",
        llm_base_url="http://127.0.0.1:8004/v1",
        embedding_model="text-embedding-3-large",
        embedding_base_url="http://127.0.0.1:8001/v1",
        storage_backend="postgres_pgvector_neo4j",
        runtime_mode="runtime",
    )
    document = Document(
        filename="doc.txt",
        content_type="text/plain",
        sha256="runtime-query",
        artifact_path=str(app.state.settings.data_dir / "doc.txt"),
        status=StageStatus.SUCCEEDED.value,
    )
    variant = Variant(name="Runtime", preset="balanced", parameters={"top_k": 12})
    session.add_all([settings, document, variant])
    await session.flush()
    if indexed:
        profile = await RuntimeProfileService(session, app.state.settings).get_active_profile()
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status=StageStatus.SUCCEEDED.value,
                index_shape=index_shape if index_shape is not None else profile.index_shape,
                chunk_count=1,
            )
        )
    await session.commit()
    return document, variant


@pytest.mark.asyncio
async def test_query_service_uses_runtime_without_chunk_search(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(session, app)

        result = await QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(),
            health_service=FakeHealthService(),
            retrieval_orchestrator=FakeOrchestrator(),
        ).run_query(
            QueryIn(query="What happened?", document_ids=[document.id], variant_ids=[variant.id])
        )

    run = result.runs[0]
    assert run.status == StageStatus.SUCCEEDED
    assert run.answer == "runtime answer: What happened?"
    assert run.runtime_profile_id == "default"
    assert run.document_ids == [document.id]
    assert run.query_config["top_k"] == 12
    assert run.reranker_traces[0]["score"] == 0.9
    assert run.token_metadata["prompt_tokens"] == 11


@pytest.mark.asyncio
async def test_query_service_records_native_scoped_runtime_success(client):
    app = client._transport.app
    runtime = FakeRuntime(
        RuntimeQueryResult(
            answer="native scoped answer",
            sources=[
                {
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "text": "Sahih al-Bukhari 7277 Hadith Collection",
                    "metadata": {"native_scope": True},
                }
            ],
            chunk_traces=[{"rank": 1, "inclusion_status": "native-scoped"}],
            timings={"runtime_query_ms": 7, "native_scoped_query": True},
        )
    )
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(session, app)

        result = await QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
            retrieval_orchestrator=FakeOrchestrator(
                answer="native scoped answer",
                sources=[
                    {
                        "chunk_id": "chunk-1",
                        "document_id": "doc-1",
                        "text": "Sahih al-Bukhari 7277 Hadith Collection",
                        "metadata": {"native_scope": True},
                    }
                ],
                chunk_traces=[{"rank": 1, "inclusion_status": "native-scoped"}],
                timings={"runtime_query_ms": 7, "native_scoped_query": True},
            ),
        ).run_query(
            QueryIn(
                query="how many hadith in bukhari",
                document_ids=[document.id],
                variant_ids=[variant.id],
            )
        )

    run = result.runs[0]
    assert run.status == StageStatus.SUCCEEDED
    assert run.answer == "native scoped answer"
    assert run.sources[0]["metadata"]["native_scope"] is True
    assert run.timings["native_scoped_query"] is True
    assert "scoped_runtime_fallback" not in run.timings


@pytest.mark.asyncio
async def test_query_service_falls_back_to_mirrored_chunks_for_native_scope_limitation(client):
    app = client._transport.app
    runtime = FakeRuntime(
        RuntimeQueryResult(
            answer="",
            sources=[],
            error=(
                "Native RAG-Anything query cannot yet enforce selected document_ids; "
                "refusing to run an unscoped runtime query."
            ),
            error_type="native_document_scope_unsupported",
        )
    )
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(session, app)
        session.add(
            Chunk(
                document_id=document.id,
                text="Sahih al-Bukhari 7277 Hadith Collection",
                source_location={"page": 1},
                metadata_json={"runtime_profile_id": "default"},
                runtime_profile_id="default",
            )
        )
        await session.commit()

        result = await QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
            retrieval_orchestrator=FakeOrchestrator(raise_native_scope_unsupported=True),
        ).run_query(
            QueryIn(
                query="how many hadith in bukhari",
                document_ids=[document.id],
                variant_ids=[variant.id],
            )
        )

    run = result.runs[0]
    assert run.status == StageStatus.SUCCEEDED
    assert run.error_type is None
    assert run.error is None
    assert "7277 Hadith Collection" in run.answer
    assert run.timings["scoped_runtime_fallback"] is True
    assert run.sources[0]["document_id"] == document.id


@pytest.mark.asyncio
async def test_query_service_allows_unscoped_runtime_query_when_no_documents_requested(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        _, variant = await _create_runtime_records(session, app, indexed=False)

        result = await QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(),
            health_service=FakeHealthService(),
            retrieval_orchestrator=FakeOrchestrator(),
        ).run_query(QueryIn(query="unscoped?", document_ids=[], variant_ids=[variant.id]))

    run = result.runs[0]
    assert run.status == StageStatus.SUCCEEDED
    assert run.answer == "runtime answer: unscoped?"


@pytest.mark.asyncio
async def test_query_service_persists_runtime_errors(client):
    app = client._transport.app
    runtime = FakeRuntime(
        RuntimeQueryResult(
            answer="",
            error="runtime exploded",
            error_type="runtime_query_error",
        )
    )
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(session, app)

        result = await QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
            retrieval_orchestrator=FakeOrchestrator(
                answer="",
                sources=[],
                error="runtime exploded",
                error_type="runtime_query_error",
            ),
        ).run_query(QueryIn(query="boom", document_ids=[document.id], variant_ids=[variant.id]))

    run = result.runs[0]
    assert run.status == StageStatus.FAILED
    assert run.error == "runtime exploded"
    assert run.error_type == "runtime_query_error"


@pytest.mark.asyncio
async def test_query_service_fails_runs_when_runtime_health_blocks(client):
    app = client._transport.app
    checks = [
        RuntimeHealthCheck(
            name="raganything",
            status="failed",
            severity="blocking",
            detail="RAG-Anything package is not installed.",
        )
    ]
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(session, app)

        result = await QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(),
            health_service=FakeHealthService(checks),
        ).run_query(
            QueryIn(query="blocked", document_ids=[document.id], variant_ids=[variant.id])
        )

    run = result.runs[0]
    assert run.status == StageStatus.FAILED
    assert run.error_type == "runtime_health_blocked"
    assert "raganything" in (run.error or "")


@pytest.mark.asyncio
async def test_query_service_requires_ready_runtime_index(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(session, app, indexed=False)

        with pytest.raises(QueryResourceNotFoundError) as exc_info:
            await QueryService(
                session,
                app.state.settings.data_dir,
                settings=app.state.settings,
                runtime_factory=FakeFactory(),
                health_service=FakeHealthService(),
            ).run_query(
                QueryIn(query="not indexed", document_ids=[document.id], variant_ids=[variant.id])
            )

    assert exc_info.value.resource == "Runtime index"
    assert exc_info.value.missing_ids == [document.id]


@pytest.mark.asyncio
async def test_query_service_rejects_stale_runtime_index_shape(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(
            session,
            app,
            index_shape={"embedding_model": "old-model"},
        )

        with pytest.raises(QueryResourceNotFoundError) as exc_info:
            await QueryService(
                session,
                app.state.settings.data_dir,
                settings=app.state.settings,
                runtime_factory=FakeFactory(),
                health_service=FakeHealthService(),
            ).run_query(
                QueryIn(query="stale index", document_ids=[document.id], variant_ids=[variant.id])
            )

    assert exc_info.value.resource == "Runtime index"
    assert exc_info.value.missing_ids == [document.id]
