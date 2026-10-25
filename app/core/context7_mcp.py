"""
Context7 MCP client wrapper.

Provides a process-wide singleton ``MultiServerMCPClient`` that connects to the
public ``https://mcp.context7.com/mcp`` endpoint using streamable_http
transport (REQ-2). When ``CONTEXT7_API_KEY`` is set, a runtime
``Authorization: Bearer <key>`` header is injected.

The module is lazy at the import boundary so it can be imported in
environments where ``langchain_mcp_adapters`` is not yet installed.

Issue: #13 - [F11] Context7 MCP integration.
ADR: docs/adr/010-context7-agent-runtime.md.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

_LOGGER = logging.getLogger(__name__)

# REQ-2: pinned at design.md §2; only used by ``build_context7_client``.
_BASE_URL: str = "https://mcp.context7.com/mcp"

# REQ-6: 5-second per-call budget; honored via ``asyncio.wait_for`` in
# ``get_context7_tools``.
_TIMEOUT_SECONDS: float = 5.0

# Process-wide singleton; lazy-initialized by ``build_context7_client``.
_CLIENT: Any = None

# Transport literal expected by langchain-mcp-adapters 0.3.2.
# (``streamable_http`` is the modern MCP HTTP transport; ``http`` was the
# pre-1.0 name and is rejected by 0.3.2. Spec lives at
# https://modelcontextprotocol.io/specification/2025-03-26/basic/transports
# — see design.md §11 for why we keep the public HTTPS URL.)
_TRANSPORT: str = "streamable_http"

# Threshold for converting an HTTP 429 into a typed
# ``context7_rate_limited`` reason. Anything else 4xx/5xx is mapped to
# ``context7_unavailable``.
_HTTP_TOO_MANY_REQUESTS: int = 429


class Context7Unavailable(Exception):
    """Raised when the Context7 MCP endpoint cannot be reached or returns an
    unrecoverable HTTP error.

    The ``reason`` attribute is one of:
      * ``context7_timeout``         - ``asyncio.TimeoutError`` after 5s
      * ``context7_unavailable``     - DNS / connection refused / generic
      * ``context7_rate_limited``    - HTTP 429
    """

    def __init__(self, message: str, reason: str = "context7_unavailable") -> None:
        super().__init__(message)
        self.reason = reason


def _build_headers() -> dict[str, str]:
    """Read ``CONTEXT7_API_KEY`` at call time and return the auth header dict.

    Empty / whitespace-only values produce an empty ``headers`` dict so the
    server runs in its free-tier default (REQ-2).
    """
    key = (os.getenv("CONTEXT7_API_KEY") or "").strip()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


def _build_config(headers: dict[str, str]) -> dict[str, Any]:
    """Translate the public config dict into the adapter's expected shape.

    ``MultiServerMCPClient`` expects a ``connections`` dict keyed by server
    name, with each value carrying ``transport``, ``url``, ``headers`` and
    ``timeout``. The adapter validates ``transport`` against the literal
    ``streamable_http`` (or ``sse`` / ``stdio`` / ``websocket``).
    """
    return {
        "context7": {
            "transport": _TRANSPORT,
            "url": _BASE_URL,
            "headers": headers,
            "timeout": _TIMEOUT_SECONDS,
        }
    }


def _get_client_class() -> Any:
    """Lazy import so collection never breaks when the wheel is absent.

    Imports are wrapped into ``Context7Unavailable`` so the agent layer can
    degrade uniformly on construction failures (adapter missing, wrong
    version, transitive ImportError). Direct ``ImportError`` re-raises are
    handled at the call-site boundary (``build_context7_client``) so callers
    that want to test import-time behavior can still observe them.
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError as e:
        raise Context7Unavailable(
            "langchain_mcp_adapters is not installed; cannot build Context7 client.",
            reason="context7_unavailable",
        ) from e
    return MultiServerMCPClient


def build_context7_client() -> Any:
    """Build (or return the cached) ``MultiServerMCPClient`` for Context7.

    Reads ``CONTEXT7_API_KEY`` at *call* time (not at import time) so that
    tests can monkeypatch the env var between calls without re-importing.

    Returns:
        ``MultiServerMCPClient`` configured for Context7's streamable-http
        endpoint, with optional ``Authorization: Bearer <key>`` header.
    """
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    try:
        MultiServerMCPClient = _get_client_class()
    except Context7Unavailable:
        raise  # already typed
    except ImportError as e:
        # Defense in depth: if a transitive import raises after the
        # ``_get_client_class`` try/except, surface it as a typed failure.
        raise Context7Unavailable(
            f"langchain_mcp_adapters import failed: {e}",
            reason="context7_unavailable",
        ) from e
    headers = _build_headers()
    connections = _build_config(headers)

    try:
        client = MultiServerMCPClient(connections=connections)
    except Exception as e:
        # Construction-time failures (bad config, network unreachable at
        # startup, etc.) are still typed so the agent layer can degrade.
        _LOGGER.warning("Context7 client construction failed: %s", e)
        raise Context7Unavailable(
            f"Failed to build Context7 MCP client: {e}",
            reason="context7_unavailable",
        ) from e

    _CLIENT = client
    _LOGGER.info(
        "Context7 MCP client built (auth=%s, url=%s, timeout=%.1fs)",
        bool(headers.get("Authorization")),
        _BASE_URL,
        _TIMEOUT_SECONDS,
    )
    return _CLIENT


def _is_rate_limited(exc: BaseException) -> bool:
    """Return True if the exception looks like an HTTP 429 response."""
    # langchain-mcp-adapters wraps httpx errors; we sniff both for resilience
    # against future adapter refactors. ``status_code`` is the most common
    # attribute; ``response.status_code`` is the httpx fallback.
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None) if response is not None else None
    return status == _HTTP_TOO_MANY_REQUESTS


async def get_context7_tools(client: Any | None = None) -> list[Any]:
    """Fetch the available tools from Context7, with a 5s timeout.

    Args:
        client: Optional pre-built ``MultiServerMCPClient``. When ``None``,
            ``build_context7_client()`` is invoked and the result cached.

    Returns:
        List of LangChain ``BaseTool`` objects. SCN-8 asserts the two known
        tool names (``resolve-library-id`` and ``query-docs``) are present.

    Raises:
        Context7Unavailable: When the call times out, the connection fails,
            or Context7 returns 4xx / 5xx after retry exhaustion.
    """
    if client is None:
        client = build_context7_client()

    try:
        tools = await asyncio.wait_for(
            client.get_tools(server_name="context7"),
            timeout=_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as e:
        _LOGGER.warning("Context7 tool fetch timed out after %.1fs", _TIMEOUT_SECONDS)
        raise Context7Unavailable(
            f"Context7 tool fetch timed out after {_TIMEOUT_SECONDS}s",
            reason="context7_timeout",
        ) from e
    except Exception as e:
        if _is_rate_limited(e):
            _LOGGER.warning("Context7 rate limit hit (HTTP 429): %s", e)
            raise Context7Unavailable(
                f"Context7 rate limit: {e}",
                reason="context7_rate_limited",
            ) from e
        _LOGGER.warning("Context7 tool fetch failed: %s", e)
        raise Context7Unavailable(
            f"Context7 tool fetch failed: {e}",
            reason="context7_unavailable",
        ) from e

    _LOGGER.info("Context7 returned %d tools: %s", len(tools), [t.name for t in tools])
    return tools


def reset_client_for_tests() -> None:
    """Clear the module-level singleton. Tests use this to start clean."""
    global _CLIENT
    _CLIENT = None
