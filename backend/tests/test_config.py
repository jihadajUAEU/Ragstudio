from pathlib import Path

from ragstudio.config import AppSettings


def test_app_settings_default_database_is_postgres(monkeypatch):
    monkeypatch.delenv("RAGSTUDIO_NEO4J_URI", raising=False)
    settings = AppSettings(data_dir=Path("/tmp/ragstudio-test"))

    assert settings.resolved_database_url.startswith("postgresql+asyncpg://")
    assert "ragstudio" in settings.resolved_database_url
    assert settings.neo4j_uri == "bolt://127.0.0.1:57687"


def test_app_settings_accepts_explicit_database_url():
    settings = AppSettings(
        data_dir=Path("/tmp/ragstudio-test"),
        database_url="postgresql+asyncpg://user:password@postgres:5432/ragstudio",
    )

    assert (
        settings.resolved_database_url
        == "postgresql+asyncpg://user:password@postgres:5432/ragstudio"
    )
