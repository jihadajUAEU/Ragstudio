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
async def test_settings_profile_saves_llm_config_without_returning_secret(client):
    payload = {
        "provider": "openai",
        "llm_provider": "openai_compatible",
        "llm_model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
        "llm_base_url": "http://10.10.9.195:8004/v1/",
        "llm_api_key": "llm-secret-token",
        "llm_timeout_ms": 15000,
        "llm_capabilities": ["text", "vision", "reasoning"],
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "sqlite",
    }

    create_response = await client.put("/api/settings/default", json=payload)

    assert create_response.status_code == 200
    body = create_response.json()
    assert body["llm_provider"] == "openai_compatible"
    assert body["llm_base_url"] == "http://10.10.9.195:8004/v1"
    assert body["llm_timeout_ms"] == 15000
    assert body["llm_capabilities"] == ["text", "vision", "reasoning"]
    assert body["has_llm_api_key"] is True
    assert "llm_api_key" not in body


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


@pytest.mark.asyncio
async def test_settings_profile_saves_mineru_config(client):
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "sqlite",
        "mineru_enabled": True,
        "mineru_base_url": "http://127.0.0.1:8765/",
        "mineru_timeout_ms": 120000,
        "mineru_poll_interval_ms": 500,
    }

    response = await client.put("/api/settings/default", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["mineru_enabled"] is True
    assert body["mineru_base_url"] == "http://127.0.0.1:8765"
    assert body["mineru_timeout_ms"] == 120000
    assert body["mineru_poll_interval_ms"] == 500


@pytest.mark.asyncio
async def test_mineru_connection_test(client, monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200
        text = "ok"

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url):
            requests.append({"url": url, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr("ragstudio.api.routes.settings.httpx.AsyncClient", FakeAsyncClient)
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "sqlite",
        "mineru_enabled": True,
        "mineru_base_url": "http://127.0.0.1:8765",
        "mineru_timeout_ms": 2000,
        "mineru_poll_interval_ms": 500,
    }

    response = await client.post("/api/settings/default/test-mineru", json=payload)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert requests == [{"url": "http://127.0.0.1:8765/health", "timeout": 2.0}]
