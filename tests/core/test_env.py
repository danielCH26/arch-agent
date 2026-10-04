from app.core.env import env_int


def test_env_int_uses_default_when_unset_or_invalid(monkeypatch):
    monkeypatch.delenv("F19_TEST_INTEGER", raising=False)
    assert env_int("F19_TEST_INTEGER", 10, 1) == 10
    monkeypatch.setenv("F19_TEST_INTEGER", "")
    assert env_int("F19_TEST_INTEGER", 10, 1) == 10
    monkeypatch.setenv("F19_TEST_INTEGER", "bad")
    assert env_int("F19_TEST_INTEGER", 10, 1) == 10
    monkeypatch.setenv("F19_TEST_INTEGER", "0")
    assert env_int("F19_TEST_INTEGER", 10, 1) == 10


def test_env_int_accepts_pool_values(monkeypatch):
    monkeypatch.setenv("F19_TEST_INTEGER", "25")
    assert env_int("F19_TEST_INTEGER", 10, 1) == 25


def _pool_size_in_subprocess(**env):
    """Importa app.core.database en un proceso limpio: no toca el engine global."""
    import os
    import subprocess
    import sys

    code = (
        "from app.core.database import engine, DB_POOL_RECYCLE, DB_MAX_OVERFLOW;"
        "print(engine.pool.size(), engine.pool._max_overflow, engine.pool._recycle)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, check=True,
        env={**os.environ, "DATABASE_URL": "postgresql://u:p@localhost:5432/x", **env},
    )
    return result.stdout.split()


def test_database_pool_uses_configured_values():
    assert _pool_size_in_subprocess(DB_POOL_SIZE="7", DB_MAX_OVERFLOW="3", DB_POOL_RECYCLE="600") == ["7", "3", "600"]


def test_database_pool_falls_back_to_defaults_on_empty_or_invalid_values():
    values = _pool_size_in_subprocess(DB_POOL_SIZE="", DB_MAX_OVERFLOW="abc", DB_POOL_RECYCLE="0")
    assert values == ["10", "20", "1800"]
