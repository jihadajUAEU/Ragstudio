from pathlib import Path

from ragstudio.db.models import Document, EvaluationSet, Experiment, Run, Variant
from ragstudio.schemas.evaluation import EvaluationCaseIn
from ragstudio.schemas.experiments import ExperimentIn, ExperimentOut, ExperimentScoreOut
from ragstudio.schemas.query import QueryIn
from ragstudio.schemas.runs import RunOut
from ragstudio.services.query_service import QueryResourceNotFoundError, QueryService
from ragstudio.services.scoring_service import ScoringService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class EvaluationSetNotFoundError(LookupError):
    pass


class ExperimentService:
    def __init__(self, session: AsyncSession, data_dir: Path):
        self.session = session
        self.data_dir = data_dir

    async def create(self, payload: ExperimentIn) -> ExperimentOut:
        evaluation_set = await self.session.get(EvaluationSet, payload.evaluation_set_id)
        if evaluation_set is None:
            raise EvaluationSetNotFoundError(payload.evaluation_set_id)

        cases = [EvaluationCaseIn.model_validate(item) for item in evaluation_set.cases]
        await self._validate_inputs(payload, cases)

        experiment = Experiment(**payload.model_dump())
        self.session.add(experiment)
        await self.session.commit()
        await self.session.refresh(experiment)

        runs: list[RunOut] = []
        scores: list[ExperimentScoreOut] = []
        query_service = QueryService(self.session, self.data_dir)
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
                score = await scoring_service.create_score(run, case)
                await self.session.flush()
                runs.append(RunOut.model_validate(run))
                scores.append(ExperimentScoreOut.model_validate(score))
            await self.session.commit()

        return ExperimentOut(
            id=experiment.id,
            name=experiment.name,
            document_ids=experiment.document_ids,
            evaluation_set_id=experiment.evaluation_set_id,
            variant_ids=experiment.variant_ids,
            objective=experiment.objective,
            runs=runs,
            scores=scores,
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
