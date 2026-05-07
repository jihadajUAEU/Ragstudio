from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, static_dir: Path | None = None) -> None:
    roots = [static_dir] if static_dir is not None else _default_static_roots()
    for root in roots:
        if root is not None and root.exists():
            app.mount("/", StaticFiles(directory=root, html=True), name="studio")
            return


def _default_static_roots() -> list[Path]:
    package_dist = Path(__file__).parent / "static" / "dist"
    repo_frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    return [package_dist, repo_frontend_dist]
