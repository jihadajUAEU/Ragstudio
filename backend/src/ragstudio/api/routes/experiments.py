from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.experiments import ExperimentIn, ExperimentOut, ExperimentPage
from ragstudio.services.experiment_service import (
    EvaluationSetNotFoundError,
    ExperimentNotFoundError,
    ExperimentService,
)
from ragstudio.services.query_service import QueryResourceNotFoundError

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


@router.post("", response_model=ExperimentOut, status_code=201)
async def create_experiment(
    payload: ExperimentIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ExperimentOut:
    try:
        return await ExperimentService(
            session,
            request.app.state.settings.data_dir,
            settings=request.app.state.settings,
        ).create(payload)
    except EvaluationSetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Evaluation set not found") from exc
    except QueryResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", response_model=ExperimentPage)
async def list_experiments(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ExperimentPage:
    return await ExperimentService(
        session,
        request.app.state.settings.data_dir,
        settings=request.app.state.settings,
    ).list()


@router.get("/{experiment_id}", response_model=ExperimentOut)
async def get_experiment(
    experiment_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ExperimentOut:
    try:
        return await ExperimentService(
            session,
            request.app.state.settings.data_dir,
            settings=request.app.state.settings,
        ).get_required(experiment_id)
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Experiment not found") from exc
