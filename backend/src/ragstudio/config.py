from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAGSTUDIO_",
        env_file=".env",
        extra="ignore",
    )

    service_name: str = "rag-anything-studio"
    data_dir: Path = Field(default_factory=lambda: Path(".ragstudio").resolve())
    database_url: str = "postgresql+asyncpg://ragstudio:ragstudio@127.0.0.1:55432/ragstudio"
    pgvector_schema: str = "public"
    pgvector_table_prefix: str = "ragstudio"
    neo4j_uri: str = "bolt://127.0.0.1:57687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "ragstudio-password"
    runtime_working_dir: Path | None = None
    allowed_reranker_hosts: list[str] = Field(
        default_factory=lambda: [
            "localhost",
            "127.0.0.1",
            "::1",
            "api.jina.ai",
            "api.cohere.ai",
        ]
    )

    @field_validator("data_dir", "runtime_working_dir", mode="before")
    @classmethod
    def normalize_path(cls, value: str | Path | None) -> Path | None:
        if value is None:
            return None
        return Path(value).expanduser().resolve()

    @field_validator("allowed_reranker_hosts", mode="before")
    @classmethod
    def normalize_allowed_hosts(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [item.strip().lower() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        return value

    @field_validator("pgvector_schema", "pgvector_table_prefix")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Database identifier must not be empty")
        if not normalized.replace("_", "").isalnum():
            raise ValueError(
                "Database identifier may contain only letters, numbers, and underscores"
            )
        return normalized

    @property
    def resolved_database_url(self) -> str:
        return self.database_url

    @property
    def resolved_runtime_working_dir(self) -> Path:
        return self.runtime_working_dir or self.data_dir / "raganything"
