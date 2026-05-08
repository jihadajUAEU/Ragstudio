from datetime import datetime
from typing import Any

from ragstudio.db.base import Base
from ragstudio.schemas.common import new_id, now_utc
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

JsonDictType = MutableDict.as_mutable(JSON().with_variant(JSONB, "postgresql"))
JsonListType = MutableList.as_mutable(JSON().with_variant(JSONB, "postgresql"))


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


class SettingsProfile(Base, TimestampMixin):
    __tablename__ = "settings_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: "default")
    provider: Mapped[str] = mapped_column(String)
    llm_model: Mapped[str] = mapped_column(String)
    llm_provider: Mapped[str] = mapped_column(String, default="openai_compatible")
    llm_base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_timeout_ms: Mapped[int] = mapped_column(Integer, default=10000)
    llm_capabilities: Mapped[list[str]] = mapped_column(
        JsonListType, default=list
    )
    embedding_model: Mapped[str] = mapped_column(String)
    storage_backend: Mapped[str] = mapped_column(String)
    embedding_provider: Mapped[str] = mapped_column(String, default="fallback")
    embedding_base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    embedding_api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    embedding_timeout_ms: Mapped[int] = mapped_column(Integer, default=10000)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, default=1536)
    embedding_batch_size: Mapped[int] = mapped_column(Integer, default=16)
    embedding_tls_verify: Mapped[bool] = mapped_column(Boolean, default=True)
    mineru_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mineru_base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    mineru_timeout_ms: Mapped[int] = mapped_column(Integer, default=1_800_000)
    mineru_poll_interval_ms: Mapped[int] = mapped_column(Integer, default=1_000)
    runtime_mode: Mapped[str] = mapped_column(String, default="runtime")
    vision_model: Mapped[str | None] = mapped_column(String, nullable=True)
    vision_base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    vision_api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    vision_timeout_ms: Mapped[int] = mapped_column(Integer, default=10000)
    reranker_provider: Mapped[str] = mapped_column(String, default="disabled")
    reranker_model: Mapped[str | None] = mapped_column(String, nullable=True)
    reranker_base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    reranker_api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    reranker_timeout_ms: Mapped[int] = mapped_column(Integer, default=10000)
    pgvector_schema: Mapped[str] = mapped_column(String, default="public")
    pgvector_table_prefix: Mapped[str] = mapped_column(String, default="ragstudio")
    neo4j_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    neo4j_username: Mapped[str | None] = mapped_column(String, nullable=True)
    neo4j_password: Mapped[str | None] = mapped_column(String, nullable=True)
    parser: Mapped[str] = mapped_column(String, default="mineru")
    parse_method: Mapped[str] = mapped_column(String, default="auto")
    chunk_token_size: Mapped[int] = mapped_column(Integer, default=1200)
    chunk_overlap_token_size: Mapped[int] = mapped_column(Integer, default=100)
    enable_image_processing: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_table_processing: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_equation_processing: Mapped[bool] = mapped_column(Boolean, default=True)
    context_window: Mapped[int] = mapped_column(Integer, default=1)
    context_mode: Mapped[str] = mapped_column(String, default="page")
    max_context_tokens: Mapped[int] = mapped_column(Integer, default=2000)
    include_headers: Mapped[bool] = mapped_column(Boolean, default=True)
    include_captions: Mapped[bool] = mapped_column(Boolean, default=True)
    query_mode: Mapped[str] = mapped_column(String, default="mix")
    top_k: Mapped[int] = mapped_column(Integer, default=40)
    chunk_top_k: Mapped[int] = mapped_column(Integer, default=20)
    enable_rerank: Mapped[bool] = mapped_column(Boolean, default=True)
    cosine_better_than_threshold: Mapped[float] = mapped_column(Float, default=0.2)
    max_total_tokens: Mapped[int] = mapped_column(Integer, default=30000)
    max_entity_tokens: Mapped[int] = mapped_column(Integer, default=6000)
    max_relation_tokens: Mapped[int] = mapped_column(Integer, default=8000)
    enable_llm_cache: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_llm_cache_for_entity_extract: Mapped[bool] = mapped_column(Boolean, default=True)
    llm_model_max_async: Mapped[int] = mapped_column(Integer, default=4)
    embedding_func_max_async: Mapped[int] = mapped_column(Integer, default=8)
    max_parallel_insert: Mapped[int] = mapped_column(Integer, default=2)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String)
    content_type: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String, unique=True)
    artifact_path: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ready")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base, TimestampMixin):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    text: Mapped[str] = mapped_column(Text)
    source_location: Mapped[dict[str, Any]] = mapped_column(
        JsonDictType, default=dict
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JsonDictType, default=dict
    )
    runtime_profile_id: Mapped[str | None] = mapped_column(String, nullable=True)
    runtime_source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    content_type: Mapped[str] = mapped_column(String, default="text")
    preview_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    document: Mapped[Document] = relationship(back_populates="chunks")


