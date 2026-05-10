import pytest


@pytest.mark.asyncio
async def test_variant_create_and_list(client):
    payload = {
        "name": "High recall graph",
        "preset": "broad",
        "parameters": {"retrieval": {"top_k": 12}, "graph": {"enabled": True}},
    }

    create_response = await client.post("/api/variants", json=payload)
    assert create_response.status_code == 201
    variant_id = create_response.json()["id"]

    list_response = await client.get("/api/variants")
    assert list_response.status_code == 200
    assert any(item["id"] == variant_id for item in list_response.json()["items"])


@pytest.mark.asyncio
async def test_variant_create_applies_preset_defaults(client):
    payload = {
        "name": "Fast with warmer output",
        "preset": "fast",
        "parameters": {"temperature": 0.4},
    }

    response = await client.post("/api/variants", json=payload)

    assert response.status_code == 201
    assert response.json()["parameters"] == {
        "top_k": 4,
        "temperature": 0.4,
        "enable_rerank": False,
    }


@pytest.mark.asyncio
async def test_variant_rejects_unknown_preset(client):
    response = await client.post(
        "/api/variants",
        json={"name": "Typo", "preset": "fasst", "parameters": {}},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_variant_update_and_delete(client):
    create_response = await client.post(
        "/api/variants",
        json={
            "name": "Draft",
            "preset": "balanced",
            "parameters": {"top_k": 8},
        },
    )
    assert create_response.status_code == 201
    variant_id = create_response.json()["id"]

    update_response = await client.put(
        f"/api/variants/{variant_id}",
        json={
            "name": "Precise citations",
            "preset": "precise",
            "parameters": {"enable_rerank": False},
        },
    )
    assert update_response.status_code == 200
    assert update_response.json() == {
        "id": variant_id,
        "name": "Precise citations",
        "preset": "precise",
        "parameters": {"top_k": 3, "temperature": 0.1, "enable_rerank": False},
    }

    defaulted_update = await client.put(
        f"/api/variants/{variant_id}",
        json={
            "name": "Fast citations",
            "preset": "fast",
        },
    )
    assert defaulted_update.status_code == 200
    assert defaulted_update.json()["parameters"] == {
        "top_k": 4,
        "temperature": 0.0,
        "enable_rerank": False,
    }

    missing_update = await client.put(
        "/api/variants/missing",
        json={
            "name": "Missing",
            "preset": "balanced",
            "parameters": {},
        },
    )
    assert missing_update.status_code == 404

    delete_response = await client.delete(f"/api/variants/{variant_id}")
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/variants/{variant_id}")
    assert get_response.status_code == 404

    missing_delete = await client.delete("/api/variants/missing")
    assert missing_delete.status_code == 404
