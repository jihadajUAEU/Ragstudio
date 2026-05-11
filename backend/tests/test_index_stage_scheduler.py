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
