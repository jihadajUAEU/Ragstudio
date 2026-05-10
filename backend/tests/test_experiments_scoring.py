import pytest
from ragstudio.db.models import Experiment, IndexRecord, Run, SettingsProfile
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.evaluation import EvaluationCaseIn
from ragstudio.schemas.runtime import RuntimeHealthCheck
from ragstudio.services.runtime_profile_service import RuntimeProfileService
from ragstudio.services.runtime_types import RuntimeQueryResult
from ragstudio.services.scoring_service import ScoringService
from sqlalchemy import select


class FakeExperimentRuntime:
    async def query(self, query, *, document_ids, query_config):
        return RuntimeQueryResult(
            answer=f"alpha beta answer for {query}",
            sources=[
                {
                    "chunk_id": "experiment-runtime-chunk",
                    "document_id": document_ids[0],
                    "text": "alpha beta answer",
                    "source_location": {},
                    "metadata": {"native_scope": True},
                }
            ],
            chunk_traces=[{"rank": 1, "inclusion_status": "prompt-included"}],
            reranker_traces=[],
            timings={"runtime_query_ms": 2},
            token_metadata={"prompt_tokens": 8},
        )


class FakeExperimentRuntimeFactory:
    def __init__(self, *_args, **_kwargs):
        self.runtime = FakeExperimentRuntime()

    def build(self, profile):
        return self.runtime


class PassingRuntimeHealthService:
    def __init__(self, *_args, **_kwargs):
        pass

    async def check(self, profile):
        return []

    def blocking_failures(self, checks):
        return []


class FakeRuntimeAnswerService:
    async def answer(self, query, evidence, profile):
        return f"alpha beta answer for {query}", {"prompt_tokens": 8}


async def _create_experiment_dependencies(client):
    upload = await client.post(
        "/api/documents",
        files={"file": ("experiment.txt", b"alpha beta answer", "text/plain")},
        data={"parser_mode": "local_fallback", "domain_metadata": "{}"},
    )
    variant = await client.post(
        "/api/variants", json={"name": "Balanced", "preset": "balanced", "parameters": {}}
    )
    evaluation = await client.post(
        "/api/evaluation-sets/import?name=Experiment",
        files={
            "file": (
                "cases.csv",
                b"id,query,expected_answer,must_include,must_avoid\n"
                b"one,alpha,alpha beta,alpha,forbidden\n",
                "text/csv",
            )
        },
    )
    return upload.json()["id"], variant.json()["id"], evaluation.json()["id"]


async def _configure_ready_runtime(client, document_id: str) -> None:
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
        await session.flush()
        profile = await RuntimeProfileService(session, app.state.settings).get_active_profile()
        session.add(
            IndexRecord(
                document_id=document_id,
                runtime_profile_id=profile.id,
                status=StageStatus.SUCCEEDED.value,
                index_shape=profile.index_shape,
                chunk_count=1,
            )
        )
        await session.commit()


