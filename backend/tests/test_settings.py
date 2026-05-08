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


@pytest.mark.asyncio
async def test_settings_profile_saves_vllm_embedding_config_without_returning_secret(client):
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "Qwen/Qwen3-Embedding-8B",
        "storage_backend": "sqlite",
        "embedding_provider": "vllm_openai",
        "embedding_base_url": "http://127.0.0.1:8001/v1/",
        "embedding_api_key": "secret-token",
        "embedding_timeout_ms": 20000,
        "embedding_dimensions": 1536,
        "embedding_batch_size": 32,
        "embedding_tls_verify": False,
    }

    create_response = await client.put("/api/settings/default", json=payload)

    assert create_response.status_code == 200
    body = create_response.json()
    assert body["embedding_provider"] == "vllm_openai"
    assert body["embedding_base_url"] == "http://127.0.0.1:8001/v1"
    assert body["has_embedding_api_key"] is True
    assert "embedding_api_key" not in body
    assert body["embedding_timeout_ms"] == 20000
    assert body["embedding_batch_size"] == 32
    assert body["embedding_tls_verify"] is False


@pytest.mark.asyncio
async def test_embedding_connection_test_validates_vector_dimensions(client, monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, headers, json):
            requests.append({"url": url, "headers": headers, "json": json, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.embedding_connection_service.httpx.AsyncClient",
        FakeAsyncClient,
    )
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "Qwen/Qwen3-Embedding-8B",
        "storage_backend": "sqlite",
        "embedding_provider": "vllm_openai",
        "embedding_base_url": "http://127.0.0.1:8001/v1",
        "embedding_api_key": "secret-token",
        "embedding_timeout_ms": 5000,
        "embedding_dimensions": 3,
        "embedding_batch_size": 16,
        "embedding_tls_verify": True,
    }

    response = await client.post("/api/settings/default/test-embedding", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["dimensions"] == 3
    assert requests == [
        {
            "url": "http://127.0.0.1:8001/v1/embeddings",
            "headers": {
                "content-type": "application/json",
                "authorization": "Bearer secret-token",
            },
            "json": {
                "model": "Qwen/Qwen3-Embedding-8B",
                "input": "Ragstudio embedding connection test",
                "dimensions": 3,
            },
            "timeout": 5.0,
        }
    ]


@pytest.mark.asyncio
async def test_embedding_connection_test_uses_saved_api_key_when_blank(
    client,
    monkeypatch,
):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, headers, json):
            requests.append({"headers": headers})
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.embedding_connection_service.httpx.AsyncClient",
        FakeAsyncClient,
    )
    saved_payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "Qwen/Qwen3-Embedding-8B",
        "storage_backend": "sqlite",
        "embedding_provider": "vllm_openai",
        "embedding_base_url": "http://127.0.0.1:8001/v1",
        "embedding_api_key": "saved-secret-token",
        "embedding_timeout_ms": 5000,
        "embedding_dimensions": 3,
        "embedding_batch_size": 16,
        "embedding_tls_verify": True,
    }
    test_payload = {
        key: value for key, value in saved_payload.items() if key != "embedding_api_key"
    }

    save_response = await client.put("/api/settings/default", json=saved_payload)
    response = await client.post("/api/settings/default/test-embedding", json=test_payload)

    assert save_response.status_code == 200
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert requests == [
        {
            "headers": {
                "content-type": "application/json",
                "authorization": "Bearer saved-secret-token",
            }
        }
    ]
