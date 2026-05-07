from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, static_dir: Path | None = None) -> None:
    root = static_dir or Path(__file__).parent / "static" / "dist"
    if root.exists():
        app.mount("/", StaticFiles(directory=root, html=True), name="studio")
