import asyncio

import pytest
from ragstudio.services.index_job_runner import IndexJobRunner


@pytest.mark.asyncio
async def test_index_job_runner_uses_injected_session_factory_for_heartbeat(
    monkeypatch,
    client,
):
    app = client._transport.app

    async with app.state.session_factory() as session:
        runner = IndexJobRunner(
            session,
            app.state.settings,
            worker_id="worker-test",
            heartbeat_interval_seconds=0,
            session_factory=app.state.session_factory,
        )

        def fail_make_engine(_database_url):
            raise AssertionError("heartbeat should not create a new engine")

        monkeypatch.setattr("ragstudio.services.index_job_runner.make_engine", fail_make_engine)

        calls = []

        async def fake_heartbeat_external(heartbeat_session, job_id):
            calls.append((heartbeat_session, job_id))
            return False

        monkeypatch.setattr(runner, "_heartbeat_external", fake_heartbeat_external)

        await runner._heartbeat_until_stopped("job-heartbeat", asyncio.Event())

        assert runner._external_session_factory is app.state.session_factory
        assert calls[0][1] == "job-heartbeat"