class IndexRecord(Base, TimestampMixin):
    __tablename__ = "index_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    runtime_profile_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ready")
    index_shape: Mapped[dict[str, Any]] = mapped_column(
        JsonDictType, default=dict
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ready")
    target_id: Mapped[str | None] = mapped_column(String, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    logs: Mapped[list[str]] = mapped_column(JsonListType, default=list)
    result: Mapped[dict[str, Any]] = mapped_column(
        JsonDictType, default=dict
    )


class Variant(Base, TimestampMixin):
    __tablename__ = "variants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String)
    preset: Mapped[str] = mapped_column(String)
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JsonDictType, default=dict
    )


class EvaluationSet(Base, TimestampMixin):
    __tablename__ = "evaluation_sets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String)
    cases: Mapped[list[dict[str, Any]]] = mapped_column(
        JsonListType, default=list
    )


class Experiment(Base, TimestampMixin):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String)
    document_ids: Mapped[list[str]] = mapped_column(
        JsonListType, default=list
    )
    evaluation_set_id: Mapped[str] = mapped_column(String)
    variant_ids: Mapped[list[str]] = mapped_column(
        JsonListType, default=list
    )
    objective: Mapped[dict[str, Any]] = mapped_column(
        JsonDictType, default=dict
    )


class Run(Base, TimestampMixin):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    variant_id: Mapped[str] = mapped_column(String)
    experiment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    runtime_profile_id: Mapped[str | None] = mapped_column(String, nullable=True)
    query: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="ready")
    answer: Mapped[str] = mapped_column(Text, default="")
    document_ids: Mapped[list[str]] = mapped_column(
        JsonListType, default=list
    )
    query_config: Mapped[dict[str, Any]] = mapped_column(
        JsonDictType, default=dict
    )
    sources: Mapped[list[dict[str, Any]]] = mapped_column(
        JsonListType, default=list
    )
    chunk_traces: Mapped[list[dict[str, Any]]] = mapped_column(
        JsonListType, default=list
    )
    reranker_traces: Mapped[list[dict[str, Any]]] = mapped_column(
        JsonListType, default=list
    )
    timings: Mapped[dict[str, Any]] = mapped_column(
        JsonDictType, default=dict
    )
    token_metadata: Mapped[dict[str, Any]] = mapped_column(
        JsonDictType, default=dict
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String, nullable=True)


class Score(Base, TimestampMixin):
    __tablename__ = "scores"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String)
    total: Mapped[int] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(
        JsonDictType, default=dict
    )


class OptimizationSession(Base, TimestampMixin):
    __tablename__ = "optimization_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(String)
    objective: Mapped[dict[str, Any]] = mapped_column(
        JsonDictType, default=dict
    )
    selected_variant_id: Mapped[str | None] = mapped_column(String, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, default="")
    tried_variant_ids: Mapped[list[str]] = mapped_column(
        JsonListType, default=list
    )
