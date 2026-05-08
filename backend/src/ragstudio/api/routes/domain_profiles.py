from fastapi import APIRouter, HTTPException, Request

from ragstudio.schemas.parsing import (
    DomainMetadataSuggestIn,
    DomainMetadataSuggestOut,
    DomainProfileIn,
    DomainProfileListOut,
    DomainProfileOut,
)
from ragstudio.services.domain_metadata_service import DomainMetadataService

router = APIRouter(prefix="/api/domain-profiles", tags=["domain-profiles"])


@router.get("", response_model=DomainProfileListOut)
async def list_domain_profiles(request: Request) -> DomainProfileListOut:
    items = DomainMetadataService(request.app.state.settings.data_dir).list_profiles()
    return DomainProfileListOut(items=items, total=len(items))


@router.post("/suggest", response_model=DomainMetadataSuggestOut)
async def suggest_domain_metadata(
    payload: DomainMetadataSuggestIn,
    request: Request,
) -> DomainMetadataSuggestOut:
    metadata = DomainMetadataService(request.app.state.settings.data_dir).suggest(payload)
    return DomainMetadataSuggestOut(domain_metadata=metadata)


@router.put("/{profile_id}", response_model=DomainProfileOut)
async def upsert_domain_profile(
    profile_id: str,
    payload: DomainProfileIn,
    request: Request,
) -> DomainProfileOut:
    profile = payload.model_copy(update={"id": profile_id})
    try:
        return DomainMetadataService(request.app.state.settings.data_dir).upsert_profile(profile)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
