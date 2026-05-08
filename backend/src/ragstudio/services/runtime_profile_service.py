from pathlib import Path
from typing import cast

from ragstudio.config import AppSettings
from ragstudio.db.models import SettingsProfile
from ragstudio.schemas.runtime import (
    QueryMode,
    RerankerProvider,
    RuntimeMode,
    RuntimeProfile,
    StorageBackend,
)
from sqlalchemy.ext.asyncio import AsyncSession


class RuntimeProfileNotConfiguredError(RuntimeError):
    pass


class RuntimeProfileService:
    def __init__(self, session: AsyncSession, settings: AppSettings):
        self.session = session
        self.settings = settings

    async def get_active_profile(self) -> RuntimeProfile:
        profile = await self.session.get(SettingsProfile, "default")
        if profile is None:
            raise RuntimeProfileNotConfiguredError("Default runtime profile is not configured.")

        runtime_working_dir = Path(self.settings.resolved_runtime_working_dir)
        runtime_working_dir.mkdir(parents=True, exist_ok=True)
        index_shape = {
            "embedding_model": profile.embedding_model,
            "embedding_dimensions": profile.embedding_dimensions or 1536,
            "parser": profile.parser or "mineru",
            "parse_method": profile.parse_method or "auto",
            "chunk_token_size": profile.chunk_token_size or 1200,
            "chunk_overlap_token_size": profile.chunk_overlap_token_size or 100,
            "graph_storage": "neo4j",
            "vector_storage": "pgvector",
        }

        return RuntimeProfile(
            id=profile.id,
            runtime_mode=cast(RuntimeMode, profile.runtime_mode or "runtime"),
            provider=profile.provider,
            llm_model=profile.llm_model,
            llm_base_url=profile.llm_base_url,
            llm_timeout_ms=profile.llm_timeout_ms or 10000,
            llm_capabilities=profile.llm_capabilities or [],
            vision_model=profile.vision_model,
            vision_base_url=profile.vision_base_url,
            vision_timeout_ms=profile.vision_timeout_ms or 10000,
            embedding_provider=profile.embedding_provider or "fallback",
            embedding_model=profile.embedding_model,
            embedding_base_url=profile.embedding_base_url,
            embedding_dimensions=profile.embedding_dimensions or 1536,
            embedding_batch_size=profile.embedding_batch_size or 16,
            embedding_timeout_ms=profile.embedding_timeout_ms or 10000,
            reranker_provider=cast(
                RerankerProvider,
                profile.reranker_provider or "disabled",
            ),
            reranker_model=profile.reranker_model,
            reranker_base_url=profile.reranker_base_url,
            reranker_timeout_ms=profile.reranker_timeout_ms or 10000,
            storage_backend=cast(
                StorageBackend,
                profile.storage_backend or "postgres_pgvector_neo4j",
            ),
            pgvector_schema=profile.pgvector_schema or self.settings.pgvector_schema,
            pgvector_table_prefix=(
                profile.pgvector_table_prefix or self.settings.pgvector_table_prefix
            ),
            neo4j_uri=profile.neo4j_uri or self.settings.neo4j_uri,
            neo4j_username=profile.neo4j_username or self.settings.neo4j_username,
            parser=profile.parser or "mineru",
            parse_method=profile.parse_method or "auto",
            chunk_token_size=profile.chunk_token_size or 1200,
            chunk_overlap_token_size=profile.chunk_overlap_token_size or 100,
            enable_image_processing=self._default_bool(profile.enable_image_processing, True),
            enable_table_processing=self._default_bool(profile.enable_table_processing, True),
            enable_equation_processing=self._default_bool(
                profile.enable_equation_processing,
                True,
            ),
            context_window=profile.context_window or 1,
            context_mode=profile.context_mode or "page",
            max_context_tokens=profile.max_context_tokens or 2000,
            include_headers=self._default_bool(profile.include_headers, True),
            include_captions=self._default_bool(profile.include_captions, True),
            query_mode=cast(QueryMode, profile.query_mode or "mix"),
            top_k=profile.top_k or 40,
            chunk_top_k=profile.chunk_top_k or 20,
            enable_rerank=self._default_bool(profile.enable_rerank, True),
            cosine_better_than_threshold=profile.cosine_better_than_threshold or 0.2,
            max_total_tokens=profile.max_total_tokens or 30000,
            max_entity_tokens=profile.max_entity_tokens or 6000,
            max_relation_tokens=profile.max_relation_tokens or 8000,
            enable_llm_cache=self._default_bool(profile.enable_llm_cache, True),
            enable_llm_cache_for_entity_extract=self._default_bool(
                profile.enable_llm_cache_for_entity_extract,
                True,
            ),
            llm_model_max_async=profile.llm_model_max_async or 4,
            embedding_func_max_async=profile.embedding_func_max_async or 8,
            max_parallel_insert=profile.max_parallel_insert or 2,
            runtime_working_dir=str(runtime_working_dir),
            index_shape=index_shape,
        )

    @staticmethod
    def _default_bool(value: bool | None, default: bool) -> bool:
        return default if value is None else bool(value)
