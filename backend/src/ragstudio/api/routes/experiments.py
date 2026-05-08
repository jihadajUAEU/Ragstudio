from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.experiments import ExperimentIn, ExperimentOut
from ragstudio.services.experiment_service import EvaluationSetNotFoundError, ExperimentService
from ragstudio.services.query_service import QueryResourceNotFoundError

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


@router.post("", response_model=ExperimentOut, status_code=201)
async def create_experiment(
    payload: ExperimentIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ExperimentOut:
    try:
        return await ExperimentService(session, request.app.state.settings.data_dir).create(payload)
    except EvaluationSetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Evaluation set not found") from exc
    except QueryResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
