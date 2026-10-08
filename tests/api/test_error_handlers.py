"""Tests for error handling decorators.

Issue #25 (F17) - Manejo de errores.

Verifies that the decorators in app.core.error_handlers correctly
translate each custom exception into the right HTTP status code
and a user-friendly error message.

Uses unittest.IsolatedAsyncioTestCase so the suite runs both under
pytest (without pytest-asyncio) and under the standard unittest runner.
"""
from __future__ import annotations

import unittest

from fastapi import HTTPException

from app.core.error_handlers import (
    handle_db_errors,
    handle_file_errors,
    handle_llm_errors,
    handle_rag_errors,
)
from app.core.exceptions import (
    DatabaseConnectionError,
    DatabaseIntegrityError,
    FileInvalidFormatError,
    FileTooLargeError,
    LLMInvalidResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
    RAGEmbeddingError,
    RAGSearchEmptyError,
)


# ---------------------------------------------------------------------------
# handle_llm_errors
# ---------------------------------------------------------------------------

class HandleLlmErrorsTests(unittest.IsolatedAsyncioTestCase):

    async def test_timeout_maps_to_504(self):
        @handle_llm_errors
        async def func():
            raise LLMTimeoutError("model took too long")

        with self.assertRaises(HTTPException) as ctx:
            await func()
        self.assertEqual(ctx.exception.status_code, 504)
        self.assertIn("tardando más de lo esperado", ctx.exception.detail)

    async def test_rate_limit_maps_to_429(self):
        @handle_llm_errors
        async def func():
            raise LLMRateLimitError("quota exceeded")

        with self.assertRaises(HTTPException) as ctx:
            await func()
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("Espera un minuto", ctx.exception.detail)

    async def test_invalid_response_maps_to_502(self):
        @handle_llm_errors
        async def func():
            raise LLMInvalidResponseError("not JSON")

        with self.assertRaises(HTTPException) as ctx:
            await func()
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("respuesta inválida", ctx.exception.detail)

    async def test_passes_through_when_no_error(self):
        @handle_llm_errors
        async def func():
            return {"ok": True}

        result = await func()
        self.assertEqual(result, {"ok": True})


# ---------------------------------------------------------------------------
# handle_db_errors
# ---------------------------------------------------------------------------

class HandleDbErrorsTests(unittest.IsolatedAsyncioTestCase):

    async def test_connection_error_maps_to_503(self):
        @handle_db_errors
        async def func():
            raise DatabaseConnectionError("connection refused")

        with self.assertRaises(HTTPException) as ctx:
            await func()
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("base de datos", ctx.exception.detail)

    async def test_integrity_error_maps_to_409(self):
        @handle_db_errors
        async def func():
            raise DatabaseIntegrityError("duplicate key")

        with self.assertRaises(HTTPException) as ctx:
            await func()
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Cambia los valores", ctx.exception.detail)

    async def test_passes_through_when_no_error(self):
        @handle_db_errors
        async def func():
            return {"ok": True}

        result = await func()
        self.assertEqual(result, {"ok": True})

    async def test_sqlalchemy_operational_error_maps_to_503(self):
        """PR #85 round 4 (danielCH26): add coverage for SQLAlchemy
        OperationalError, not just our typed DatabaseConnectionError."""
        from sqlalchemy.exc import OperationalError

        @handle_db_errors
        async def func():
            raise OperationalError("SELECT 1", {}, Exception("db down"))

        with self.assertRaises(HTTPException) as ctx:
            await func()
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("No pudimos conectar", ctx.exception.detail)

    async def test_sqlalchemy_integrity_error_maps_to_409(self):
        """PR #85 round 4 (danielCH26): add coverage for SQLAlchemy
        IntegrityError (unique/FK violations). Regression guard for the
        round-3 bug where IntegrityError was caught by the broader
        DBAPIError clause and returned 503 instead of 409."""
        from sqlalchemy.exc import IntegrityError

        @handle_db_errors
        async def func():
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))

        with self.assertRaises(HTTPException) as ctx:
            await func()
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Ya existe un recurso", ctx.exception.detail)

    async def test_integrity_error_takes_precedence_over_dbapi(self):
        """Specifically guard against the round-3 bug: IntegrityError
        is a subclass of DBAPIError. If the except clauses get reordered,
        the broader DBAPIError clause would catch IntegrityError first and
        map it to 503. The order in the decorator source must be:
        IntegrityError BEFORE (OperationalError, DBAPIError)."""
        from sqlalchemy.exc import IntegrityError

        @handle_db_errors
        async def func():
            # 409 is IntegrityError (FK or unique violation)
            raise IntegrityError("INSERT", {}, Exception("FK violation"))

        with self.assertRaises(HTTPException) as ctx:
            await func()
        # If this test ever returns 503, the except order has been
        # regressed and the bug from round 3 is back.
        self.assertEqual(
            ctx.exception.status_code, 409,
            "IntegrityError must map to 409, not 503 (round-3 regression)",
        )


