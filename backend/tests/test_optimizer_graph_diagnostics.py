import pytest
from ragstudio.db.models import Experiment, Run, Score
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.runtime import RuntimeHealthCheck
from ragstudio.services.diagnostics_service import DiagnosticsService
from ragstudio.services.optimizer_service import OptimizerService
from ragstudio.services.runtime_factory import RuntimeUnavailableError


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
async def test_optimizer_prefers_fully_scored_variant_over_partial_high_score_with_failures(client):
    transport = client._transport
    async with transport.app.state.session_factory() as session:
        experiment = Experiment(
            name="Reliability optimizer experiment",
            document_ids=[],
            evaluation_set_id="eval",
            variant_ids=["partial", "reliable"],
            objective={"metric": "total"},
        )
        session.add(experiment)
        await session.flush()
        runs = [
            Run(
                variant_id="partial",
                experiment_id=experiment.id,
                query="q1",
                status="succeeded",
                answer="excellent once",
            ),
            Run(
                variant_id="partial",
                experiment_id=experiment.id,
                query="q2",
                status="failed",
                error="backend timeout",
            ),
            Run(
                variant_id="partial",
                experiment_id=experiment.id,
                query="q3",
                status="failed",
                error="backend timeout",
            ),
            Run(
                variant_id="reliable",
                experiment_id=experiment.id,
                query="q1",
                status="succeeded",
                answer="good",
            ),
            Run(
                variant_id="reliable",
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
                Score(run_id=runs[3].id, total=80, details={"total": 80}),
                Score(run_id=runs[4].id, total=80, details={"total": 80}),
            ]
        )
        await session.commit()
        experiment_id = experiment.id
        reliable_run_ids = {runs[3].id, runs[4].id}

    response = await client.post(
        "/api/optimizer", json={"experiment_id": experiment_id, "objective": {}}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_variant_id"] == "reliable"
    assert payload["selected_run_id"] in reliable_run_ids
    summaries = {item["variant_id"]: item for item in payload["candidate_summaries"]}
    assert summaries["partial"]["score_status"] == "partial"
    assert summaries["partial"]["average_score"] == 100
    assert summaries["partial"]["failed_run_count"] == 2
    assert summaries["reliable"]["score_status"] == "scoreable"
    assert summaries["reliable"]["average_score"] == 80


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

    assert {node["id"] for node in graph.nodes} == {f"{document.id}:a", f"{document.id}:b"}
    assert {tuple(node["labels"]) for node in graph.nodes} == {("RelationshipMetadata",)}
    assert graph.edges[0]["id"] == f"{document.id}:a-b-related"
    assert graph.detail == "Relationship metadata fallback graph."


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

    assert {node["id"] for node in graph["nodes"]} == {
        f"{document.id}:older-a",
        f"{document.id}:older-b",
    }
    assert graph["edges"][0]["id"] == f"{document.id}:older-a-older-b-related"
    assert graph["detail"] == "Relationship metadata fallback graph."


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

    assert {node["id"] for node in graph.nodes} == {
        f"{document.id}:reference:2:255",
        f"{document.id}:topic:throne_verse",
    }
    assert {tuple(node["labels"]) for node in graph.nodes} == {("RelationshipMetadata",)}
    assert graph.edges == [
        {
            "id": f"{document.id}:reference:2:255-topic:throne_verse-mentions",
            "source": f"{document.id}:reference:2:255",
            "target": f"{document.id}:topic:throne_verse",
            "type": "mentions",
            "properties": {
                "document_id": document.id,
                "source_relationship_id": "reference:2:255",
                "target_relationship_id": "topic:throne_verse",
                "page": 12,
            },
        }
    ]
    assert graph.detail == "Relationship metadata fallback graph."


@pytest.mark.asyncio
async def test_graph_fallback_scopes_identical_relationship_ids_by_document(client):
    from ragstudio.db.models import Chunk, Document
    from ragstudio.schemas.common import StageStatus
    from ragstudio.services.graph_service import GraphService

    app = client._transport.app
    async with app.state.session_factory() as session:
        documents = [
            Document(
                filename=f"relationships-{index}.txt",
                content_type="text/plain",
                sha256=f"relationships-shared-{index}",
                artifact_path=str(app.state.settings.data_dir / f"relationships-{index}.txt"),
                status=StageStatus.SUCCEEDED.value,
            )
            for index in range(2)
        ]
        session.add_all(documents)
        await session.flush()
        session.add_all(
            [
                Chunk(
                    document_id=document.id,
                    text=f"Document {index} relationship.",
                    metadata_json={
                        "relationship_metadata": {
                            "graph_relationships": [
                                {
                                    "source": "shared-source",
                                    "target": "shared-target",
                                    "type": "mentions",
                                }
                            ]
                        }
                    },
                )
                for index, document in enumerate(documents)
            ]
        )
        await session.commit()

        graph = await GraphService(session, app.state.settings).get_graph()

    document_ids = {document.id for document in documents}
    assert {node["properties"]["document_id"] for node in graph.nodes} == document_ids
    assert {node["id"] for node in graph.nodes} == {
        f"{document.id}:shared-source" for document in documents
    } | {f"{document.id}:shared-target" for document in documents}
    assert {edge["id"] for edge in graph.edges} == {
        f"{document.id}:shared-source-shared-target-mentions" for document in documents
    }
    assert {edge["properties"]["document_id"] for edge in graph.edges} == document_ids


@pytest.mark.asyncio
async def test_graph_explains_empty_runtime_graph_with_projection_status(
    client,
    monkeypatch,
):
    from ragstudio.db.models import Chunk, Document, GraphProjectionRecord
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
            filename="runtime-empty-graph.txt",
            content_type="text/plain",
            sha256="runtime-empty-graph",
            artifact_path=str(app.state.settings.data_dir / "runtime-empty-graph.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="Related evidence",
                metadata_json={
                    "relationship_metadata": {
                        "graph_relationships": [
                            {"source": "chunk:0", "target": "ref:one", "type": "references"}
                        ]
                    }
                },
            )
        )
        session.add(
            GraphProjectionRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status="failed",
                error="neo4j write failed",
            )
        )
        await session.commit()

    response = await client.get("/api/graph")

    assert response.status_code == 200
    payload = response.json()
    assert {node["id"] for node in payload["nodes"]} == {"chunk:0", "ref:one"}
    assert "Graph projection is not ready" in payload["detail"]
    assert "relationship metadata fallback graph" in payload["detail"]
    assert "Latest graph projection failed: neo4j write failed" in payload["detail"]


