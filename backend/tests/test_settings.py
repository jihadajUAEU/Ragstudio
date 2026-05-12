import pytest
from ragstudio.db.models import SettingsProfile


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
async def test_settings_reject_fallback_local_storage(client):
    payload = {
        "provider": "openai",
        "runtime_mode": "runtime",
        "llm_model": "gpt-4.1",
        "embedding_model": "fallback",
        "storage_backend": "fallback_local",
    }

    response = await client.put("/api/settings/default", json=payload)

    assert response.status_code == 422
    assert "postgres_pgvector_neo4j" in str(response.json()["detail"])


@pytest.mark.asyncio
async def test_settings_get_default_reports_legacy_profile_without_crashing(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="legacy",
                llm_model="legacy-llm",
                embedding_model="legacy-embedding",
                storage_backend="fallback_local",
                runtime_mode="fallback",
                embedding_provider="fallback",
            )
        )
        await session.commit()

    response = await client.get("/api/settings/default")

    assert response.status_code == 409
    assert "legacy values" in response.json()["detail"]
    assert "postgres_pgvector_neo4j" in response.json()["detail"]


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
                "reranker": {
                    "apiUrl": "http://10.10.9.193:8005/v1",
                    "model": "Qwen/Qwen3-Reranker-8B",
                    "endpoint": "/v1/rerank",
                    "timeoutMs": 10000,
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
    assert body["patch"]["mineru_require_hpc"] is True
    assert body["patch"]["mineru_base_url"] == "http://10.10.9.19:8765"
    assert body["patch"]["mineru_timeout_ms"] == 14400000
    assert body["patch"]["enable_rerank"] is True
    assert body["patch"]["reranker_provider"] == "generic_http"
    assert body["patch"]["reranker_model"] == "Qwen/Qwen3-Reranker-8B"
    assert body["patch"]["reranker_base_url"] == "http://10.10.9.193:8005/v1/rerank"
    assert body["patch"]["reranker_timeout_ms"] == 10000
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
        ({"embeddings": {"timeoutMs": 1800001}}, "embeddings.timeoutMs"),
        ({"hpcMineru": {"enabled": "yes"}}, "hpcMineru.enabled"),
        ({"hpcMineru": {"timeoutMs": -1}}, "hpcMineru.timeoutMs"),
        ({"reranker": {"apiUrl": 42}}, "reranker.apiUrl"),
        ({"reranker": {"model": False}}, "reranker.model"),
        ({"reranker": {"endpoint": 42}}, "reranker.endpoint"),
        ({"reranker": {"timeoutMs": 0}}, "reranker.timeoutMs"),
        ({"reranker": {"timeoutMs": 1800001}}, "reranker.timeoutMs"),
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
        "mineru_require_hpc": True,
    }

    response = await client.put("/api/settings/default", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["mineru_enabled"] is True
    assert body["mineru_base_url"] == "http://127.0.0.1:8765"
    assert body["mineru_timeout_ms"] == 14400000
    assert body["mineru_poll_interval_ms"] == 500
    assert body["mineru_require_hpc"] is True


@pytest.mark.asyncio
async def test_mineru_connection_test(client, monkeypatch):
    requests = []

    class FakeClient:
        def __init__(self, base_url, timeout_ms, poll_interval_ms):
            requests.append(
                {
                    "base_url": base_url,
                    "timeout_ms": timeout_ms,
                    "poll_interval_ms": poll_interval_ms,
                }
            )

        async def health(self):
            from ragstudio.services.mineru_client import MinerUSidecarHealth

            return MinerUSidecarHealth(
                ready=True,
                detail="RAG-Anything sidecar ready",
                version="hybrid",
                hpc_enabled=True,
                hpc_mode="coordinator",
                raw={},
            )

    monkeypatch.setattr("ragstudio.api.routes.settings.MinerUClient", FakeClient)
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
    assert requests == [
        {
            "base_url": "http://127.0.0.1:8765",
            "timeout_ms": 2000,
            "poll_interval_ms": 500,
        }
    ]


@pytest.mark.asyncio
async def test_mineru_connection_test_reports_hpc_mode(client, monkeypatch):
    class FakeClient:
        def __init__(self, base_url, timeout_ms, poll_interval_ms):
            self.base_url = base_url

        async def health(self):
            from ragstudio.services.mineru_client import MinerUSidecarHealth

            return MinerUSidecarHealth(
                ready=True,
                detail="RAG-Anything sidecar ready",
                version="hybrid",
                hpc_enabled=True,
                hpc_mode="coordinator",
                raw={},
            )

    monkeypatch.setattr("ragstudio.api.routes.settings.MinerUClient", FakeClient)
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "postgres_pgvector_neo4j",
        "mineru_enabled": True,
        "mineru_base_url": "http://10.10.9.19:8765",
        "mineru_require_hpc": True,
    }

    response = await client.post("/api/settings/default/test-mineru", json=payload)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "HPC coordinator mode" in response.json()["detail"]


