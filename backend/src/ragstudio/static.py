from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response


def mount_frontend(app: FastAPI, static_dir: Path | None = None) -> None:
    roots = [static_dir] if static_dir is not None else _default_static_roots()
    for root in roots:
        if root is not None and root.exists():
            app.mount("/", SPAStaticFiles(directory=root, html=True), name="studio")
            return


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope) -> Response:
        if path.startswith(("api/", "openapi.json")) and scope["method"] not in {"GET", "HEAD"}:
            raise StarletteHTTPException(status_code=404)
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith(("api/", "openapi.json")):
                return await super().get_response("index.html", scope)
            raise
        if response.status_code != 404 or path.startswith(("api/", "openapi.json")):
            return response
        return await super().get_response("index.html", scope)


def _default_static_roots() -> list[Path]:
    package_dist = Path(__file__).parent / "static" / "dist"
    repo_frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    return [package_dist, repo_frontend_dist]
