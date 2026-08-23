"""
Fixtures compartidos para todos los tests.

Issue: #7 - HU12 Configuración de LLM
"""

import os
import pytest
from cryptography.fernet import Fernet


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
