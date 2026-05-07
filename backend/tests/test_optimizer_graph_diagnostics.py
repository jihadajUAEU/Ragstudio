import pytest

from ragstudio.db.models import Experiment


@pytest.mark.asyncio
async def test_optimizer_recommends_best_variant_from_experiment_runs(client):
    upload = await client.post(
        "/api/documents",
        files={"file": ("optimizer.txt", b"alpha beta answer", "text/plain")},
    )
    document_id = upload.json()["id"]
    await client.post(f"/api/chunks/index/{document_id}")
    first = await client.post("/api/variants", json={"name": "First", "preset": "balanced", "parameters": {}})
    second = await client.post("/api/variants", json={"name": "Second", "preset": "balanced", "parameters": {}})
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

    response = await client.post("/api/optimizer", json={"experiment_id": experiment.json()["id"], "objective": {}})

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_variant_id"] in {first.json()["id"], second.json()["id"]}
    assert payload["selected_run_id"]
    assert set(payload["tried_variant_ids"]) == {first.json()["id"], second.json()["id"]}


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
async def test_diagnostics_returns_capabilities_and_fallback_warning(client):
    response = await client.get("/api/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert "raganything_available" in payload["capabilities"]
    assert "fallback_active" in payload["capabilities"]
    assert "raganything" in payload["dependency_status"]
    assert any("fallback" in warning.lower() for warning in payload["warnings"])
