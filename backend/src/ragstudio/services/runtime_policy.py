from typing import Literal, cast

RuntimeMode = Literal["runtime", "fallback", "degraded"]
StorageBackend = Literal["postgres_pgvector_neo4j", "fallback_local"]
ParserMode = Literal["local_fallback", "mineru_strict", "mineru_with_fallback"]
EmbeddingProvider = Literal["fallback", "vllm_openai"]

DEFAULT_RUNTIME_MODE: RuntimeMode = "runtime"
DEFAULT_STORAGE_BACKEND: StorageBackend = "postgres_pgvector_neo4j"
DEFAULT_PARSER_MODE: ParserMode = "mineru_strict"
DEFAULT_EMBEDDING_PROVIDER: EmbeddingProvider = "vllm_openai"

VALID_RUNTIME_MODES = {"runtime", "fallback", "degraded"}
VALID_STORAGE_BACKENDS = {"postgres_pgvector_neo4j", "fallback_local"}
VALID_PARSER_MODES = {"local_fallback", "mineru_strict", "mineru_with_fallback"}
VALID_EMBEDDING_PROVIDERS = {"fallback", "vllm_openai"}


def normalize_storage_backend(value: str | None) -> StorageBackend:
    if value in VALID_STORAGE_BACKENDS:
        return cast(StorageBackend, value)
    return DEFAULT_STORAGE_BACKEND


def normalize_runtime_mode(
    value: str | None,
    storage_backend: str | None,
) -> RuntimeMode:
    if normalize_storage_backend(storage_backend) == "fallback_local":
        return "fallback"
    if value in VALID_RUNTIME_MODES:
        return cast(RuntimeMode, value)
    return DEFAULT_RUNTIME_MODE


def normalize_parser_mode(value: str | None) -> ParserMode:
    if value in VALID_PARSER_MODES:
        return cast(ParserMode, value)
    return DEFAULT_PARSER_MODE


def normalize_embedding_provider(value: str | None) -> EmbeddingProvider:
    if value in VALID_EMBEDDING_PROVIDERS:
        return cast(EmbeddingProvider, value)
    return DEFAULT_EMBEDDING_PROVIDER
