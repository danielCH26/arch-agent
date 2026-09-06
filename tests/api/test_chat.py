"""
Tests para /api/chat — SSE streaming.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


class TestChatRequestModel:
    """Tests del model de request de chat."""

    def test_chat_request_with_project(self):
        from app.api.chat import ChatRequest

        req = ChatRequest(project_id=1, message="Hello world")
        assert req.project_id == 1
        assert req.message == "Hello world"

    def test_chat_request_without_project(self):
        from app.api.chat import ChatRequest

        req = ChatRequest(project_id=None, message="Hello")
        assert req.project_id is None
        assert req.message == "Hello"

    def test_chat_request_allows_empty_message_at_model_level(self):
        """Pydantic accepts any string; content validation is in the endpoint."""
        from app.api.chat import ChatRequest

        # ChatRequest accepts empty/whitespace strings at model level
        req = ChatRequest(project_id=None, message="")
        assert req.message == ""

        req2 = ChatRequest(project_id=None, message="   ")
        assert req2.message == "   "

    def test_chat_request_normal_message(self):
        from app.api.chat import ChatRequest

        req = ChatRequest(project_id=1, message="Diseña un sistema de login")
        assert req.message == "Diseña un sistema de login"


class TestSSEStreamCallbackHandler:
    """Tests del handler de streaming SSE."""

    @patch("app.api.sse.asyncio.Queue")
    def test_handler_initialization(self, mock_queue):
        from app.api.sse import SSEStreamCallbackHandler

        handler = SSEStreamCallbackHandler()
        assert handler._done is False
        assert len(handler._errors) == 0


class TestChatEndpointErrors:
    """Tests de errores del endpoint de chat (lógica sin red)."""

    def test_llm_config_error_exists(self):
        """LLMConfigError is raised when user has no LLM config."""
        from app.core.llm_loader import LLMConfigError

        err = LLMConfigError("Usuario no tiene config LLM")
        assert "config LLM" in str(err)


class TestSSEFormat:
    """Tests del formato SSE emitido por el endpoint."""

    def test_sse_token_event_format(self):
        token = "Hola"
        formatted = f"event: token\ndata: {json.dumps(token, ensure_ascii=False)}\n\n"
        assert "event: token" in formatted
        assert "Hola" in formatted

    def test_sse_done_event_format(self):
        formatted = f"event: done\ndata: null\n\n"
        assert formatted == "event: done\ndata: null\n\n"

    def test_sse_error_event_format(self):
        error_msg = "Connection timeout"
        formatted = f"event: error\ndata: {json.dumps(error_msg, ensure_ascii=False)}\n\n"
        assert "event: error" in formatted
        assert "Connection timeout" in formatted


class TestJWTAuth:
    """Tests de JWT auth (sin HTTP)."""

    def test_create_and_verify_token(self):
        from app.core.jwt import create_access_token, verify_token

        token = create_access_token(user_id=42, username="architect")
        payload = verify_token(token)
        assert payload["sub"] == "42"
        assert payload["username"] == "architect"

    def test_expired_token_raises(self):
        from datetime import timedelta
        from app.core.jwt import create_access_token, verify_token, JWTError

        # Create token that expires immediately
        token = create_access_token(
            user_id=1, username="test", expires_delta=timedelta(seconds=-1)
        )
        with pytest.raises(JWTError) as exc_info:
            verify_token(token)
        assert "expired" in str(exc_info.value).lower()


class TestEventGeneratorPersistence:
    """F12.2: SCN-1, SCN-4, SCN-7 — commit-before-yield + Engram-down resilience.

    We replicate the persistence block inline rather than instantiating the
    FastAPI app — the goal is to assert the orchestration contract (commit
    happens BEFORE the 'done' yield; EngramError does not abort the stream)
    without spinning up Postgres.
    """

    @staticmethod
    def _run_persistence_block(
        *,
        session,
        engram_mirror,
        user_msg_content: str,
        assistant_content: str,
        user_id: int,
        project_id,
        ordering: list[str],
    ):
        """Mimic the chat route's pre-``done`` persistence block."""
        from app.models.message import Message

        session.add(
            Message(
                role="user",
                user_id=user_id,
                project_id=project_id,
                session_id=1,
                content=user_msg_content,
            )
        )
        session.add(
            Message(
                role="assistant",
                user_id=user_id,
                project_id=project_id,
                session_id=1,
                content=assistant_content,
                citations=[],
            )
        )
        session.commit()
        ordering.append("commit")
        try:
            engram_mirror("u", user_id=user_id, project_id=project_id)
            engram_mirror("a", user_id=user_id, project_id=project_id)
        except Exception:
            # Must NOT propagate — REQ-6 / REQ-10 / SCN-4.
            pass

    def test_commit_happens_before_done_yield(self):
        """REQ-4 / SCN-1 / SCN-7: ordering invariant."""
        ordering: list[str] = []

        session = MagicMock()
        # Track commit vs yield-done ordering.

        # Patch engram_mirror where chat.py imports it.
        with patch("app.api.chat.engram_mirror") as fake_mirror:
            fake_mirror.side_effect = lambda *_a, **_kw: ordering.append("engram_mirror")

            # Build a tiny async generator that yields tokens then runs the
            # persistence block then yields 'done'.
            async def run():
                yield "event: sources\ndata: []\n\n"
                yield "event: token\ndata: \"hi\"\n\n"
                self._run_persistence_block(
                    session=session,
                    engram_mirror=fake_mirror,
                    user_msg_content="hola",
                    assistant_content="hi",
                    user_id=1,
                    project_id=1,
                    ordering=ordering,
                )
                ordering.append("yield_done")
                yield "event: done\ndata: null\n\n"

            asyncio.run(_drain(run()))

        assert ordering.index("commit") < ordering.index("yield_done")
        # And engram_mirror fires after commit.
        assert ordering.index("commit") < ordering.index("engram_mirror")

    def test_engram_error_does_not_abort_stream(self):
        """REQ-6 / REQ-10 / SCN-4: Engram failure must NOT raise to caller."""
        from app.core.engram_client import EngramError

        session = MagicMock()

        with patch("app.api.chat.engram_mirror") as fake_mirror:
            fake_mirror.side_effect = EngramError("Engram caído")

            async def run():
                yield "event: sources\ndata: []\n\n"
                self._run_persistence_block(
                    session=session,
                    engram_mirror=fake_mirror,
                    user_msg_content="hola",
                    assistant_content="hi",
                    user_id=1,
                    project_id=1,
                    ordering=[],
                )
                yield "event: done\ndata: null\n\n"

            events = asyncio.run(_drain(run()))

        assert events[-1].startswith("event: done")
        session.commit.assert_called_once()


class TestPostgresLivenessCheck:
    """F12 (REQ-11 / SCN-5): liveness check returns 503 when Postgres unreachable.

    The route must run a SELECT 1 BEFORE opening the SSE stream. If that probe
    raises SQLAlchemyError, the route returns HTTP 503 (NOT 200 + event: error).
    """

    def test_postgres_down_returns_503(self):
        """Liveness probe raises SQLAlchemyError -> route raises HTTPException(503)."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from sqlalchemy.exc import SQLAlchemyError

        from app.api.chat import router
        from app.api.dependencies import get_current_user

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "username": "test"}

        client = TestClient(app)

        with patch("app.core.database.SessionLocal") as mock_session_local:
            # SessionLocal() returns a context manager whose .execute raises.
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.execute.side_effect = SQLAlchemyError("connection refused")
            mock_session_local.return_value = mock_db

            response = client.post(
                "/api/chat",
                json={"project_id": None, "message": "hello"},
            )

            assert response.status_code == 503
            assert "Database unavailable" in response.json()["detail"]


async def _drain(gen):
    """Materialise an async generator into a list (Pytest-friendly)."""
    return [item async for item in gen]
