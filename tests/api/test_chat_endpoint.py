"""Tests para /api/chat endpoint (``POST /api/chat``).

Validaciones:
  - 422 cuando el body no cumple el schema de ``ChatRequest``
    (mensaje vacio o faltante, gracias a ``Field(min_length=1)``).
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
    """Pydantic validates ChatRequest before the route body runs."""

    def test_request_validation_min_message_length(self):
        with _chat_client() as client:
            r = client.post(
                "/api/chat",
                json={"project_id": 5, "message": ""},
            )

        # Pydantic Field(min_length=1) -> 422
        assert r.status_code == 422
        body = r.json()
        assert "detail" in body

    def test_request_validation_requires_message(self):
        with _chat_client() as client:
            r = client.post(
                "/api/chat",
                json={"project_id": 5},  # missing message
            )

        # Pydantic: missing required field -> 422
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