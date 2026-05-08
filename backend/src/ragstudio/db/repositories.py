from collections.abc import Sequence
from typing import TypeVar

from ragstudio.db.base import Base
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ModelT = TypeVar("ModelT", bound=Base)


class Repository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, model: type[ModelT], item_id: str) -> ModelT | None:
        return await self.session.get(model, item_id)

    async def list(self, model: type[ModelT]) -> Sequence[ModelT]:
        result = await self.session.execute(select(model).order_by(model.created_at.desc()))  # type: ignore[attr-defined]
        return result.scalars().all()

    async def add(self, item: ModelT) -> ModelT:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete(self, item: ModelT) -> None:
        await self.session.delete(item)
        await self.session.commit()
