from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.diagnostics import DiagnosticsOut
from ragstudio.services.diagnostics_service import DiagnosticsService

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("", response_model=DiagnosticsOut)
async def get_diagnostics(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> DiagnosticsOut:
    return await DiagnosticsService(session, request.app.state.settings).get_diagnostics()
