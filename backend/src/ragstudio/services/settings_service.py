from typing import cast

from ragstudio.db.models import SettingsProfile
from ragstudio.schemas.settings import (
    EmbeddingProvider,
    LlmCapability,
    LlmProvider,
    SettingsProfileIn,
    SettingsProfileOut,
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
        values = data.model_dump(exclude={"embedding_api_key", "llm_api_key"})
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

    def _to_out(self, profile: SettingsProfile) -> SettingsProfileOut:
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
            storage_backend=profile.storage_backend,
            embedding_provider=cast(
                EmbeddingProvider,
                profile.embedding_provider if profile.embedding_provider else "fallback",
            ),
            embedding_base_url=profile.embedding_base_url,
            has_embedding_api_key=bool(profile.embedding_api_key),
            embedding_timeout_ms=profile.embedding_timeout_ms or 10000,
            embedding_dimensions=profile.embedding_dimensions or 1536,
            embedding_batch_size=profile.embedding_batch_size or 16,
            embedding_tls_verify=bool(profile.embedding_tls_verify),
            mineru_enabled=bool(profile.mineru_enabled),
            mineru_base_url=profile.mineru_base_url,
            mineru_timeout_ms=profile.mineru_timeout_ms or 1_800_000,
            mineru_poll_interval_ms=profile.mineru_poll_interval_ms or 1_000,
        )
