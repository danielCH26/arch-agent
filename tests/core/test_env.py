from app.core.env import env_float, env_int


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


def test_env_float_uses_default_when_unset_empty_or_invalid(monkeypatch):
    monkeypatch.delenv("F19_TEST_FLOAT", raising=False)
    assert env_float("F19_TEST_FLOAT", 300.0) == 300.0
    for raw in ("", "   ", "abc", "nan", "inf", "-inf", "-1"):
        monkeypatch.setenv("F19_TEST_FLOAT", raw)
        assert env_float("F19_TEST_FLOAT", 300.0, minimum=0.0) == 300.0, raw


def test_env_float_accepts_zero_and_decimals(monkeypatch):
    monkeypatch.setenv("F19_TEST_FLOAT", "0")
    assert env_float("F19_TEST_FLOAT", 300.0, minimum=0.0) == 0.0  # 0 desactiva el tope
    monkeypatch.setenv("F19_TEST_FLOAT", "1.5")
    assert env_float("F19_TEST_FLOAT", 300.0, minimum=0.0) == 1.5


def _proposal_constants_in_subprocess(**env):
    """Importa proposal_generator en un proceso limpio con variables dadas."""
    import os
    import subprocess
    import sys

    code = (
        "from app.core import proposal_generator as p;"
        "print(p.PROPOSAL_MAX_SECONDS, p.PROPOSAL_SAVE_RESERVE_S,"
        " p.PROPOSAL_EXPECTED_CHARS, p.PROPOSAL_PROGRESS_INTERVAL_S)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, check=True,
        env={**os.environ, "DATABASE_URL": "postgresql://u:p@localhost:5432/x", **env},
    )
    return result.stdout.split()


def test_proposal_limits_use_configured_values():
    values = _proposal_constants_in_subprocess(
        PROPOSAL_MAX_SECONDS="120", PROPOSAL_SAVE_RESERVE_S="5",
        PROPOSAL_EXPECTED_CHARS="4000", PROPOSAL_PROGRESS_INTERVAL_S="0.5",
    )
    assert values == ["120.0", "5.0", "4000", "0.5"]


def test_proposal_limits_fall_back_to_defaults_on_empty_or_invalid_values():
    """Un valor vacío en .env no debe impedir el arranque (antes: ValueError al importar)."""
    values = _proposal_constants_in_subprocess(
        PROPOSAL_MAX_SECONDS="", PROPOSAL_SAVE_RESERVE_S="abc",
        PROPOSAL_EXPECTED_CHARS="", PROPOSAL_PROGRESS_INTERVAL_S="-3",
    )
    assert values == ["300.0", "10.0", "6000", "1.0"]


def _eval_in_subprocess(expression: str, **env) -> list[str]:
    """Importa proposal_generator/proposals en un proceso limpio y evalúa ``expression``."""
    import os
    import subprocess
    import sys

    code = (
        "from app.core import proposal_generator as p;"
        "from app.api import proposals as api;"
        f"print({expression})"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, check=True,
        env={**os.environ, "DATABASE_URL": "postgresql://u:p@localhost:5432/x", **env},
    )
    return result.stdout.split()


_RAG_TUNING_EXPR = (
    "p.PROPOSAL_RAG_TOP_N, p.PROPOSAL_RAG_CANDIDATE_CHUNKS, p.PROPOSAL_MAX_ITER, "
    "api.PROPOSAL_MAX_ITER, p.PROPOSAL_COMPLEXITY_PENALTY, api.SSE_HEARTBEAT_SECONDS"
)


def test_proposal_tuning_falls_back_to_defaults_on_empty_or_invalid_values():
    """Un .env con valores vacíos o inválidos no debe romper el import (antes: ValueError)."""
    values = _eval_in_subprocess(
        _RAG_TUNING_EXPR,
        PROPOSAL_RAG_TOP_N="", PROPOSAL_RAG_CANDIDATE_CHUNKS="abc", PROPOSAL_MAX_ITER="",
        PROPOSAL_COMPLEXITY_PENALTY="x", SSE_HEARTBEAT_SECONDS="",
    )
    assert values == ["3", "40", "5", "5", "0.08", "15.0"]


def test_proposal_tuning_uses_configured_values_and_shares_max_iter():
    values = _eval_in_subprocess(
        _RAG_TUNING_EXPR,
        PROPOSAL_RAG_TOP_N="4", PROPOSAL_RAG_CANDIDATE_CHUNKS="60", PROPOSAL_MAX_ITER="7",
        PROPOSAL_COMPLEXITY_PENALTY="0", SSE_HEARTBEAT_SECONDS="2.5",
    )
    # PROPOSAL_MAX_ITER es una sola definición; el heartbeat acepta valores >= 1 s.
    assert values == ["4", "60", "7", "7", "0.0", "2.5"]


def test_sse_heartbeat_below_the_minimum_returns_to_the_default_not_a_clamp():
    """Como el resto de env_float: por debajo del mínimo (1 s) vuelve al default (15 s)."""
    for raw in ("0", "0.2", "-3"):
        values = _eval_in_subprocess("api.SSE_HEARTBEAT_SECONDS", SSE_HEARTBEAT_SECONDS=raw)
        assert values == ["15.0"], raw
    assert _eval_in_subprocess("api.SSE_HEARTBEAT_SECONDS", SSE_HEARTBEAT_SECONDS="1") == ["1.0"]
