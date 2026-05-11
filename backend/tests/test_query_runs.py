import pytest
from ragstudio.db.models import Document, IndexRecord, SettingsProfile, Variant
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.runtime import RuntimeHealthCheck
from ragstudio.services.runtime_profile_service import RuntimeProfileService
from ragstudio.services.runtime_types import RuntimeQueryResult


class FakeRuntime:
    def __init__(self, result: RuntimeQueryResult | None = None):
        self.result = result

    async def query(self, query, *, document_ids, query_config):
        if self.result is not None:
            return self.result
        return RuntimeQueryResult(
            answer=f"runtime route: {query}",
            sources=[
                {
                    "chunk_id": "runtime-chunk-1",
                    "document_id": document_ids[0],
                    "text": f"runtime route: {query}",
                    "source_location": {},
                    "metadata": {"native_scope": True},
                }
            ],
            chunk_traces=[{"rank": 1, "inclusion_status": "prompt-included"}],
            reranker_traces=[{"rank": 1, "score": 0.75}],
            timings={"runtime_query_ms": 3},
            token_metadata={"prompt_tokens": 9},
        )

    async def index_document(self, artifact_path):
        return []

    async def delete_document_index(self, document_id):
        return None

    def capability_report(self):
        return {"active_backend": "runtime", "raganything_available": True}


class FakeRuntimeFactory:
    def __init__(self, *_args, **_kwargs):
        self.runtime = FakeRuntime()

    def build(self, profile):
        return self.runtime


class FakeRuntimeAnswerService:
    async def answer(self, query, evidence, profile):
        return f"runtime route: {query}", {"prompt_tokens": 9}


class PassingHealthService:
    def __init__(self, *_args, **_kwargs):
        pass

    async def check(self, profile):
        return []

    def blocking_failures(self, checks):
        return []


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
async def test_query_invalid_document_id_returns_error_without_persisting_runs(client):
    variant = await client.post(
        "/api/variants",
        json={"name": "Document Missing", "preset": "balanced", "parameters": {}},
    )

    response = await client.post(
        "/api/query",
        json={
            "query": "missing document",
            "document_ids": ["missing-document"],
            "variant_ids": [variant.json()["id"]],
        },
    )

    assert response.status_code == 404
    runs = await client.get("/api/runs")
    assert runs.json()["total"] == 0
@pytest.mark.asyncio
async def test_query_route_uses_runtime_profile_when_configured(client, monkeypatch):
    monkeypatch.setattr(
        "ragstudio.services.query_service.RAGAnythingRuntimeFactory",
        FakeRuntimeFactory,
    )
    monkeypatch.setattr(
        "ragstudio.services.query_service.RuntimeHealthService",
        PassingHealthService,
    )
    monkeypatch.setattr(
        "ragstudio.services.retrieval_orchestrator.RuntimeAnswerService",
        FakeRuntimeAnswerService,
    )
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
            )
        )
        document = Document(
            filename="runtime.txt",
            content_type="text/plain",
            sha256="runtime-route-query",
            artifact_path=str(app.state.settings.data_dir / "runtime.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        variant = Variant(name="Runtime Route", preset="balanced", parameters={"top_k": 7})
        session.add_all([document, variant])
        await session.flush()
        profile = await RuntimeProfileService(session, app.state.settings).get_active_profile()
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status=StageStatus.SUCCEEDED.value,
                index_shape=profile.index_shape,
                chunk_count=1,
            )
        )
        await session.commit()
        document_id = document.id
        variant_id = variant.id

    response = await client.post(
        "/api/query",
        json={
            "query": "runtime question",
            "document_ids": [document_id],
            "variant_ids": [variant_id],
        },
    )

    assert response.status_code == 200
    run = response.json()["runs"][0]
    assert run["status"] == "succeeded"
    assert run["answer"] == "runtime route: runtime question"
    assert run["runtime_profile_id"] == "default"
    assert run["query_config"]["top_k"] == 7
    assert run["query_config"]["parser"] == "mineru"
    assert run["timings"]["runtime_query_ms"] == 3
    assert run["token_metadata"]["prompt_tokens"] == 9


