"""
Fixtures compartidos para todos los tests.

Issue: #7 - HU12 Configuración de LLM
"""

import os
import pytest
from cryptography.fernet import Fernet


# Configurar ANTES de cualquier import del proyecto para que
# app.core.database cree el engine con la DB de test, no la real.
os.environ.setdefault(
    "DATABASE_URL", "postgresql://asistente:asistente@localhost:5432/asistente_db"
)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-32chars")


def pytest_configure(config):
    """Hook que corre antes de cualquier test collection."""
    # Garantizar que las env vars esten seteadas cuando se carguen los modulos.
    os.environ.setdefault(
        "DATABASE_URL", "postgresql://asistente:asistente@localhost:5432/asistente_db"
    )
    os.environ.setdefault(
        "JWT_SECRET_KEY", "test-secret-key-for-testing-only-32chars"
    )


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
