"""Smoke tests for the Langfuse tracer module skeleton.

These tests verify only that the module imports and exposes the expected
public surface and the ``_env_present()`` helper. The real implementation
lands in slice F11.3b.
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
    """F11.3b implementation: when Langfuse env vars are not set, the factory
    returns ``None`` (free-tier default, no Langfuse coupling)."""
    from app.core import langfuse_tracer

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert langfuse_tracer.get_langfuse_handler() is None


def test_get_langfuse_handler_returns_handler_with_env(monkeypatch):
    """F11.3b implementation: with both Langfuse env vars set, the factory
    returns a configured ``CallbackHandler`` instance (not ``None``)."""
    from app.core import langfuse_tracer

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk_test_1234567890")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk_test_1234567890")
    handler = langfuse_tracer.get_langfuse_handler()
    assert handler is not None
