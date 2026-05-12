import time

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session, get_settings
from ragstudio.config import AppSettings
from ragstudio.schemas.settings import (
    EmbeddingConnectionTestOut,
    LlmConnectionTestOut,
    MinerUConnectionTestOut,
    ProviderSyncPreviewIn,
    ProviderSyncPreviewOut,
    RerankerConnectionTestOut,
    SettingsProfileIn,
    SettingsProfileOut,
)
from ragstudio.services.embedding_connection_service import EmbeddingConnectionService
from ragstudio.services.llm_connection_service import LlmConnectionService
from ragstudio.services.mineru_client import MinerUClient
from ragstudio.services.provider_manifest_service import (
    ProviderManifestError,
    ProviderManifestService,
)
from ragstudio.services.reranker_connection_service import RerankerConnectionService
from ragstudio.services.runtime_policy import (
    ProductPolicyError,
    enforce_product_runtime_settings,
)
from ragstudio.services.settings_service import SettingsService

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/default", response_model=SettingsProfileOut)
async def get_default_settings(session: AsyncSession = Depends(get_session)) -> SettingsProfileOut:
    try:
        profile = await SettingsService(session).get_default()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=_legacy_profile_detail(exc)) from exc
    if profile is None:
        raise HTTPException(status_code=404, detail="Default settings profile is not configured")
    return profile


@router.put("/default", response_model=SettingsProfileOut)
async def put_default_settings(
    payload: SettingsProfileIn,
    session: AsyncSession = Depends(get_session),
) -> SettingsProfileOut:
    try:
        enforce_product_runtime_settings(
            storage_backend=payload.storage_backend,
            runtime_mode=payload.runtime_mode,
        )
    except ProductPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await SettingsService(session).upsert_default(payload)


@router.post("/default/sync-provider-preview", response_model=ProviderSyncPreviewOut)
async def sync_provider_preview(
    payload: ProviderSyncPreviewIn,
    session: AsyncSession = Depends(get_session),
) -> ProviderSyncPreviewOut:
    settings_service = SettingsService(session)
    try:
        current = await settings_service.get_default()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=_legacy_profile_detail(exc)) from exc
    try:
        return await ProviderManifestService().preview(payload.manifest_url, current)
    except ProviderManifestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _legacy_profile_detail(exc: ValueError) -> str:
    return (
        f"{exc}. The saved runtime profile contains legacy values that are not valid for "
        "the MinerU/Postgres runtime. Save Settings with storage_backend="
        "postgres_pgvector_neo4j, runtime_mode=runtime, and embedding_provider=vllm_openai."
    )


@router.post("/default/test-embedding", response_model=EmbeddingConnectionTestOut)
async def test_embedding_settings(
    payload: SettingsProfileIn,
    session: AsyncSession = Depends(get_session),
) -> EmbeddingConnectionTestOut:
    resolved_payload = await SettingsService(session).resolve_embedding_test_payload(payload)
    return await EmbeddingConnectionService().test(resolved_payload)


@router.post("/default/test-llm", response_model=LlmConnectionTestOut)
async def test_llm_settings(
    payload: SettingsProfileIn,
    session: AsyncSession = Depends(get_session),
) -> LlmConnectionTestOut:
    resolved_payload = await SettingsService(session).resolve_llm_test_payload(payload)
    return await LlmConnectionService().test(resolved_payload)


@router.post("/default/test-reranker", response_model=RerankerConnectionTestOut)
async def test_reranker_settings(
    payload: SettingsProfileIn,
    session: AsyncSession = Depends(get_session),
    settings: AppSettings = Depends(get_settings),
) -> RerankerConnectionTestOut:
    resolved_payload = await SettingsService(session).resolve_reranker_test_payload(payload)
    return await RerankerConnectionService(settings.allowed_reranker_hosts).test(
        resolved_payload
    )


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
        health = await MinerUClient(
            base_url=base_url,
            timeout_ms=payload.mineru_timeout_ms,
            poll_interval_ms=payload.mineru_poll_interval_ms,
        ).health()
        latency_ms = int((time.perf_counter() - started) * 1000)
        if not health.ready:
            return MinerUConnectionTestOut(
                ok=False,
                base_url=base_url,
                latency_ms=latency_ms,
                detail=health.detail or "MinerU sidecar is not ready.",
            )
        if payload.mineru_require_hpc and not health.is_hpc_coordinator:
            return MinerUConnectionTestOut(
                ok=False,
                base_url=base_url,
                latency_ms=latency_ms,
                detail=(
                    "MinerU sidecar is reachable but reports local mode. "
                    f"hpcMineru.enabled={health.hpc_enabled}; "
                    f"mode={health.hpc_mode or 'unknown'}. "
                    "Start the HPC coordinator sidecar or disable the HPC requirement."
                ),
            )
        mode_detail = (
            "HPC coordinator mode"
            if health.is_hpc_coordinator
            else f"{health.hpc_mode or 'unknown'} mode"
        )
        return MinerUConnectionTestOut(
            ok=True,
            base_url=base_url,
            latency_ms=latency_ms,
            detail=f"{health.detail or 'MinerU health check succeeded.'} ({mode_detail}).",
        )
    except httpx.HTTPError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return MinerUConnectionTestOut(
            ok=False,
            base_url=base_url,
            latency_ms=latency_ms,
            detail=f"MinerU health check failed: {exc}",
        )
