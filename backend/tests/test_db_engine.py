from ragstudio.db.engine import is_postgres_url


def test_is_postgres_url_detects_asyncpg_url():
    assert is_postgres_url("postgresql+asyncpg://ragstudio:ragstudio@127.0.0.1/ragstudio")


def test_is_postgres_url_rejects_sqlite_url():
    assert not is_postgres_url("sqlite+aiosqlite:////tmp/ragstudio.sqlite3")
