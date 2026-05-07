from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import Experiment, OptimizationSession, Run, Score
from ragstudio.schemas.optimizer import OptimizerIn, OptimizerOut


class ExperimentNotFoundError(LookupError):
    pass


class OptimizerService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def recommend(self, payload: OptimizerIn) -> OptimizerOut:
        experiment = await self.session.get(Experiment, payload.experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(payload.experiment_id)

        runs_result = await self.session.execute(
            select(Run).where(Run.experiment_id == payload.experiment_id).order_by(Run.created_at.asc())
        )
        runs = list(runs_result.scalars().all())
        tried_variant_ids = list(dict.fromkeys(run.variant_id for run in runs))

        if not runs:
            session = OptimizationSession(
                experiment_id=payload.experiment_id,
                objective=payload.objective or experiment.objective,
                selected_variant_id=None,
                explanation="No runs are available for this experiment.",
                tried_variant_ids=tried_variant_ids,
            )
            self.session.add(session)
            await self.session.commit()
            await self.session.refresh(session)
            return self._out(session, selected_run_id=None)

        scores_result = await self.session.execute(select(Score).where(Score.run_id.in_([run.id for run in runs])))
        scores_by_run_id = {score.run_id: score for score in scores_result.scalars().all()}
        best_run = max(runs, key=lambda run: (scores_by_run_id.get(run.id).total if run.id in scores_by_run_id else 0))
        best_score = scores_by_run_id.get(best_run.id)
        total = best_score.total if best_score else 0
        session = OptimizationSession(
            experiment_id=payload.experiment_id,
            objective=payload.objective or experiment.objective,
            selected_variant_id=best_run.variant_id,
            explanation=f"Selected variant {best_run.variant_id} from run {best_run.id} with score {total}.",
            tried_variant_ids=tried_variant_ids,
        )
        self.session.add(session)
        await self.session.commit()
        await self.session.refresh(session)
        return self._out(session, selected_run_id=best_run.id)

    def _out(self, session: OptimizationSession, selected_run_id: str | None) -> OptimizerOut:
        return OptimizerOut(
            id=session.id,
            experiment_id=session.experiment_id,
            objective=session.objective,
            selected_variant_id=session.selected_variant_id,
            selected_run_id=selected_run_id,
            explanation=session.explanation,
            tried_variant_ids=session.tried_variant_ids,
        )
