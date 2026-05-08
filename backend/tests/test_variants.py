import pytest


@pytest.mark.asyncio
async def test_variant_create_and_list(client):
    payload = {
        "name": "High recall graph",
        "preset": "high_recall",
        "parameters": {"retrieval": {"top_k": 12}, "graph": {"enabled": True}},
    }

    create_response = await client.post("/api/variants", json=payload)
    assert create_response.status_code == 201
    variant_id = create_response.json()["id"]

    list_response = await client.get("/api/variants")
    assert list_response.status_code == 200
    assert any(item["id"] == variant_id for item in list_response.json()["items"])