@pytest.mark.asyncio
async def test_query_route_fails_unsupported_scoped_native_query(client, monkeypatch):
    runtime_result = RuntimeQueryResult(
        answer="",
        sources=[],
        error=(
            "LightRAG vector storage does not support storage-level "
            "full_doc_id filtering."
        ),
        error_type="native_document_scope_unsupported",
        timings={"runtime_query_ms": 7, "native_scoped_query": True},
    )

    class ScopedUnsupportedRuntimeFactory:
        def __init__(self, *_args, **_kwargs):
            pass

        def build(self, profile):
            return FakeRuntime(runtime_result)

    monkeypatch.setattr(
        "ragstudio.services.query_service.RAGAnythingRuntimeFactory",
        ScopedUnsupportedRuntimeFactory,
    )
    monkeypatch.setattr(
        "ragstudio.services.query_service.RuntimeHealthService",
        PassingHealthService,
    )
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
            )
        )
        document = Document(
            filename="runtime-scoped-unsupported.txt",
            content_type="text/plain",
            sha256="runtime-scoped-unsupported-query",
            artifact_path=str(app.state.settings.data_dir / "runtime-scoped-unsupported.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        variant = Variant(
            name="Runtime Scoped Unsupported",
            preset="balanced",
            parameters={"top_k": 7},
        )
        session.add_all([document, variant])
        await session.flush()
        profile = await RuntimeProfileService(session, app.state.settings).get_active_profile()
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status=StageStatus.SUCCEEDED.value,
                index_shape=profile.index_shape,
                chunk_count=1,
            )
        )
        await session.commit()
        document_id = document.id
        variant_id = variant.id

    response = await client.post(
        "/api/query",
        json={
            "query": "scoped runtime?",
            "document_ids": [document_id],
            "variant_ids": [variant_id],
        },
    )

    assert response.status_code == 200
    run = response.json()["runs"][0]
    assert run["status"] == "failed"
    assert run["error_type"] == "native_document_scope_unsupported"
    assert "full_doc_id filtering" in run["error"]
    assert run["answer"] == ""
    assert run["sources"] == []
    assert run["chunk_traces"] == []
    assert run["timings"]["runtime_query_ms"] == 7
    assert run["timings"]["native_scoped_query"] is True
    assert run["timings"]["native_stage_ms"] >= 0
    assert run["timings"]["metadata_ms"] >= 0
    removed_timing_key = "scoped_runtime" + "_fallback"
    assert removed_timing_key not in run["timings"]


@pytest.mark.asyncio
async def test_query_route_returns_failed_run_when_runtime_health_blocks(client, monkeypatch):
    monkeypatch.setattr(
        "ragstudio.services.query_service.RuntimeHealthService",
        BlockingHealthService,
    )
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
            )
        )
        document = Document(
            filename="runtime-blocked-query.txt",
            content_type="text/plain",
            sha256="runtime-blocked-query",
            artifact_path=str(app.state.settings.data_dir / "runtime-blocked-query.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        variant = Variant(name="Runtime Blocked", preset="balanced", parameters={})
        session.add_all([document, variant])
        await session.commit()
        document_id = document.id
        variant_id = variant.id

    response = await client.post(
        "/api/query",
        json={
            "query": "runtime blocked?",
            "document_ids": [document_id],
            "variant_ids": [variant_id],
        },
    )

    assert response.status_code == 200
    run = response.json()["runs"][0]
    assert run["status"] == "failed"
    assert run["runtime_profile_id"] == "default"
    assert run["error_type"] == "runtime_health_blocked"
    error = run["error"].lower()
    assert "raganything" in error or "lightrag" in error or "neo4j" in error
