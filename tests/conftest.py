"""
Fixtures compartidos para todos los tests.

Issue: #7 - HU12 Configuración de LLM
"""

import os
import pytest
from cryptography.fernet import Fernet


# Only set defaults if NOT already set. This preserves skipif semantics:
# tests that require DATABASE_URL will skip when the var is not set.
# CI provides DATABASE_URL explicitly via env: block in the workflow.
if "DATABASE_URL" not in os.environ:
    os.environ.setdefault(
        "DATABASE_URL", "postgresql://asistente:asistente@localhost:5432/asistente_db"
    )
if "JWT_SECRET_KEY" not in os.environ:
    os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-32chars")


def pytest_configure(config):
    """Hook que corre antes de cualquier test collection."""
    # Only set defaults if NOT already set (respects skipif on DB-dependent tests)
    if "DATABASE_URL" not in os.environ:
        os.environ["DATABASE_URL"] = "postgresql://asistente:asistente@localhost:5432/asistente_db"
    if "JWT_SECRET_KEY" not in os.environ:
        os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-testing-only-32chars"


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
