from typing import Any, Literal

from pydantic import Field

from ragstudio.schemas.common import StudioModel

RuntimeMode = Literal["runtime", "fallback", "degraded"]
RuntimeOverallStatus = Literal["ready", "degraded", "failed", "fallback"]
RuntimeCheckStatus = Literal["ok", "warning", "failed", "skipped"]
RuntimeCheckSeverity = Literal["info", "warning", "blocking"]
StorageBackend = Literal["postgres_pgvector_neo4j", "fallback_local"]
RerankerProvider = Literal["disabled", "cohere_compatible", "jina_compatible", "generic_http"]
QueryMode = Literal["mix", "hybrid", "local", "global", "naive"]


class RuntimeHealthCheck(StudioModel):
    name: str
    status: RuntimeCheckStatus
    severity: RuntimeCheckSeverity = "info"
    latency_ms: int | None = None
    detail: str
    error_type: str | None = None
    remediation: str | None = None


class RuntimeProfile(StudioModel):
    id: str
    runtime_mode: RuntimeMode
    provider: str
    llm_model: str
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_timeout_ms: int
    llm_capabilities: list[str] = Field(default_factory=list)
    vision_model: str | None = None
    vision_base_url: str | None = None
    vision_api_key: str | None = None
    vision_timeout_ms: int
    embedding_provider: str
    embedding_model: str
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_dimensions: int
    embedding_batch_size: int
    embedding_timeout_ms: int
    reranker_provider: RerankerProvider
    reranker_model: str | None = None
    reranker_base_url: str | None = None
    reranker_api_key: str | None = None
    reranker_timeout_ms: int
    storage_backend: StorageBackend
    pgvector_schema: str
    pgvector_table_prefix: str
    neo4j_uri: str | None = None
    neo4j_username: str | None = None
    neo4j_password: str | None = None
    parser: str
    parse_method: str
    chunk_token_size: int
    chunk_overlap_token_size: int
    enable_image_processing: bool
    enable_table_processing: bool
    enable_equation_processing: bool
    context_window: int
    context_mode: str
    max_context_tokens: int
    include_headers: bool
    include_captions: bool
    query_mode: QueryMode
    top_k: int
    chunk_top_k: int
    enable_rerank: bool
    cosine_better_than_threshold: float
    max_total_tokens: int
    max_entity_tokens: int
    max_relation_tokens: int
    enable_llm_cache: bool
    enable_llm_cache_for_entity_extract: bool
    llm_model_max_async: int
    embedding_func_max_async: int
    max_parallel_insert: int
    runtime_working_dir: str
    index_shape: dict[str, Any]
