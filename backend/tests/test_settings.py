import pytest


@pytest.mark.asyncio
async def test_settings_profile_round_trip(client):
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "postgres_pgvector_neo4j",
    }

    create_response = await client.put("/api/settings/default", json=payload)
    assert create_response.status_code == 200

    read_response = await client.get("/api/settings/default")
    assert read_response.status_code == 200
    assert read_response.json()["provider"] == "openai"
    assert read_response.json()["storage_backend"] == "postgres_pgvector_neo4j"
    assert read_response.json()["runtime_mode"] == "runtime"
    assert read_response.json()["query_mode"] == "mix"
    assert read_response.json()["top_k"] == 40


@pytest.mark.asyncio
async def test_settings_profile_forces_fallback_mode_for_fallback_storage(client):
    payload = {
        "provider": "openai",
        "runtime_mode": "runtime",
        "llm_model": "gpt-4.1",
        "embedding_model": "fallback",
        "storage_backend": "fallback_local",
    }

    response = await client.put("/api/settings/default", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["storage_backend"] == "fallback_local"
    assert body["runtime_mode"] == "fallback"


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
        "storage_backend": "postgres_pgvector_neo4j",
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
        "storage_backend": "postgres_pgvector_neo4j",
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
        "storage_backend": "postgres_pgvector_neo4j",
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
        "storage_backend": "postgres_pgvector_neo4j",
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
async def test_provider_sync_preview_maps_manifest_without_persisting(client, monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "version": 2,
                "updatedAt": "2026-05-07T08:23:27.928Z",
                "reasoning": {
                    "apiUrl": "http://10.10.9.195:8004/v1",
                    "model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
                    "timeoutMs": 5000,
                },
                "embeddings": {
                    "apiUrl": "http://10.10.9.192:8001/v1",
                    "model": "Qwen/Qwen3-Embedding-8B",
                    "dimensions": 1536,
                    "timeoutMs": 10000,
                },
                "hpcMineru": {
                    "enabled": True,
                    "apiUrl": "http://10.10.9.19:8765",
                    "timeoutMs": 1800000,
                },
                "stt": {"apiUrl": "http://10.10.9.196:8002/v1"},
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url):
            assert url == "https://updates.jihadaj.com/providers.json"
            assert self.timeout == 5.0
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.provider_manifest_service.httpx.AsyncClient",
        FakeAsyncClient,
    )
    save_response = await client.put(
        "/api/settings/default",
        json={
            "provider": "openai",
            "llm_model": "gpt-4.1",
            "embedding_model": "text-embedding-3-large",
            "storage_backend": "postgres_pgvector_neo4j",
        },
    )

    response = await client.post(
        "/api/settings/default/sync-provider-preview",
        json={"manifest_url": "https://updates.jihadaj.com/providers.json"},
    )
    read_response = await client.get("/api/settings/default")

    assert save_response.status_code == 200
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["manifest_version"] == 2
    assert body["updated_at"] == "2026-05-07T08:23:27.928Z"
    assert body["patch"]["llm_provider"] == "openai_compatible"
    assert body["patch"]["llm_base_url"] == "http://10.10.9.195:8004/v1"
    assert body["patch"]["llm_model"] == "QuantTrio/Qwen3-VL-32B-Instruct-AWQ"
    assert body["patch"]["llm_timeout_ms"] == 5000
    assert body["patch"]["llm_capabilities"] == ["text", "vision", "reasoning"]
    assert body["patch"]["embedding_provider"] == "vllm_openai"
    assert body["patch"]["embedding_base_url"] == "http://10.10.9.192:8001/v1"
    assert body["patch"]["embedding_model"] == "Qwen/Qwen3-Embedding-8B"
    assert body["patch"]["embedding_dimensions"] == 1536
    assert body["patch"]["embedding_timeout_ms"] == 10000
    assert body["patch"]["mineru_enabled"] is True
    assert body["patch"]["mineru_base_url"] == "http://10.10.9.19:8765"
    assert body["patch"]["mineru_timeout_ms"] == 1800000
    assert "llm_base_url" in body["changed_fields"]
    assert "stt" in body["ignored_sections"]
    assert read_response.json()["llm_model"] == "gpt-4.1"


@pytest.mark.asyncio
async def test_provider_sync_preview_accepts_partial_manifest(client, monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"version": 3, "embeddings": {"model": "Qwen/Qwen3-Embedding-8B"}}

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.provider_manifest_service.httpx.AsyncClient",
        FakeAsyncClient,
    )

    response = await client.post(
        "/api/settings/default/sync-provider-preview",
        json={"manifest_url": "https://updates.jihadaj.com/providers.json"},
    )

    assert response.status_code == 200
    assert response.json()["patch"] == {
        "embedding_provider": "vllm_openai",
        "embedding_model": "Qwen/Qwen3-Embedding-8B",
    }


