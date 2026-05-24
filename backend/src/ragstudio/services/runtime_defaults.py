from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeDefaults:
    llm_timeout_ms: int = 10_000
    embedding_timeout_ms: int = 10_000
    embedding_dimensions: int = 1_536
    embedding_batch_size: int = 16
    mineru_timeout_ms: int = 14_400_000
    mineru_poll_interval_ms: int = 1_000
    mineru_max_concurrent_files: int = 1
    vision_timeout_ms: int = 10_000
    reranker_timeout_ms: int = 10_000
    chunk_token_size: int = 1_200
    chunk_overlap_token_size: int = 100
    context_window: int = 1
    max_context_tokens: int = 2_000
    top_k: int = 40
    chunk_top_k: int = 20
    cosine_better_than_threshold: float = 0.2
    max_total_tokens: int = 30_000
    max_entity_tokens: int = 6_000
    max_relation_tokens: int = 8_000
    llm_model_max_async: int = 4
    embedding_func_max_async: int = 8
    max_parallel_insert: int = 2


@dataclass(frozen=True, slots=True)
class RuntimeLimits:
    timeout_min_ms: int = 100
    timeout_max_ms: int = 1_800_000
    mineru_timeout_max_ms: int = 28_800_000
    mineru_poll_interval_max_ms: int = 60_000
    mineru_max_concurrent_files_max: int = 8
    embedding_dimensions_max: int = 65_536
    embedding_batch_size_max: int = 1_024
    chunk_token_size_min: int = 100
    chunk_token_size_max: int = 8_192
    chunk_overlap_token_size_max: int = 2_048
    context_window_max: int = 10
    max_context_tokens_max: int = 100_000
    top_k_max: int = 200
    runtime_token_budget_max: int = 1_000_000
    async_limit_max: int = 128
    max_parallel_insert_max: int = 64


RUNTIME_DEFAULTS = RuntimeDefaults()
RUNTIME_LIMITS = RuntimeLimits()


def numeric_default_column_sql(name: str) -> str:
    value = getattr(RUNTIME_DEFAULTS, name)
    column_type = "FLOAT" if isinstance(value, float) else "INTEGER"
    return f"{column_type} DEFAULT {value} NOT NULL"
