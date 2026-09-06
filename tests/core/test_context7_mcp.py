"""Smoke tests for the Context7 MCP client module skeleton (slice F11.1).

These tests verify only that the module imports and exposes the expected
public surface and pinned constants. The real client logic lands in
slice F11.2.
"""

from __future__ import annotations

import importlib


def test_module_imports():
    mod = importlib.import_module("app.core.context7_mcp")
    assert mod is not None


def test_pinned_constants():
    from app.core import context7_mcp

    assert context7_mcp._BASE_URL == "https://mcp.context7.com/mcp"
    assert context7_mcp._TIMEOUT_SECONDS == 5.0


def test_public_callables_exist():
    from app.core import context7_mcp

    assert callable(getattr(context7_mcp, "build_context7_client", None))
    assert callable(getattr(context7_mcp, "get_context7_tools", None))
    assert callable(getattr(context7_mcp, "reset_client_for_tests", None))


def test_context7_unavailable_exception():
    from app.core.context7_mcp import Context7Unavailable

    err = Context7Unavailable("boom", reason="context7_timeout")
    assert err.reason == "context7_timeout"
    assert "boom" in str(err)