@pytest.mark.asyncio
async def test_mineru_connection_test_rejects_local_mode_when_required(client, monkeypatch):
    class FakeClient:
        def __init__(self, base_url, timeout_ms, poll_interval_ms):
            self.base_url = base_url

        async def health(self):
            from ragstudio.services.mineru_client import MinerUSidecarHealth

            return MinerUSidecarHealth(
                ready=True,
                detail="RAG-Anything sidecar ready",
                version="hybrid",
                hpc_enabled=False,
                hpc_mode="local",
                raw={},
            )

    monkeypatch.setattr("ragstudio.api.routes.settings.MinerUClient", FakeClient)
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "postgres_pgvector_neo4j",
        "mineru_enabled": True,
        "mineru_base_url": "http://10.10.9.19:8765",
        "mineru_require_hpc": True,
    }

    response = await client.post("/api/settings/default/test-mineru", json=payload)

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "local mode" in response.json()["detail"]


@pytest.mark.asyncio
async def test_mineru_connection_test_reports_invalid_health_payload(client, monkeypatch):
    class FakeClient:
        def __init__(self, base_url, timeout_ms, poll_interval_ms):
            self.base_url = base_url

        async def health(self):
            from ragstudio.services.mineru_client import MinerUSidecarHealth

            return MinerUSidecarHealth(
                ready=False,
                detail="MinerU health check returned invalid JSON.",
                version=None,
                hpc_enabled=False,
                hpc_mode=None,
                raw={},
            )

    monkeypatch.setattr("ragstudio.api.routes.settings.MinerUClient", FakeClient)
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "postgres_pgvector_neo4j",
        "mineru_enabled": True,
        "mineru_base_url": "http://10.10.9.19:8765",
        "mineru_require_hpc": True,
    }

    response = await client.post("/api/settings/default/test-mineru", json=payload)

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["detail"] == "MinerU health check returned invalid JSON."


@pytest.mark.asyncio
async def test_settings_accepts_llm_reranker_with_llm_fallback(client):
    response = await client.put(
        "/api/settings/default",
        json={
            "provider": "openai-compatible",
            "llm_provider": "openai_compatible",
            "llm_model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
            "llm_base_url": "http://10.10.9.195:8004/v1",
            "embedding_provider": "vllm_openai",
            "embedding_model": "Qwen/Qwen3-Embedding-8B",
            "embedding_base_url": "http://10.10.9.192:8001/v1",
            "embedding_dimensions": 1536,
            "storage_backend": "postgres_pgvector_neo4j",
            "runtime_mode": "runtime",
            "mineru_enabled": True,
            "mineru_base_url": "http://10.10.9.193:8003",
            "reranker_provider": "llm",
            "reranker_model": "",
            "reranker_base_url": "",
            "reranker_fallback_provider": "disabled",
            "enable_rerank": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reranker_provider"] == "llm"
    assert body["reranker_fallback_provider"] == "disabled"


@pytest.mark.asyncio
async def test_settings_accepts_dedicated_bge_with_llm_fallback(client):
    response = await client.put(
        "/api/settings/default",
        json={
            "provider": "openai-compatible",
            "llm_provider": "openai_compatible",
            "llm_model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
            "llm_base_url": "http://10.10.9.195:8004/v1",
            "embedding_provider": "vllm_openai",
            "embedding_model": "Qwen/Qwen3-Embedding-8B",
            "embedding_base_url": "http://10.10.9.192:8001/v1",
            "embedding_dimensions": 1536,
            "storage_backend": "postgres_pgvector_neo4j",
            "runtime_mode": "runtime",
            "mineru_enabled": True,
            "mineru_base_url": "http://10.10.9.193:8003",
            "reranker_provider": "generic_http",
            "reranker_model": "BAAI/bge-reranker-v2-m3",
            "reranker_base_url": "http://127.0.0.1:8002/v1/rerank",
            "reranker_fallback_provider": "llm",
            "enable_rerank": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reranker_provider"] == "generic_http"
    assert body["reranker_model"] == "BAAI/bge-reranker-v2-m3"
    assert body["reranker_fallback_provider"] == "llm"


@pytest.mark.asyncio
async def test_reranker_connection_test_calls_configured_rerank_endpoint(client, monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{"index": 1, "relevance_score": 0.98}]}

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
        "ragstudio.services.reranker_service.httpx.AsyncClient",
        FakeAsyncClient,
    )
    payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "postgres_pgvector_neo4j",
        "reranker_provider": "generic_http",
        "reranker_model": "Qwen/Qwen3-Reranker-8B",
        "reranker_base_url": "http://127.0.0.1:8005/v1/rerank",
        "reranker_api_key": "secret-reranker-token",
        "reranker_timeout_ms": 5000,
        "enable_rerank": True,
    }

    response = await client.post("/api/settings/default/test-reranker", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["provider"] == "generic_http"
    assert body["model"] == "Qwen/Qwen3-Reranker-8B"
    assert requests == [
        {
            "url": "http://127.0.0.1:8005/v1/rerank",
            "headers": {
                "Content-Type": "application/json",
                "Authorization": "Bearer secret-reranker-token",
            },
            "json": {
                "query": "Which passage is most relevant to Ragstudio reranking?",
                "documents": [
                    "Ragstudio checks parser health.",
                    "Ragstudio reranks retrieved evidence before answering.",
                ],
                "top_n": 2,
                "model": "Qwen/Qwen3-Reranker-8B",
            },
            "timeout": 5.0,
        }
    ]


@pytest.mark.asyncio
async def test_reranker_connection_test_uses_saved_api_key_when_blank(client, monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{"index": 1, "relevance_score": 0.98}]}

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
        "ragstudio.services.reranker_service.httpx.AsyncClient",
        FakeAsyncClient,
    )
    saved_payload = {
        "provider": "openai",
        "llm_model": "gpt-4.1",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "postgres_pgvector_neo4j",
        "reranker_provider": "generic_http",
        "reranker_model": "Qwen/Qwen3-Reranker-8B",
        "reranker_base_url": "http://127.0.0.1:8005/v1/rerank",
        "reranker_api_key": "saved-reranker-token",
        "enable_rerank": True,
    }
    test_payload = {key: value for key, value in saved_payload.items() if key != "reranker_api_key"}

    save_response = await client.put("/api/settings/default", json=saved_payload)
    response = await client.post("/api/settings/default/test-reranker", json=test_payload)

    assert save_response.status_code == 200
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert requests == [
        {
            "headers": {
                "Content-Type": "application/json",
                "Authorization": "Bearer saved-reranker-token",
            }
        }
    ]


