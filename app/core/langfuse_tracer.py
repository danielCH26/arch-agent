"""
Langfuse tracing factory.

``get_langfuse_handler()`` returns a configured ``CallbackHandler`` when both
``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` are present in the
environment, otherwise ``None``. The free-tier default is untraced (no
credentials, no Langfuse coupling).

The ``langfuse`` import is guarded so the module is import-safe when the
``langfuse`` wheel is not installed in the current environment.

Issue: #13 - [F11] Context7 MCP integration.
ADR: docs/adr/010-context7-agent-runtime.md.
"""
from __future__ import annotations

import logging
import os
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Imported lazily so the module collects even without the langfuse wheel.
# When the import fails, ``CallbackHandler`` is left as ``None`` and
# ``get_langfuse_handler()`` always returns ``None`` after a WARNING log.
CallbackHandler: Any = None
try:
    from langfuse.langchain import CallbackHandler as _CallbackHandler

    CallbackHandler = _CallbackHandler
except Exception:  # ImportError or any constructor-side import failure
    CallbackHandler = None


def _env_present() -> bool:
    """True when both Langfuse keys are non-empty after ``.strip()``."""
    public = (os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip()
    secret = (os.getenv("LANGFUSE_SECRET_KEY") or "").strip()
    return bool(public) and bool(secret)


def _build_handler() -> Any:
    """Construct a ``CallbackHandler`` instance, swallowing SDK failures."""
    if CallbackHandler is None:
        _LOGGER.warning(
            "Langfuse is not installed; agent will run without tracing."
        )
        return None
    try:
        return CallbackHandler()
    except Exception as e:
        # Construction can fail on bad credentials, missing OTLP endpoint,
        # network unreachable at startup, etc. SCN-6 / design.md §15 risk 2.
        _LOGGER.warning(
            "Langfuse CallbackHandler construction failed; agent will run "
            "without tracing. error=%s",
            e,
        )
        return None


def get_langfuse_handler() -> Any:
    """Return a Langfuse ``CallbackHandler`` or ``None``.

    When the env vars are missing or empty (free-tier default), this returns
    ``None`` and emits a WARNING so the misconfiguration is visible in the
    backend log even though the chat flow still works (REQ-5, SCN-6).

    SDK construction errors (bad credentials, missing OTLP endpoint, etc.)
    are swallowed into the same ``None`` + WARNING path so a Langfuse outage
    never breaks the chat response (design.md §9).
    """
    if not _env_present():
        _LOGGER.warning(
            "Langfuse env vars missing; agent will run without tracing."
        )
        return None
    return _build_handler()
