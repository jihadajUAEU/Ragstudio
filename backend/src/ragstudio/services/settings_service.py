from typing import cast

from ragstudio.db.models import SettingsProfile
from ragstudio.schemas.runtime import (
    QueryMode,
    RerankerFallbackProvider,
    RerankerProvider,
)
from ragstudio.schemas.settings import (
    MINERU_DEFAULT_TIMEOUT_MS,
    LlmCapability,
    LlmProvider,
    SettingsProfileIn,
    SettingsProfileOut,
)
from ragstudio.services.runtime_policy import (
    normalize_embedding_provider,
    normalize_runtime_mode,
    normalize_storage_backend,
)
from sqlalchemy.ext.asyncio import AsyncSession


class SettingsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_default(self) -> SettingsProfileOut | None:
        profile = await self.session.get(SettingsProfile, "default")
        if profile is None:
            return None
        return self._to_out(profile)

    async def upsert_default(self, data: SettingsProfileIn) -> SettingsProfileOut:
        profile = await self.session.get(SettingsProfile, "default")
        values = data.model_dump(
            exclude={
                "embedding_api_key",
                "llm_api_key",
                "vision_api_key",
                "reranker_api_key",
                "neo4j_password",
            }
        )
        values = self._normalize_runtime_values(values)
        if profile is None:
            profile = SettingsProfile(id="default", **values)
            self.session.add(profile)
        else:
            for key, value in values.items():
                setattr(profile, key, value)
        if data.embedding_api_key is not None:
            profile.embedding_api_key = data.embedding_api_key or None
        if data.llm_api_key is not None:
            profile.llm_api_key = data.llm_api_key or None
        if data.vision_api_key is not None:
            profile.vision_api_key = data.vision_api_key or None
        if data.reranker_api_key is not None:
            profile.reranker_api_key = data.reranker_api_key or None
        if data.neo4j_password is not None:
            profile.neo4j_password = data.neo4j_password or None
        await self.session.commit()
        await self.session.refresh(profile)
        return self._to_out(profile)

    async def resolve_embedding_test_payload(self, data: SettingsProfileIn) -> SettingsProfileIn:
        if data.embedding_api_key:
            return data

        profile = await self.session.get(SettingsProfile, "default")
        if profile is None or not profile.embedding_api_key:
            return data

        return data.model_copy(update={"embedding_api_key": profile.embedding_api_key})

    async def resolve_llm_test_payload(self, data: SettingsProfileIn) -> SettingsProfileIn:
        if data.llm_api_key:
            return data

        profile = await self.session.get(SettingsProfile, "default")
        if profile is None or not profile.llm_api_key:
            return data

        return data.model_copy(update={"llm_api_key": profile.llm_api_key})

    async def resolve_reranker_test_payload(self, data: SettingsProfileIn) -> SettingsProfileIn:
        if data.reranker_api_key:
            return data

        profile = await self.session.get(SettingsProfile, "default")
        if profile is None or not profile.reranker_api_key:
            return data

        return data.model_copy(update={"reranker_api_key": profile.reranker_api_key})

    def _to_out(self, profile: SettingsProfile) -> SettingsProfileOut:
        def default_bool(value: bool | None, default: bool) -> bool:
            return default if value is None else bool(value)

        return SettingsProfileOut(
            id=profile.id,
            provider=profile.provider,
            llm_model=profile.llm_model,
            llm_provider=cast(
                LlmProvider,
                profile.llm_provider if profile.llm_provider else "openai_compatible",
            ),
            llm_base_url=profile.llm_base_url,
            has_llm_api_key=bool(profile.llm_api_key),
            llm_timeout_ms=profile.llm_timeout_ms or 10000,
            llm_capabilities=[
                cast(LlmCapability, capability)
                for capability in (profile.llm_capabilities or [])
                if capability in {"text", "vision", "reasoning"}
            ],
            embedding_model=profile.embedding_model,
            storage_backend=normalize_storage_backend(profile.storage_backend),
            embedding_provider=normalize_embedding_provider(profile.embedding_provider),
            embedding_base_url=profile.embedding_base_url,
            has_embedding_api_key=bool(profile.embedding_api_key),
            embedding_timeout_ms=profile.embedding_timeout_ms or 10000,
            embedding_dimensions=profile.embedding_dimensions or 1536,
            embedding_batch_size=profile.embedding_batch_size or 16,
            embedding_tls_verify=default_bool(profile.embedding_tls_verify, True),
            mineru_enabled=bool(profile.mineru_enabled),
            mineru_base_url=profile.mineru_base_url,
            mineru_timeout_ms=max(profile.mineru_timeout_ms or 0, MINERU_DEFAULT_TIMEOUT_MS),
            mineru_poll_interval_ms=profile.mineru_poll_interval_ms or 1_000,
            mineru_require_hpc=default_bool(profile.mineru_require_hpc, True),
            runtime_mode=normalize_runtime_mode(
                profile.runtime_mode,
                profile.storage_backend,
            ),
            vision_model=profile.vision_model,
            vision_base_url=profile.vision_base_url,
            has_vision_api_key=bool(profile.vision_api_key),
            vision_timeout_ms=profile.vision_timeout_ms or 10000,
            reranker_provider=cast(
                RerankerProvider,
                profile.reranker_provider if profile.reranker_provider else "disabled",
            ),
            reranker_fallback_provider=cast(
                RerankerFallbackProvider,
                profile.reranker_fallback_provider or "disabled",
            ),
            reranker_model=profile.reranker_model,
            reranker_base_url=profile.reranker_base_url,
            has_reranker_api_key=bool(profile.reranker_api_key),
            reranker_timeout_ms=profile.reranker_timeout_ms or 10000,
            pgvector_schema=profile.pgvector_schema or "public",
            pgvector_table_prefix=profile.pgvector_table_prefix or "ragstudio",
            neo4j_uri=profile.neo4j_uri,
            neo4j_username=profile.neo4j_username,
            has_neo4j_password=bool(profile.neo4j_password),
            parser=profile.parser or "mineru",
            parse_method=profile.parse_method or "auto",
            chunk_token_size=profile.chunk_token_size or 1200,
            chunk_overlap_token_size=profile.chunk_overlap_token_size or 100,
            enable_image_processing=default_bool(profile.enable_image_processing, True),
            enable_table_processing=default_bool(profile.enable_table_processing, True),
            enable_equation_processing=default_bool(profile.enable_equation_processing, True),
            context_window=profile.context_window or 1,
            context_mode=profile.context_mode or "page",
            max_context_tokens=profile.max_context_tokens or 2000,
            include_headers=default_bool(profile.include_headers, True),
            include_captions=default_bool(profile.include_captions, True),
            query_mode=cast(QueryMode, profile.query_mode or "mix"),
            top_k=profile.top_k or 40,
            chunk_top_k=profile.chunk_top_k or 20,
            enable_rerank=default_bool(profile.enable_rerank, True),
            cosine_better_than_threshold=profile.cosine_better_than_threshold or 0.2,
            max_total_tokens=profile.max_total_tokens or 30000,
            max_entity_tokens=profile.max_entity_tokens or 6000,
            max_relation_tokens=profile.max_relation_tokens or 8000,
            enable_llm_cache=default_bool(profile.enable_llm_cache, True),
            enable_llm_cache_for_entity_extract=default_bool(
                profile.enable_llm_cache_for_entity_extract,
                True,
            ),
            llm_model_max_async=profile.llm_model_max_async or 4,
            embedding_func_max_async=profile.embedding_func_max_async or 8,
            max_parallel_insert=profile.max_parallel_insert or 2,
        )

    def _normalize_runtime_values(self, values: dict[str, object]) -> dict[str, object]:
        storage_backend = normalize_storage_backend(
            cast(str | None, values.get("storage_backend"))
        )
        values["storage_backend"] = storage_backend
        values["runtime_mode"] = normalize_runtime_mode(
            cast(str | None, values.get("runtime_mode")),
            storage_backend,
        )
        values["embedding_provider"] = normalize_embedding_provider(
            cast(str | None, values.get("embedding_provider"))
        )
        timeout = values.get("mineru_timeout_ms")
        if isinstance(timeout, int):
            values["mineru_timeout_ms"] = max(timeout, MINERU_DEFAULT_TIMEOUT_MS)
        return values
