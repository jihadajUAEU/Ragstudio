from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from ragstudio.api.routes import ROUTERS
from ragstudio.config import AppSettings
from ragstudio.logging import configure_logging


def create_app(data_dir: Path | None = None) -> FastAPI:
    configure_logging()
    settings = AppSettings(data_dir=data_dir or Path(".ragstudio").resolve())
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        yield

    app = FastAPI(title="RAG-Anything Studio", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    for router in ROUTERS:
        app.include_router(router)
    return app


def main() -> None:
    uvicorn.run("ragstudio.app:create_app", factory=True, host="127.0.0.1", port=8000)
