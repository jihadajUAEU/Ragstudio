from datetime import datetime
from typing import Any

from ragstudio.db.base import Base
from ragstudio.schemas.common import new_id, now_utc
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


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
        MutableDict.as_mutable(JSON), default=dict
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON), default=dict
    )
    document: Mapped[Document] = relationship(back_populates="chunks")


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ready")
    target_id: Mapped[str | None] = mapped_column(String, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    logs: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSON), default=list)
    result: Mapped[dict[str, Any]] = mapped_column(MutableDict.as_mutable(JSON), default=dict)


class Variant(Base, TimestampMixin):
    __tablename__ = "variants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String)
    preset: Mapped[str] = mapped_column(String)
    parameters: Mapped[dict[str, Any]] = mapped_column(MutableDict.as_mutable(JSON), default=dict)


class EvaluationSet(Base, TimestampMixin):
    __tablename__ = "evaluation_sets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String)
    cases: Mapped[list[dict[str, Any]]] = mapped_column(MutableList.as_mutable(JSON), default=list)


class Experiment(Base, TimestampMixin):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String)
    document_ids: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSON), default=list)
    evaluation_set_id: Mapped[str] = mapped_column(String)
    variant_ids: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSON), default=list)
    objective: Mapped[dict[str, Any]] = mapped_column(MutableDict.as_mutable(JSON), default=dict)


class Run(Base, TimestampMixin):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    variant_id: Mapped[str] = mapped_column(String)
    experiment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    query: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="ready")
    answer: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[list[dict[str, Any]]] = mapped_column(
        MutableList.as_mutable(JSON), default=list
    )
    chunk_traces: Mapped[list[dict[str, Any]]] = mapped_column(
        MutableList.as_mutable(JSON), default=list
    )
    timings: Mapped[dict[str, Any]] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Score(Base, TimestampMixin):
    __tablename__ = "scores"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String)
    total: Mapped[int] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(MutableDict.as_mutable(JSON), default=dict)


class OptimizationSession(Base, TimestampMixin):
    __tablename__ = "optimization_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(String)
    objective: Mapped[dict[str, Any]] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    selected_variant_id: Mapped[str | None] = mapped_column(String, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, default="")
    tried_variant_ids: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSON), default=list)
