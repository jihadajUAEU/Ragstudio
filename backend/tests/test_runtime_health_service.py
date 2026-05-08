import pytest
from ragstudio.schemas.runtime import RuntimeProfile
from ragstudio.services.runtime_health_service import RuntimeHealthService


def profile(**overrides):
    data = {
        "id": "default",
        "runtime_mode": "runtime",
        "provider": "openai-compatible",
        "llm_model": "gpt-4o",
        "llm_base_url": "http://127.0.0.1:8004/v1",
        "llm_timeout_ms": 10000,
        "llm_capabilities": ["text", "vision"],
        "vision_model": None,
        "vision_base_url": None,
        "vision_timeout_ms": 10000,
        "embedding_provider": "vllm_openai",
        "embedding_model": "text-embedding-3-large",
        "embedding_base_url": "http://127.0.0.1:8001/v1",
        "embedding_dimensions": 3072,
        "embedding_batch_size": 32,
        "embedding_timeout_ms": 10000,
        "reranker_provider": "disabled",
        "reranker_model": None,
        "reranker_base_url": None,
        "reranker_timeout_ms": 10000,
        "storage_backend": "postgres_pgvector_neo4j",
        "pgvector_schema": "public",
        "pgvector_table_prefix": "ragstudio",
        "neo4j_uri": "bolt://127.0.0.1:57687",
        "neo4j_username": "neo4j",
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


@pytest.mark.asyncio
async def test_runtime_health_marks_missing_required_urls_as_blocking():
    checks = await RuntimeHealthService().check(profile(llm_base_url=None))

    llm = next(item for item in checks if item.name == "llm")
    assert llm.status == "failed"
    assert llm.severity == "blocking"
    assert llm.error_type == "configuration"


@pytest.mark.asyncio
async def test_runtime_health_skips_disabled_reranker():
    checks = await RuntimeHealthService().check(profile(reranker_provider="disabled"))

    reranker = next(item for item in checks if item.name == "reranker")
    assert reranker.status == "skipped"
    assert reranker.severity == "info"


@pytest.mark.asyncio
async def test_runtime_health_reports_missing_profile_as_blocking():
    checks = await RuntimeHealthService().check(None)

    assert [item.name for item in checks] == ["runtime_profile"]
    assert RuntimeHealthService().blocking_failures(checks) == checks
