import pytest
from ragstudio.db.models import (
    Chunk,
    Document,
    GraphProjectionRecord,
    IndexRecord,
    SettingsProfile,
    Variant,
)
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn
from ragstudio.schemas.query import QueryIn
from ragstudio.schemas.runtime import RuntimeHealthCheck
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_persistence_service import ChunkPersistenceService
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.query_service import (
    QueryResourceNotFoundError,
    QueryRuntimeReadinessError,
    QueryService,
)
from ragstudio.services.retrieval_orchestrator import RetrievalOrchestrator
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_profile_service import RuntimeProfileService
from ragstudio.services.runtime_types import RuntimeQueryResult


class FakeRuntime:
    def __init__(self, result: RuntimeQueryResult | None = None):
        self.result = result
        self.query_calls = 0

    def capability_report(self):
        return {"active_backend": "runtime", "raganything_available": True}

    async def delete_document_index(self, document_id):
        return None

    async def index_document(self, artifact_path):
        return []

    async def query(self, query, *, document_ids, query_config):
        self.query_calls += 1
        if self.result is not None:
            return self.result
        return RuntimeQueryResult(
            answer=f"runtime answer: {query}",
            sources=([{"document_id": document_ids[0], "text": "source"}] if document_ids else []),
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
        return [item for item in checks if item.status == "failed" and item.severity == "blocking"]


class FakeChunkSearchService:
    async def search(self, search_in):
        return type(
            "SearchResult",
            (),
            {
                "items": [
                    type(
                        "ChunkLike",
                        (),
                        {
                            "id": "metadata-1",
                            "document_id": (
                                search_in.document_ids[0] if search_in.document_ids else "doc-1"
                            ),
                            "text": "Sahih al-Bukhari\n\n7277 Hadith Collection",
                            "source_location": {"page": 1},
                            "metadata": {"score": 10.0},
                        },
                    )()
                ],
                "total": 1,
            },
        )()


class FakeAnswerService:
    async def answer(self, query, evidence, profile):
        return "Sahih al-Bukhari contains 7277 hadith.", {"prompt_tokens": 12}


class FakeGraphExpansionService:
    async def expand(self, query, *, seeds, profile, document_ids, limit):
        return [], [{"stage": "graph_expansion", "status": "skipped", "reason": "test"}]


class FailingGraphExpansionService:
    async def expand(self, query, *, seeds, profile, document_ids, limit):
        raise RuntimeError("neo4j unavailable")


class FakeRerankerService:
    async def rerank(self, query, chunks, profile):
        return chunks, [{"provider": "disabled", "status": "disabled"}]


async def _create_runtime_records(
    session,
    app,
    *,
    indexed: bool = True,
    index_shape: dict | None = None,
    settings_overrides: dict | None = None,
):
    settings_values = {
        "id": "default",
        "provider": "openai-compatible",
        "llm_model": "gpt-4o",
        "llm_base_url": "http://127.0.0.1:8004/v1",
        "embedding_model": "text-embedding-3-large",
        "embedding_base_url": "http://127.0.0.1:8001/v1",
        "storage_backend": "postgres_pgvector_neo4j",
        "runtime_mode": "runtime",
    }
    settings_values.update(settings_overrides or {})
    settings = SettingsProfile(**settings_values)
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


def _real_retrieval_orchestrator() -> RetrievalOrchestrator:
    return RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )


def _graph_failing_retrieval_orchestrator() -> RetrievalOrchestrator:
    return RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FailingGraphExpansionService(),
    )


def _real_chunk_retrieval_orchestrator(session, data_dir) -> RetrievalOrchestrator:
    return RetrievalOrchestrator(
        chunk_service=ChunkService(session, data_dir),
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )


@pytest.mark.asyncio
async def test_query_service_uses_runtime_orchestrator_path(client):
    app = client._transport.app
    runtime = FakeRuntime()
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(session, app, indexed=False)
        profile = await RuntimeProfileService(session, app.state.settings).get_active_profile()
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id=profile.id,
                status=StageStatus.SUCCEEDED.value,
                index_shape={
                    **profile.index_shape,
                    "parser_mode": "mineru_strict",
                    "canonical_chunk_count": 1,
                    "runtime_chunk_count": 1,
                },
                chunk_count=1,
            )
        )
        await session.commit()

        service = QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
            retrieval_orchestrator=_real_retrieval_orchestrator(),
        )
        payload = QueryIn(
            query="What happened?",
            document_ids=[document.id],
            variant_ids=[variant.id],
        )

        await service.preflight_runtime_readiness(payload)
        result = await service.run_query(payload)

    run = result.runs[0]
    assert run.status == StageStatus.SUCCEEDED
    assert run.answer == "Sahih al-Bukhari contains 7277 hadith."
    assert run.runtime_profile_id == "default"
    assert run.document_ids == [document.id]
    assert run.query_config["top_k"] == 12
    assert run.query_config["retrieval_mode"] == "hybrid"
    assert runtime.query_calls == 1
    assert "index_degraded" not in run.timings
    assert run.timings["planner_ms"] >= 0
    assert run.timings["metadata_ms"] >= 0
    assert run.timings["answer_ms"] >= 0
    assert run.reranker_traces[0]["status"] == "disabled"
    assert run.token_metadata["prompt_tokens"] == 12


