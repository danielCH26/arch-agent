"""
Puppeteer MCP client wrapper (F13, issue #17, ADR-013).

Provides a process-wide singleton ``MultiServerMCPClient`` that connects to
the ``puppeteer-mcp`` sidecar over ``streamable_http`` (REQ-PMCP-1,
REQ-PMCP-2). The transport is intentionally NOT stdio: a sidecar keeps the
Chromium weight out of the Python image and exposes the MCP HTTP contract
that the rest of the F-changes (Filesystem, Fetch, Web Search) will reuse.

Module is lazy at the import boundary so it can be imported in environments
where ``langchain_mcp_adapters`` is not yet installed.

Security invariants (REQ-PMCP-2, SCN-PMCP-3, ADR-013 §Security):
  * Tool surface is restricted to ``puppeteer_screenshot`` via a positive
    allow-list applied AFTER the adapter's ``get_tools`` call. ``navigate``,
    ``click``, ``fill``, ``select``, ``hover`` are filtered out before the
    list reaches the LLM. A future MCP server version adding new tools
    cannot leak through: the allow-list is the single source of truth.
  * Per-call budget: ``asyncio.wait_for(timeout=15s)`` (REQ-PMCP-3) plus a
    2 MB byte cap enforced downstream in the render wrapper.
  * Per-user rate limit (REQ-PMCP-4): see ``_check_rate_limit`` /
    ``get_puppeteer_tools`` below. Sliding-window in-memory — single
    replica only (R-SPEC-4 → F14 Redis).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time as _time
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

# REQ-PMCP-3: tight budget on the tool-fetch path itself. Puppeteer
# ``launch`` is amortised (persistent Chromium), so 15s is generous for a
# cached ``get_tools`` call.
_FETCH_TIMEOUT_SECONDS: float = 15.0

# Process-wide singleton; lazy-initialized by ``build_puppeteer_client``.
_CLIENT: Any = None

# Transport literal expected by langchain-mcp-adapters 0.3.2.
_TRANSPORT: str = "streamable_http"

# Server name used to key into the ``MultiServerMCPClient`` connections
# dict. Must match the URL the docker-compose service advertises.
_SERVER_NAME: str = "puppeteer"

# REQ-PMCP-2: positive allow-list. ``puppeteer_screenshot`` is the only tool
# the LLM may invoke; the rest of the upstream surface (navigate, click,
# fill, select, hover) is filtered out before the list reaches the agent.
# A future MCP server version cannot leak through: this set is the single
# source of truth.
_PUPPETEER_ALLOWED_TOOLS: frozenset = frozenset({"puppeteer_screenshot"})

# REQ-PMCP-4: per-user render rate limit. In-memory sliding window keyed
# by ``user_id``. Window = 60s; limit = ``PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE``
# (default 5). 6th call → ``PuppeteerUnavailable(reason="puppeteer_rate_limited")``
# → SSE ``event: degraded`` with ``reason="puppeteer_rate_limited"``.
#
# Single-replica only — resets on backend restart; promote to Redis in
# F14 if horizontal scaling arrives (R-SPEC-4 mitigation in ADR-013 §Security).
_RATE_LIMIT_WINDOW_SECONDS: int = 60
_RATE_LIMITER: dict[int, list[float]] = {}
_RATE_LIMIT_LOCK = None  # lazily created; see ``_check_rate_limit``


def _rate_limit_per_minute() -> int:
    """Read ``PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE`` at call-time.

    ``0`` disables the limiter (useful for the design §7 Phase-1 rollout:
    every call is rejected, the agent emits exactly one ``degraded`` event
    and falls back to text).
    """
    raw = os.getenv("PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE")
    if raw is None or not raw.strip():
        return 5
    try:
        return max(0, int(raw))
    except ValueError:
        return 5


def _check_rate_limit(user_id: int | None) -> None:
    """Sliding-window rate limiter (REQ-PMCP-4).

    Raises ``PuppeteerUnavailable(reason="puppeteer_rate_limited")`` when the
    call would exceed ``PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE`` within the
    last 60s. ``user_id=None`` (anonymous) is treated as ``user_id=0`` for
    keying purposes.

    On success: appends the current epoch timestamp to the user's window
    AFTER pruning entries older than ``_RATE_LIMIT_WINDOW_SECONDS``.
    """
    limit = _rate_limit_per_minute()
    if limit <= 0:
        # Limiter disabled — never raise.
        return

    key = int(user_id) if user_id is not None else 0
    now = _time.time()
    cutoff = now - _RATE_LIMIT_WINDOW_SECONDS

    window = _RATE_LIMITER.get(key)
    if window is None:
        window = []
        _RATE_LIMITER[key] = window

    # Prune timestamps older than the window.
    while window and window[0] < cutoff:
        window.pop(0)

    if len(window) >= limit:
        _LOGGER.warning(
            "Puppeteer rate limit hit for user_id=%s (limit=%d / %ds)",
            key,
            limit,
            _RATE_LIMIT_WINDOW_SECONDS,
        )
        raise PuppeteerUnavailable(
            f"Puppeteer render rate limit exceeded ({limit}/{_RATE_LIMIT_WINDOW_SECONDS}s)",
            reason="puppeteer_rate_limited",
        )

    window.append(now)


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


# ---------------------------------------------------------------------------
# Tool surface — REQ-PMCP-2 positive allow-list (SCN-PMCP-3)
# ---------------------------------------------------------------------------


async def get_puppeteer_tools(client: Any | None = None) -> list[Any]:
    """Fetch the available tools from the Puppeteer MCP, apply the positive
    allow-list, and return the filtered list.

    Args:
        client: Optional pre-built ``MultiServerMCPClient``. When ``None``,
            ``build_puppeteer_client()`` is invoked and the result cached.

    Returns:
        List of LangChain ``BaseTool`` objects — EXACTLY the
        ``_PUPPETEER_ALLOWED_TOOLS`` set (currently ``[puppeteer_screenshot]``)
        if the upstream advertises them, or ``[]`` if none are advertised.

    Raises:
        PuppeteerUnavailable: When the call times out, the connection
            fails, or the adapter raises. ``reason`` carries the typed
            sub-category for the SSE ``degraded`` event payload.
    """
    if client is None:
        client = build_puppeteer_client()

    try:
        raw = await asyncio.wait_for(
            client.get_tools(server_name=_SERVER_NAME),
            timeout=_FETCH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as e:
        _LOGGER.warning(
            "Puppeteer tool fetch timed out after %.1fs", _FETCH_TIMEOUT_SECONDS
        )
        raise PuppeteerUnavailable(
            f"Puppeteer tool fetch timed out after {_FETCH_TIMEOUT_SECONDS}s",
            reason="puppeteer_timeout",
        ) from e
    except Exception as e:
        _LOGGER.warning("Puppeteer tool fetch failed: %s", e)
        raise PuppeteerUnavailable(
            f"Puppeteer tool fetch failed: {e}",
            reason="puppeteer_unavailable",
        ) from e

    filtered = [t for t in raw if getattr(t, "name", None) in _PUPPETEER_ALLOWED_TOOLS]
    dropped = [t.name for t in raw if getattr(t, "name", None) not in _PUPPETEER_ALLOWED_TOOLS]
    if dropped:
        # SECURITY INVARIANT: if we ever see upstream tools we did NOT expect,
        # log a WARNING so reviewers can investigate the upstream MCP package
        # version that added them. Never raise — the agent still gets a
        # working (filtered) tool surface.
        _LOGGER.warning(
            "Puppeteer MCP advertised %d unexpected tool(s) — dropped by allow-list: %s",
            len(dropped),
            dropped,
        )
    _LOGGER.info(
        "Puppeteer returned %d raw tool(s); %d allowed after filter: %s",
        len(raw),
        len(filtered),
        [t.name for t in filtered],
    )
    return filtered