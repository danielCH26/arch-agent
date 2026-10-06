"""Tests for the global exception handlers in server.py.

PR #85 round 4 (Soomri): rewritten to use a fresh ``FastAPI()`` per test
instead of the real ``server.app``. The real app loads routers + middleware +
mounts the SPA on ``/`` when ``frontend/dist`` exists, which captures the
mocked test routes and causes 10 failures in any environment that builds
the frontend (including a CI that runs ``npm run build`` before tests).

Each test now creates its own ``app`` + registers the global handler, so:
- The SPA-mounted ``/`` can't intercept test routes.
- Routes don't accumulate across tests (no leak of ``app.router.routes``).
- The test passes with or without ``frontend/dist`` present.

Soomri's review item 8 explicitly suggested "or better, use a global
exception_handler" — these tests prove that wiring maps our typed errors
to the right HTTP codes.
"""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.core.exceptions import (
    ArchAgentError,
    DatabaseConnectionError,
    DatabaseIntegrityError,
    FileInvalidFormatError,
    FileTooLargeError,
    LLMInvalidResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
    RAGEmbeddingError,
)


def _build_test_app_with_route(raise_exc: Exception, route_path: str):
    """Build a fresh FastAPI() with the global handler, attach a route that
    raises ``raise_exc`` on GET, and return a TestClient.

    We use a fresh ``FastAPI()`` per test (NOT ``server.app``) so:
    1. The SPA-mounted ``/`` doesn't intercept the test routes.
    2. Routes don't leak between tests (each app is fresh and GC'd).
    3. The test is independent of whether ``frontend/dist`` is built.

    ``route_path`` MUST be unique per test — FastAPI caches the first
    handler registered for a given path and ignores later re-registrations
    (it logs a warning, not an error), so reusing ``/_test_route_raises``
    would make every test exercise the FIRST exception class registered.
    """
    from fastapi import FastAPI
    from server import _archagent_handler

    app = FastAPI()
    app.add_exception_handler(ArchAgentError, _archagent_handler)

    @app.get(route_path)
    async def _route():
        raise raise_exc

    return TestClient(app, raise_server_exceptions=False)


class TestGlobalExceptionHandler(unittest.TestCase):
    def test_database_connection_error_maps_to_503(self):
        client = _build_test_app_with_route(DatabaseConnectionError("sin conexion"), "/_test_route_raises_dbconn")
        resp = client.get("/_test_route_raises_dbconn")
        assert resp.status_code == 503
        assert "base de datos" in resp.json()["detail"]
        client.close()

    def test_database_integrity_error_maps_to_409(self):
        client = _build_test_app_with_route(DatabaseIntegrityError("duplicado"), "/_test_route_raises_dbinteg")
        resp = client.get("/_test_route_raises_dbinteg")
        assert resp.status_code == 409
        assert "Ya existe un recurso" in resp.json()["detail"]
        client.close()

    def test_file_invalid_format_maps_to_415(self):
        client = _build_test_app_with_route(FileInvalidFormatError(".exe no permitido"), "/_test_route_raises_filetype")
        resp = client.get("/_test_route_raises_filetype")
        assert resp.status_code == 415
        assert "PDF" in resp.json()["detail"]
        client.close()

    def test_file_too_large_maps_to_413(self):
        client = _build_test_app_with_route(FileTooLargeError("11 MB max"), "/_test_route_raises_filetoobig")
        resp = client.get("/_test_route_raises_filetoobig")
        assert resp.status_code == 413
        # Detail filled at runtime from the exception message
        assert "11" in resp.json()["detail"]
        client.close()

    def test_llm_invalid_response_maps_to_502(self):
        client = _build_test_app_with_route(LLMInvalidResponseError("parse error"), "/_test_route_raises_llminv")
        resp = client.get("/_test_route_raises_llminv")
        assert resp.status_code == 502
        client.close()

    def test_llm_rate_limit_maps_to_429(self):
        client = _build_test_app_with_route(LLMRateLimitError("429 from provider"), "/_test_route_raises_llmrate")
        resp = client.get("/_test_route_raises_llmrate")
        assert resp.status_code == 429
        client.close()

    def test_llm_timeout_maps_to_504(self):
        client = _build_test_app_with_route(LLMTimeoutError("provider timeout"), "/_test_route_raises_llmtimeout")
        resp = client.get("/_test_route_raises_llmtimeout")
        assert resp.status_code == 504
        client.close()

    def test_rag_embedding_maps_to_503(self):
        client = _build_test_app_with_route(RAGEmbeddingError("provider down"), "/_test_route_raises_rag")
        resp = client.get("/_test_route_raises_rag")
        assert resp.status_code == 503
        assert "Verifica tu conexión" in resp.json()["detail"]
        client.close()

    def test_unknown_archagent_error_maps_to_500(self):
        """RAGSearchError lives in app.core.rag (not in app.core.exceptions);
        it is handled locally by the RAG endpoints and is intentionally NOT
        in the global handler.
        """
        client = _build_test_app_with_route(ArchAgentError("unknown"), "/_test_route_raises_arch")
        resp = client.get("/_test_route_raises_arch")
        # Unhandled sub-classes fall back to 500 with a generic Spanish message;
        # we do NOT leak the exception text to the client.
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(
            resp.json()["detail"],
            "Ocurrió un error inesperado. Intenta de nuevo.",
        )
        client.close()


class TestGlobalHandlerCoexistsWithDecorators(unittest.TestCase):
    """Endpoints that still use @handle_db_errors are wrapped by the decorator;
    the exception never reaches the global handler (it's HTTPException already).
    This guards against us silently breaking the decorator path while adding
    the global handler.
    """
    def test_decorated_endpoint_still_returns_decorator_code(self):
        """Soomri round 5: build a fresh app WITHOUT the global handler so the
        409 can only come from ``@handle_db_errors``. Using ``server.app``
        (which mounts the SPA on ``/`` when ``frontend/dist`` exists) made
        the test 404 in any environment that built the frontend.
        """
        from fastapi import FastAPI
        from app.core.error_handlers import handle_db_errors

        # No add_exception_handler here — the 409 must come from the decorator.
        app = FastAPI()

        @app.get("/_test_route_decorated_db")
        @handle_db_errors
        async def _decorated_route():
            from app.core.exceptions import DatabaseIntegrityError
            raise DatabaseIntegrityError("foo")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/_test_route_decorated_db")
        self.assertEqual(resp.status_code, 409)
        client.close()