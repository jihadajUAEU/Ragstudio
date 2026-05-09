import asyncio
from collections.abc import Coroutine
from typing import Any

from fastapi import FastAPI


def create_background_task(app: FastAPI, coroutine: Coroutine[Any, Any, None]) -> None:
    tasks = getattr(app.state, "background_tasks", None)
    if tasks is None:
        tasks = set()
        app.state.background_tasks = tasks
    task = asyncio.create_task(coroutine)
    tasks.add(task)
    task.add_done_callback(tasks.discard)