async def _assert_experiment_rejected_without_rows(client, name: str) -> None:
    transport = client._transport
    async with transport.app.state.session_factory() as session:
        experiments = await session.execute(select(Experiment).where(Experiment.name == name))
        runs = await session.execute(select(Run).where(Run.experiment_id.is_not(None)))

    assert experiments.scalars().all() == []
    assert runs.scalars().all() == []


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
async def test_create_experiment_runs_cases_and_persists_runs(client, monkeypatch):
    monkeypatch.setattr(
        "ragstudio.services.query_service.RAGAnythingRuntimeFactory",
        FakeExperimentRuntimeFactory,
    )
    monkeypatch.setattr(
        "ragstudio.services.query_service.RuntimeHealthService",
        PassingRuntimeHealthService,
    )
    monkeypatch.setattr(
        "ragstudio.services.retrieval_orchestrator.RuntimeAnswerService",
        FakeRuntimeAnswerService,
    )
    document_id, variant_id, evaluation_id = await _create_experiment_dependencies(client)
    await _configure_ready_runtime(client, document_id)

    response = await client.post(
        "/api/experiments",
        json={
            "name": "Smoke experiment",
            "document_ids": [document_id],
            "evaluation_set_id": evaluation_id,
            "variant_ids": [variant_id],
            "objective": {"metric": "total"},
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "Smoke experiment"
    assert len(payload["runs"]) == 1
    assert payload["runs"][0]["status"] == "succeeded"
    assert "alpha" in payload["runs"][0]["answer"].lower()
    assert len(payload["scores"]) == 1
    assert payload["scores"][0]["run_id"] == payload["runs"][0]["id"]
    assert payload["scores"][0]["total"] == 100
    assert payload["scores"][0]["details"]["expected_hits"] == ["alpha", "beta"]

    runs = await client.get("/api/runs")
    assert runs.json()["total"] == 1

    experiments = await client.get("/api/experiments")
    assert experiments.status_code == 200
    experiments_payload = experiments.json()
    assert experiments_payload["total"] == 1
    latest_experiment = experiments_payload["items"][0]
    assert latest_experiment["id"] == payload["id"]
    assert latest_experiment["name"] == "Smoke experiment"
    assert latest_experiment["objective"] == {"metric": "total"}
    assert latest_experiment["run_count"] == 1
    assert latest_experiment["score_count"] == 1
    assert "runs" not in latest_experiment
    assert "scores" not in latest_experiment

    experiment_detail = await client.get(f"/api/experiments/{payload['id']}")
    assert experiment_detail.status_code == 200
    assert experiment_detail.json() == payload


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
async def test_create_experiment_prevalidates_missing_variant_without_persisting_rows(
    client, reindex_document
):
    upload = await client.post(
        "/api/documents",
        files={"file": ("validation.txt", b"alpha beta answer", "text/plain")},
        data={"parser_mode": "local_fallback", "domain_metadata": "{}"},
    )
    document_id = upload.json()["id"]
    await reindex_document(document_id)
    evaluation = await client.post(
        "/api/evaluation-sets/import?name=Validation",
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
            "name": "Bad variant",
            "document_ids": [document_id],
            "evaluation_set_id": evaluation.json()["id"],
            "variant_ids": ["missing-variant"],
            "objective": {},
        },
    )

    assert response.status_code == 404

    transport = client._transport
    async with transport.app.state.session_factory() as session:
        experiments = await session.execute(
            select(Experiment).where(Experiment.name == "Bad variant")
        )
        runs = await session.execute(select(Run).where(Run.experiment_id.is_not(None)))

    assert experiments.scalars().all() == []
    assert runs.scalars().all() == []


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

    transport = client._transport
    async with transport.app.state.session_factory() as session:
        experiments = await session.execute(
            select(Experiment).where(Experiment.name == "Bad document")
        )
        runs = await session.execute(select(Run).where(Run.experiment_id.is_not(None)))

    assert experiments.scalars().all() == []
    assert runs.scalars().all() == []


@pytest.mark.asyncio
async def test_create_experiment_rejects_missing_runtime_profile_without_persisting_rows(client):
    document_id, variant_id, evaluation_id = await _create_experiment_dependencies(client)

    response = await client.post(
        "/api/experiments",
        json={
            "name": "Missing runtime profile",
            "document_ids": [document_id],
            "evaluation_set_id": evaluation_id,
            "variant_ids": [variant_id],
            "objective": {},
        },
    )

    assert response.status_code == 409
    assert "runtime_profile" in response.json()["detail"]
    await _assert_experiment_rejected_without_rows(client, "Missing runtime profile")


@pytest.mark.asyncio
async def test_create_experiment_rejects_fallback_runtime_without_persisting_rows(client):
    document_id, variant_id, evaluation_id = await _create_experiment_dependencies(client)
    transport = client._transport
    async with transport.app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="fallback",
                llm_model="fallback",
                embedding_model="fallback",
                storage_backend="fallback_local",
                runtime_mode="fallback",
            )
        )
        await session.commit()

    response = await client.post(
        "/api/experiments",
        json={
            "name": "Fallback runtime",
            "document_ids": [document_id],
            "evaluation_set_id": evaluation_id,
            "variant_ids": [variant_id],
            "objective": {},
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "runtime_mode" in detail
    assert "Runtime mode 'fallback'" in detail
    await _assert_experiment_rejected_without_rows(client, "Fallback runtime")


@pytest.mark.asyncio
async def test_create_experiment_rejects_blocking_runtime_health_without_persisting_rows(
    client,
    monkeypatch,
):
    class BlockingRuntimeHealthService:
        def __init__(self, *_args, **_kwargs):
            pass

        async def check(self, profile):
            return [
                RuntimeHealthCheck(
                    name="pgvector",
                    status="failed",
                    severity="blocking",
                    detail="PGVector health check failed.",
                )
            ]

        def blocking_failures(self, checks):
            return [item for item in checks if item.status == "failed"]

    monkeypatch.setattr(
        "ragstudio.services.query_service.RuntimeHealthService",
        BlockingRuntimeHealthService,
    )
    document_id, variant_id, evaluation_id = await _create_experiment_dependencies(client)
    transport = client._transport
    async with transport.app.state.session_factory() as session:
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
        await session.commit()

    response = await client.post(
        "/api/experiments",
        json={
            "name": "Blocked runtime health",
            "document_ids": [document_id],
            "evaluation_set_id": evaluation_id,
            "variant_ids": [variant_id],
            "objective": {},
        },
    )

    assert response.status_code == 409
    assert "PGVector health check failed" in response.json()["detail"]
    await _assert_experiment_rejected_without_rows(client, "Blocked runtime health")


@pytest.mark.asyncio
async def test_create_experiment_prevalidates_runtime_index_without_persisting_rows(
    client,
    monkeypatch,
):
    class PassingHealthService:
        def __init__(self, *_args, **_kwargs):
            pass

        async def check(self, profile):
            return []

        def blocking_failures(self, checks):
            return []

    monkeypatch.setattr(
        "ragstudio.services.query_service.RuntimeHealthService",
        PassingHealthService,
    )
    upload = await client.post(
        "/api/documents",
        files={"file": ("runtime-experiment.txt", b"alpha beta answer", "text/plain")},
    )
    document_id = upload.json()["id"]
    variant = await client.post(
        "/api/variants", json={"name": "Runtime Balanced", "preset": "balanced", "parameters": {}}
    )
    evaluation = await client.post(
        "/api/evaluation-sets/import?name=RuntimeValidation",
        files={
            "file": (
                "cases.csv",
                b"id,query,expected_answer\none,alpha,alpha beta\n",
                "text/csv",
            )
        },
    )

    transport = client._transport
    async with transport.app.state.session_factory() as session:
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
        await session.commit()

    response = await client.post(
        "/api/experiments",
        json={
            "name": "Missing runtime index",
            "document_ids": [document_id],
            "evaluation_set_id": evaluation.json()["id"],
            "variant_ids": [variant.json()["id"]],
            "objective": {},
        },
    )

    assert response.status_code == 404
    assert "Runtime index not found" in response.json()["detail"]

    async with transport.app.state.session_factory() as session:
        experiments = await session.execute(
            select(Experiment).where(Experiment.name == "Missing runtime index")
        )
        runs = await session.execute(select(Run).where(Run.experiment_id.is_not(None)))

    assert experiments.scalars().all() == []
    assert runs.scalars().all() == []
