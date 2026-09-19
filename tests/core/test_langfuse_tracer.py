"""
Tests for app.core.langfuse_tracer (slice F11.3b).

Covers REQ-5 / SCN-6 / SCN-7:
  - Env unset → ``None`` + WARNING captured (caplog)
  - Env set → non-``None`` handler
  - Whitespace-only env vars count as unset
  - SDK construction errors fall back to ``None`` + WARNING
  - The langfuse SDK is wired through the lazy import so the module is
    safe to import when the wheel is missing.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _env_present helper (already covered in slice F11.1 smoke tests; keep one
# regression here so the F11.3b slice owns the contract end-to-end)
# ---------------------------------------------------------------------------


def test_env_present_requires_both_keys(monkeypatch):
    from app.core import langfuse_tracer

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert langfuse_tracer._env_present() is False

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    assert langfuse_tracer._env_present() is False

    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    assert langfuse_tracer._env_present() is True


def test_env_present_strips_whitespace(monkeypatch):
    from app.core import langfuse_tracer

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "   ")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    assert langfuse_tracer._env_present() is False


# ---------------------------------------------------------------------------
# get_langfuse_handler
# ---------------------------------------------------------------------------


def test_get_langfuse_handler_returns_none_when_env_unset(monkeypatch, caplog):
    from app.core import langfuse_tracer

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    with caplog.at_level(logging.WARNING, logger="app.core.langfuse_tracer"):
        result = langfuse_tracer.get_langfuse_handler()

    assert result is None
    assert any("Langfuse env vars missing" in r.message for r in caplog.records)


def test_get_langfuse_handler_emits_warning_at_logger(caplog):
    """The WARNING must come from the module logger, not root."""
    import os

    from app.core import langfuse_tracer

    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    os.environ.pop("LANGFUSE_SECRET_KEY", None)

    with caplog.at_level(logging.WARNING, logger="app.core.langfuse_tracer"):
        langfuse_tracer.get_langfuse_handler()

    module_records = [r for r in caplog.records if r.name == "app.core.langfuse_tracer"]
    assert any(r.levelno == logging.WARNING for r in module_records)


def test_get_langfuse_handler_returns_handler_when_env_set(monkeypatch):
    from app.core import langfuse_tracer

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk_test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk_test")

    fake_handler = MagicMock(name="CallbackHandler")

    # Patch the module-level CallbackHandler alias so the test does not need a
    # real Langfuse account / network reachability.
    with patch.object(langfuse_tracer, "CallbackHandler", MagicMock(return_value=fake_handler)):
        result = langfuse_tracer.get_langfuse_handler()

    assert result is fake_handler


def test_get_langfuse_handler_returns_none_when_callback_handler_missing(monkeypatch, caplog):
    """If the langfuse wheel isn't installed, return None + WARNING."""
    from app.core import langfuse_tracer

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk_test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk_test")

    with patch.object(langfuse_tracer, "CallbackHandler", None), \
         caplog.at_level(logging.WARNING, logger="app.core.langfuse_tracer"):
        result = langfuse_tracer.get_langfuse_handler()

    assert result is None
    assert any("Langfuse is not installed" in r.message for r in caplog.records)


def test_get_langfuse_handler_swallows_sdk_construction_error(monkeypatch, caplog):
    """Construction failures fall back to ``None`` + WARNING (REQ-5)."""
    from app.core import langfuse_tracer

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk_test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk_test")

    with patch.object(
        langfuse_tracer, "CallbackHandler",
        MagicMock(side_effect=RuntimeError("simulated network outage")),
    ), caplog.at_level(logging.WARNING, logger="app.core.langfuse_tracer"):
        result = langfuse_tracer.get_langfuse_handler()

    assert result is None
    assert any("CallbackHandler construction failed" in r.message for r in caplog.records)


def test_get_langfuse_handler_does_not_log_when_handler_built(monkeypatch, caplog):
    """No WARNING is emitted on the happy path."""
    import logging

    from app.core import langfuse_tracer

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk_test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk_test")

    fake_handler = MagicMock(name="CallbackHandler")
    with patch.object(langfuse_tracer, "CallbackHandler", MagicMock(return_value=fake_handler)), \
         caplog.at_level(logging.WARNING, logger="app.core.langfuse_tracer"):
        result = langfuse_tracer.get_langfuse_handler()

    assert result is fake_handler
    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning_records == []


# ---------------------------------------------------------------------------
# Module is import-safe when the langfuse wheel is missing (F11.1 contract)
# ---------------------------------------------------------------------------


def test_callback_handler_alias_is_a_class_or_none():
    """The module-level ``CallbackHandler`` is either the real class or ``None``.

    Either value lets the module import succeed; both are exercised by tests.
    """
    from app.core import langfuse_tracer

    # The wheel is installed in this environment, so the alias should be the
    # real class. The contract is "non-empty" (i.e. something callable or None).
    assert langfuse_tracer.CallbackHandler is None or callable(
        langfuse_tracer.CallbackHandler
    )
