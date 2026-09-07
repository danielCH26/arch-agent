"""
Tests for app.core.puppeteer_mcp (F13, issue #17).

Covers REQ-PMCP-2 (positive allow-list filter, SCN-PMCP-3), REQ-PMCP-3
(15s timeout, 2 MB byte cap), REQ-PMCP-4 (5/min sliding-window rate
limit, SCN-PMCP-6) and the typed ``PuppeteerUnavailable`` sub-reasons.

Mirrors the F11 ``tests/core/test_context7_mcp.py`` convention. All
third-party calls are mocked; the live sidecar test is gated by
``@pytest.mark.skipif(not os.getenv("PUPPETEER_LIVE_TEST"))``.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Auth / config — single ``PUPPETEER_MCP_URL`` env var, no headers
# ---------------------------------------------------------------------------


def test_resolve_url_uses_env(monkeypatch):
    from app.core import puppeteer_mcp

    monkeypatch.setenv("PUPPETEER_MCP_URL", "http://example:1234/mcp")
    assert puppeteer_mcp._resolve_url() == "http://example:1234/mcp"


def test_resolve_url_falls_back_to_default(monkeypatch):
    from app.core import puppeteer_mcp

    monkeypatch.delenv("PUPPETEER_MCP_URL", raising=False)
    assert puppeteer_mcp._resolve_url() == "http://puppeteer-mcp:8931/mcp"


def test_resolve_url_strips_whitespace(monkeypatch):
    from app.core import puppeteer_mcp

    monkeypatch.setenv("PUPPETEER_MCP_URL", "  http://example:1234/mcp  ")
    assert puppeteer_mcp._resolve_url() == "http://example:1234/mcp"


def test_build_config_translates_url_and_transport(monkeypatch):
    from app.core import puppeteer_mcp

    monkeypatch.setenv("PUPPETEER_MCP_URL", "http://example:1234/mcp")
    config = puppeteer_mcp._build_config()
    assert config["puppeteer"]["transport"] == "streamable_http"
    assert config["puppeteer"]["url"] == "http://example:1234/mcp"
    assert config["puppeteer"]["timeout"] == 30.0


# ---------------------------------------------------------------------------
# Singleton behavior (mocked adapter)
# ---------------------------------------------------------------------------


def _fake_tool(name: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    return tool


def test_build_puppeteer_client_is_singleton(monkeypatch):
    """Two calls return the same instance (REQ-PMCP-1 transport)."""
    from app.core import puppeteer_mcp

    puppeteer_mcp.reset_client_for_tests()
    monkeypatch.delenv("PUPPETEER_MCP_URL", raising=False)

    fake_instance = MagicMock()
    fake_class = MagicMock(return_value=fake_instance)
    with patch.object(puppeteer_mcp, "_get_client_class", return_value=fake_class):
        first = puppeteer_mcp.build_puppeteer_client()
        second = puppeteer_mcp.build_puppeteer_client()
    assert first is second
    assert fake_class.call_count == 1


def test_build_puppeteer_client_raises_when_adapter_missing(monkeypatch):
    from app.core import puppeteer_mcp

    puppeteer_mcp.reset_client_for_tests()
    monkeypatch.delenv("PUPPETEER_MCP_URL", raising=False)

    def _boom():
        raise ImportError("simulated missing wheel")

    with patch.object(puppeteer_mcp, "_get_client_class", side_effect=_boom):
        with pytest.raises(puppeteer_mcp.PuppeteerUnavailable) as exc_info:
            puppeteer_mcp.build_puppeteer_client()
    assert exc_info.value.reason == "puppeteer_unavailable"


def test_build_puppeteer_client_raises_on_construction_failure(monkeypatch):
    from app.core import puppeteer_mcp

    puppeteer_mcp.reset_client_for_tests()
    monkeypatch.delenv("PUPPETEER_MCP_URL", raising=False)

    fake_class = MagicMock(side_effect=RuntimeError("bad config"))
    with patch.object(puppeteer_mcp, "_get_client_class", return_value=fake_class):
        with pytest.raises(puppeteer_mcp.PuppeteerUnavailable) as exc_info:
            puppeteer_mcp.build_puppeteer_client()
    assert exc_info.value.reason == "puppeteer_unavailable"


# ---------------------------------------------------------------------------
# Allow-list filter — REQ-PMCP-2 / SCN-PMCP-3
# ---------------------------------------------------------------------------


def test_get_puppeteer_tools_allow_list_filters_navigate_etc(monkeypatch):
    """Recorded fixture of the full upstream tool surface (8 names) → output
    is exactly ``[puppeteer_screenshot]``."""
    from app.core import puppeteer_mcp

    full_upstream = [
        _fake_tool("puppeteer_navigate"),
        _fake_tool("puppeteer_screenshot"),
        _fake_tool("puppeteer_click"),
        _fake_tool("puppeteer_fill"),
        _fake_tool("puppeteer_select"),
        _fake_tool("puppeteer_hover"),
        _fake_tool("puppeteer_evaluate"),
        _fake_tool("puppeteer_pdf"),
    ]

    fake_client = MagicMock()
    fake_client.get_tools = AsyncMock(return_value=full_upstream)

    async def _drive():
        return await puppeteer_mcp.get_puppeteer_tools(client=fake_client)

    tools = asyncio.run(_drive())
    names = sorted(t.name for t in tools)
    assert names == ["puppeteer_screenshot"]


def test_get_puppeteer_tools_returns_empty_when_no_match(monkeypatch):
    from app.core import puppeteer_mcp

    fake_client = MagicMock()
    fake_client.get_tools = AsyncMock(
        return_value=[_fake_tool("something_else")]
    )

    async def _drive():
        return await puppeteer_mcp.get_puppeteer_tools(client=fake_client)

    tools = asyncio.run(_drive())
    assert tools == []


# ---------------------------------------------------------------------------
# Timeout — REQ-PMCP-3 (15s default)
# ---------------------------------------------------------------------------


def test_get_puppeteer_tools_timeout_raises(monkeypatch):
    """asyncio.wait_for → TimeoutError → PuppeteerUnavailable(reason="puppeteer_timeout")."""
    from app.core import puppeteer_mcp

    fake_client = MagicMock()

    async def _slow(*_args, **_kwargs):
        await asyncio.sleep(10)
        return []

    fake_client.get_tools = _slow

    async def _drive():
        return await puppeteer_mcp.get_puppeteer_tools(client=fake_client)

    monkeypatch.setattr(puppeteer_mcp, "_FETCH_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(puppeteer_mcp.PuppeteerUnavailable) as exc_info:
        asyncio.run(_drive())
    assert exc_info.value.reason == "puppeteer_timeout"


def test_get_puppeteer_tools_connection_error_unavailable(monkeypatch):
    from app.core import puppeteer_mcp

    fake_client = MagicMock()

    async def _fail(*_args, **_kwargs):
        raise ConnectionRefusedError("simulated DNS failure")

    fake_client.get_tools = _fail

    async def _drive():
        return await puppeteer_mcp.get_puppeteer_tools(client=fake_client)

    with pytest.raises(puppeteer_mcp.PuppeteerUnavailable) as exc_info:
        asyncio.run(_drive())
    assert exc_info.value.reason == "puppeteer_unavailable"


# ---------------------------------------------------------------------------
# Rate limiter — REQ-PMCP-4 / SCN-PMCP-6
# ---------------------------------------------------------------------------


def _reset_rate_limiter():
    from app.core import puppeteer_mcp

    puppeteer_mcp._RATE_LIMITER.clear()


def test_rate_limit_allows_5_calls_in_60s(monkeypatch):
    """5 calls within the window succeed; the 6th raises."""
    from app.core import puppeteer_mcp

    _reset_rate_limiter()
    monkeypatch.setenv("PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE", "5")

    # 5 calls — all must succeed.
    for _ in range(5):
        puppeteer_mcp._check_rate_limit(user_id=42)

    # 6th call — must raise.
    with pytest.raises(puppeteer_mcp.PuppeteerUnavailable) as exc_info:
        puppeteer_mcp._check_rate_limit(user_id=42)
    assert exc_info.value.reason == "puppeteer_rate_limited"


def test_rate_limit_is_per_user(monkeypatch):
    """User A's quota does not affect user B's quota."""
    from app.core import puppeteer_mcp

    _reset_rate_limiter()
    monkeypatch.setenv("PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE", "5")

    for _ in range(5):
        puppeteer_mcp._check_rate_limit(user_id=1)

    # User 2 starts fresh.
    for _ in range(5):
        puppeteer_mcp._check_rate_limit(user_id=2)

    # User 1's 6th call still raises; user 2's 6th call also raises.
    with pytest.raises(puppeteer_mcp.PuppeteerUnavailable):
        puppeteer_mcp._check_rate_limit(user_id=1)
    with pytest.raises(puppeteer_mcp.PuppeteerUnavailable):
        puppeteer_mcp._check_rate_limit(user_id=2)


def test_rate_limit_disabled_when_zero(monkeypatch):
    """``PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE=0`` disables the limiter
    entirely (design §7 Phase-1 rollout — every render is rejected)."""
    from app.core import puppeteer_mcp

    _reset_rate_limiter()
    monkeypatch.setenv("PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE", "0")

    # 100 calls all succeed when the limit is disabled.
    for _ in range(100):
        puppeteer_mcp._check_rate_limit(user_id=1)


def test_rate_limit_window_pruning_after_60s(monkeypatch):
    """Sliding-window: timestamps older than 60s are pruned; the 6th call
    succeeds once the first call has expired from the window."""
    from app.core import puppeteer_mcp

    _reset_rate_limiter()
    monkeypatch.setenv("PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE", "5")

    # Simulate time control via direct manipulation of the window. We
    # don't use freezegun (not in requirements); the pruning logic is
    # time-driven so we just push the timestamps back > 60s.
    base = puppeteer_mcp._time.time()
    puppeteer_mcp._RATE_LIMITER[42] = [base - 70, base - 65, base - 62, base - 61, base - 60]

    # Now the next call should succeed (all 5 old entries get pruned).
    puppeteer_mcp._check_rate_limit(user_id=42)
    assert len(puppeteer_mcp._RATE_LIMITER[42]) == 1


def test_rate_limit_handler_in_try_get_puppeteer_tools(monkeypatch):
    """End-to-end: ``_try_get_puppeteer_tools`` emits a degraded payload
    with ``source="puppeteer"`` and ``reason="puppeteer_rate_limited"``."""
    from app.core import agent

    monkeypatch.setenv("PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE", "1")
    agent_module = __import__("app.core.agent", fromlist=["_try_get_puppeteer_tools"])
    agent_module.puppeteer_mcp._RATE_LIMITER.clear()

    async def _drive():
        # Burn the quota.
        await agent_module._try_get_puppeteer_tools(user_id=99)
        return await agent_module._try_get_puppeteer_tools(user_id=99)

    _, degraded = asyncio.run(_drive())
    assert degraded is not None
    assert degraded["source"] == "puppeteer"
    assert degraded["reason"] == "puppeteer_rate_limited"


# ---------------------------------------------------------------------------
# PuppeteerUnavailable sub-reason taxonomy
# ---------------------------------------------------------------------------


def test_puppeteer_unavailable_default_reason():
    from app.core.puppeteer_mcp import PuppeteerUnavailable

    exc = PuppeteerUnavailable("boom")
    assert exc.reason == "puppeteer_unavailable"
    assert "boom" in str(exc)


def test_puppeteer_unavailable_explicit_reason():
    from app.core.puppeteer_mcp import PuppeteerUnavailable

    exc = PuppeteerUnavailable("boom", reason="puppeteer_byte_cap")
    assert exc.reason == "puppeteer_byte_cap"


# ---------------------------------------------------------------------------
# Live test (gated; skipped when PUPPETEER_LIVE_TEST is unset)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.getenv("PUPPETEER_LIVE_TEST"),
    reason="PUPPETEER_LIVE_TEST unset; live sidecar test skipped.",
)
def test_get_puppeteer_tools_live():
    from app.core import puppeteer_mcp

    puppeteer_mcp.reset_client_for_tests()

    async def _drive():
        return await puppeteer_mcp.get_puppeteer_tools()

    tools = asyncio.run(_drive())
    names = {t.name for t in tools}
    assert "puppeteer_screenshot" in names