@pytest.mark.asyncio
async def test_provider_sync_preview_rejects_invalid_manifest_url(client):
    response = await client.post(
        "/api/settings/default/sync-provider-preview",
        json={"manifest_url": "ftp://updates.jihadaj.com/providers.json"},
    )

    assert response.status_code == 422
    assert "manifest_url" in response.text


@pytest.mark.parametrize(
    ("manifest", "field_name"),
    [
        ({"reasoning": {"apiUrl": 42}}, "reasoning.apiUrl"),
        ({"reasoning": {"model": False}}, "reasoning.model"),
        ({"reasoning": {"timeoutMs": True}}, "reasoning.timeoutMs"),
        ({"reasoning": {"capabilities": ["text", 42]}}, "reasoning.capabilities"),
        ({"embeddings": {"dimensions": False}}, "embeddings.dimensions"),
        ({"embeddings": {"timeoutMs": 0}}, "embeddings.timeoutMs"),
        ({"hpcMineru": {"enabled": "yes"}}, "hpcMineru.enabled"),
        ({"hpcMineru": {"timeoutMs": -1}}, "hpcMineru.timeoutMs"),
    ],
)
@pytest.mark.asyncio
async def test_provider_sync_preview_rejects_invalid_supported_field_types(
    client, monkeypatch, manifest, field_name
):
    class FakeResponse:
        status_code = 200

        def json(self):
            return manifest

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.provider_manifest_service.httpx.AsyncClient",
        FakeAsyncClient,
    )

    response = await client.post(
        "/api/settings/default/sync-provider-preview",
        json={"manifest_url": "https://updates.jihadaj.com/providers.json"},
    )

    assert response.status_code == 502
    assert field_name in response.json()["detail"]


@pytest.mark.asyncio
async def test_llm_connection_test_calls_chat_completions(client, monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

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
        "ragstudio.services.llm_connection_service.httpx.AsyncClient",
        FakeAsyncClient,
    )
    payload = {
        "provider": "openai",
        "llm_provider": "openai_compatible",
        "llm_model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
        "llm_base_url": "http://10.10.9.195:8004/v1",
        "llm_api_key": "secret-token",
        "llm_timeout_ms": 5000,
        "llm_capabilities": ["text", "vision", "reasoning"],
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "postgres_pgvector_neo4j",
    }

    response = await client.post("/api/settings/default/test-llm", json=payload)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert requests == [
        {
            "url": "http://10.10.9.195:8004/v1/chat/completions",
            "headers": {
                "content-type": "application/json",
                "authorization": "Bearer secret-token",
            },
            "json": {
                "model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
                "messages": [{"role": "user", "content": "Ragstudio LLM connection test"}],
                "max_tokens": 8,
                "temperature": 0,
            },
            "timeout": 5.0,
        }
    ]


@pytest.mark.asyncio
async def test_llm_connection_test_uses_saved_api_key_when_blank(client, monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

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
        "ragstudio.services.llm_connection_service.httpx.AsyncClient",
        FakeAsyncClient,
    )
    saved_payload = {
        "provider": "openai",
        "llm_provider": "openai_compatible",
        "llm_model": "Qwen/Qwen3-32B",
        "llm_base_url": "http://10.10.9.195:8004/v1",
        "llm_api_key": "saved-llm-secret",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "postgres_pgvector_neo4j",
    }
    test_payload = {key: value for key, value in saved_payload.items() if key != "llm_api_key"}

    save_response = await client.put("/api/settings/default", json=saved_payload)
    response = await client.post("/api/settings/default/test-llm", json=test_payload)

    assert save_response.status_code == 200
    assert response.status_code == 200
    assert requests == [
        {
            "headers": {
                "content-type": "application/json",
                "authorization": "Bearer saved-llm-secret",
            }
        }
    ]


@pytest.mark.asyncio
async def test_settings_profile_saves_mineru_config(client):
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "postgres_pgvector_neo4j",
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
        "storage_backend": "postgres_pgvector_neo4j",
        "mineru_enabled": True,
        "mineru_base_url": "http://127.0.0.1:8765",
        "mineru_timeout_ms": 2000,
        "mineru_poll_interval_ms": 500,
    }

    response = await client.post("/api/settings/default/test-mineru", json=payload)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert requests == [{"url": "http://127.0.0.1:8765/health", "timeout": 2.0}]
