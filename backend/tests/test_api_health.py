import pytest


@pytest.mark.asyncio
async def test_health_returns_ready(client):
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "rag-anything-studio"
