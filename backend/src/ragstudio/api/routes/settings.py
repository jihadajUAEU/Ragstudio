from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.settings import SettingsProfileIn, SettingsProfileOut
from ragstudio.services.settings_service import SettingsService

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/default", response_model=SettingsProfileOut)
async def get_default_settings(session: AsyncSession = Depends(get_session)) -> SettingsProfileOut:
    profile = await SettingsService(session).get_default()
    if profile is None:
        raise HTTPException(status_code=404, detail="Default settings profile is not configured")
    return profile


@router.put("/default", response_model=SettingsProfileOut)
async def put_default_settings(
    payload: SettingsProfileIn,
    session: AsyncSession = Depends(get_session),
) -> SettingsProfileOut:
    return await SettingsService(session).upsert_default(payload)
