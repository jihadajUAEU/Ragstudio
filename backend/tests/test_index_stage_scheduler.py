import asyncio

import pytest

from ragstudio.services.index_stage_scheduler import (
    StageBranchResult,
    IndexStageBranch,
    IndexStageScheduler,
)


@pytest.mark.asyncio
async def test_orchestrator_runs_independent_branches_concurrently():
    events: list[str] = []
    release = asyncio.Event()

    async def studio_branch():
        events.append("studio-start")
        await release.wait()
        events.append("studio-done")
        return {"chunks": 1754}

    async def runtime_branch():
        events.append("runtime-start")
        release.set()
        await asyncio.sleep(0)
        events.append("runtime-done")
        return {"runtime_chunks": 1754}

    result = await IndexStageScheduler(max_parallel_branches=2).run(
        [
            IndexStageBranch("studio_chunks", studio_branch, critical=True),
            IndexStageBranch("runtime_enrichment", runtime_branch, critical=False),
        ]
    )

    assert events[:2] == ["studio-start", "runtime-start"]
    assert result["studio_chunks"].status == "succeeded"
    assert result["runtime_enrichment"].status == "succeeded"
    assert result["studio_chunks"].value == {"chunks": 1754}


@pytest.mark.asyncio
async def test_orchestrator_converts_non_critical_failures_to_warnings():
    async def studio_branch():
        return {"chunks": 1754}

    async def runtime_branch():
        raise RuntimeError("runtime enrichment unavailable")

    result = await IndexStageScheduler(max_parallel_branches=2).run(
        [
            IndexStageBranch("studio_chunks", studio_branch, critical=True),
            IndexStageBranch("runtime_enrichment", runtime_branch, critical=False),
        ]
    )

    assert result["studio_chunks"].status == "succeeded"
    assert result["runtime_enrichment"] == StageBranchResult(
        status="skipped",
        value=None,
        warning="runtime enrichment unavailable",
    )


@pytest.mark.asyncio
async def test_orchestrator_cancels_sibling_branches_on_critical_failure():
    events: list[str] = []
    sibling_started = asyncio.Event()

    async def studio_branch():
        await sibling_started.wait()
        events.append("studio-failed")
        raise RuntimeError("studio persistence failed")

    async def runtime_branch():
        events.append("runtime-start")
        sibling_started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            events.append("runtime-cancelled")
            raise
        events.append("runtime-finished")
        return {"runtime_chunks": 1754}

    with pytest.raises(RuntimeError, match="studio persistence failed"):
        await IndexStageScheduler(max_parallel_branches=2).run(
            [
                IndexStageBranch("studio_chunks", studio_branch, critical=True),
                IndexStageBranch("runtime_enrichment", runtime_branch, critical=False),
            ]
        )

    await asyncio.sleep(0)

    assert "runtime-finished" not in events
    assert events == ["runtime-start", "studio-failed", "runtime-cancelled"]


@pytest.mark.asyncio
async def test_orchestrator_respects_single_branch_parallelism_limit():
    active = 0
    peak_active = 0
    events: list[str] = []

    async def make_branch(name: str):
        nonlocal active, peak_active
        active += 1
        peak_active = max(peak_active, active)
        events.append(f"{name}-start")
        await asyncio.sleep(0)
        events.append(f"{name}-done")
        active -= 1
        return name

    result = await IndexStageScheduler(max_parallel_branches=1).run(
        [
            IndexStageBranch("first", lambda: make_branch("first"), critical=True),
            IndexStageBranch("second", lambda: make_branch("second"), critical=True),
            IndexStageBranch("third", lambda: make_branch("third"), critical=False),
        ]
    )

    assert peak_active == 1
    assert events == [
        "first-start",
        "first-done",
        "second-start",
        "second-done",
        "third-start",
        "third-done",
    ]
    assert result["first"].value == "first"
    assert result["second"].value == "second"
    assert result["third"].value == "third"
