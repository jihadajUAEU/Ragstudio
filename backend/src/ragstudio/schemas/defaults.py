from __future__ import annotations

from ragstudio.schemas.common import StudioModel


class RuntimeDefaultsOut(StudioModel):
    llm_timeout_ms: int
    embedding_timeout_ms: int
    embedding_dimensions: int
    embedding_batch_size: int
    mineru_timeout_ms: int
    mineru_poll_interval_ms: int
    mineru_max_concurrent_files: int
    vision_timeout_ms: int
    reranker_timeout_ms: int
    chunk_token_size: int
    chunk_overlap_token_size: int
    context_window: int
    max_context_tokens: int
    top_k: int
    chunk_top_k: int
    cosine_better_than_threshold: float
    max_total_tokens: int
    max_entity_tokens: int
    max_relation_tokens: int
    llm_model_max_async: int
    embedding_func_max_async: int
    max_parallel_insert: int


class DefaultsOut(StudioModel):
    runtime: RuntimeDefaultsOut
    policy_versions: dict[str, str]
