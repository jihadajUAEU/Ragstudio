from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.api.upload_utils import read_upload_file
from ragstudio.db.models import SettingsProfile
from ragstudio.schemas.parsing import (
    DomainMetadataSuggestOut,
    DomainProfileIn,
    DomainProfileListOut,
    DomainProfileOut,
)
from ragstudio.services.domain_metadata_ai_suggester import DomainMetadataAiSuggester
from ragstudio.services.domain_metadata_service import DomainMetadataService
from ragstudio.services.metadata_json_schema import (
    reference_custom_json_example,
    validate_custom_json,
)
from ragstudio.services.page_sampler import PageSampler

router = APIRouter(prefix="/api/domain-profiles", tags=["domain-profiles"])


@router.get("", response_model=DomainProfileListOut)
async def list_domain_profiles(request: Request) -> DomainProfileListOut:
    items = DomainMetadataService(request.app.state.settings.data_dir).list_profiles()
    return DomainProfileListOut(items=items, total=len(items))


@router.get("/reference-json-example")
async def get_reference_json_example() -> dict[str, object]:
    return {"custom_json": reference_custom_json_example()}


@router.post("/suggest", response_model=DomainMetadataSuggestOut)
async def suggest_domain_metadata(
    request: Request,
    session: AsyncSession = Depends(get_session),
    file: UploadFile = File(...),
    profile_id: str | None = Form(default=None),
) -> DomainMetadataSuggestOut:
    service = DomainMetadataService(request.app.state.settings.data_dir)
    baseline_profile = None
    if profile_id:
        profile = service.get_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Domain profile not found.")
        baseline_profile = profile.metadata

    settings_profile = await session.get(SettingsProfile, "default")
    if settings_profile is None:
        raise HTTPException(
            status_code=409,
            detail="Default settings profile is required for AI metadata autosuggest.",
        )

    filename = file.filename or "upload"
    content_type = file.content_type or "application/octet-stream"
    data = await read_upload_file(file)
    sampler = PageSampler(max_pages=10)
    pages = sampler.sample(data, filename=filename, content_type=content_type)
    if not pages:
        raise HTTPException(
            status_code=422,
            detail="Could not sample pages from this file for AI metadata autosuggest.",
        )
    try:
        return await DomainMetadataAiSuggester().suggest(
            settings_profile=settings_profile,
            filename=filename,
            content_type=content_type,
            pages=pages,
            sampler_warnings=sampler.warnings,
            baseline_profile=baseline_profile,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.put("/{profile_id}", response_model=DomainProfileOut)
async def upsert_domain_profile(
    profile_id: str,
    payload: DomainProfileIn,
    request: Request,
) -> DomainProfileOut:
    try:
        validate_custom_json(payload.metadata.custom_json)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    profile = payload.model_copy(update={"id": profile_id})
    try:
        return DomainMetadataService(request.app.state.settings.data_dir).upsert_profile(profile)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
