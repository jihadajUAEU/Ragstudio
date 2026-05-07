from ragstudio.db.models import Experiment, OptimizationSession, Run, Score
from ragstudio.schemas.optimizer import OptimizerCandidateSummary, OptimizerIn, OptimizerOut
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


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
            select(Run)
            .where(Run.experiment_id == payload.experiment_id)
            .order_by(Run.created_at.asc())
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

        scores_result = await self.session.execute(
            select(Score).where(Score.run_id.in_([run.id for run in runs]))
        )
        scores_by_run_id = {score.run_id: score for score in scores_result.scalars().all()}
        candidate_summaries = self._summarize_candidates(runs, scores_by_run_id)
        selected_summary = max(
            candidate_summaries,
            key=lambda item: (item.average_score, item.total_score, item.run_count),
        )
        selected_run_id = selected_summary.best_run_id
        session = OptimizationSession(
            experiment_id=payload.experiment_id,
            objective=payload.objective or experiment.objective,
            selected_variant_id=selected_summary.variant_id,
            explanation=(
                f"Selected variant {selected_summary.variant_id} with average score "
                f"{selected_summary.average_score:.2f} across {selected_summary.run_count} runs "
                f"(total {selected_summary.total_score:.2f})."
            ),
            tried_variant_ids=tried_variant_ids,
        )
        self.session.add(session)
        await self.session.commit()
        await self.session.refresh(session)
        return self._out(
            session, selected_run_id=selected_run_id, candidate_summaries=candidate_summaries
        )

    def _summarize_candidates(
        self, runs: list[Run], scores_by_run_id: dict[str, Score]
    ) -> list[OptimizerCandidateSummary]:
        grouped: dict[str, list[tuple[Run, float]]] = {}
        for run in runs:
            grouped.setdefault(run.variant_id, []).append(
                (run, self._run_score(run, scores_by_run_id.get(run.id)))
            )

        summaries: list[OptimizerCandidateSummary] = []
        for variant_id, scored_runs in grouped.items():
            total_score = sum(score for _, score in scored_runs)
            best_run, best_run_score = max(scored_runs, key=lambda item: item[1])
            summaries.append(
                OptimizerCandidateSummary(
                    variant_id=variant_id,
                    run_count=len(scored_runs),
                    average_score=round(total_score / len(scored_runs), 2),
                    total_score=round(total_score, 2),
                    best_run_id=best_run.id,
                    best_run_score=round(best_run_score, 2),
                )
            )
        return summaries

    def _run_score(self, run: Run, score: Score | None) -> float:
        if score is not None:
            return float(score.total)
        if run.error:
            return 0.0
        return float(min(100, 50 + (10 * len(run.sources))))

    def _out(
        self,
        session: OptimizationSession,
        selected_run_id: str | None,
        candidate_summaries: list[OptimizerCandidateSummary] | None = None,
    ) -> OptimizerOut:
        return OptimizerOut(
            id=session.id,
            experiment_id=session.experiment_id,
            objective=session.objective,
            selected_variant_id=session.selected_variant_id,
            selected_run_id=selected_run_id,
            explanation=session.explanation,
            tried_variant_ids=session.tried_variant_ids,
            candidate_summaries=candidate_summaries or [],
        )