@pytest.mark.asyncio
async def test_runtime_index_shape_tracks_provider_and_pgvector_target(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="gpt-4o",
                llm_base_url="http://127.0.0.1:8004/v1",
                embedding_provider="vllm_openai",
                embedding_model="text-embedding-3-large",
                embedding_base_url="http://127.0.0.1:8001/v1",
                embedding_dimensions=1536,
                pgvector_schema="rag_custom",
                pgvector_table_prefix="tenant_a",
                storage_backend="postgres_pgvector_neo4j",
                runtime_mode="runtime",
            )
        )
        await session.commit()

        profile = await RuntimeProfileService(session, app.state.settings).get_active_profile()

    assert profile.index_shape["runtime_profile_id"] == "default"
    assert profile.index_shape["embedding_provider"] == "vllm_openai"
    assert profile.index_shape["embedding_model"] == "text-embedding-3-large"
    assert profile.index_shape["embedding_dimensions"] == 1536
    assert profile.index_shape["pgvector_schema"] == "rag_custom"
    assert profile.index_shape["pgvector_table_prefix"] == "tenant_a"


@pytest.mark.asyncio
async def test_query_service_degrades_native_scope_limitation_to_metadata(client):
    app = client._transport.app
    runtime = FakeRuntime(
        RuntimeQueryResult(
            answer="",
            sources=[],
            error=(
                "LightRAG vector storage does not support storage-level "
                "full_doc_id filtering."
            ),
            error_type="native_document_scope_unsupported",
            timings={"runtime_query_ms": 7, "native_scoped_query": True},
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
            retrieval_orchestrator=_real_retrieval_orchestrator(),
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
    assert run.answer == "Sahih al-Bukhari contains 7277 hadith."
    assert run.sources
    assert run.timings["runtime_query_ms"] == 7
    assert run.timings["native_scoped_query"] is True
    assert run.timings["native_stage_ms"] >= 0
    assert run.timings["metadata_ms"] >= 0
    assert run.timings["native_degraded"] is True
    assert run.timings["native_error_type"] == "native_document_scope_unsupported"
    assert "full_doc_id filtering" in run.timings["native_error"]
    assert run.chunk_traces


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
            retrieval_orchestrator=_real_retrieval_orchestrator(),
        ).run_query(QueryIn(query="unscoped?", document_ids=[], variant_ids=[variant.id]))

    run = result.runs[0]
    assert run.status == StageStatus.SUCCEEDED
    assert run.answer == "Sahih al-Bukhari contains 7277 hadith."


@pytest.mark.asyncio
async def test_query_service_degrades_pending_runtime_index_to_metadata(client):
    app = client._transport.app
    runtime = FakeRuntime()
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(session, app, indexed=False)
        profile = await RuntimeProfileService(session, app.state.settings).get_active_profile()
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id=profile.id,
                status=StageStatus.FAILED.value,
                index_shape=profile.index_shape,
                chunk_count=1,
                error="embedding dimension mismatch",
            )
        )
        await ChunkPersistenceService(session).persist(
            document,
            [
                AdapterChunk(
                    text="[19:13] وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً",
                    source_location={"page": 312, "reference": "19:13"},
                    metadata={
                        "preview_ref": "19:13",
                        "reference_metadata": {"references": ["19:13"]},
                        "parser_metadata": {"backend": "mineru"},
                    },
                )
            ],
            options=IndexDocumentIn(
                parser_mode="mineru_strict",
                domain_metadata=DomainMetadata(domain="quran_tafseer", language="arabic"),
            ),
            commit=True,
            runtime_profile_id=profile.id,
            index_shape=profile.index_shape,
        )
        await session.commit()

        result = await QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
            retrieval_orchestrator=_real_chunk_retrieval_orchestrator(
                session,
                app.state.settings.data_dir,
            ),
        ).run_query(
            QueryIn(
                query="حنانا",
                document_ids=[document.id],
                variant_ids=[variant.id],
            )
        )

    run = result.runs[0]
    assert run.status == StageStatus.SUCCEEDED
    assert run.answer == "Sahih al-Bukhari contains 7277 hadith."
    assert run.sources
    assert run.sources[0]["document_id"] == document.id
    assert run.sources[0]["source_location"]["reference"] == "19:13"
    assert runtime.query_calls == 0
    assert run.timings["index_degraded"] is True
    assert run.timings["index_degraded_reason"] == "embedding dimension mismatch"
    assert run.timings["retrieval_mode"] == "metadata_fallback"


