from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.variants import VariantIn, VariantOut, VariantPage
from ragstudio.services.variant_service import VariantService

router = APIRouter(prefix="/api/variants", tags=["variants"])


@router.post("", response_model=VariantOut, status_code=201)
async def create_variant(
    payload: VariantIn,
    session: AsyncSession = Depends(get_session),
) -> VariantOut:
    return await VariantService(session).create(payload)


@router.get("", response_model=VariantPage)
async def list_variants(session: AsyncSession = Depends(get_session)) -> VariantPage:
    return await VariantService(session).list()


@router.get("/{variant_id}", response_model=VariantOut)
async def get_variant(variant_id: str, session: AsyncSession = Depends(get_session)) -> VariantOut:
    try:
        return await VariantService(session).get_required(variant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Variant not found") from exc
