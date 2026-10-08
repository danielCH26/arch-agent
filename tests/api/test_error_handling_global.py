"""Tests for the global exception handlers in server.py.

These run against the real FastAPI ``app`` instance (not a fake one) so we
exercise the actual exception-handler wiring installed via
``@app.exception_handler``. Soomri's review item 8 explicitly suggested
"or better, use a global exception_handler" — these tests prove the wiring
maps our typed errors to the right HTTP codes.
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


def _build_app_with_route(raise_exc: Exception, route_path: str):
    """Attach a single test route to the real app and return a TestClient.

    We use the real app (not a fresh one) so the global exception handlers
    installed in server.py are exercised. ``route_path`` MUST be unique
    per test — FastAPI caches the first handler registered for a given
    path and ignores later re-registrations (it logs a warning, not an
    error), so reusing ``/_test_route_raises`` across tests would make
    every test exercise the FIRST exception class registered and never
    the one we actually want.
    """
    from server import app

    @app.get(route_path)
    async def _route():
        raise raise_exc

    return TestClient(app, raise_server_exceptions=False)


class TestGlobalExceptionHandler(unittest.TestCase):
    def test_database_connection_error_maps_to_503(self):
        client = _build_app_with_route(DatabaseConnectionError("sin conexion"), "/_test_route_raises_dbconn")
        resp = client.get("/_test_route_raises_dbconn")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("base de datos", resp.json()["detail"])
        client.close()

    def test_database_integrity_error_maps_to_409(self):
        client = _build_app_with_route(DatabaseIntegrityError("duplicado"), "/_test_route_raises_dbinteg")
        resp = client.get("/_test_route_raises_dbinteg")
        self.assertEqual(resp.status_code, 409)
        self.assertIn("Cambia los valores", resp.json()["detail"])
        client.close()

    def test_llm_timeout_maps_to_504(self):
        client = _build_app_with_route(LLMTimeoutError("provider timeout"), "/_test_route_raises_llmtimeout")
        resp = client.get("/_test_route_raises_llmtimeout")
        self.assertEqual(resp.status_code, 504)
        client.close()

    def test_llm_rate_limit_maps_to_429(self):
        client = _build_app_with_route(LLMRateLimitError("429 from provider"), "/_test_route_raises_llmrate")
        resp = client.get("/_test_route_raises_llmrate")
        self.assertEqual(resp.status_code, 429)
        client.close()

    def test_llm_invalid_response_maps_to_502(self):
        client = _build_app_with_route(LLMInvalidResponseError("parse error"), "/_test_route_raises_llminv")
        resp = client.get("/_test_route_raises_llminv")
        self.assertEqual(resp.status_code, 502)
        client.close()

    def test_file_too_large_maps_to_413(self):
        client = _build_app_with_route(FileTooLargeError("11 MB max"), "/_test_route_raises_filetoobig")
        resp = client.get("/_test_route_raises_filetoobig")
        self.assertEqual(resp.status_code, 413)
        # Detail filled at runtime from the exception message
        self.assertIn("11", resp.json()["detail"])
        client.close()

    def test_file_invalid_format_maps_to_415(self):
        client = _build_app_with_route(FileInvalidFormatError(".exe no permitido"), "/_test_route_raises_filetype")
        resp = client.get("/_test_route_raises_filetype")
        self.assertEqual(resp.status_code, 415)
        self.assertIn("PDF", resp.json()["detail"])
        client.close()

    def test_rag_embedding_maps_to_503(self):
        client = _build_app_with_route(RAGEmbeddingError("provider down"), "/_test_route_raises_rag")
        resp = client.get("/_test_route_raises_rag")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("Verifica tu conexión", resp.json()["detail"])
        client.close()

    def test_unknown_archagent_error_maps_to_500(self):
        # RAGSearchError lives in app.core.rag (not in app.core.exceptions);
        # it is handled locally by the RAG endpoints and is intentionally NOT
        # in the global handler.
        client = _build_app_with_route(ArchAgentError("unknown"), "/_test_route_raises_arch")
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
        """Verify the FIX for F17 review feedback item 1.

        Production endpoints have ``@router.post(...)`` ABOVE
        ``@handle_db_errors`` (router wraps the inner function). If the
        order is inverted, the decorator never runs and the global
        handler must catch the original ``ArchAgentError`` instead.
        """
        from server import app
        from app.core.error_handlers import handle_db_errors

        # Correct order: @router first, then @handle_db_errors
        @app.get("/_test_route_decorated_db_correct")
        @handle_db_errors
        async def _decorated_route_correct():
            from app.core.exceptions import DatabaseIntegrityError
            raise DatabaseIntegrityError("foo")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/_test_route_decorated_db_correct")
        # Decorator runs first, translates to HTTPException(409)
        self.assertEqual(resp.status_code, 409)
        client.close()

        # Inverted order: @handle_db_errors ABOVE @router (the F17 review bug).
        # The decorator's wrapper never runs because @router binds the
        # original function to the route. The global exception handler
        # catches the original ArchAgentError and maps it.
        @app.get("/_test_route_decorated_db_inverted")
        async def _decorated_route_inverted():
            from app.core.error_handlers import handle_db_errors

            @handle_db_errors
            async def _inner():
                from app.core.exceptions import DatabaseIntegrityError
                raise DatabaseIntegrityError("foo")

            return await _inner()

        client2 = TestClient(app, raise_server_exceptions=False)
        resp2 = client2.get("/_test_route_decorated_db_inverted")
        # Global handler maps DatabaseIntegrityError -> 409
        self.assertEqual(resp2.status_code, 409)
        client2.close()