from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.variants import VariantIn, VariantOut, VariantPage, VariantUpdate
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


@router.put("/{variant_id}", response_model=VariantOut)
async def update_variant(
    variant_id: str,
    payload: VariantUpdate,
    session: AsyncSession = Depends(get_session),
) -> VariantOut:
    variant = await VariantService(session).update(variant_id, payload)
    if variant is None:
        raise HTTPException(status_code=404, detail="Variant not found")
    return variant


@router.delete("/{variant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_variant(
    variant_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    variant = await VariantService(session).delete(variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Variant not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
