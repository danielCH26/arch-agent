"""Tests para /api/chat endpoint (``POST /api/chat``).

Validaciones:
  - 400 cuando el mensaje esta vacio o es solo whitespace (chequeo manual
    en el endpoint, NO Pydantic, porque quitamos ``min_length=1`` en F18
    round 3 para que el frontend siga asumiendo ``detail`` como string).
  - 422 cuando el body no cumple el schema de ``ChatRequest`` en lo
    demas (tipo incorrecto, falta de campos requeridos que no son message,
    coercion de ``project_id``).
  - El endpoint es ``StreamingResponse`` SSE — la forma del stream se cubre
    en ``test_chat.py`` con mocks de ``run_agent`` + ``similarity_search``.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest


@contextmanager
def _chat_client(user=None):
    """Yield TestClient with auth override on server.app."""
    from fastapi.testclient import TestClient
    from server import app
    from app.api.dependencies import get_current_user

    if user is None:
        user = {"user_id": 1, "username": "laura", "jti": None}
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


class TestChatEndpointValidation:
    """Manual check for empty/whitespace message; Pydantic for the rest."""

    def test_request_validation_empty_message_returns_400(self):
        """Empty message is caught by the route's manual validation, not Pydantic."""
        with _chat_client() as client:
            r = client.post(
                "/api/chat",
                json={"project_id": 5, "message": ""},
            )

        assert r.status_code == 400
        body = r.json()
        assert "detail" in body
        # detail is a string (frontend expects this)
        assert isinstance(body["detail"], str)

    def test_request_validation_whitespace_message_returns_400(self):
        """Whitespace-only message is also caught by the manual validation."""
        with _chat_client() as client:
            r = client.post(
                "/api/chat",
                json={"project_id": 5, "message": "   "},
            )

        assert r.status_code == 400
        body = r.json()
        assert isinstance(body["detail"], str)

    def test_request_validation_missing_message_returns_422(self):
        """Missing message field is rejected by Pydantic (required field)."""
        with _chat_client() as client:
            r = client.post(
                "/api/chat",
                json={"project_id": 5},  # missing message
            )

        # Pydantic: required field missing -> 422 (not 400, that's for empty)
        assert r.status_code == 422
        body = r.json()
        assert "detail" in body

    def test_request_validation_message_must_be_string(self):
        """Non-string message is rejected by Pydantic (422, not 500)."""
        with _chat_client() as client:
            r = client.post(
                "/api/chat",
                json={"project_id": 5, "message": 12345},
            )

        assert r.status_code == 422
        body = r.json()
        assert "detail" in body

    def test_request_validation_project_id_must_be_int_or_null(self):
        with _chat_client() as client:
            r = client.post(
                "/api/chat",
                json={"project_id": "not-an-int", "message": "Hi"},
            )

        # Pydantic: int|None coercion fails on string -> 422
        assert r.status_code == 422


class TestChatEndpointAuth:
    """Auth is enforced before any DB / LLM work."""

    def test_unauthenticated_request_rejected(self):
        from fastapi.testclient import TestClient
        from server import app

        # No dependency override -> real auth flow rejects the request.
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/api/chat",
            json={"project_id": 5, "message": "Hi"},
        )

        # No Bearer token -> 401 (or 403, depending on JWT error mapping).
        assert r.status_code in {401, 403}