"""
Context7 MCP client wrapper.

Provides a process-wide singleton ``MultiServerMCPClient`` that connects to the
public ``https://mcp.context7.com/mcp`` endpoint using HTTP (streamable_http)
transport. When ``CONTEXT7_API_KEY`` is set in the environment, a runtime
``Authorization: Bearer ...`` header is injected.

This module is intentionally lazy at the import boundary so it can be imported
in environments where ``langchain_mcp_adapters`` is not yet installed (the
``build_context7_client()`` and ``get_context7_tools()`` helpers import the
adapter only when they are called).

Issue: #13 - [F11] Context7 MCP integration.
ADR: docs/adr/010-context7-agent-runtime.md.
"""
from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

# REQ-2: pinned at design.md §2; only used by ``build_context7_client``.
_BASE_URL: str = "https://mcp.context7.com/mcp"

# REQ-6: 5-second per-call budget; honored via ``asyncio.wait_for`` in
# ``get_context7_tools``.
_TIMEOUT_SECONDS: float = 5.0

# Process-wide singleton; lazy-initialized by ``build_context7_client``.
_CLIENT: Any = None


class Context7Unavailable(Exception):
    """Raised when the Context7 MCP endpoint cannot be reached or returns an
    unrecoverable HTTP error.

    The ``reason`` attribute is one of:
      * ``context7_timeout``         - ``asyncio.TimeoutError`` after 5s
      * ``context7_unavailable``     - DNS / connection refused / generic
      * ``context7_rate_limited``    - HTTP 429 / 5xx after retry exhaustion
    """

    def __init__(self, message: str, reason: str = "context7_unavailable") -> None:
        super().__init__(message)
        self.reason = reason


def build_context7_client() -> Any:
    """Build (or return the cached) ``MultiServerMCPClient`` for Context7.

    Reads ``CONTEXT7_API_KEY`` at *call* time (not at import time) so that
    tests can monkeypatch the env var between calls without re-importing.

    Returns:
        ``MultiServerMCPClient`` configured for Context7's streamable-http
        endpoint, with optional ``Authorization: Bearer <key>`` header.
    """
    # NOTE: stub body — full implementation lands in slice F11.2.
    raise NotImplementedError("build_context7_client lands in slice F11.2")


async def get_context7_tools(client: Any | None = None) -> list[Any]:
    """Fetch the available tools from Context7, with a 5s timeout.

    Args:
        client: Optional pre-built ``MultiServerMCPClient``. When ``None``,
            the module-level singleton (or a freshly built client) is used.

    Returns:
        List of LangChain ``BaseTool`` objects. Today this returns
        ``resolve-library-id`` and ``query-docs`` (see SCN-8).

    Raises:
        Context7Unavailable: When the call times out, the connection fails,
            or Context7 returns 4xx / 5xx after retry exhaustion.
    """
    # NOTE: stub body — full implementation lands in slice F11.2.
    raise NotImplementedError("get_context7_tools lands in slice F11.2")


def reset_client_for_tests() -> None:
    """Clear the module-level singleton. Tests use this to start clean."""
    global _CLIENT
    _CLIENT = None
