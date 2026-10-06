"""Integration test for the F17 error handling on a real FastAPI route.

This is the test both reviewers asked for (Soomri's checklist item 5):
it registers a real route through ``APIRouter`` with a ``@handle_db_errors``
decorator and asserts the HTTP status code, proving the decorator is
actually reached by FastAPI (not shadowed by decorator ordering).

The regression this guards against is subtle: with

    @handle_db_errors      # applied AFTER the router registered the function
    @router.post(...)

FastAPI registers the *undecorated* function, so the wrapper never runs and
the endpoint answers 500 instead of 409/503.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError

from app.api.dependencies import get_current_user
from app.core.error_handlers import handle_db_errors
from app.core.exceptions import DatabaseConnectionError, DatabaseIntegrityError


# --- A minimal app with one real route per exception family ---------------


def _build_app(handler, exc: Exception) -> FastAPI:
    """Build a FastAPI app whose single route raises ``exc``.

    The decorator order below is the one the reviewers asked for:
    ``@router.post`` first, ``@handler`` immediately above the function.
    """
    app = FastAPI()
    router = app.router

    @router.post("/boom")
    @handler
    async def boom(current_user: dict = Depends(get_current_user)):
        raise exc

    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 1,
        "username": "tester",
    }
    return app


class TestDecoratorReachedByFastAPI(unittest.TestCase):
    """The wrapper must run, so the custom exception becomes its HTTP code."""

    def test_our_integrity_error_maps_to_409(self):
        app = _build_app(handle_db_errors, DatabaseIntegrityError("duplicado"))
        with TestClient(app) as client:
            resp = client.post("/boom")
        self.assertEqual(resp.status_code, 409)
        self.assertIn("Cambia los valores", resp.json()["detail"])

    def test_our_connection_error_maps_to_503(self):
        app = _build_app(handle_db_errors, DatabaseConnectionError("sin conexion"))
        with TestClient(app) as client:
            resp = client.post("/boom")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("base de datos", resp.json()["detail"])

    def test_sqlalchemy_integrity_error_is_translated(self):
        """Real SQLAlchemy errors are mapped at the boundary (Soomri #2)."""
        exc = IntegrityError("INSERT", {}, Exception("duplicate key"))
        app = _build_app(handle_db_errors, exc)
        with TestClient(app) as client:
            resp = client.post("/boom")
        self.assertEqual(resp.status_code, 409)

    def test_sqlalchemy_operational_error_is_translated(self):
        exc = OperationalError("SELECT 1", {}, Exception("server closed"))
        app = _build_app(handle_db_errors, exc)
        with TestClient(app) as client:
            resp = client.post("/boom")
        self.assertEqual(resp.status_code, 503)


class TestResponsesDocumentedInOpenAPI(unittest.TestCase):
    """The new response codes must show up in the generated OpenAPI schema."""

    def test_documented_codes_appear_in_schema(self):
        from app.api.projects import router as projects_router
        from app.api.documents import router as documents_router
        from app.api.chat import router as chat_router

        app = FastAPI()
        app.include_router(projects_router)
        app.include_router(documents_router)
        app.include_router(chat_router)

        with TestClient(app) as client:
            schema = client.get("/openapi.json").json()

        def codes_for(path: str, method: str = "get") -> set[str]:
            return set(schema["paths"][path][method].get("responses", {}))

        # GET /api/projects (read-only) documents 503
        self.assertIn("503", codes_for("/api/projects"))
        # POST /api/projects (writes) documents 409 + 503
        self.assertIn("409", codes_for("/api/projects", "post"))
        self.assertIn("503", codes_for("/api/projects", "post"))
        # upload documents documents 413 + 415 + 503
        self.assertIn("413", codes_for("/api/documents/upload", "post"))
        self.assertIn("415", codes_for("/api/documents/upload", "post"))
        # chat documents the LLM family
        self.assertIn("429", codes_for("/api/chat", "post"))
        self.assertIn("502", codes_for("/api/chat", "post"))
        self.assertIn("504", codes_for("/api/chat", "post"))
