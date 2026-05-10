import pytest
from ragstudio.db.models import Experiment, Run, Score
from ragstudio.schemas.runtime import RuntimeHealthCheck
from ragstudio.services.diagnostics_service import DiagnosticsService
from ragstudio.services.optimizer_service import OptimizerService
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
    assert summaries["spiky"]["score_status"] == "scoreable"
    assert summaries["steady"]["average_score"] == 60
    assert summaries["steady"]["total_score"] == 120
    assert summaries["steady"]["scoreable_run_count"] == 2


@pytest.mark.asyncio
async def test_optimizer_ranks_unscored_success_below_formal_score(client):
    transport = client._transport
    async with transport.app.state.session_factory() as session:
        experiment = Experiment(
            name="Unscored optimizer experiment",
            document_ids=[],
            evaluation_set_id="eval",
            variant_ids=["formal", "unscored"],
            objective={"metric": "total"},
        )
        session.add(experiment)
        await session.flush()
        scored_run = Run(
            variant_id="formal",
            experiment_id=experiment.id,
            query="q1",
            status="succeeded",
            answer="formally scored",
            sources=[{"id": "source-1"}],
        )
        unscored_run = Run(
            variant_id="unscored",
            experiment_id=experiment.id,
            query="q1",
            status="succeeded",
            answer="many sources but no score",
            sources=[{"id": f"source-{index}"} for index in range(20)],
        )
        session.add_all([scored_run, unscored_run])
        await session.flush()
        session.add(Score(run_id=scored_run.id, total=40, details={"total": 40}))
        await session.commit()
        experiment_id = experiment.id
        scored_run_id = scored_run.id

    response = await client.post(
        "/api/optimizer", json={"experiment_id": experiment_id, "objective": {}}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_variant_id"] == "formal"
    assert payload["selected_run_id"] == scored_run_id
    summaries = {item["variant_id"]: item for item in payload["candidate_summaries"]}
    assert set(summaries) == {"formal", "unscored"}
    assert summaries["formal"]["average_score"] == 40
    assert summaries["formal"]["score_status"] == "scoreable"
    assert summaries["unscored"]["average_score"] is None
    assert summaries["unscored"]["total_score"] is None
    assert summaries["unscored"]["best_run_score"] is None
    assert summaries["unscored"]["score_status"] == "unscored"
    assert summaries["unscored"]["unscored_run_count"] == 1


def test_optimizer_run_score_failed_and_error_runs_are_zero():
    service = OptimizerService(session=None)

    failed_score = service._run_score(
        Run(variant_id="failed", query="q1", status="failed", answer="", sources=[]),
        score=None,
    )
    error_score = service._run_score(
        Run(
            variant_id="error",
            query="q1",
            status="succeeded",
            answer="",
            sources=[],
            error="boom",
        ),
        score=None,
    )
    unscored_score = service._run_score(
        Run(variant_id="unscored", query="q1", status="succeeded", answer="", sources=[]),
        score=None,
    )

    assert failed_score.score == 0
    assert failed_score.rank_group == 0
    assert error_score.score == 0
    assert error_score.rank_group == 0
    assert unscored_score.score is None
    assert unscored_score.rank_group == 1


@pytest.mark.asyncio
async def test_optimizer_prefers_unscored_success_over_failed_run(client):
    transport = client._transport
    async with transport.app.state.session_factory() as session:
        experiment = Experiment(
            name="Failure bucket optimizer experiment",
            document_ids=[],
            evaluation_set_id="eval",
            variant_ids=["failed", "unscored"],
            objective={"metric": "total"},
        )
        session.add(experiment)
        await session.flush()
        failed_run = Run(
            variant_id="failed",
            experiment_id=experiment.id,
            query="q1",
            status="failed",
            answer="",
            error="boom",
        )
        unscored_run = Run(
            variant_id="unscored",
            experiment_id=experiment.id,
            query="q1",
            status="succeeded",
            answer="ok",
        )
        session.add_all([failed_run, unscored_run])
        await session.commit()
        experiment_id = experiment.id

    response = await client.post(
        "/api/optimizer", json={"experiment_id": experiment_id, "objective": {}}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_variant_id"] == "unscored"
    summaries = {item["variant_id"]: item for item in payload["candidate_summaries"]}
    assert summaries["failed"]["score_status"] == "failed"
    assert summaries["failed"]["average_score"] is None
    assert summaries["failed"]["best_run_score"] is None
    assert summaries["failed"]["failed_run_count"] == 1
    assert summaries["unscored"]["score_status"] == "unscored"


def test_optimizer_treats_unscoreable_persisted_score_as_unscored():
    service = OptimizerService(session=None)
    run = Run(variant_id="rubric", query="q1", status="succeeded", answer="ok")
    score = Score(run_id=run.id, total=0, details={"scoreable": False})

    run_score = service._run_score(run, score)

    assert run_score.score is None
    assert run_score.rank_group == 1
    assert run_score.unscored_success is True


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
async def test_graph_returns_empty_fallback_detail(client):
    response = await client.get("/api/graph")

    assert response.status_code == 200
    assert response.json() == {
        "nodes": [],
        "edges": [],
        "detail": "No runtime graph or relationship metadata is available.",
    }


@pytest.mark.asyncio
async def test_graph_fallback_scans_only_relationship_metadata_chunks(client):
    from ragstudio.db.models import Chunk, Document
    from ragstudio.schemas.common import StageStatus
    from ragstudio.services.graph_service import GraphService

    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="graph.txt",
            content_type="text/plain",
            sha256="graph-filtered",
            artifact_path=str(app.state.settings.data_dir / "graph.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add_all(
            [
                Chunk(document_id=document.id, text="plain", metadata_json={}),
                Chunk(
                    document_id=document.id,
                    text="relationship",
                    metadata_json={
                        "relationship_metadata": {
                            "graph_relationships": [
                                {"source": "a", "target": "b", "type": "related"}
                            ]
                        }
                    },
                ),
            ]
        )
        await session.commit()

        graph = await GraphService(session, app.state.settings).get_graph()

    assert {node["id"] for node in graph.nodes} == {"a", "b"}
    assert graph.edges[0]["id"] == "a-b-related"
    assert graph.detail is None


@pytest.mark.asyncio
async def test_graph_fallback_limits_after_relationship_metadata_filter(client):
    from datetime import UTC, datetime, timedelta

    from ragstudio.db.models import Chunk, Document
    from ragstudio.schemas.common import StageStatus
    from ragstudio.services.graph_service import GraphService

    app = client._transport.app
    now = datetime.now(UTC)
    async with app.state.session_factory() as session:
        document = Document(
            filename="graph-limit.txt",
            content_type="text/plain",
            sha256="graph-limit-filtered",
            artifact_path=str(app.state.settings.data_dir / "graph-limit.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add_all(
            [
                Chunk(
                    document_id=document.id,
                    text="newer plain",
                    metadata_json={},
                    created_at=now,
                    updated_at=now,
                ),
                Chunk(
                    document_id=document.id,
                    text="older relationship",
                    metadata_json={
                        "relationship_metadata": {
                            "graph_relationships": [
                                {"source": "older-a", "target": "older-b", "type": "related"}
                            ]
                        }
                    },
                    created_at=now - timedelta(days=1),
                    updated_at=now - timedelta(days=1),
                ),
            ]
        )
        await session.commit()

        graph = await GraphService(session, app.state.settings)._relationship_metadata_graph(
            limit=1
        )

    assert {node["id"] for node in graph["nodes"]} == {"older-a", "older-b"}
    assert graph["edges"][0]["id"] == "older-a-older-b-related"
    assert graph["detail"] is None


@pytest.mark.asyncio
async def test_graph_service_builds_fallback_graph_from_chunk_relationship_metadata(client):
    from ragstudio.db.models import Chunk, Document
    from ragstudio.schemas.common import StageStatus
    from ragstudio.services.graph_service import GraphService

    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="relationships.txt",
            content_type="text/plain",
            sha256="relationships-graph",
            artifact_path=str(app.state.settings.data_dir / "relationships.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="Surah 2 ayah 255 mentions the Throne Verse.",
                source_location={"page": 12},
                metadata_json={
                    "relationship_metadata": {
                        "graph_relationships": [
                            {
                                "source": "reference:2:255",
                                "target": "topic:throne_verse",
                                "type": "mentions",
                                "source_label": "2:255",
                                "target_label": "Throne Verse",
                            }
                        ]
                    }
                },
            )
        )
        await session.commit()

        graph = await GraphService(session, app.state.settings).get_graph()

    assert {node["id"] for node in graph.nodes} == {"reference:2:255", "topic:throne_verse"}
    assert graph.edges == [
        {
            "id": "reference:2:255-topic:throne_verse-mentions",
            "source": "reference:2:255",
            "target": "topic:throne_verse",
            "type": "mentions",
            "properties": {"document_id": document.id, "page": 12},
        }
    ]


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
    assert payload.dependency_status["native_scoped_query"] is True
    assert payload.dependency_status["scoped_query"] == "raganything_full_doc_id_vector"
    assert (
        payload.dependency_status["scoped_query_detail"]
        == "Selected-document native query uses LightRAG chunk full_doc_id "
        "filtering with vector/naive retrieval; graph modes are not used "
        "under document scope."
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
    assert payload.dependency_status["native_scoped_query"] is False
    assert payload.dependency_status["scoped_query"] == "unavailable"
    assert (
        payload.dependency_status["scoped_query_detail"]
        == "Selected-document native query is unavailable until runtime dependencies "
        "are healthy."
    )
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
