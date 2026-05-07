from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import EvaluationSet, Experiment, Run
from ragstudio.schemas.evaluation import EvaluationCaseIn
from ragstudio.schemas.experiments import ExperimentIn, ExperimentOut
from ragstudio.schemas.query import QueryIn
from ragstudio.schemas.runs import RunOut
from ragstudio.services.query_service import QueryService
from ragstudio.services.scoring_service import ScoringService


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

        experiment = Experiment(**payload.model_dump())
        self.session.add(experiment)
        await self.session.commit()
        await self.session.refresh(experiment)

        runs: list[RunOut] = []
        query_service = QueryService(self.session, self.data_dir)
        scoring_service = ScoringService(self.session)
        cases = [EvaluationCaseIn.model_validate(item) for item in evaluation_set.cases]

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
                runs.append(RunOut.model_validate(run))
            await self.session.commit()

        return ExperimentOut(
            id=experiment.id,
            name=experiment.name,
            document_ids=experiment.document_ids,
            evaluation_set_id=experiment.evaluation_set_id,
            variant_ids=experiment.variant_ids,
            objective=experiment.objective,
            runs=runs,
        )
