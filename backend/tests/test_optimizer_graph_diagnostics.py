import pytest
from ragstudio.db.models import Experiment, Run, Score
from ragstudio.schemas.runtime import RuntimeHealthCheck
from ragstudio.services.diagnostics_service import DiagnosticsService
from ragstudio.services.runtime_factory import RuntimeUnavailableError


@pytest.mark.asyncio
async def test_optimizer_recommends_best_variant_from_experiment_runs(client):
    upload = await client.post(
        "/api/documents",
        files={"file": ("optimizer.txt", b"alpha beta answer", "text/plain")},
    )
    document_id = upload.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")
    first = await client.post(
        "/api/variants", json={"name": "First", "preset": "balanced", "parameters": {}}
    )
    second = await client.post(
        "/api/variants", json={"name": "Second", "preset": "balanced", "parameters": {}}
    )
    evaluation = await client.post(
        "/api/evaluation-sets/import?name=Optimizer",
        files={
            "file": (
                "cases.csv",
                b"id,query,expected_answer,must_include\none,alpha,alpha beta,alpha\n",
                "text/csv",
            )
        },
    )
    experiment = await client.post(
        "/api/experiments",
        json={
            "name": "Optimizer experiment",
            "document_ids": [document_id],
            "evaluation_set_id": evaluation.json()["id"],
            "variant_ids": [first.json()["id"], second.json()["id"]],
            "objective": {"metric": "total"},
        },
    )

    response = await client.post(
        "/api/optimizer", json={"experiment_id": experiment.json()["id"], "objective": {}}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_variant_id"] in {first.json()["id"], second.json()["id"]}
    assert payload["selected_run_id"]
    assert set(payload["tried_variant_ids"]) == {first.json()["id"], second.json()["id"]}


@pytest.mark.asyncio
async def test_optimizer_aggregates_scores_per_variant_across_runs(client):
    transport = client._transport
    async with transport.app.state.session_factory() as session:
        experiment = Experiment(
            name="Aggregate optimizer experiment",
            document_ids=[],
            evaluation_set_id="eval",
            variant_ids=["spiky", "steady"],
            objective={"metric": "total"},
        )
        session.add(experiment)
        await session.flush()
        runs = [
            Run(
                variant_id="spiky",
                experiment_id=experiment.id,
                query="q1",
                status="succeeded",
                answer="great",
            ),
            Run(
                variant_id="spiky",
                experiment_id=experiment.id,
                query="q2",
                status="succeeded",
                answer="poor",
            ),
            Run(
                variant_id="steady",
                experiment_id=experiment.id,
                query="q1",
                status="succeeded",
                answer="good",
            ),
            Run(
                variant_id="steady",
                experiment_id=experiment.id,
                query="q2",
                status="succeeded",
                answer="good",
            ),
        ]
        session.add_all(runs)
        await session.flush()
        session.add_all(
            [
                Score(run_id=runs[0].id, total=100, details={"total": 100}),
                Score(run_id=runs[1].id, total=0, details={"total": 0}),
                Score(run_id=runs[2].id, total=60, details={"total": 60}),
                Score(run_id=runs[3].id, total=60, details={"total": 60}),
            ]
        )
        await session.commit()
        experiment_id = experiment.id

    response = await client.post(
        "/api/optimizer", json={"experiment_id": experiment_id, "objective": {}}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_variant_id"] == "steady"
    assert payload["selected_run_id"] in {runs[2].id, runs[3].id}
    assert "average score 60.00" in payload["explanation"]
    summaries = {item["variant_id"]: item for item in payload["candidate_summaries"]}
    assert summaries["spiky"]["average_score"] == 50
    assert summaries["spiky"]["total_score"] == 100
    assert summaries["steady"]["average_score"] == 60
    assert summaries["steady"]["total_score"] == 120


@pytest.mark.asyncio
async def test_optimizer_empty_runs_returns_no_runs_explanation(client):
    transport = client._transport
    async with transport.app.state.session_factory() as session:
        experiment = Experiment(
            name="Empty experiment",
            document_ids=[],
            evaluation_set_id="eval",
            variant_ids=[],
            objective={},
        )
        session.add(experiment)
        await session.commit()
        await session.refresh(experiment)
        experiment_id = experiment.id

    response = await client.post(f"/api/optimizer/{experiment_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_variant_id"] is None
    assert payload["selected_run_id"] is None
    assert "No runs" in payload["explanation"]


@pytest.mark.asyncio
async def test_graph_returns_adapter_graph_shape(client):
    response = await client.get("/api/graph")

    assert response.status_code == 200
    assert response.json() == {"nodes": [], "edges": []}


@pytest.mark.asyncio
async def test_graph_returns_conflict_when_native_graph_unavailable(client, monkeypatch):
    class ReadyRuntimeHealthService:
        def __init__(self, session, *, verify_storage):
            self.session = session
            self.verify_storage = verify_storage

        async def check(self, profile):
            return []

        def blocking_failures(self, checks):
            return []

    class BrokenRuntime:
        async def graph(self):
            raise RuntimeUnavailableError("Neo4j is not reachable")

    class BrokenRuntimeFactory:
        def __init__(self, settings):
            self.settings = settings

        def build(self, profile):
            return BrokenRuntime()

    monkeypatch.setattr(
        "ragstudio.services.graph_service.RAGAnythingRuntimeFactory",
        BrokenRuntimeFactory,
    )
    monkeypatch.setattr(
        "ragstudio.services.graph_service.RuntimeHealthService",
        ReadyRuntimeHealthService,
    )

    settings = await client.put(
        "/api/settings/default",
        json={
            "provider": "openai-compatible",
            "runtime_mode": "runtime",
            "llm_model": "gpt-4o",
            "embedding_model": "text-embedding-3-large",
            "storage_backend": "postgres_pgvector_neo4j",
        },
    )
    assert settings.status_code == 200

    response = await client.get("/api/graph")

    assert response.status_code == 409
    assert response.json()["detail"] == "Neo4j is not reachable"


@pytest.mark.asyncio
async def test_graph_returns_conflict_when_runtime_health_blocks(client, monkeypatch):
    class BlockingRuntimeHealthService:
        def __init__(self, session, *, verify_storage):
            self.session = session
            self.verify_storage = verify_storage

        async def check(self, profile):
            return [
                RuntimeHealthCheck(
                    name="pgvector",
                    status="failed",
                    severity="blocking",
                    detail="PGVector health check failed.",
                ),
                RuntimeHealthCheck(
                    name="neo4j",
                    status="ok",
                    detail="Neo4j connectivity and authentication succeeded.",
                ),
            ]

        def blocking_failures(self, checks):
            return [item for item in checks if item.status == "failed"]

    class UnusedRuntimeFactory:
        def __init__(self, settings):
            self.settings = settings

        def build(self, profile):
            raise AssertionError("runtime graph should not be built when health fails")

    monkeypatch.setattr(
        "ragstudio.services.graph_service.RAGAnythingRuntimeFactory",
        UnusedRuntimeFactory,
    )
    monkeypatch.setattr(
        "ragstudio.services.graph_service.RuntimeHealthService",
        BlockingRuntimeHealthService,
    )

    settings = await client.put(
        "/api/settings/default",
        json={
            "provider": "openai-compatible",
            "runtime_mode": "runtime",
            "llm_model": "gpt-4o",
            "embedding_model": "text-embedding-3-large",
            "storage_backend": "postgres_pgvector_neo4j",
        },
    )
    assert settings.status_code == 200

    response = await client.get("/api/graph")

    assert response.status_code == 409
    assert "PGVector health check failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_graph_returns_conflict_when_neo4j_health_blocks(client, monkeypatch):
    class BlockingRuntimeHealthService:
        def __init__(self, session, *, verify_storage):
            self.session = session
            self.verify_storage = verify_storage

        async def check(self, profile):
            return [
                RuntimeHealthCheck(
                    name="pgvector",
                    status="ok",
                    detail="PGVector extension and schema are reachable.",
                ),
                RuntimeHealthCheck(
                    name="neo4j",
                    status="failed",
                    severity="blocking",
                    detail="Neo4j URI is not configured.",
                ),
            ]

        def blocking_failures(self, checks):
            return [item for item in checks if item.status == "failed"]

    class UnusedRuntimeFactory:
        def __init__(self, settings):
            self.settings = settings

        def build(self, profile):
            raise AssertionError("runtime graph should not be built when health fails")

    monkeypatch.setattr(
        "ragstudio.services.graph_service.RAGAnythingRuntimeFactory",
        UnusedRuntimeFactory,
    )
    monkeypatch.setattr(
        "ragstudio.services.graph_service.RuntimeHealthService",
        BlockingRuntimeHealthService,
    )

    settings = await client.put(
        "/api/settings/default",
        json={
            "provider": "openai-compatible",
            "runtime_mode": "runtime",
            "llm_model": "gpt-4o",
            "embedding_model": "text-embedding-3-large",
            "storage_backend": "postgres_pgvector_neo4j",
        },
    )
    assert settings.status_code == 200

    response = await client.get("/api/graph")

    assert response.status_code == 409
    assert "Neo4j URI is not configured" in response.json()["detail"]


@pytest.mark.asyncio
async def test_diagnostics_returns_capabilities_and_dependency_status(client):
    response = await client.get("/api/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert "raganything_available" in payload["capabilities"]
    assert "fallback_active" in payload["capabilities"]
    assert payload["capabilities"]["indexing"] is True
    assert payload["capabilities"]["query"] is True
    assert payload["overall_status"] == "fallback"
    assert "raganything" in payload["dependency_status"]
    if payload["capabilities"]["raganything_available"]:
        assert any(
            "Default runtime profile is not configured" in warning
            for warning in payload["warnings"]
        )
    else:
        assert any("./scripts/setup.sh" in warning for warning in payload["warnings"])


@pytest.mark.asyncio
async def test_diagnostics_warns_when_graph_is_disabled_by_fallback_mode(client):
    response = await client.put(
        "/api/settings/default",
        json={
            "provider": "openai-compatible",
            "runtime_mode": "fallback",
            "llm_model": "gpt-4o",
            "embedding_model": "text-embedding-3-large",
            "storage_backend": "fallback_local",
        },
    )
    assert response.status_code == 200

    diagnostics = await client.get("/api/diagnostics")

    assert diagnostics.status_code == 200
    payload = diagnostics.json()
    assert payload["capabilities"]["graph"] is False
    assert any(
        "Graph is unavailable because fallback mode" in warning
        for warning in payload["warnings"]
    )


@pytest.mark.asyncio
async def test_diagnostics_reports_native_dependency_status_for_runtime_mode(client):
    class ReadyRuntimeHealthService:
        async def check(self, profile):
            return [
                RuntimeHealthCheck(
                    name="raganything",
                    status="ok",
                    detail="RAG-Anything package is importable.",
                ),
                RuntimeHealthCheck(
                    name="lightrag",
                    status="ok",
                    detail="LightRAG package is importable.",
                ),
                RuntimeHealthCheck(
                    name="neo4j",
                    status="ok",
                    detail="Neo4j connectivity and authentication succeeded.",
                ),
            ]

        def blocking_failures(self, checks):
            return []

    settings = await client.put(
        "/api/settings/default",
        json={
            "provider": "openai-compatible",
            "runtime_mode": "runtime",
            "llm_model": "gpt-4o",
            "embedding_model": "text-embedding-3-large",
            "storage_backend": "postgres_pgvector_neo4j",
        },
    )
    assert settings.status_code == 200

    transport = client._transport
    async with transport.app.state.session_factory() as session:
        payload = await DiagnosticsService(
            session,
            transport.app.state.settings,
            health_service=ReadyRuntimeHealthService(),
        ).get_diagnostics()

    assert payload.capabilities["fallback_active"] is False
    assert payload.capabilities["graph"] is True
    assert payload.dependency_status["active_backend"] == "runtime"
    assert payload.dependency_status["indexing"] == "raganything"
    assert payload.dependency_status["query"] == "raganything"
    assert payload.dependency_status["graph"] == "neo4j"
    assert payload.dependency_status["scoped_query"] is False
    assert (
        payload.dependency_status["scoped_query_detail"]
        == "Native RAG-Anything query cannot yet enforce selected document_ids."
    )


@pytest.mark.asyncio
async def test_diagnostics_requires_runtime_packages_for_native_graph(client):
    class MissingPackageHealthService:
        async def check(self, profile):
            return [
                RuntimeHealthCheck(
                    name="raganything",
                    status="failed",
                    severity="blocking",
                    detail="RAG-Anything package is not importable.",
                ),
                RuntimeHealthCheck(
                    name="lightrag",
                    status="ok",
                    detail="LightRAG package is importable.",
                ),
                RuntimeHealthCheck(
                    name="neo4j",
                    status="ok",
                    detail="Neo4j connectivity and authentication succeeded.",
                ),
            ]

        def blocking_failures(self, checks):
            return [item for item in checks if item.status == "failed"]

    settings = await client.put(
        "/api/settings/default",
        json={
            "provider": "openai-compatible",
            "runtime_mode": "runtime",
            "llm_model": "gpt-4o",
            "embedding_model": "text-embedding-3-large",
            "storage_backend": "postgres_pgvector_neo4j",
        },
    )
    assert settings.status_code == 200

    transport = client._transport
    async with transport.app.state.session_factory() as session:
        payload = await DiagnosticsService(
            session,
            transport.app.state.settings,
            health_service=MissingPackageHealthService(),
        ).get_diagnostics()

    assert payload.capabilities["graph"] is False
    assert payload.dependency_status["graph"] == "unavailable"
    assert payload.overall_status == "failed"


def test_diagnostics_suppresses_missing_dependency_warning_when_package_available():
    class AvailableFallbackAdapter:
        def capability_report(self):
            return {
                "raganything_available": True,
                "active_backend": "fallback",
                "indexing": "line_split_fallback",
                "query": "simple_fallback",
                "graph": "placeholder",
            }

    payload = DiagnosticsService(adapter=AvailableFallbackAdapter()).get_diagnostics()

    assert payload.dependency_status["raganything"] == "available"
    assert payload.capabilities["fallback_active"] is True
    assert payload.warnings == []
