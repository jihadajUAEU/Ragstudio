import pytest
from ragstudio.app import create_app
from ragstudio.schemas.settings import SettingsProfileIn
from ragstudio.services.runtime_profile_service import RuntimeProfileService
from ragstudio.services.settings_service import SettingsService


@pytest.mark.asyncio
async def test_runtime_profile_uses_saved_settings(client):
    payload = {
        "provider": "openai-compatible",
        "runtime_mode": "runtime",
        "llm_model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
        "llm_base_url": "http://127.0.0.1:8004/v1",
        "llm_capabilities": ["text", "vision", "reasoning"],
        "embedding_model": "Qwen/Qwen3-Embedding-8B",
        "embedding_provider": "vllm_openai",
        "embedding_base_url": "http://127.0.0.1:8001/v1",
        "embedding_dimensions": 1536,
        "storage_backend": "postgres_pgvector_neo4j",
        "reranker_provider": "cohere_compatible",
        "reranker_model": "BAAI/bge-reranker-v2-m3",
        "reranker_base_url": "http://127.0.0.1:8002/v1/rerank",
        "neo4j_uri": "bolt://127.0.0.1:57687",
        "neo4j_username": "neo4j",
        "neo4j_password": "secret",
        "query_mode": "mix",
        "top_k": 40,
        "chunk_top_k": 20,
    }

    response = await client.put("/api/settings/default", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["runtime_mode"] == "runtime"
    assert body["storage_backend"] == "postgres_pgvector_neo4j"
    assert body["has_neo4j_password"] is True
    assert body["has_reranker_api_key"] is False
    assert "neo4j_password" not in body


@pytest.mark.asyncio
async def test_runtime_profile_service_normalizes_index_shape(tmp_path, database_url):
    payload = SettingsProfileIn(
        provider="openai-compatible",
        runtime_mode="runtime",
        llm_model="gpt-4o",
        llm_base_url="http://127.0.0.1:8004/v1",
        embedding_model="text-embedding-3-large",
        embedding_api_key="embedding-secret",
        embedding_dimensions=3072,
        storage_backend="postgres_pgvector_neo4j",
        llm_api_key="llm-secret",
        vision_api_key="vision-secret",
        reranker_api_key="reranker-secret",
        neo4j_password="neo4j-secret",
        parser="mineru",
        parse_method="auto",
        chunk_token_size=1200,
        chunk_overlap_token_size=100,
    )
    app = create_app(
        data_dir=tmp_path,
        database_url=database_url,
    )
    async with app.router.lifespan_context(app):
        async with app.state.session_factory() as session:
            await SettingsService(session).upsert_default(payload)
            profile = await RuntimeProfileService(
                session,
                app.state.settings,
            ).get_active_profile()

    assert profile.id == "default"
    assert profile.runtime_mode == "runtime"
    assert profile.llm_api_key == "llm-secret"
    assert profile.embedding_api_key == "embedding-secret"
    assert profile.vision_api_key == "vision-secret"
    assert profile.reranker_api_key == "reranker-secret"
    assert profile.neo4j_password == "neo4j-secret"
    assert profile.index_shape == {
        "runtime_profile_id": "default",
        "embedding_provider": "vllm_openai",
        "embedding_model": "text-embedding-3-large",
        "embedding_dimensions": 3072,
        "pgvector_schema": "public",
        "pgvector_table_prefix": "ragstudio",
        "parser": "mineru",
        "parse_method": "auto",
        "chunk_token_size": 1200,
        "chunk_overlap_token_size": 100,
        "graph_storage": "neo4j",
        "vector_storage": "pgvector",
    }
