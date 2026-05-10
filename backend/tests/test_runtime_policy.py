from ragstudio.services.runtime_policy import (
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_PARSER_MODE,
    DEFAULT_RUNTIME_MODE,
    DEFAULT_STORAGE_BACKEND,
    normalize_embedding_provider,
    normalize_parser_mode,
    normalize_runtime_mode,
    normalize_storage_backend,
)


def test_runtime_policy_defaults_are_explicit():
    assert DEFAULT_RUNTIME_MODE == "runtime"
    assert DEFAULT_STORAGE_BACKEND == "postgres_pgvector_neo4j"
    assert DEFAULT_PARSER_MODE == "mineru_strict"
    assert DEFAULT_EMBEDDING_PROVIDER == "vllm_openai"


def test_fallback_storage_forces_fallback_runtime():
    assert normalize_runtime_mode("runtime", "fallback_local") == "fallback"


def test_invalid_runtime_storage_and_provider_values_use_runtime_defaults():
    assert normalize_runtime_mode("nonsense", "postgres_pgvector_neo4j") == "runtime"
    assert normalize_storage_backend("nonsense") == "postgres_pgvector_neo4j"
    assert normalize_parser_mode("nonsense") == "mineru_strict"
    assert normalize_embedding_provider("nonsense") == "vllm_openai"