@pytest.mark.asyncio
async def test_query_service_surfaces_graph_degradation_while_succeeding(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(session, app)
        session.add(
            GraphProjectionRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status=StageStatus.SUCCEEDED.value,
                node_count=2,
                edge_count=1,
            )
        )
        await session.commit()

        result = await QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(),
            health_service=FakeHealthService(),
            retrieval_orchestrator=_graph_failing_retrieval_orchestrator(),
        ).run_query(
            QueryIn(query="What happened?", document_ids=[document.id], variant_ids=[variant.id])
        )

    run = result.runs[0]
    assert run.status == StageStatus.SUCCEEDED
    assert run.error is None
    assert run.error_type is None
    assert run.timings["graph_degraded"] is True
    assert run.timings["graph_error_type"] == "RuntimeError"
    graph_trace = next(trace for trace in run.chunk_traces if trace["stage"] == "graph_expansion")
    assert graph_trace["status"] == "failed"
    assert graph_trace["reason"] == "RuntimeError"


@pytest.mark.asyncio
async def test_query_service_disables_graph_expansion_when_projection_is_stale(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(session, app)
        session.add(
            GraphProjectionRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status="stale",
                error="Superseded by a newer indexing attempt.",
                node_count=7,
                edge_count=6,
            )
        )
        await session.commit()

        result = await QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(),
            health_service=FakeHealthService(),
            retrieval_orchestrator=_graph_failing_retrieval_orchestrator(),
        ).run_query(
            QueryIn(query="What happened?", document_ids=[document.id], variant_ids=[variant.id])
        )

    run = result.runs[0]
    assert run.status == StageStatus.SUCCEEDED
    assert run.timings["graph_degraded"] is True
    assert run.timings["graph_degraded_reason"] == "Superseded by a newer indexing attempt."
    assert run.timings["graph_expansion_mode"] == "disabled"
    assert run.timings["graph_error_type"] == "graph_projection_not_ready"
    graph_trace = next(trace for trace in run.chunk_traces if trace["stage"] == "graph_expansion")
    assert graph_trace["status"] == "skipped"
    assert graph_trace["reason"] == "graph_projection_not_ready"


@pytest.mark.asyncio
async def test_query_service_degrades_runtime_errors_to_metadata(client):
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
            retrieval_orchestrator=_real_retrieval_orchestrator(),
        ).run_query(QueryIn(query="boom", document_ids=[document.id], variant_ids=[variant.id]))

    run = result.runs[0]
    assert run.status == StageStatus.SUCCEEDED
    assert run.error is None
    assert run.error_type is None
    assert run.answer == "Sahih al-Bukhari contains 7277 hadith."
    assert run.timings["native_degraded"] is True
    assert run.timings["native_error"] == "runtime exploded"
    assert run.timings["native_error_type"] == "runtime_query_error"


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
        ).run_query(QueryIn(query="blocked", document_ids=[document.id], variant_ids=[variant.id]))

    run = result.runs[0]
    assert run.status == StageStatus.FAILED
    assert run.error_type == "runtime_health_blocked"
    assert "raganything" in (run.error or "")


