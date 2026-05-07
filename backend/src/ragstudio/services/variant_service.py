from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import Variant
from ragstudio.schemas.variants import VariantIn, VariantOut, VariantPage


class VariantService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: VariantIn) -> VariantOut:
        variant = Variant(**data.model_dump())
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
