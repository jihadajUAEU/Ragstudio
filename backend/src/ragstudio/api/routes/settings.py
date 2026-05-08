import time

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.settings import (
    EmbeddingConnectionTestOut,
    MinerUConnectionTestOut,
    SettingsProfileIn,
    SettingsProfileOut,
)
from ragstudio.services.embedding_connection_service import EmbeddingConnectionService
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


@router.post("/default/test-embedding", response_model=EmbeddingConnectionTestOut)
async def test_embedding_settings(
    payload: SettingsProfileIn,
    session: AsyncSession = Depends(get_session),
) -> EmbeddingConnectionTestOut:
    resolved_payload = await SettingsService(session).resolve_embedding_test_payload(payload)
    return await EmbeddingConnectionService().test(resolved_payload)


@router.post("/default/test-mineru", response_model=MinerUConnectionTestOut)
async def test_mineru_settings(payload: SettingsProfileIn) -> MinerUConnectionTestOut:
    base_url = payload.mineru_base_url or ""
    if not base_url:
        return MinerUConnectionTestOut(
            ok=False,
            base_url="",
            latency_ms=0,
            detail="MinerU base URL is not configured.",
        )

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=payload.mineru_timeout_ms / 1000) as client:
            response = await client.get(f"{base_url}/health")
        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            return MinerUConnectionTestOut(
                ok=False,
                base_url=base_url,
                latency_ms=latency_ms,
                detail=f"MinerU health check returned HTTP {response.status_code}.",
            )
        detail = "MinerU health check succeeded."
        try:
            health_payload = response.json()
            if isinstance(health_payload, dict):
                detail_value = (
                    health_payload.get("detail")
                    or health_payload.get("status")
                    or health_payload.get("service")
                    or health_payload.get("version")
                )
                if detail_value:
                    detail = str(detail_value)
        except (AttributeError, ValueError):
            if response.text.strip():
                detail = response.text.strip()
        return MinerUConnectionTestOut(
            ok=True,
            base_url=base_url,
            latency_ms=latency_ms,
            detail=detail,
        )
    except httpx.HTTPError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return MinerUConnectionTestOut(
            ok=False,
            base_url=base_url,
            latency_ms=latency_ms,
            detail=str(exc),
        )