@pytest.mark.asyncio
async def test_query_preflight_rejects_missing_runtime_settings(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="preflight-missing-settings.txt",
            content_type="text/plain",
            sha256="preflight-missing-settings",
            artifact_path=str(app.state.settings.data_dir / "preflight-missing-settings.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        variant = Variant(name="Preflight Missing Settings", preset="balanced", parameters={})
        session.add_all([document, variant])
        await session.commit()

        with pytest.raises(QueryRuntimeReadinessError) as exc_info:
            await QueryService(
                session,
                app.state.settings.data_dir,
            ).preflight_runtime_readiness(
                QueryIn(query="missing", document_ids=[document.id], variant_ids=[variant.id])
            )

    assert exc_info.value.error_type == "runtime_profile_missing"
    assert "Runtime profile settings are not available" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_preflight_rejects_missing_runtime_profile(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="preflight-missing-profile.txt",
            content_type="text/plain",
            sha256="preflight-missing-profile",
            artifact_path=str(app.state.settings.data_dir / "preflight-missing-profile.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        variant = Variant(name="Preflight Missing Profile", preset="balanced", parameters={})
        session.add_all([document, variant])
        await session.commit()

        with pytest.raises(QueryRuntimeReadinessError) as exc_info:
            await QueryService(
                session,
                app.state.settings.data_dir,
                settings=app.state.settings,
            ).preflight_runtime_readiness(
                QueryIn(query="missing", document_ids=[document.id], variant_ids=[variant.id])
            )

    assert exc_info.value.error_type == "runtime_profile_missing"
    assert "runtime_profile" in str(exc_info.value)

@pytest.mark.asyncio
async def test_query_preflight_rejects_blocking_runtime_health(client):
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
        document, variant = await _create_runtime_records(session, app, indexed=False)

        with pytest.raises(QueryRuntimeReadinessError) as exc_info:
            await QueryService(
                session,
                app.state.settings.data_dir,
                settings=app.state.settings,
                health_service=FakeHealthService(checks),
            ).preflight_runtime_readiness(
                QueryIn(query="blocked", document_ids=[document.id], variant_ids=[variant.id])
            )

    assert exc_info.value.error_type == "runtime_health_blocked"
    assert "raganything" in str(exc_info.value)


@pytest.mark.asyncio
async def test_query_preflight_allows_llm_reranker_without_dedicated_endpoint(
    client, monkeypatch
):
    app = client._transport.app

    def fake_import_module(module_name):
        if module_name in {"raganything", "lightrag"}:
            return object()
        raise ModuleNotFoundError(module_name)

    monkeypatch.setattr(
        "ragstudio.services.runtime_health_service.import_module",
        fake_import_module,
    )
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(
            session,
            app,
            indexed=False,
            settings_overrides={
                "reranker_provider": "llm",
                "reranker_base_url": None,
                "enable_rerank": True,
            },
        )

        await QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            health_service=RuntimeHealthService(),
        ).preflight_runtime_readiness(
            QueryIn(query="llm rerank", document_ids=[document.id], variant_ids=[variant.id]),
            validate_index_readiness=False,
        )


@pytest.mark.asyncio
async def test_query_preflight_requires_ready_runtime_index(client):
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
            ).preflight_runtime_readiness(
                QueryIn(query="not indexed", document_ids=[document.id], variant_ids=[variant.id])
            )

    assert exc_info.value.resource == "Runtime index"
    assert exc_info.value.missing_ids == [document.id]


@pytest.mark.asyncio
async def test_query_preflight_rejects_stale_runtime_index_shape(client):
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
            ).preflight_runtime_readiness(
                QueryIn(query="stale index", document_ids=[document.id], variant_ids=[variant.id])
            )

    assert exc_info.value.resource == "Runtime index"
    assert exc_info.value.missing_ids == [document.id]


@pytest.mark.asyncio
async def test_query_service_fast_mode_caps_slow_stages(client):
    app = client._transport.app
    runtime = FakeRuntime()
    async with app.state.session_factory() as session:
        document, variant = await _create_runtime_records(
            session,
            app,
            indexed=False,
            settings_overrides={"enable_rerank": True},
        )
        variant.parameters = {
            "enable_rerank": True,
            "native_query_timeout_ms": 15000,
        }
        profile = await RuntimeProfileService(session, app.state.settings).get_active_profile()
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id=profile.id,
                status=StageStatus.SUCCEEDED.value,
                index_shape=profile.index_shape,
                chunk_count=1,
            )
        )
        await session.commit()

        service = QueryService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
            runtime_factory=FakeFactory(runtime),
            health_service=FakeHealthService(),
            retrieval_orchestrator=_real_retrieval_orchestrator(),
        )
        result = await service.run_query(
            QueryIn(
                query="What happened?",
                document_ids=[document.id],
                variant_ids=[variant.id],
                response_mode="fast",
                answer_budget_ms=1200,
                response_budget_ms=7500,
            )
        )

    run = result.runs[0]
    assert run.status == StageStatus.SUCCEEDED
    assert run.query_config["response_mode"] == "fast"
    assert run.query_config["answer_budget_ms"] == 1200
    assert run.query_config["response_budget_ms"] == 7500
    assert run.query_config["enable_rerank"] is False
    assert run.query_config["native_query_timeout_ms"] == 2500
