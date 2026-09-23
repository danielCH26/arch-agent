"""Tests for the Langfuse tracer module (F14).

Cover the ``_env_present()`` helper, the ``get_langfuse_handler()`` factory
(both branches: configured and unconfigured), and the ``flush()`` helper
used by ``chat.py``/``elicitation.py`` to export a trace right away instead
of waiting for the SDK's background export cycle.
"""

from __future__ import annotations

import importlib


def test_module_imports():
    mod = importlib.import_module("app.core.langfuse_tracer")
    assert mod is not None


def test_env_present_helper_both_set(monkeypatch):
    from app.core import langfuse_tracer

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk_test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk_test")
    assert langfuse_tracer._env_present() is True


def test_env_present_helper_unset(monkeypatch):
    from app.core import langfuse_tracer

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert langfuse_tracer._env_present() is False


def test_env_present_helper_whitespace(monkeypatch):
    """Whitespace-only env vars count as unset (REQ-5)."""
    from app.core import langfuse_tracer

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "   ")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk_test")
    assert langfuse_tracer._env_present() is False


def test_get_langfuse_handler_returns_none_without_env(monkeypatch):
    """When Langfuse env vars are not set, the factory returns ``None`` --
    the app runs untraced instead of crashing."""
    from app.core import langfuse_tracer

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert langfuse_tracer.get_langfuse_handler() is None


def test_get_langfuse_handler_returns_handler_with_env(monkeypatch):
    """With both Langfuse env vars set, the factory returns a configured
    ``CallbackHandler`` instance (not ``None``)."""
    from app.core import langfuse_tracer

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk_test_1234567890")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk_test_1234567890")
    handler = langfuse_tracer.get_langfuse_handler()
    assert handler is not None


def test_flush_noop_when_callbackhandler_none(monkeypatch):
    """No SDK / import failed -> flush() is a silent no-op, never raises."""
    from app.core import langfuse_tracer

    monkeypatch.setattr(langfuse_tracer, "CallbackHandler", None)
    langfuse_tracer.flush()  # must not raise


def test_flush_calls_get_client_flush(monkeypatch):
    """flush() reaches the SDK's get_client().flush() -- this is what
    chat.py/elicitation.py rely on to export a trace immediately instead of
    waiting for the SDK's background export cycle (regression: elicitation
    used to skip this call entirely, see PR #79 review)."""
    from app.core import langfuse_tracer

    monkeypatch.setattr(langfuse_tracer, "CallbackHandler", object())

    flushed = {"called": False}

    class FakeClient:
        def flush(self):
            flushed["called"] = True

    import langfuse as langfuse_module
    monkeypatch.setattr(langfuse_module, "get_client", lambda: FakeClient())

    langfuse_tracer.flush()
    assert flushed["called"] is True


def test_flush_swallows_export_errors(monkeypatch):
    """A network/export failure during flush() must never bubble up -- a
    Langfuse outage should not turn into a 500 for the user."""
    from app.core import langfuse_tracer

    monkeypatch.setattr(langfuse_tracer, "CallbackHandler", object())

    class FailingClient:
        def flush(self):
            raise ConnectionError("langfuse-web unreachable")

    import langfuse as langfuse_module
    monkeypatch.setattr(langfuse_module, "get_client", lambda: FailingClient())

    langfuse_tracer.flush()  # must not raise
