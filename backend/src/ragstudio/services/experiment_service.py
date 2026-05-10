from __future__ import annotations

from pathlib import Path

from ragstudio.config import AppSettings
from ragstudio.db.models import Document, EvaluationSet, Experiment, Run, Score, Variant
from ragstudio.schemas.evaluation import EvaluationCaseIn
from ragstudio.schemas.experiments import (
    ExperimentIn,
    ExperimentOut,
    ExperimentPage,
    ExperimentScoreOut,
    ExperimentSummaryOut,
)
from ragstudio.schemas.query import QueryIn
from ragstudio.schemas.runs import RunOut
from ragstudio.services.query_service import QueryResourceNotFoundError, QueryService
from ragstudio.services.scoring_service import ScoringService
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class EvaluationSetNotFoundError(LookupError):
    pass


class ExperimentNotFoundError(LookupError):
    pass


class ExperimentService:
    def __init__(
        self,
        session: AsyncSession,
        data_dir: Path,
        *,
        settings: AppSettings | None = None,
    ):
        self.session = session
        self.data_dir = data_dir
        self.settings = settings

    async def create(self, payload: ExperimentIn) -> ExperimentOut:
        evaluation_set = await self.session.get(EvaluationSet, payload.evaluation_set_id)
        if evaluation_set is None:
            raise EvaluationSetNotFoundError(payload.evaluation_set_id)

        cases = [EvaluationCaseIn.model_validate(item) for item in evaluation_set.cases]
        await self._validate_inputs(payload, cases)
        query_service = QueryService(self.session, self.data_dir, settings=self.settings)
        for case in cases:
            await query_service.preflight_runtime_readiness(
                QueryIn(
                    query=case.query,
                    document_ids=case.documents or payload.document_ids,
                    variant_ids=payload.variant_ids,
                )
            )

        experiment = Experiment(**payload.model_dump())
        self.session.add(experiment)
        await self.session.commit()
        await self.session.refresh(experiment)

        scoring_service = ScoringService(self.session)

        for case in cases:
            query_result = await query_service.run_query(
                QueryIn(
                    query=case.query,
                    document_ids=case.documents or payload.document_ids,
                    variant_ids=payload.variant_ids,
                )
            )
            for run_out in query_result.runs:
                run = await self.session.get(Run, run_out.id)
                if run is None:
                    continue
                run.experiment_id = experiment.id
                await scoring_service.create_score(run, case)
                await self.session.flush()
            await self.session.commit()

        return await self._build_experiment_out(experiment)

    async def list(self) -> ExperimentPage:
        run_counts = (
            select(
                Run.experiment_id.label("experiment_id"),
                func.count(Run.id).label("run_count"),
            )
            .where(Run.experiment_id.is_not(None))
            .group_by(Run.experiment_id)
            .subquery()
        )
        score_counts = (
            select(
                Run.experiment_id.label("experiment_id"),
                func.count(Score.id).label("score_count"),
            )
            .join(Score, Score.run_id == Run.id)
            .where(Run.experiment_id.is_not(None))
            .group_by(Run.experiment_id)
            .subquery()
        )
        result = await self.session.execute(
            select(
                Experiment,
                func.coalesce(run_counts.c.run_count, 0),
                func.coalesce(score_counts.c.score_count, 0),
            )
            .outerjoin(run_counts, run_counts.c.experiment_id == Experiment.id)
            .outerjoin(score_counts, score_counts.c.experiment_id == Experiment.id)
            .order_by(Experiment.created_at.desc())
        )
        items = [
            ExperimentSummaryOut(
                id=experiment.id,
                name=experiment.name,
                document_ids=experiment.document_ids,
                evaluation_set_id=experiment.evaluation_set_id,
                variant_ids=experiment.variant_ids,
                objective=experiment.objective,
                run_count=run_count,
                score_count=score_count,
            )
            for experiment, run_count, score_count in result.all()
        ]
        return ExperimentPage(items=items, total=len(items))

    async def get_required(self, experiment_id: str) -> ExperimentOut:
        experiment = await self.session.get(Experiment, experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(experiment_id)
        return await self._build_experiment_out(experiment)

    async def _build_experiment_out(self, experiment: Experiment) -> ExperimentOut:
        runs_result = await self.session.execute(
            select(Run)
            .where(Run.experiment_id == experiment.id)
            .order_by(Run.created_at.asc())
        )
        runs = runs_result.scalars().all()
        run_ids = [run.id for run in runs]

        scores: list[Score] = []
        if run_ids:
            scores_result = await self.session.execute(
                select(Score)
                .where(Score.run_id.in_(run_ids))
                .order_by(Score.created_at.asc())
            )
            scores = list(scores_result.scalars().all())

        return ExperimentOut(
            id=experiment.id,
            name=experiment.name,
            document_ids=experiment.document_ids,
            evaluation_set_id=experiment.evaluation_set_id,
            variant_ids=experiment.variant_ids,
            objective=experiment.objective,
            runs=[RunOut.model_validate(run) for run in runs],
            scores=[ExperimentScoreOut.model_validate(score) for score in scores],
        )

    async def _validate_inputs(self, payload: ExperimentIn, cases: list[EvaluationCaseIn]) -> None:
        missing_variants = await self._missing_ids(Variant, payload.variant_ids)
        if missing_variants:
            raise QueryResourceNotFoundError("Variant", missing_variants)

        document_ids = list(payload.document_ids)
        for case in cases:
            document_ids.extend(case.documents)
        missing_documents = await self._missing_ids(Document, document_ids)
        if missing_documents:
            raise QueryResourceNotFoundError("Document", missing_documents)

    async def _missing_ids(
        self, model: type[Document] | type[Variant], ids: list[str]
    ) -> list[str]:
        if not ids:
            return []
        requested_ids = list(dict.fromkeys(ids))
        result = await self.session.execute(select(model.id).where(model.id.in_(requested_ids)))
        found_ids = set(result.scalars().all())
        return [item_id for item_id in requested_ids if item_id not in found_ids]
