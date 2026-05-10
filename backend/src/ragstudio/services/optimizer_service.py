from dataclasses import dataclass
from datetime import datetime

from ragstudio.db.models import Experiment, OptimizationSession, Run, Score
from ragstudio.schemas.optimizer import OptimizerCandidateSummary, OptimizerIn, OptimizerOut
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class ExperimentNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class _RunScore:
    run: Run
    rank_group: int
    score: float | None
    scoreable: bool
    failed: bool

    @property
    def unscored_success(self) -> bool:
        return not self.scoreable and not self.failed


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
            .order_by(Run.created_at.asc(), Run.id.asc())
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
        selected_summary = sorted(candidate_summaries, key=self._summary_sort_key)[0]
        selected_run_id = selected_summary.best_run_id
        session = OptimizationSession(
            experiment_id=payload.experiment_id,
            objective=payload.objective or experiment.objective,
            selected_variant_id=selected_summary.variant_id,
            explanation=(
                f"Selected variant {selected_summary.variant_id} with "
                f"{self._summary_score_phrase(selected_summary)} across "
                f"{selected_summary.run_count} runs."
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
        grouped: dict[str, list[_RunScore]] = {}
        for run in runs:
            grouped.setdefault(run.variant_id, []).append(self._run_score(run, scores_by_run_id.get(run.id)))

        summaries: list[OptimizerCandidateSummary] = []
        for variant_id, run_scores in grouped.items():
            scoreable_scores = [item.score for item in run_scores if item.scoreable and item.score is not None]
            total_score = sum(scoreable_scores) if scoreable_scores else None
            average_score = (
                round(total_score / len(scoreable_scores), 2)
                if total_score is not None and scoreable_scores
                else None
            )
            failed_count = sum(1 for item in run_scores if item.failed)
            unscored_count = sum(1 for item in run_scores if item.unscored_success)
            scoreable_count = len(scoreable_scores)
            best = sorted(run_scores, key=self._run_score_sort_key)[0]
            best_run_score = best.score if best.scoreable else None
            summaries.append(
                OptimizerCandidateSummary(
                    variant_id=variant_id,
                    run_count=len(run_scores),
                    average_score=average_score,
                    total_score=round(total_score, 2) if total_score is not None else None,
                    best_run_id=best.run.id,
                    best_run_score=round(best_run_score, 2) if best_run_score is not None else None,
                    score_status=self._score_status(
                        run_count=len(run_scores),
                        scoreable_count=scoreable_count,
                        unscored_count=unscored_count,
                        failed_count=failed_count,
                    ),
                    scoreable_run_count=scoreable_count,
                    unscored_run_count=unscored_count,
                    failed_run_count=failed_count,
                )
            )
        return summaries

    def _run_score(self, run: Run, score: Score | None) -> _RunScore:
        if run.error or run.status in {"failed", "error"}:
            return _RunScore(run=run, rank_group=0, score=0.0, scoreable=False, failed=True)
        if score is not None and score.details.get("scoreable") is not False:
            return _RunScore(
                run=run,
                rank_group=2,
                score=float(score.total),
                scoreable=True,
                failed=False,
            )
        return _RunScore(run=run, rank_group=1, score=None, scoreable=False, failed=False)

    def _run_score_sort_key(self, item: _RunScore) -> tuple[int, float, datetime, str]:
        return (
            -item.rank_group,
            -(item.score if item.score is not None else -1.0),
            item.run.created_at,
            item.run.id,
        )

    def _summary_sort_key(self, item: OptimizerCandidateSummary) -> tuple:
        status_rank = {
            "scoreable": 4,
            "partial": 3,
            "unscored": 2,
            "failed": 1,
        }.get(item.score_status, 0)
        return (
            -status_rank,
            item.failed_run_count,
            -(item.average_score if item.average_score is not None else -1.0),
            -(item.total_score if item.total_score is not None else -1.0),
            -item.scoreable_run_count,
            -item.unscored_run_count,
            item.variant_id,
        )

    def _score_status(
        self,
        *,
        run_count: int,
        scoreable_count: int,
        unscored_count: int,
        failed_count: int,
    ) -> str:
        if scoreable_count == run_count:
            return "scoreable"
        if scoreable_count:
            return "partial"
        if unscored_count:
            return "unscored"
        if failed_count:
            return "failed"
        return "unscored"

    def _summary_score_phrase(self, summary: OptimizerCandidateSummary) -> str:
        if summary.average_score is None or summary.total_score is None:
            return f"{summary.score_status} score status"
        return (
            f"average score {summary.average_score:.2f} "
            f"(total {summary.total_score:.2f})"
        )

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
