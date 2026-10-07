"""
Fixtures compartidos para todos los tests.

Issue: #7 - HU12 Configuración de LLM

Important: do NOT set DATABASE_URL here. Postgres-backed tests use
``pytest.mark.skipif(not os.environ.get("DATABASE_URL"))`` to opt in.
CI sets DATABASE_URL explicitly via the workflow; local runs without it
must skip those tests cleanly rather than connecting to a default DB
that may not exist (HU10 v3 review fix).
"""

import os
import pytest
from cryptography.fernet import Fernet


# Only JWT_SECRET_KEY gets a default; DATABASE_URL is intentionally left
# unset so Postgres-backed ``skipif(not DATABASE_URL)`` markers fire.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-32chars")


def pytest_configure(config):
    """Hook que corre antes de cualquier test collection."""
    # Same as module top: never inject a DATABASE_URL default. Tests
    # requiring Postgres opt in via ``DATABASE_URL`` in the runner env.
    os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-32chars")


@pytest.fixture(autouse=True)
def setup_encryption_key():
    """
    Fixture automático: garantiza que ENCRYPTION_KEY esté configurada.

    Genera una clave nueva para cada test, así no hay acoplamiento entre tests.
    """
    os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    yield
    # Cleanup opcional
    # os.environ.pop("ENCRYPTION_KEY", None)


@pytest.fixture(autouse=True)
def reset_puppeteer_state():
    """Clear the puppeteer-mcp client cache and rate limiter between tests.

    Without this autouse, F11 tests that share ``user_id=None`` would
    accumulate entries in the module-level ``_RATE_LIMITER`` and the 6th
    test in a run would emit ``degraded`` (rate-limited) before its
    expected first event. Resetting both keeps each test deterministic
    regardless of execution order — the sidecar may be healthy (so the
    real fetch would otherwise succeed) or down (so the real fetch would
    otherwise fail); the reset prevents pollution either way.
    """
    from app.core import puppeteer_mcp

    puppeteer_mcp.reset_client_for_tests()
    yield
    puppeteer_mcp.reset_client_for_tests()
