import pytest

from ragstudio.db.models import Run
from ragstudio.schemas.evaluation import EvaluationCaseIn
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
    assert score.details["must_include_missing"] == ["gamma"]
    assert score.details["must_avoid_hits"] == ["forbidden"]


@pytest.mark.asyncio
async def test_create_experiment_runs_cases_and_persists_runs(client):
    upload = await client.post(
        "/api/documents",
        files={"file": ("experiment.txt", b"alpha beta answer", "text/plain")},
    )
    document_id = upload.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")
    variant = await client.post("/api/variants", json={"name": "Balanced", "preset": "balanced", "parameters": {}})
    evaluation = await client.post(
        "/api/evaluation-sets/import?name=Experiment",
        files={
            "file": (
                "cases.csv",
                b"id,query,expected_answer,must_include,must_avoid\none,alpha,alpha beta,alpha,forbidden\n",
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

    runs = await client.get("/api/runs")
    assert runs.json()["total"] == 1


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
async def test_create_experiment_relies_on_query_validation_for_missing_variant(client):
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
