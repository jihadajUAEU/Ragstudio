import pytest
from ragstudio.config import AppSettings
from ragstudio.db.models import Job
from ragstudio.schemas.common import StageStatus
from ragstudio.services.background_runner_factory import BackgroundRunnerFactory
from ragstudio.services.index_job_runner import IndexJobRunner


@pytest.mark.asyncio
async def test_background_runner_factory_dispatches_index_document(client, tmp_path):
    app = client._transport.app
    async with app.state.session_factory() as session:
        factory = BackgroundRunnerFactory(
            session,
            AppSettings(data_dir=tmp_path),
            worker_id="worker-a",
            lease_seconds=123,
        )
        job = Job(
            id="job-index",
            type="index_document",
            target_id="doc-1",
            status=StageStatus.RUNNING.value,
            progress=1,
            logs=[],
            result={},
        )

        runner = factory.runner_for(job)

    assert factory.job_types == ["index_document"]
    assert isinstance(runner, IndexJobRunner)
    assert runner.worker_id == "worker-a"
    assert runner.lease_seconds == 123


@pytest.mark.asyncio
async def test_background_runner_factory_rejects_unknown_job_type(client, tmp_path):
    app = client._transport.app
    async with app.state.session_factory() as session:
        factory = BackgroundRunnerFactory(
            session,
            AppSettings(data_dir=tmp_path),
            worker_id="worker-a",
        )
        job = Job(
            id="job-other",
            type="other_job",
            target_id="doc-1",
            status=StageStatus.RUNNING.value,
            progress=1,
            logs=[],
            result={},
        )

        with pytest.raises(RuntimeError, match="Unsupported job type"):
            factory.runner_for(job)
