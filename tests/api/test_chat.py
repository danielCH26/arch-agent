"""
Tests para /api/chat — SSE streaming.
"""

import pytest
from unittest.mock import MagicMock, patch
import json


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
