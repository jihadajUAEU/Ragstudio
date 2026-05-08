from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator

from ragstudio.schemas.common import StudioModel

EmbeddingProvider = Literal["fallback", "vllm_openai"]


class SettingsProfileIn(StudioModel):
    provider: str
    llm_model: str
    embedding_model: str
    storage_backend: str
    embedding_provider: EmbeddingProvider = "fallback"
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_timeout_ms: int = Field(default=10000, ge=100, le=1_800_000)
    embedding_dimensions: int = Field(default=1536, ge=1, le=65536)
    embedding_batch_size: int = Field(default=16, ge=1, le=1024)
    embedding_tls_verify: bool = True

    @field_validator("embedding_base_url")
    @classmethod
    def validate_embedding_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        if not normalized:
            return None
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Embedding base URL must be an http or https URL")
        if parsed.username or parsed.password:
            raise ValueError("Embedding base URL must not include credentials")
        return normalized

    @field_validator("embedding_api_key")
    @classmethod
    def normalize_embedding_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class SettingsProfileOut(StudioModel):
    id: str
    provider: str
    llm_model: str
    embedding_model: str
    storage_backend: str
    embedding_provider: EmbeddingProvider
    embedding_base_url: str | None
    has_embedding_api_key: bool
    embedding_timeout_ms: int
    embedding_dimensions: int
    embedding_batch_size: int
    embedding_tls_verify: bool


class EmbeddingConnectionTestOut(StudioModel):
    ok: bool
    provider: str
    model: str
    dimensions: int | None
    latency_ms: int
    detail: str
