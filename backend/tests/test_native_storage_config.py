import asyncio
import os

import pytest
from ragstudio.config import AppSettings
from ragstudio.schemas.runtime import RuntimeProfile
from ragstudio.services.native_storage_config import (
    NATIVE_STORAGE_ENV_LOCK,
    derive_native_storage_config,
    scoped_native_storage_env,
)


def profile(**overrides):
    data = {
        "id": "tenant",
        "runtime_mode": "runtime",
        "provider": "openai-compatible",
        "llm_model": "gpt-4o",
        "llm_timeout_ms": 10000,
        "vision_timeout_ms": 10000,
        "embedding_provider": "vllm_openai",
        "embedding_model": "text-embedding-3-large",
        "embedding_dimensions": 1536,
        "embedding_batch_size": 16,
        "embedding_timeout_ms": 10000,
        "reranker_provider": "disabled",
        "reranker_timeout_ms": 10000,
        "storage_backend": "postgres_pgvector_neo4j",
        "pgvector_schema": "public",
        "pgvector_table_prefix": "ragstudio",
        "neo4j_uri": "bolt://127.0.0.1:7687",
        "neo4j_username": "neo4j",
        "neo4j_password": "secret",
        "parser": "mineru",
        "parse_method": "auto",
        "chunk_token_size": 1200,
        "chunk_overlap_token_size": 100,
        "enable_image_processing": True,
        "enable_table_processing": True,
        "enable_equation_processing": True,
        "context_window": 1,
        "context_mode": "page",
        "max_context_tokens": 2000,
        "include_headers": True,
        "include_captions": True,
        "query_mode": "mix",
        "top_k": 40,
        "chunk_top_k": 20,
        "enable_rerank": True,
        "cosine_better_than_threshold": 0.2,
        "max_total_tokens": 30000,
        "max_entity_tokens": 6000,
        "max_relation_tokens": 8000,
        "enable_llm_cache": True,
        "enable_llm_cache_for_entity_extract": True,
        "llm_model_max_async": 4,
        "embedding_func_max_async": 8,
        "max_parallel_insert": 2,
        "runtime_working_dir": "/tmp/ragstudio-runtime",
        "index_shape": {},
    }
    data.update(overrides)
    return RuntimeProfile(**data)


def test_derive_native_storage_config_from_runtime_profile_and_settings():
    config = derive_native_storage_config(
        profile(id="tenant-one"),
        AppSettings(
            database_url=(
                "postgresql+asyncpg://studio%40user:p%23ss@db.internal:6543/ragstudio"
            )
        ),
    )

    assert config.postgres_host == "db.internal"
    assert config.postgres_port == "6543"
    assert config.postgres_user == "studio@user"
    assert config.postgres_password == "p#ss"
    assert config.postgres_database == "ragstudio"
    assert config.workspace == "ragstudio_tenant-one"
    assert config.neo4j_uri == "bolt://127.0.0.1:7687"


@pytest.mark.asyncio
async def test_scoped_native_storage_env_sets_thread_visible_values_and_restores(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "previous-host")
    monkeypatch.delenv("POSTGRES_WORKSPACE", raising=False)
    monkeypatch.delenv("NEO4J_URI", raising=False)
    config = derive_native_storage_config(
        profile(neo4j_uri=None),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    async with scoped_native_storage_env(config):
        assert NATIVE_STORAGE_ENV_LOCK.locked() is True
        assert os.environ["POSTGRES_HOST"] == "localhost"
        assert os.environ["POSTGRES_WORKSPACE"] == "ragstudio_tenant"
        assert await asyncio.to_thread(os.environ.get, "POSTGRES_WORKSPACE") == (
            "ragstudio_tenant"
        )
        assert "NEO4J_URI" not in os.environ

    assert os.environ["POSTGRES_HOST"] == "previous-host"
    assert "POSTGRES_WORKSPACE" not in os.environ
    assert "NEO4J_URI" not in os.environ
