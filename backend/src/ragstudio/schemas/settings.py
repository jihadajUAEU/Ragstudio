from typing import Literal, Self
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator

from ragstudio.schemas.common import StudioModel
from ragstudio.schemas.runtime import (
    QueryMode,
    RerankerFallbackProvider,
    RerankerProvider,
    RuntimeMode,
    StorageBackend,
)

EmbeddingProvider = Literal["fallback", "vllm_openai"]
LlmProvider = Literal["openai_compatible"]
LlmCapability = Literal["text", "vision", "reasoning"]
MINERU_DEFAULT_TIMEOUT_MS = 14_400_000


class SettingsProfileIn(StudioModel):
    provider: str
    llm_model: str
    llm_provider: LlmProvider = "openai_compatible"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_timeout_ms: int = Field(default=10000, ge=100, le=1_800_000)
    llm_capabilities: list[LlmCapability] = Field(default_factory=list)
    embedding_model: str
    storage_backend: StorageBackend
    embedding_provider: EmbeddingProvider = "fallback"
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_timeout_ms: int = Field(default=10000, ge=100, le=1_800_000)
    embedding_dimensions: int = Field(default=1536, ge=1, le=65536)
    embedding_batch_size: int = Field(default=16, ge=1, le=1024)
    embedding_tls_verify: bool = True
    mineru_enabled: bool = False
    mineru_base_url: str | None = None
    mineru_timeout_ms: int = Field(default=MINERU_DEFAULT_TIMEOUT_MS, ge=100, le=28_800_000)
    mineru_poll_interval_ms: int = Field(default=1_000, ge=100, le=60_000)
    mineru_require_hpc: bool = True
    runtime_mode: RuntimeMode = "fallback"
    vision_model: str | None = None
    vision_base_url: str | None = None
    vision_api_key: str | None = None
    vision_timeout_ms: int = Field(default=10000, ge=100, le=1_800_000)
    reranker_provider: RerankerProvider = "disabled"
    reranker_fallback_provider: RerankerFallbackProvider = "disabled"
    reranker_model: str | None = None
    reranker_base_url: str | None = None
    reranker_api_key: str | None = None
    reranker_timeout_ms: int = Field(default=10000, ge=100, le=1_800_000)
    pgvector_schema: str = "public"
    pgvector_table_prefix: str = "ragstudio"
    neo4j_uri: str | None = None
    neo4j_username: str | None = None
    neo4j_password: str | None = None
    parser: str = "mineru"
    parse_method: str = "auto"
    chunk_token_size: int = Field(default=1200, ge=100, le=8192)
    chunk_overlap_token_size: int = Field(default=100, ge=0, le=2048)
    enable_image_processing: bool = True
    enable_table_processing: bool = True
    enable_equation_processing: bool = True
    context_window: int = Field(default=1, ge=0, le=10)
    context_mode: str = "page"
    max_context_tokens: int = Field(default=2000, ge=100, le=100000)
    include_headers: bool = True
    include_captions: bool = True
    query_mode: QueryMode = "mix"
    top_k: int = Field(default=40, ge=1, le=200)
    chunk_top_k: int = Field(default=20, ge=1, le=200)
    enable_rerank: bool = True
    cosine_better_than_threshold: float = Field(default=0.2, ge=0, le=1)
    max_total_tokens: int = Field(default=30000, ge=1000, le=1000000)
    max_entity_tokens: int = Field(default=6000, ge=0, le=1000000)
    max_relation_tokens: int = Field(default=8000, ge=0, le=1000000)
    enable_llm_cache: bool = True
    enable_llm_cache_for_entity_extract: bool = True
    llm_model_max_async: int = Field(default=4, ge=1, le=128)
    embedding_func_max_async: int = Field(default=8, ge=1, le=128)
    max_parallel_insert: int = Field(default=2, ge=1, le=64)

    @model_validator(mode="after")
    def normalize_runtime_storage_pair(self) -> Self:
        if self.storage_backend == "fallback_local":
            self.runtime_mode = "fallback"
        return self

    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_base_url(cls, value: str | None) -> str | None:
        return cls._validate_http_base_url(value, "LLM base URL")

    @field_validator("embedding_base_url")
    @classmethod
    def validate_embedding_base_url(cls, value: str | None) -> str | None:
        return cls._validate_http_base_url(value, "Embedding base URL")

    @field_validator("vision_base_url")
    @classmethod
    def validate_vision_base_url(cls, value: str | None) -> str | None:
        return cls._validate_http_base_url(value, "Vision base URL")

    @field_validator("reranker_base_url")
    @classmethod
    def validate_reranker_base_url(cls, value: str | None) -> str | None:
        return cls._validate_http_base_url(value, "Reranker base URL")

    @field_validator("mineru_base_url")
    @classmethod
    def validate_mineru_base_url(cls, value: str | None) -> str | None:
        return cls._validate_http_base_url(value, "MinerU base URL")

    @field_validator("neo4j_uri")
    @classmethod
    def validate_neo4j_uri(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        parsed = urlparse(normalized)
        if parsed.scheme not in {"bolt", "neo4j", "neo4j+s", "bolt+s"} or not parsed.netloc:
            raise ValueError("Neo4j URI must use bolt, neo4j, neo4j+s, or bolt+s")
        return normalized

    @classmethod
    def _validate_http_base_url(cls, value: str | None, label: str) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        if not normalized:
            return None
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"{label} must be an http or https URL")
        if parsed.username or parsed.password:
            raise ValueError(f"{label} must not include credentials")
        return normalized

    @field_validator("llm_api_key")
    @classmethod
    def normalize_llm_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("embedding_api_key")
    @classmethod
    def normalize_embedding_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("vision_api_key", "reranker_api_key", "neo4j_password")
    @classmethod
    def normalize_runtime_secret(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("llm_capabilities")
    @classmethod
    def normalize_llm_capabilities(cls, value: list[LlmCapability]) -> list[LlmCapability]:
        ordered: list[LlmCapability] = []
        for capability in value:
            if capability not in ordered:
                ordered.append(capability)
        return ordered


class SettingsProfileOut(StudioModel):
    id: str
    provider: str
    llm_model: str
    llm_provider: LlmProvider
    llm_base_url: str | None
    has_llm_api_key: bool
    llm_timeout_ms: int
    llm_capabilities: list[LlmCapability]
    embedding_model: str
    storage_backend: StorageBackend
    embedding_provider: EmbeddingProvider
    embedding_base_url: str | None
    has_embedding_api_key: bool
    embedding_timeout_ms: int
    embedding_dimensions: int
    embedding_batch_size: int
    embedding_tls_verify: bool
    mineru_enabled: bool
    mineru_base_url: str | None
    mineru_timeout_ms: int
    mineru_poll_interval_ms: int
    mineru_require_hpc: bool
    runtime_mode: RuntimeMode
    vision_model: str | None
    vision_base_url: str | None
    has_vision_api_key: bool
    vision_timeout_ms: int
    reranker_provider: RerankerProvider
    reranker_fallback_provider: RerankerFallbackProvider
    reranker_model: str | None
    reranker_base_url: str | None
    has_reranker_api_key: bool
    reranker_timeout_ms: int
    pgvector_schema: str
    pgvector_table_prefix: str
    neo4j_uri: str | None
    neo4j_username: str | None
    has_neo4j_password: bool
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


class EmbeddingConnectionTestOut(StudioModel):
    ok: bool
    provider: str
    model: str
    dimensions: int | None
    latency_ms: int
    detail: str


class LlmConnectionTestOut(StudioModel):
    ok: bool
    provider: str
    model: str
    latency_ms: int
    detail: str


class MinerUConnectionTestOut(StudioModel):
    ok: bool
    base_url: str
    latency_ms: int
    detail: str


class ProviderSyncPreviewIn(StudioModel):
    manifest_url: str

    @field_validator("manifest_url")
    @classmethod
    def validate_manifest_url(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Provider manifest URL must be an http or https URL")
        if parsed.username or parsed.password:
            raise ValueError("Provider manifest URL must not include credentials")
        return normalized


class ProviderSyncPreviewOut(StudioModel):
    ok: bool
    manifest_url: str
    manifest_version: int | None = None
    updated_at: str | None = None
    patch: dict[str, object]
    changed_fields: list[str]
    ignored_sections: list[str]
    detail: str
