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


def test_app_settings_keeps_private_reranker_hosts_out_of_defaults():
    settings = AppSettings(data_dir=Path("/tmp/ragstudio-test"))

    assert "10.10.9.193" not in settings.allowed_reranker_hosts
    assert "127.0.0.1" in settings.allowed_reranker_hosts


def test_app_settings_accepts_explicit_private_reranker_hosts():
    settings = AppSettings(
        data_dir=Path("/tmp/ragstudio-test"),
        allowed_reranker_hosts="127.0.0.1,10.10.9.*",
    )

    assert settings.allowed_reranker_hosts == ["127.0.0.1", "10.10.9.*"]


def test_app_settings_accepts_json_reranker_hosts_from_env(monkeypatch):
    monkeypatch.setenv("RAGSTUDIO_ALLOWED_RERANKER_HOSTS", '["127.0.0.1","10.10.9.*"]')

    settings = AppSettings(data_dir=Path("/tmp/ragstudio-test"))

    assert settings.allowed_reranker_hosts == ["127.0.0.1", "10.10.9.*"]
