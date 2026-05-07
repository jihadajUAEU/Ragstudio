from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.api.deps import get_session
from ragstudio.schemas.optimizer import OptimizerIn, OptimizerOut
from ragstudio.services.optimizer_service import ExperimentNotFoundError, OptimizerService

router = APIRouter(prefix="/api/optimizer", tags=["optimizer"])


@router.post("", response_model=OptimizerOut)
async def recommend(
    payload: OptimizerIn,
    session: AsyncSession = Depends(get_session),
) -> OptimizerOut:
    try:
        return await OptimizerService(session).recommend(payload)
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Experiment not found") from exc


@router.post("/{experiment_id}", response_model=OptimizerOut)
async def recommend_for_experiment(
    experiment_id: str,
    session: AsyncSession = Depends(get_session),
) -> OptimizerOut:
    return await recommend(OptimizerIn(experiment_id=experiment_id), session)