@pytest.mark.asyncio
async def test_reranker_connection_test_uses_saved_llm_key_for_llm_provider(
    client, monkeypatch
):
    requests = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '[{"index": 1, "score": 0.98, "reason": "matches"}]'
                        }
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, headers, json):
            requests.append({"url": url, "headers": headers, "json": json})
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.llm_reranker_service.httpx.AsyncClient",
        FakeAsyncClient,
    )
    saved_payload = {
        "provider": "openai",
        "llm_provider": "openai_compatible",
        "llm_model": "gpt-4.1",
        "llm_base_url": "http://127.0.0.1:8004/v1",
        "llm_api_key": "saved-llm-token",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "postgres_pgvector_neo4j",
        "reranker_provider": "llm",
        "reranker_fallback_provider": "disabled",
        "enable_rerank": True,
    }
    test_payload = {key: value for key, value in saved_payload.items() if key != "llm_api_key"}

    save_response = await client.put("/api/settings/default", json=saved_payload)
    response = await client.post("/api/settings/default/test-reranker", json=test_payload)

    assert save_response.status_code == 200
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert requests == [
        {
            "url": "http://127.0.0.1:8004/v1/chat/completions",
            "headers": {
                "Content-Type": "application/json",
                "Authorization": "Bearer saved-llm-token",
            },
            "json": {
                "model": "gpt-4.1",
                "temperature": 0,
                "messages": requests[0]["json"]["messages"],
            },
        }
    ]


@pytest.mark.asyncio
async def test_reranker_connection_test_does_not_hide_primary_failure_with_fallback(
    client, monkeypatch
):
    calls = []

    async def fake_rerank(self, query, chunks, profile):
        calls.append({"query": query, "provider": profile.reranker_provider})
        return chunks, [
            {
                "provider": "generic_http",
                "model": profile.reranker_model,
                "status": "failed",
                "detail": "primary reranker unavailable",
                "fallback_provider": "llm",
            },
            {
                "provider": "llm",
                "model": profile.llm_model,
                "rank": 1,
                "original_rank": 2,
                "chunk_id": "reranker-test-strong",
                "score": 0.91,
            },
        ]

    monkeypatch.setattr("ragstudio.services.reranker_service.RerankerService.rerank", fake_rerank)
    payload = {
        "provider": "openai",
        "llm_provider": "openai_compatible",
        "llm_model": "gpt-4.1",
        "llm_base_url": "http://127.0.0.1:8004/v1",
        "llm_api_key": "llm-token",
        "embedding_model": "text-embedding-3-large",
        "storage_backend": "postgres_pgvector_neo4j",
        "reranker_provider": "generic_http",
        "reranker_model": "Qwen/Qwen3-Reranker-8B",
        "reranker_base_url": "http://127.0.0.1:8005/v1/rerank",
        "reranker_fallback_provider": "llm",
        "enable_rerank": True,
    }

    response = await client.post("/api/settings/default/test-reranker", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["detail"] == "primary reranker unavailable"
    assert calls == [
        {
            "query": "Which passage is most relevant to Ragstudio reranking?",
            "provider": "generic_http",
        }
    ]
