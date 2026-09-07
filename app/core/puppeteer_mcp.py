"""
Puppeteer MCP client wrapper (F13, issue #17, ADR-013).

Provides a process-wide singleton ``MultiServerMCPClient`` that connects to
the ``puppeteer-mcp`` sidecar over ``streamable_http`` (REQ-PMCP-1,
REQ-PMCP-2). The transport is intentionally NOT stdio: a sidecar keeps the
Chromium weight out of the Python image and exposes the MCP HTTP contract
that the rest of the F-changes (Filesystem, Fetch, Web Search) will reuse.

Module is lazy at the import boundary so it can be imported in environments
where ``langchain_mcp_adapters`` is not yet installed. The tool allow-list
filter and the per-user rate limit are layered in by separate tasks
(T13.2.2 + T13.2.3) — this scaffold ships the transport only.
"""
from __future__ import annotations

import logging
import os
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Default URL matches docker-compose.yml. Tests should monkeypatch the env
# var BEFORE ``build_puppeteer_client`` is invoked so the singleton picks
# up the test URL.
_DEFAULT_URL: str = "http://puppeteer-mcp:8931/mcp"

# REQ-PMCP-1: per-call budget honored via ``asyncio.wait_for`` inside
# ``get_puppeteer_tools`` (the parent callsite wraps it). 30s here is the
# adapter-level ceiling; the wait_for budget is the tighter number.
_TIMEOUT_SECONDS: float = 30.0

# Process-wide singleton; lazy-initialized by ``build_puppeteer_client``.
_CLIENT: Any = None

# Transport literal expected by langchain-mcp-adapters 0.3.2.
_TRANSPORT: str = "streamable_http"

# Server name used to key into the ``MultiServerMCPClient`` connections
# dict. Must match the URL the docker-compose service advertises.
_SERVER_NAME: str = "puppeteer"


class PuppeteerUnavailable(Exception):
    """Raised when the Puppeteer MCP endpoint cannot be reached or returns
    an unrecoverable HTTP error.

    The ``reason`` attribute is one of:
      * ``puppeteer_timeout``       - ``asyncio.TimeoutError`` after 15s
      * ``puppeteer_unavailable``   - DNS / connection refused / generic
      * ``puppeteer_rate_limited``  - per-user rate limit exceeded (REQ-PMCP-4)
      * ``puppeteer_byte_cap``      - render response > PUPPETEER_MAX_RENDER_BYTES
    """

    def __init__(self, message: str, reason: str = "puppeteer_unavailable") -> None:
        super().__init__(message)
        self.reason = reason


def _resolve_url() -> str:
    """Return the MCP URL, reading ``PUPPETEER_MCP_URL`` at call-time so
    # monkeypatched env vars are honored without re-importing the module.
    """
    url = (os.getenv("PUPPETEER_MCP_URL") or "").strip()
    return url or _DEFAULT_URL


def _build_config() -> dict[str, Any]:
    """Translate the public config dict into the adapter's expected shape.

    ``MultiServerMCPClient`` expects a ``connections`` dict keyed by server
    name with each value carrying ``transport`` + ``url`` + ``timeout``.
    """
    return {
        _SERVER_NAME: {
            "transport": _TRANSPORT,
            "url": _resolve_url(),
            "timeout": _TIMEOUT_SECONDS,
        }
    }


def _get_client_class() -> Any:
    """Lazy import so collection never breaks when the wheel is absent.

    Direct ``ImportError`` re-raises are surfaced at the call-site boundary
    (``build_puppeteer_client``) so callers that want to test import-time
    behavior can still observe them.
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError as e:
        raise PuppeteerUnavailable(
            "langchain_mcp_adapters is not installed; cannot build Puppeteer client.",
            reason="puppeteer_unavailable",
        ) from e
    return MultiServerMCPClient


def build_puppeteer_client() -> Any:
    """Build (or return the cached) ``MultiServerMCPClient`` for Puppeteer.

    Reads ``PUPPETEER_MCP_URL`` at *call* time (not at import time) so that
    tests can monkeypatch the env var between calls without re-importing.

    Returns:
        ``MultiServerMCPClient`` configured for the puppeteer-mcp sidecar
        over the modern streamable_http transport.
    """
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    try:
        MultiServerMCPClient = _get_client_class()
    except PuppeteerUnavailable:
        raise  # already typed
    except ImportError as e:
        # Defense in depth: if a transitive import raises after the
        # ``_get_client_class`` try/except, surface it as a typed failure.
        raise PuppeteerUnavailable(
            f"langchain_mcp_adapters import failed: {e}",
            reason="puppeteer_unavailable",
        ) from e
    connections = _build_config()

    try:
        client = MultiServerMCPClient(connections=connections)
    except Exception as e:
        # Construction-time failures (bad config, network unreachable at
        # startup, etc.) are still typed so the agent layer can degrade.
        _LOGGER.warning("Puppeteer client construction failed: %s", e)
        raise PuppeteerUnavailable(
            f"Failed to build Puppeteer MCP client: {e}",
            reason="puppeteer_unavailable",
        ) from e

    _CLIENT = client
    _LOGGER.info(
        "Puppeteer MCP client built (url=%s, transport=%s, timeout=%.1fs)",
        _resolve_url(),
        _TRANSPORT,
        _TIMEOUT_SECONDS,
    )
    return _CLIENT


def reset_client_for_tests() -> None:
    """Clear the module-level singleton. Tests use this to start clean."""
    global _CLIENT
    _CLIENT = None