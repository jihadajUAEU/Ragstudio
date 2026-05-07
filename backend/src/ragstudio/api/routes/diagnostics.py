from fastapi import APIRouter

from ragstudio.schemas.diagnostics import DiagnosticsOut
from ragstudio.services.diagnostics_service import DiagnosticsService

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("", response_model=DiagnosticsOut)
async def get_diagnostics() -> DiagnosticsOut:
    return DiagnosticsService().get_diagnostics()
