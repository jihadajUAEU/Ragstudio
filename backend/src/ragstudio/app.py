from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from ragstudio.api.routes import ROUTERS
from ragstudio.config import AppSettings
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.logging import configure_logging
from ragstudio.static import mount_frontend


def create_app(data_dir: Path | None = None, database_url: str | None = None) -> FastAPI:
    configure_logging()
    settings = AppSettings()
    if data_dir is not None or database_url is not None:
        update: dict[str, object] = {}
        if data_dir is not None:
            update["data_dir"] = data_dir
        if database_url is not None:
            update["database_url"] = database_url
        settings = settings.model_copy(update=update)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_runtime_working_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.resolved_database_url)
    session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        await init_db(engine)
        yield
        await engine.dispose()

    app = FastAPI(title="RAG-Anything Studio", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    for router in ROUTERS:
        app.include_router(router)
    mount_frontend(app)
    return app


def main() -> None:
    uvicorn.run("ragstudio.app:create_app", factory=True, host="127.0.0.1", port=8000)
