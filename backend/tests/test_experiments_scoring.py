import pytest
from ragstudio.db.models import Document, EvaluationSet, Run, SettingsProfile, Variant
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.evaluation import EvaluationCaseIn
from ragstudio.schemas.experiments import ExperimentIn
from ragstudio.services.experiment_service import ExperimentService
from ragstudio.services.query_service import QueryService
from ragstudio.services.retrieval_evidence import OrchestratedAnswer
from ragstudio.services.scoring_service import ScoringService


def test_scoring_service_scores_expected_include_and_avoid_terms():
    case = EvaluationCaseIn(
        id="case-1",
        query="What is included?",
        expected_answer="alpha beta",
        must_include=["alpha"],
        must_avoid=["forbidden"],
    )
    run = Run(id="run-1", variant_id="variant-1", query=case.query, answer="Alpha beta answer")

    score = ScoringService().score(run, case)

    assert score.total == 100
    assert score.details["scoreable"] is True
    assert score.details["expected_hits"] == ["alpha", "beta"]
    assert score.details["must_include_missing"] == []
    assert score.details["must_avoid_hits"] == []


def test_scoring_service_penalizes_missing_and_avoided_terms():
    case = EvaluationCaseIn(
        id="case-1",
        query="What is included?",
        expected_answer="alpha beta",
        must_include=["gamma"],
        must_avoid=["forbidden"],
    )
    run = Run(id="run-1", variant_id="variant-1", query=case.query, answer="Alpha forbidden answer")

    score = ScoringService().score(run, case)

    assert score.total < 50
    assert score.details["scoreable"] is True
    assert score.details["must_include_missing"] == ["gamma"]
    assert score.details["must_avoid_hits"] == ["forbidden"]


def test_scoring_service_marks_rubric_only_case_unscoreable():
    case = EvaluationCaseIn(
        id="case-1",
        query="Explain the answer.",
        expected_structure={"sections": ["summary", "evidence"]},
        rubric={"grounding": "Answer should cite evidence."},
    )

    score = ScoringService().score_answer("A structured answer with evidence.", case)

    assert score["total"] == 0
    assert score["scoreable"] is False
    assert score["reason"] == (
        "No expected_answer, must_include, or must_avoid signals were provided."
    )


@pytest.mark.asyncio
async def test_create_experiment_missing_evaluation_set_returns_404(client):
    response = await client.post(
        "/api/experiments",
        json={
            "name": "Missing eval",
            "document_ids": [],
            "evaluation_set_id": "missing",
            "variant_ids": [],
            "objective": {},
        },
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_experiment_prevalidates_missing_document_without_persisting_rows(client):
    variant = await client.post(
        "/api/variants", json={"name": "Balanced", "preset": "balanced", "parameters": {}}
    )
    evaluation = await client.post(
        "/api/evaluation-sets/import?name=MissingDocument",
        files={
            "file": (
                "cases.csv",
                b"id,query,expected_answer\none,alpha,alpha beta\n",
                "text/csv",
            )
        },
    )

    response = await client.post(
        "/api/experiments",
        json={
            "name": "Bad document",
            "document_ids": ["missing-document"],
            "evaluation_set_id": evaluation.json()["id"],
            "variant_ids": [variant.json()["id"]],
            "objective": {},
        },
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_experiment_allows_degraded_metadata_fallback(client, monkeypatch):
    app = client._transport.app
    query_configs: list[dict] = []

    class PassingHealthService:
        def __init__(self, *_args, **_kwargs):
            pass

        async def check(self, profile):
            return []

        def blocking_failures(self, checks):
            return []

    class FakeRuntimeFactory:
        def __init__(self, *_args, **_kwargs):
            pass

        def build(self, profile):
            return object()

    class MetadataFallbackOrchestrator:
        async def query(
            self,
            query,
            *,
            runtime,
            profile,
            document_ids,
            variant_id,
            query_config,
        ):
            query_configs.append(query_config)
            return OrchestratedAnswer(
                answer="alpha beta",
                sources=[{"document_id": document_ids[0], "text": "alpha beta"}],
                chunk_traces=[{"stage": "metadata"}],
                reranker_traces=[],
                timings={"metadata_ms": 1},
                token_metadata={"prompt_tokens": 2},
            )

    monkeypatch.setattr(
        "ragstudio.services.query_service.RuntimeHealthService",
        PassingHealthService,
    )
    monkeypatch.setattr(
        "ragstudio.services.query_service.RAGAnythingRuntimeFactory",
        FakeRuntimeFactory,
    )
    monkeypatch.setattr(
        QueryService,
        "_retrieval_orchestrator",
        lambda self: MetadataFallbackOrchestrator(),
    )

    async with app.state.session_factory() as session:
        document = Document(
            filename="degraded.txt",
            content_type="text/plain",
            sha256="experiment-degraded-sha",
            artifact_path=str(app.state.settings.data_dir / "degraded.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        variant = Variant(name="Runtime", preset="balanced", parameters={})
        evaluation_set = EvaluationSet(
            name="Degraded",
            cases=[
                {
                    "id": "case-1",
                    "query": "alpha?",
                    "expected_answer": "alpha beta",
                }
            ],
        )
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
        session.add_all([document, variant, evaluation_set])
        await session.commit()

        result = await ExperimentService(
            session,
            app.state.settings.data_dir,
            settings=app.state.settings,
        ).create(
            ExperimentIn(
                name="Allows degraded fallback",
                document_ids=[document.id],
                evaluation_set_id=evaluation_set.id,
                variant_ids=[variant.id],
                objective={},
            )
        )

    assert len(result.runs) == 1
    assert result.runs[0].status == StageStatus.SUCCEEDED
    assert result.runs[0].timings["index_degraded"] is True
    assert result.scores[0].total == 100
    assert query_configs[0]["retrieval_mode"] == "metadata"
