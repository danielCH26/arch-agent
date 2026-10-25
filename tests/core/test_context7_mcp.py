"""
Tests for app.core.context7_mcp (slice F11.2).

Covers REQ-2 (singleton + runtime auth header), REQ-6 (5s timeout) and
SCN-4 / SCN-5 / SCN-8 (recorded fixture + auth + tool-name pin).

All third-party calls are mocked — the live ``https://mcp.context7.com/mcp``
test is gated by ``@pytest.mark.skipif(not os.getenv("CONTEXT7_API_KEY"))``.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Auth header / config construction
# ---------------------------------------------------------------------------


def test_build_headers_unset(monkeypatch):
    from app.core import context7_mcp

    monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)
    assert context7_mcp._build_headers() == {}


def test_build_headers_empty_string(monkeypatch):
    from app.core import context7_mcp

    monkeypatch.setenv("CONTEXT7_API_KEY", "")
    assert context7_mcp._build_headers() == {}


def test_build_headers_whitespace_only(monkeypatch):
    from app.core import context7_mcp

    monkeypatch.setenv("CONTEXT7_API_KEY", "   ")
    assert context7_mcp._build_headers() == {}


def test_build_headers_with_key(monkeypatch):
    from app.core import context7_mcp

    monkeypatch.setenv("CONTEXT7_API_KEY", "ctx7_test_key")
    headers = context7_mcp._build_headers()
    assert headers == {"Authorization": "Bearer ctx7_test_key"}


def test_build_headers_strips_whitespace_around_key(monkeypatch):
    from app.core import context7_mcp

    monkeypatch.setenv("CONTEXT7_API_KEY", "  ctx7_test_key  ")
    headers = context7_mcp._build_headers()
    assert headers == {"Authorization": "Bearer ctx7_test_key"}


def test_build_config_translates_headers_and_transport(monkeypatch):
    from app.core import context7_mcp

    monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)
    config = context7_mcp._build_config({})
    assert config["context7"]["transport"] == "streamable_http"
    assert config["context7"]["url"] == "https://mcp.context7.com/mcp"
    assert config["context7"]["headers"] == {}
    assert config["context7"]["timeout"] == 5.0


# ---------------------------------------------------------------------------
# Singleton behavior (mocked adapter)
# ---------------------------------------------------------------------------


def _fake_tool(name: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    return tool


def test_build_context7_client_passes_bearer_header(monkeypatch):
    """The Authorization header must reach the adapter when key is set."""
    from app.core import context7_mcp

    monkeypatch.setenv("CONTEXT7_API_KEY", "ctx7_live_key")
    context7_mcp.reset_client_for_tests()

    captured: dict = {}
    fake_class = MagicMock()

    def _factory(connections):
        captured["connections"] = connections
        return MagicMock()

    fake_class.side_effect = _factory

    with patch.object(context7_mcp, "_get_client_class", return_value=fake_class):
        context7_mcp.build_context7_client()

    headers = captured["connections"]["context7"]["headers"]
    assert headers == {"Authorization": "Bearer ctx7_live_key"}
    assert captured["connections"]["context7"]["transport"] == "streamable_http"
    assert captured["connections"]["context7"]["url"] == "https://mcp.context7.com/mcp"


def test_build_context7_client_is_singleton(monkeypatch):
    """Two calls return the same instance (REQ-2)."""
    from app.core import context7_mcp

    context7_mcp.reset_client_for_tests()
    monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)

    fake_instance = MagicMock()
    fake_class = MagicMock(return_value=fake_instance)
    with patch.object(context7_mcp, "_get_client_class", return_value=fake_class):
        first = context7_mcp.build_context7_client()
        second = context7_mcp.build_context7_client()
    assert first is second
    # The factory only ran once (singleton short-circuits the second call).
    assert fake_class.call_count == 1


def test_build_context7_client_raises_when_adapter_missing(monkeypatch):
    """When ``langchain_mcp_adapters`` is missing, return a typed error."""
    from app.core import context7_mcp

    context7_mcp.reset_client_for_tests()
    monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)

    def _boom():
        raise ImportError("simulated missing wheel")

    with patch.object(context7_mcp, "_get_client_class", side_effect=_boom):
        with pytest.raises(context7_mcp.Context7Unavailable) as exc_info:
            context7_mcp.build_context7_client()
    assert exc_info.value.reason == "context7_unavailable"


def test_build_context7_client_raises_on_construction_failure(monkeypatch):
    """Adapter constructor errors are typed as Context7Unavailable."""
    from app.core import context7_mcp

    context7_mcp.reset_client_for_tests()
    monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)

    fake_class = MagicMock(side_effect=RuntimeError("bad config"))
    with patch.object(context7_mcp, "_get_client_class", return_value=fake_class):
        with pytest.raises(context7_mcp.Context7Unavailable) as exc_info:
            context7_mcp.build_context7_client()
    assert exc_info.value.reason == "context7_unavailable"


# ---------------------------------------------------------------------------
# Tool fetch + timeout (REQ-6)
# ---------------------------------------------------------------------------


def test_get_context7_tools_returns_recorded_names(monkeypatch):
    """Recorded fixture asserts SCN-8 pins both tool names."""
    from app.core import context7_mcp
    from tests.fixtures.context7_tools import (
        EXPECTED_TOOL_NAMES,
        get_recorded_context7_tools,
    )

    fake_client = MagicMock()
    fake_client.get_tools = AsyncMock(return_value=get_recorded_context7_tools())

    async def _drive():
        return await context7_mcp.get_context7_tools(client=fake_client)

    tools = asyncio.run(_drive())
    tool_names = [t.name for t in tools]
    assert set(tool_names) == set(EXPECTED_TOOL_NAMES)
    assert "resolve-library-id" in tool_names
    assert "query-docs" in tool_names


def test_get_context7_tools_5s_timeout(monkeypatch):
    """When the fetch takes >5s, raise ``context7_timeout``."""
    from app.core import context7_mcp

    fake_client = MagicMock()

    async def _slow(*_args, **_kwargs):
        await asyncio.sleep(10)
        return []

    fake_client.get_tools = _slow

    async def _drive():
        return await context7_mcp.get_context7_tools(client=fake_client)

    # Shrink the timeout for test speed.
    monkeypatch.setattr(context7_mcp, "_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(context7_mcp.Context7Unavailable) as exc_info:
        asyncio.run(_drive())
    assert exc_info.value.reason == "context7_timeout"


def test_get_context7_tools_connection_error(monkeypatch):
    """DNS / connection refused -> ``context7_unavailable``."""
    from app.core import context7_mcp

    fake_client = MagicMock()

    async def _fail(*_args, **_kwargs):
        raise ConnectionRefusedError("simulated DNS failure")

    fake_client.get_tools = _fail

    async def _drive():
        return await context7_mcp.get_context7_tools(client=fake_client)

    with pytest.raises(context7_mcp.Context7Unavailable) as exc_info:
        asyncio.run(_drive())
    assert exc_info.value.reason == "context7_unavailable"


def test_get_context7_tools_rate_limited(monkeypatch):
    """HTTP 429 -> ``context7_rate_limited``."""
    from app.core import context7_mcp

    fake_client = MagicMock()

    class _RateLimitedError(Exception):
        def __init__(self):
            self.status_code = 429

    async def _fail(*_args, **_kwargs):
        raise _RateLimitedError()

    fake_client.get_tools = _fail

    async def _drive():
        return await context7_mcp.get_context7_tools(client=fake_client)

    with pytest.raises(context7_mcp.Context7Unavailable) as exc_info:
        asyncio.run(_drive())
    assert exc_info.value.reason == "context7_rate_limited"


def test_get_context7_tools_rate_limit_via_response_attr(monkeypatch):
    """HTTP status is sometimes on ``response.status_code`` (httpx style)."""
    from app.core import context7_mcp

    fake_client = MagicMock()

    class _Resp:
        status_code = 429

    class _Wrapped(Exception):
        def __init__(self):
            self.response = _Resp()

    async def _fail(*_args, **_kwargs):
        raise _Wrapped()

    fake_client.get_tools = _fail

    async def _drive():
        return await context7_mcp.get_context7_tools(client=fake_client)

    with pytest.raises(context7_mcp.Context7Unavailable) as exc_info:
        asyncio.run(_drive())
    assert exc_info.value.reason == "context7_rate_limited"


def test_get_context7_tools_5xx_maps_to_unavailable(monkeypatch):
    """Non-429 4xx/5xx errors map to ``context7_unavailable``."""
    from app.core import context7_mcp

    fake_client = MagicMock()

    class _ServerError(Exception):
        def __init__(self):
            self.status_code = 503

    async def _fail(*_args, **_kwargs):
        raise _ServerError()

    fake_client.get_tools = _fail

    async def _drive():
        return await context7_mcp.get_context7_tools(client=fake_client)

    with pytest.raises(context7_mcp.Context7Unavailable) as exc_info:
        asyncio.run(_drive())
    assert exc_info.value.reason == "context7_unavailable"


# ---------------------------------------------------------------------------
# Live test (gated; skipped when CONTEXT7_API_KEY is unset)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.getenv("CONTEXT7_API_KEY"),
    reason="CONTEXT7_API_KEY unset; live test skipped.",
)
def test_get_context7_tools_live_against_public_endpoint():
    """SCN-5 / SCN-8: hit the real MCP server and assert tool names."""
    from app.core import context7_mcp

    context7_mcp.reset_client_for_tests()

    async def _drive():
        return await context7_mcp.get_context7_tools()

    tools = asyncio.run(_drive())
    names = {t.name for t in tools}
    assert "resolve-library-id" in names
    assert "query-docs" in names
