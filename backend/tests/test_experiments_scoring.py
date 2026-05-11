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
