from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IndexStageBranch:
    name: str
    run: Callable[[], Awaitable[Any]]
    critical: bool


@dataclass(frozen=True)
class StageBranchResult:
    status: str
    value: Any = None
    warning: str | None = None


class IndexStageScheduler:
    _global_semaphores: dict[tuple[int, int], asyncio.Semaphore] = {}

    def __init__(self, *, max_parallel_branches: int = 2):
        loop_key = id(asyncio.get_running_loop())
        self._semaphore = self._global_semaphores.setdefault(
            (loop_key, max_parallel_branches),
            asyncio.Semaphore(max_parallel_branches),
        )

    async def run(self, branches: list[IndexStageBranch]) -> dict[str, StageBranchResult]:
        async def run_branch(branch: IndexStageBranch) -> tuple[str, StageBranchResult]:
            async with self._semaphore:
                try:
                    value = await branch.run()
                except Exception as exc:
                    if branch.critical:
                        raise
                    return branch.name, StageBranchResult(
                        status="skipped",
                        warning=str(exc),
                    )
                return branch.name, StageBranchResult(status="succeeded", value=value)

        tasks = [asyncio.create_task(run_branch(branch)) for branch in branches]
        try:
            pairs = await asyncio.gather(*tasks)
        except Exception:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return dict(pairs)
