from fastapi import APIRouter

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "rag-anything-studio"}
