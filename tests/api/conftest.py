"""
Fixtures para tests de API REST.

Usa mocking puro (sin TestClient) para evitar el overhead de langchain.
"""

import os
import pytest
from unittest.mock import MagicMock, patch

# Configurar entorno antes de importar la app.
# NOTA: estos tests usan mocking puro (sin DB real), por lo que NO seteamos
# DATABASE_URL acá — setearla contaminaba otras suites que sí la necesitan
# (el engine de app.core.database se crea al importar y lee el env una vez).
# Solo seteamos las vars que los módulos importados exigen en runtime.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-32ch")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRES_MINUTES", "60")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-32-chars!!")


@pytest.fixture
def mock_db():
    """DB session mock para tests de API."""
    mock = MagicMock()
    return mock


@pytest.fixture
def mock_user():
    """User mock con password_hash pre-bcrypteado."""
    user = MagicMock()
    user.id = 1
    user.username = "testuser"
    user.email = "test@test.com"
    user.password_hash = (
        "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4gHr3T.9l0lLR3q"  # "Test@1234"
    )
    user.llm_base_url = None
    user.llm_model = None
    user.encrypted_api_key = None
    return user


@pytest.fixture
def mock_project(mock_user):
    """Project mock."""
    proj = MagicMock()
    proj.id = 1
    proj.user_id = mock_user.id
    proj.name = "Test Project"
    proj.description = "A test project"
    proj.current_phase = "requerimientos"
    proj.phase_ready = False
    proj.created_at = None
    return proj


@pytest.fixture
def auth_token(mock_user):
    """JWT token válido para mock_user."""
    from app.core.jwt import create_access_token

    return create_access_token(user_id=mock_user.id, username=mock_user.username)


@pytest.fixture
def auth_headers(auth_token):
    """Headers con Authorization Bearer token."""
    return {"Authorization": f"Bearer {auth_token}"}
