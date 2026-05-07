import pytest


@pytest.mark.asyncio
async def test_settings_profile_round_trip(client):
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "sqlite",
    }

    create_response = await client.put("/api/settings/default", json=payload)
    assert create_response.status_code == 200

    read_response = await client.get("/api/settings/default")
    assert read_response.status_code == 200
    assert read_response.json()["provider"] == "openai"
    assert read_response.json()["storage_backend"] == "sqlite"
