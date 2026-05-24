from fastapi.testclient import TestClient
from ragstudio.app import create_app
from ragstudio.services.runtime_defaults import RUNTIME_DEFAULTS


def test_defaults_api_returns_runtime_defaults() -> None:
    client = TestClient(create_app())

    response = client.get("/api/defaults")

    assert response.status_code == 200
    body = response.json()
    assert body["runtime"]["top_k"] == RUNTIME_DEFAULTS.top_k
    assert body["runtime"]["chunk_top_k"] == RUNTIME_DEFAULTS.chunk_top_k
    assert body["runtime"]["max_context_tokens"] == RUNTIME_DEFAULTS.max_context_tokens
    assert body["runtime"]["cosine_better_than_threshold"] == (
        RUNTIME_DEFAULTS.cosine_better_than_threshold
    )
    assert body["policy_versions"]["retrieval"] == "2026-05-24"
