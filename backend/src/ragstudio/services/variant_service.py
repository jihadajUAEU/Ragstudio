from ragstudio.db.models import Variant
from ragstudio.schemas.variants import (
    VARIANT_PRESET_DEFAULTS,
    VariantIn,
    VariantOut,
    VariantPage,
    VariantUpdate,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class VariantService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: VariantIn) -> VariantOut:
        payload = data.model_dump()
        payload["parameters"] = self._parameters_with_preset_defaults(
            payload["preset"], payload["parameters"]
        )
        variant = Variant(**payload)
        self.session.add(variant)
        await self.session.commit()
        await self.session.refresh(variant)
        return VariantOut.model_validate(variant)

    async def list(self) -> VariantPage:
        result = await self.session.execute(select(Variant).order_by(Variant.created_at.desc()))
        variants = [VariantOut.model_validate(item) for item in result.scalars().all()]
        return VariantPage(items=variants, total=len(variants))

    async def get_required(self, variant_id: str) -> VariantOut:
        variant = await self.session.get(Variant, variant_id)
        if variant is None:
            raise KeyError(variant_id)
        return VariantOut.model_validate(variant)

    async def update(self, variant_id: str, data: VariantUpdate) -> VariantOut | None:
        variant = await self.session.get(Variant, variant_id)
        if variant is None:
            return None

        payload = data.model_dump()
        variant.name = payload["name"]
        variant.preset = payload["preset"]
        variant.parameters = self._parameters_with_preset_defaults(
            payload["preset"], payload["parameters"]
        )
        await self.session.commit()
        await self.session.refresh(variant)
        return VariantOut.model_validate(variant)

    async def delete(self, variant_id: str) -> VariantOut | None:
        variant = await self.session.get(Variant, variant_id)
        if variant is None:
            return None

        deleted = VariantOut.model_validate(variant)
        await self.session.delete(variant)
        await self.session.commit()
        return deleted

    def _parameters_with_preset_defaults(
        self, preset: str, parameters: dict[str, object]
    ) -> dict[str, object]:
        return {**VARIANT_PRESET_DEFAULTS[preset], **parameters}
