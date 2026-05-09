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
            "id": f"reference:2:255-topic:throne_verse-mentions-document:{document.id}",
            "source": "reference:2:255",
            "target": "topic:throne_verse",
            "type": "mentions",
            "properties": {"document_id": document.id, "page": 12},
        }
    ]


@pytest.mark.asyncio
async def test_graph_service_namespaces_chunk_local_relationship_nodes(client):
    from ragstudio.db.models import Chunk, Document
    from ragstudio.schemas.common import StageStatus
    from ragstudio.services.graph_service import GraphService

    app = client._transport.app
    async with app.state.session_factory() as session:
        first_document = Document(
            filename="relationships-one.txt",
            content_type="text/plain",
            sha256="relationships-graph-one",
            artifact_path=str(app.state.settings.data_dir / "relationships-one.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        second_document = Document(
            filename="relationships-two.txt",
            content_type="text/plain",
            sha256="relationships-graph-two",
            artifact_path=str(app.state.settings.data_dir / "relationships-two.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add_all([first_document, second_document])
        await session.flush()
        session.add_all(
            [
                Chunk(
                    document_id=first_document.id,
                    text="First document chunk.",
                    source_location={"page": 1},
                    metadata_json={
                        "relationship_metadata": {
                            "graph_relationships": [
                                {
                                    "source": "chunk:0",
                                    "target": "topic:shared",
                                    "type": "mentions",
                                    "source_label": "First chunk",
                                    "target_label": "Shared topic",
                                }
                            ]
                        }
                    },
                ),
                Chunk(
                    document_id=second_document.id,
                    text="Second document chunk.",
                    source_location={"page": 2},
                    metadata_json={
                        "relationship_metadata": {
                            "graph_relationships": [
                                {
                                    "source": "chunk:0",
                                    "target": "topic:shared",
                                    "type": "mentions",
                                    "source_label": "Second chunk",
                                    "target_label": "Shared topic",
                                }
                            ]
                        }
                    },
                ),
            ]
        )
        await session.commit()

        graph = await GraphService(session, app.state.settings).get_graph()

    chunk_nodes = [node for node in graph.nodes if node["id"].endswith(":chunk:0")]
    assert len(chunk_nodes) == 2
    assert {node["properties"]["document_id"] for node in chunk_nodes} == {
        first_document.id,
        second_document.id,
    }
    assert {node["properties"]["page"] for node in chunk_nodes} == {1, 2}
    assert {node["id"] for node in graph.nodes if node["id"] == "topic:shared"} == {
        "topic:shared"
    }

    chunk_edges = [edge for edge in graph.edges if edge["target"] == "topic:shared"]
    assert len(chunk_edges) == 2
    assert {edge["properties"]["document_id"] for edge in chunk_edges} == {
        first_document.id,
        second_document.id,
    }
    assert {edge["properties"]["page"] for edge in chunk_edges} == {1, 2}
    assert len({edge["source"] for edge in chunk_edges}) == 2


@pytest.mark.asyncio
async def test_graph_service_preserves_global_relationship_provenance_per_document(client):
    from ragstudio.db.models import Chunk, Document
    from ragstudio.schemas.common import StageStatus
    from ragstudio.services.graph_service import GraphService

    app = client._transport.app
    async with app.state.session_factory() as session:
        first_document = Document(
            filename="global-relationships-one.txt",
            content_type="text/plain",
            sha256="global-relationships-one",
            artifact_path=str(app.state.settings.data_dir / "global-relationships-one.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        second_document = Document(
            filename="global-relationships-two.txt",
            content_type="text/plain",
            sha256="global-relationships-two",
            artifact_path=str(app.state.settings.data_dir / "global-relationships-two.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add_all([first_document, second_document])
        await session.flush()
        session.add_all(
            [
                Chunk(
                    document_id=first_document.id,
                    text="First global relationship.",
                    source_location={"page": 113, "document_id": "overwritten"},
                    metadata_json={
                        "relationship_metadata": {
                            "graph_relationships": [
                                {
                                    "source": "ref:113:1",
                                    "target": "ref:113:2",
                                    "type": "next_ayah",
                                    "source_label": "113:1",
                                    "target_label": "113:2",
                                }
                            ]
                        }
                    },
                ),
                Chunk(
                    document_id=second_document.id,
                    text="Second global relationship.",
                    source_location={"page": 114, "label": "overwritten"},
                    metadata_json={
                        "relationship_metadata": {
                            "graph_relationships": [
                                {
                                    "source": "ref:113:1",
                                    "target": "ref:113:2",
                                    "type": "next_ayah",
                                    "source_label": "113:1",
                                    "target_label": "113:2",
                                }
                            ]
                        }
                    },
                ),
            ]
        )
        await session.commit()

        graph = await GraphService(session, app.state.settings).get_graph()

    assert {node["id"] for node in graph.nodes} == {"ref:113:1", "ref:113:2"}
    source_node = next(node for node in graph.nodes if node["id"] == "ref:113:1")
    target_node = next(node for node in graph.nodes if node["id"] == "ref:113:2")
    assert source_node["properties"]["label"] == "113:1"
    assert target_node["properties"]["label"] == "113:2"
    assert set(source_node["properties"]["document_ids"]) == {
        first_document.id,
        second_document.id,
    }
    assert set(target_node["properties"]["document_ids"]) == {
        first_document.id,
        second_document.id,
    }
    source_locations = {
        tuple(sorted(location.items())) for location in source_node["properties"]["locations"]
    }
    assert source_locations == {
        tuple(sorted({"document_id": first_document.id, "page": 113}.items())),
        tuple(
            sorted(
                {
                    "document_id": second_document.id,
                    "page": 114,
                    "label": "overwritten",
                }.items()
            )
        ),
    }

    edges = {edge["id"]: edge for edge in graph.edges}
    assert edges == {
        f"ref:113:1-ref:113:2-next_ayah-document:{first_document.id}": {
            "id": f"ref:113:1-ref:113:2-next_ayah-document:{first_document.id}",
            "source": "ref:113:1",
            "target": "ref:113:2",
            "type": "next_ayah",
            "properties": {"page": 113, "document_id": first_document.id},
        },
        f"ref:113:1-ref:113:2-next_ayah-document:{second_document.id}": {
            "id": f"ref:113:1-ref:113:2-next_ayah-document:{second_document.id}",
            "source": "ref:113:1",
            "target": "ref:113:2",
            "type": "next_ayah",
            "properties": {
                "page": 114,
                "label": "overwritten",
                "document_id": second_document.id,
            },
        },
    }


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
async def test_graph_returns_fallback_relationships_when_native_graph_unavailable(
    client, monkeypatch
):
    from ragstudio.db.models import Chunk, Document
    from ragstudio.schemas.common import StageStatus

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

    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="runtime-fallback-relationships.txt",
            content_type="text/plain",
            sha256="runtime-fallback-relationships",
            artifact_path=str(app.state.settings.data_dir / "runtime-fallback-relationships.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="Runtime fallback relationship chunk.",
                source_location={"page": 7},
                metadata_json={
                    "relationship_metadata": {
                        "graph_relationships": [
                            {
                                "source": "chunk:0",
                                "target": "topic:runtime_fallback",
                                "type": "mentions",
                                "source_label": "Runtime chunk",
                                "target_label": "Runtime fallback",
                            }
                        ]
                    }
                },
            )
        )
        await session.commit()

    response = await client.get("/api/graph")

    assert response.status_code == 200
    payload = response.json()
    chunk_node = next(node for node in payload["nodes"] if node["id"].endswith(":chunk:0"))
    assert chunk_node["properties"] == {
        "page": 7,
        "label": "Runtime chunk",
        "document_id": document.id,
    }
    assert any(node["id"] == "topic:runtime_fallback" for node in payload["nodes"])
    assert payload["edges"] == [
        {
            "id": f"{chunk_node['id']}-topic:runtime_fallback-mentions",
            "source": chunk_node["id"],
            "target": "topic:runtime_fallback",
            "type": "mentions",
            "properties": {"page": 7, "document_id": document.id},
        }
    ]


@pytest.mark.asyncio
async def test_graph_returns_fallback_relationships_when_native_graph_is_empty(
    client, monkeypatch
):
    from ragstudio.db.models import Chunk, Document
    from ragstudio.schemas.common import StageStatus

    class ReadyRuntimeHealthService:
        def __init__(self, session, *, verify_storage):
            self.session = session
            self.verify_storage = verify_storage

        async def check(self, profile):
            return []

        def blocking_failures(self, checks):
            return []

    class EmptyRuntime:
        async def graph(self):
            return {"nodes": [], "edges": []}

    class EmptyRuntimeFactory:
        def __init__(self, settings):
            self.settings = settings

        def build(self, profile):
            return EmptyRuntime()

    monkeypatch.setattr(
        "ragstudio.services.graph_service.RAGAnythingRuntimeFactory",
        EmptyRuntimeFactory,
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

    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="runtime-empty-graph-relationships.txt",
            content_type="text/plain",
            sha256="runtime-empty-graph-relationships",
            artifact_path=str(app.state.settings.data_dir / "runtime-empty-graph-relationships.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="Runtime empty graph fallback relationship chunk.",
                source_location={"page": 8},
                metadata_json={
                    "relationship_metadata": {
                        "graph_relationships": [
                            {
                                "source": "reference:8:1",
                                "target": "topic:empty_runtime",
                                "type": "mentions",
                                "source_label": "8:1",
                                "target_label": "Empty runtime",
                            }
                        ]
                    }
                },
            )
        )
        await session.commit()

    response = await client.get("/api/graph")

    assert response.status_code == 200
    payload = response.json()
    assert {node["id"] for node in payload["nodes"]} == {
        "reference:8:1",
        "topic:empty_runtime",
    }
    assert payload["edges"] == [
        {
            "id": f"reference:8:1-topic:empty_runtime-mentions-document:{document.id}",
            "source": "reference:8:1",
            "target": "topic:empty_runtime",
            "type": "mentions",
            "properties": {"page": 8, "document_id": document.id},
        }
    ]


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