@pytest.mark.asyncio
async def test_graph_endpoint_does_not_return_runtime_graph_when_projection_is_stale(
    client,
    monkeypatch,
):
    from ragstudio.db.models import Document, GraphProjectionRecord
    from ragstudio.schemas.common import StageStatus

    class ReadyRuntimeHealthService:
        def __init__(self, session, *, verify_storage):
            self.session = session
            self.verify_storage = verify_storage

        async def check(self, profile):
            return []

        def blocking_failures(self, checks):
            return []

    class StaleRuntime:
        async def graph(self):
            return {
                "nodes": [{"id": "stale-node", "labels": ["Old"], "properties": {}}],
                "edges": [],
            }

    class StaleRuntimeFactory:
        def __init__(self, settings):
            self.settings = settings

        def build(self, profile):
            return StaleRuntime()

    monkeypatch.setattr(
        "ragstudio.services.graph_service.RAGAnythingRuntimeFactory",
        StaleRuntimeFactory,
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
            filename="stale-graph.txt",
            content_type="text/plain",
            sha256="stale-graph",
            artifact_path=str(app.state.settings.data_dir / "stale-graph.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
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

    response = await client.get("/api/graph")

    assert response.status_code == 200
    payload = response.json()
    assert payload["nodes"] == []
    assert payload["edges"] == []
    assert "Graph projection is not ready" in payload["detail"]
    assert "Latest graph projection stale: Superseded by a newer indexing attempt." in payload[
        "detail"
    ]
    assert "stale-node" not in str(payload)


@pytest.mark.asyncio
async def test_graph_endpoint_blocks_stale_projection_even_with_newer_success(
    client,
    monkeypatch,
):
    from datetime import UTC, datetime, timedelta

    from ragstudio.db.models import Document, GraphProjectionRecord
    from ragstudio.schemas.common import StageStatus

    class ReadyRuntimeHealthService:
        def __init__(self, session, *, verify_storage):
            self.session = session
            self.verify_storage = verify_storage

        async def check(self, profile):
            return []

        def blocking_failures(self, checks):
            return []

    class StaleRuntime:
        async def graph(self):
            return {
                "nodes": [{"id": "stale-node", "labels": ["Old"], "properties": {}}],
                "edges": [],
            }

    class StaleRuntimeFactory:
        def __init__(self, settings):
            self.settings = settings

        def build(self, profile):
            return StaleRuntime()

    monkeypatch.setattr(
        "ragstudio.services.graph_service.RAGAnythingRuntimeFactory",
        StaleRuntimeFactory,
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
    now = datetime.now(UTC)
    async with app.state.session_factory() as session:
        stale_document = Document(
            filename="stale-graph-a.txt",
            content_type="text/plain",
            sha256="stale-graph-a",
            artifact_path=str(app.state.settings.data_dir / "stale-graph-a.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        ready_document = Document(
            filename="ready-graph-b.txt",
            content_type="text/plain",
            sha256="ready-graph-b",
            artifact_path=str(app.state.settings.data_dir / "ready-graph-b.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add_all([stale_document, ready_document])
        await session.flush()
        session.add_all(
            [
                GraphProjectionRecord(
                    document_id=stale_document.id,
                    runtime_profile_id="default",
                    status="stale",
                    error="Superseded by a newer indexing attempt.",
                    node_count=7,
                    edge_count=6,
                    created_at=now - timedelta(minutes=5),
                    updated_at=now - timedelta(minutes=5),
                ),
                GraphProjectionRecord(
                    document_id=ready_document.id,
                    runtime_profile_id="default",
                    status="succeeded",
                    node_count=2,
                    edge_count=1,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await session.commit()

    response = await client.get("/api/graph")

    assert response.status_code == 200
    payload = response.json()
    assert payload["nodes"] == []
    assert "Graph projection is not ready" in payload["detail"]
    assert "Latest graph projection stale: Superseded by a newer indexing attempt." in payload[
        "detail"
    ]
    assert "stale-node" not in str(payload)


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
    assert payload["capabilities"]["indexing"] is False
    assert payload["capabilities"]["query"] is False
    assert payload["capabilities"]["graph"] is False
    assert payload["overall_status"] == "ready"
    assert "raganything" in payload["dependency_status"]
    assert payload["dependency_status"]["graph"] == "unavailable"
    if payload["capabilities"]["raganything_available"]:
        assert any(
            "Default runtime profile is not configured" in warning
            for warning in payload["warnings"]
        )
    else:
        assert any("./scripts/setup.sh" in warning for warning in payload["warnings"])


@pytest.mark.asyncio
async def test_diagnostics_reports_stale_running_jobs(client):
    from datetime import timedelta

    from ragstudio.db.models import Job
    from ragstudio.schemas.common import now_utc

    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            Job(
                type="index_document",
                target_id="doc-stale-worker",
                status=StageStatus.RUNNING.value,
                progress=75,
                logs=["Search ready."],
                result={"indexing_stage": {"stage": "search_ready"}},
                worker_id="worker-stale",
                lease_expires_at=now_utc() - timedelta(minutes=5),
                heartbeat_at=now_utc() - timedelta(minutes=10),
            )
        )
        await session.commit()

    response = await client.get("/api/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["dependency_status"]["stale_running_jobs"] == 1
    assert payload["dependency_status"]["ready_index_jobs"] == 0
    assert "1 indexing job has an expired worker lease." in payload["warnings"]


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
    assert payload.dependency_status["native_scoped_query"] == "conditional"
    assert payload.dependency_status["scoped_query"] == "requires_storage_verification"
    assert (
        payload.dependency_status["scoped_query_detail"]
        == "Selected-document native query requires LightRAG chunk storage with "
        "full_doc_id filtering support; the storage backend is verified when "
        "a scoped query initializes LightRAG."
    )


@pytest.mark.asyncio
async def test_diagnostics_treats_disabled_reranker_as_available_runtime(client):
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
                    name="llm",
                    status="ok",
                    detail="LLM base URL is configured.",
                ),
                RuntimeHealthCheck(
                    name="embedding",
                    status="ok",
                    detail="Embedding base URL is configured.",
                ),
                RuntimeHealthCheck(
                    name="reranker",
                    status="skipped",
                    detail="Reranker is disabled for this profile.",
                ),
                RuntimeHealthCheck(
                    name="pgvector",
                    status="ok",
                    detail="PGVector extension and schema are reachable.",
                ),
                RuntimeHealthCheck(
                    name="neo4j",
                    status="ok",
                    detail="Neo4j connectivity and authentication succeeded.",
                ),
                RuntimeHealthCheck(
                    name="parser",
                    status="ok",
                    detail="Parser is configured.",
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

    assert payload.overall_status == "ready"
    assert payload.capabilities["indexing"] is True
    assert payload.capabilities["query"] is True
    assert payload.capabilities["graph"] is True
    assert payload.dependency_status["indexing"] == "raganything"
    assert payload.dependency_status["query"] == "raganything"
    assert payload.dependency_status["graph"] == "neo4j"
    assert payload.dependency_status["scoped_query"] == "requires_storage_verification"


@pytest.mark.asyncio
async def test_diagnostics_treats_required_skipped_check_as_unavailable_runtime(client):
    class SkippedParserHealthService:
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
                    name="llm",
                    status="ok",
                    detail="LLM base URL is configured.",
                ),
                RuntimeHealthCheck(
                    name="embedding",
                    status="ok",
                    detail="Embedding base URL is configured.",
                ),
                RuntimeHealthCheck(
                    name="reranker",
                    status="skipped",
                    detail="Reranker is disabled for this profile.",
                ),
                RuntimeHealthCheck(
                    name="pgvector",
                    status="ok",
                    detail="PGVector extension and schema are reachable.",
                ),
                RuntimeHealthCheck(
                    name="neo4j",
                    status="ok",
                    detail="Neo4j connectivity and authentication succeeded.",
                ),
                RuntimeHealthCheck(
                    name="parser",
                    status="skipped",
                    detail="Parser sidecar is not configured.",
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
            health_service=SkippedParserHealthService(),
        ).get_diagnostics()

    assert payload.overall_status == "degraded"
    assert payload.capabilities["indexing"] is False
    assert payload.capabilities["query"] is False
    assert payload.capabilities["graph"] is False
    assert payload.dependency_status["indexing"] == "unavailable"
    assert payload.dependency_status["query"] == "unavailable"
    assert payload.dependency_status["graph"] == "unavailable"


@pytest.mark.asyncio
async def test_diagnostics_reports_latest_graph_projection_status(client):
    from ragstudio.db.models import Document, GraphProjectionRecord

    class ReadyRuntimeHealthService:
        async def check(self, profile):
            return [
                RuntimeHealthCheck(
                    name="raganything",
                    status="ok",
                    detail="RAG-Anything package is importable.",
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

    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="projection-diagnostics.txt",
            content_type="text/plain",
            sha256="projection-diagnostics",
            artifact_path=str(app.state.settings.data_dir / "projection-diagnostics.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add(
            GraphProjectionRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status="failed",
                error="neo4j write failed",
            )
        )
        await session.commit()

        payload = await DiagnosticsService(
            session,
            app.state.settings,
            health_service=ReadyRuntimeHealthService(),
        ).get_diagnostics()

    assert payload.dependency_status["graph_projection"] == "failed"
    assert payload.dependency_status["graph_projection_detail"] == "neo4j write failed"
    assert any(
        warning == "Graph projection failed: neo4j write failed"
        for warning in payload.warnings
    )


@pytest.mark.asyncio
async def test_diagnostics_scopes_graph_projection_status_to_active_profile(client):
    from datetime import UTC, datetime, timedelta

    from ragstudio.db.models import Document, GraphProjectionRecord

    class ReadyRuntimeHealthService:
        async def check(self, profile):
            return [
                RuntimeHealthCheck(
                    name="raganything",
                    status="ok",
                    detail="RAG-Anything package is importable.",
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

    app = client._transport.app
    created_at = datetime(2026, 5, 10, tzinfo=UTC)
    async with app.state.session_factory() as session:
        document = Document(
            filename="projection-diagnostics-scope.txt",
            content_type="text/plain",
            sha256="projection-diagnostics-scope",
            artifact_path=str(app.state.settings.data_dir / "projection-diagnostics-scope.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        session.add_all(
            [
                GraphProjectionRecord(
                    document_id=document.id,
                    runtime_profile_id="default",
                    status="succeeded",
                    node_count=2,
                    edge_count=1,
                    created_at=created_at,
                ),
                GraphProjectionRecord(
                    document_id=document.id,
                    runtime_profile_id="other-profile",
                    status="failed",
                    error="other profile failed",
                    created_at=created_at + timedelta(minutes=1),
                ),
            ]
        )
        await session.commit()

        payload = await DiagnosticsService(
            session,
            app.state.settings,
            health_service=ReadyRuntimeHealthService(),
        ).get_diagnostics()

    assert payload.dependency_status["graph_projection"] == "succeeded"
    assert payload.dependency_status["graph_projection_detail"] == "2 nodes, 1 edges"
    assert all("other profile failed" not in warning for warning in payload.warnings)


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
                "active_backend": "local_parser",
                "parser": "line_split",
                "indexing": "line_split_local",
            }

    payload = DiagnosticsService(adapter=AvailableFallbackAdapter()).get_diagnostics()

    assert payload.dependency_status["raganything"] == "available"
    assert payload.capabilities["fallback_active"] is True
    assert payload.capabilities["query"] is False
    assert payload.capabilities["graph"] is False
    assert payload.warnings == []
