import pytest
from ragstudio.db.models import Experiment, Run, SettingsProfile
from ragstudio.schemas.evaluation import EvaluationCaseIn
from ragstudio.services.scoring_service import ScoringService
from sqlalchemy import select


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
async def test_create_experiment_runs_cases_and_persists_runs(client):
    upload = await client.post(
        "/api/documents",
        files={"file": ("experiment.txt", b"alpha beta answer", "text/plain")},
    )
    document_id = upload.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")
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

    response = await client.post(
        "/api/experiments",
        json={
            "name": "Smoke experiment",
            "document_ids": [document_id],
            "evaluation_set_id": evaluation.json()["id"],
            "variant_ids": [variant.json()["id"]],
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
async def test_create_experiment_prevalidates_missing_variant_without_persisting_rows(client):
    upload = await client.post(
        "/api/documents",
        files={"file": ("validation.txt", b"alpha beta answer", "text/plain")},
    )
    document_id = upload.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")
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
async def test_create_experiment_prevalidates_runtime_index_without_persisting_rows(
    client,
    monkeypatch,
):
    class PassingHealthService:
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
