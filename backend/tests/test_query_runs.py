import pytest
from ragstudio.db.models import Document, IndexRecord, SettingsProfile, Variant
from ragstudio.schemas.common import StageStatus
from ragstudio.services.runtime_profile_service import RuntimeProfileService
from ragstudio.services.runtime_types import RuntimeQueryResult


class FakeRuntime:
    async def query(self, query, *, document_ids, query_config):
        return RuntimeQueryResult(
            answer=f"runtime route: {query}",
            sources=[{"document_id": document_ids[0]}],
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
    def __init__(self):
        self.runtime = FakeRuntime()

    def build(self, profile):
        return self.runtime


class PassingHealthService:
    async def check(self, profile):
        return []

    def blocking_failures(self, checks):
        return []


@pytest.mark.asyncio
async def test_query_creates_run_with_answer_and_chunk_trace(client):
    upload = await client.post(
        "/api/documents",
        files={"file": ("sample.txt", b"alpha answer source", "text/plain")},
    )
    document_id = upload.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")
    variant = await client.post(
        "/api/variants",
        json={"name": "Balanced", "preset": "balanced", "parameters": {}},
    )

    response = await client.post(
        "/api/query",
        json={
            "query": "alpha?",
            "document_ids": [document_id],
            "variant_ids": [variant.json()["id"]],
        },
    )

    assert response.status_code == 200
    run = response.json()["runs"][0]
    assert run["status"] == "succeeded"
    assert "alpha" in run["answer"]
    assert run["sources"][0]["document_id"] == document_id
    assert run["chunk_traces"][0]["inclusion_status"] == "prompt-included"
    assert run["timings"]["search_ms"] >= 0


@pytest.mark.asyncio
async def test_list_runs_returns_persisted_query_runs(client):
    upload = await client.post(
        "/api/documents",
        files={"file": ("history.txt", b"history answer", "text/plain")},
    )
    document_id = upload.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")
    variant = await client.post(
        "/api/variants",
        json={"name": "History", "preset": "balanced", "parameters": {}},
    )
    query = await client.post(
        "/api/query",
        json={
            "query": "history",
            "document_ids": [document_id],
            "variant_ids": [variant.json()["id"]],
        },
    )
    run_id = query.json()["runs"][0]["id"]

    response = await client.get("/api/runs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == run_id
    assert payload["items"][0]["answer"]


@pytest.mark.asyncio
async def test_query_invalid_variant_id_returns_error_without_persisting_runs(client):
    upload = await client.post(
        "/api/documents",
        files={"file": ("variant-missing.txt", b"variant missing", "text/plain")},
    )
    document_id = upload.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")

    response = await client.post(
        "/api/query",
        json={
            "query": "missing variant",
            "document_ids": [document_id],
            "variant_ids": ["missing-variant"],
        },
    )

    assert response.status_code == 404
    runs = await client.get("/api/runs")
    assert runs.json()["total"] == 0


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
async def test_query_creates_one_run_per_variant(client):
    upload = await client.post(
        "/api/documents",
        files={"file": ("multi.txt", b"shared answer", "text/plain")},
    )
    document_id = upload.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")
    first = await client.post(
        "/api/variants", json={"name": "First", "preset": "balanced", "parameters": {}}
    )
    second = await client.post(
        "/api/variants", json={"name": "Second", "preset": "balanced", "parameters": {}}
    )
    variant_ids = [first.json()["id"], second.json()["id"]]

    response = await client.post(
        "/api/query",
        json={"query": "shared", "document_ids": [document_id], "variant_ids": variant_ids},
    )

    assert response.status_code == 200
    runs = response.json()["runs"]
    assert [run["variant_id"] for run in runs] == variant_ids
    assert all(run["status"] == "succeeded" for run in runs)

    persisted_runs = await client.get("/api/runs")
    assert persisted_runs.json()["total"] == 2


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
    assert run["reranker_traces"][0]["score"] == 0.75
    assert run["token_metadata"]["prompt_tokens"] == 9


@pytest.mark.asyncio
async def test_query_route_returns_failed_run_when_runtime_health_blocks(client):
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
