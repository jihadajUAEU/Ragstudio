from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import SettingsProfile
from ragstudio.schemas.settings import SettingsProfileIn, SettingsProfileOut


class SettingsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_default(self) -> SettingsProfileOut | None:
        profile = await self.session.get(SettingsProfile, "default")
        if profile is None:
            return None
        return SettingsProfileOut.model_validate(profile)

    async def upsert_default(self, data: SettingsProfileIn) -> SettingsProfileOut:
        profile = await self.session.get(SettingsProfile, "default")
        if profile is None:
            profile = SettingsProfile(id="default", **data.model_dump())
            self.session.add(profile)
        else:
            for key, value in data.model_dump().items():
                setattr(profile, key, value)
        await self.session.commit()
        await self.session.refresh(profile)
        return SettingsProfileOut.model_validate(profile)