# ---------------------------------------------------------------------------
# handle_file_errors
# ---------------------------------------------------------------------------

class HandleFileErrorsTests(unittest.IsolatedAsyncioTestCase):

    async def test_too_large_maps_to_413(self):
        @handle_file_errors
        async def func():
            raise FileTooLargeError("60MB exceeds 10MB limit")

        with self.assertRaises(HTTPException) as ctx:
            await func()
        self.assertEqual(ctx.exception.status_code, 413)
        self.assertIn("tamaño máximo permitido", ctx.exception.detail)

    async def test_invalid_format_maps_to_415(self):
        @handle_file_errors
        async def func():
            raise FileInvalidFormatError("only PDF, MD, TXT allowed")

        with self.assertRaises(HTTPException) as ctx:
            await func()
        self.assertEqual(ctx.exception.status_code, 415)
        self.assertIn("PDF, Markdown o texto plano", ctx.exception.detail)

    async def test_passes_through_when_no_error(self):
        @handle_file_errors
        async def func():
            return {"ok": True}

        result = await func()
        self.assertEqual(result, {"ok": True})


# ---------------------------------------------------------------------------
# handle_rag_errors
# ---------------------------------------------------------------------------

class HandleRagErrorsTests(unittest.IsolatedAsyncioTestCase):

    async def test_embedding_error_maps_to_503(self):
        @handle_rag_errors
        async def func():
            raise RAGEmbeddingError("embedding service unavailable")

        with self.assertRaises(HTTPException) as ctx:
            await func()
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("Verifica tu conexión", ctx.exception.detail)

    async def test_search_empty_propagates_unwrapped(self):
        """RAGSearchEmptyError is NOT an HTTP error - the endpoint is
        expected to catch it and return a 200 with an empty list. The
        decorator must let it pass through unchanged.
        """
        @handle_rag_errors
        async def func():
            raise RAGSearchEmptyError("no matches")

        with self.assertRaises(RAGSearchEmptyError):
            await func()

    async def test_passes_through_when_no_error(self):
        @handle_rag_errors
        async def func():
            return {"results": []}

        result = await func()
        self.assertEqual(result, {"results": []})


# ---------------------------------------------------------------------------
# Decorator stack ordering
# ---------------------------------------------------------------------------

class DecoratorStackOrderingTests(unittest.IsolatedAsyncioTestCase):

    async def test_inner_decorator_wins_on_shared_status_code(self):
        """When the inner decorator catches an exception, the outer one
        (router.post) sees an HTTPException, not the original. This is the
        documented stacking order: @handle_*_errors closest to the function.
        """
        @handle_db_errors
        async def func():
            raise DatabaseIntegrityError("test ordering")

        with self.assertRaises(HTTPException) as ctx:
            await func()
        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
