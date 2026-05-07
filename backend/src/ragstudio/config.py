from pathlib import Path

from pydantic import BaseModel, Field


class AppSettings(BaseModel):
    service_name: str = "rag-anything-studio"
    data_dir: Path = Field(default_factory=lambda: Path(".ragstudio").resolve())
    database_url: str | None = None

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{self.data_dir / 'studio.sqlite3'}"
