from typing import Literal, cast

RuntimeMode = Literal["runtime"]
StorageBackend = Literal["postgres_pgvector_neo4j"]
ParserMode = Literal["mineru_strict"]
EmbeddingProvider = Literal["vllm_openai"]

DEFAULT_RUNTIME_MODE: RuntimeMode = "runtime"
DEFAULT_STORAGE_BACKEND: StorageBackend = "postgres_pgvector_neo4j"
DEFAULT_PARSER_MODE: ParserMode = "mineru_strict"
DEFAULT_EMBEDDING_PROVIDER: EmbeddingProvider = "vllm_openai"

VALID_RUNTIME_MODES = {"runtime"}
VALID_STORAGE_BACKENDS = {"postgres_pgvector_neo4j"}
VALID_PARSER_MODES = {"mineru_strict"}
VALID_EMBEDDING_PROVIDERS = {"vllm_openai"}


class ProductPolicyError(ValueError):
    pass


def normalize_storage_backend(value: str | None) -> StorageBackend:
    if value == "fallback_local":
        raise ValueError("fallback_local has been removed from product runtime")
    if value in VALID_STORAGE_BACKENDS:
        return cast(StorageBackend, value)
    if value is None or value == "":
        return DEFAULT_STORAGE_BACKEND
    raise ValueError(f"{value} is not a supported product storage backend")


def normalize_runtime_mode(
    value: str | None,
    storage_backend: str | None,
) -> RuntimeMode:
    if value == "fallback" or storage_backend == "fallback_local":
        raise ValueError("fallback runtime mode has been removed from product runtime")
    if value == "degraded":
        raise ValueError("degraded runtime mode cannot execute product indexing")
    if value in VALID_RUNTIME_MODES:
        return cast(RuntimeMode, value)
    if value is None or value == "":
        return DEFAULT_RUNTIME_MODE
    raise ValueError(f"{value} is not a supported product runtime mode")


def normalize_parser_mode(value: str | None) -> ParserMode:
    if value in {"local_fallback", "mineru_with_fallback"}:
        raise ValueError(f"{value} has been removed from product parsing")
    if value in VALID_PARSER_MODES:
        return cast(ParserMode, value)
    if value is None or value == "":
        return DEFAULT_PARSER_MODE
    raise ValueError(f"{value} is not a supported product parser mode")


def normalize_embedding_provider(value: str | None) -> EmbeddingProvider:
    if value == "fallback":
        raise ValueError("fallback embedding provider has been removed from product runtime")
    if value in VALID_EMBEDDING_PROVIDERS:
        return cast(EmbeddingProvider, value)
    if value is None or value == "":
        return DEFAULT_EMBEDDING_PROVIDER
    raise ValueError(f"{value} is not a supported product embedding provider")


def enforce_product_index_options(*, parser_mode: str) -> None:
    if parser_mode != DEFAULT_PARSER_MODE:
        raise ProductPolicyError(
            "Production indexing requires parser_mode=mineru_strict. "
            f"Received {parser_mode!r}."
        )


def enforce_product_runtime_settings(
    *,
    storage_backend: str,
    runtime_mode: str | None = None,
) -> None:
    if storage_backend != DEFAULT_STORAGE_BACKEND:
        raise ProductPolicyError(
            "Production runtime requires storage_backend=postgres_pgvector_neo4j. "
            f"Received {storage_backend!r}."
        )
    if runtime_mode in {"fallback", "degraded"}:
        raise ProductPolicyError(
            "Production runtime requires runtime_mode=runtime. "
            f"Received {runtime_mode!r}."
        )
