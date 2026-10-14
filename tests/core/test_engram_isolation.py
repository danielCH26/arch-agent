"""Regression tests for Engram mirror per-user isolation (PR #104 review #5).

The PR #104 rework of the F12 message store dropped the per-user
``project_key`` scoping: every mirror now targets ``ENGRAM_PROJECT``
(or ``\"arch-agent\"`` as fallback) regardless of ``user_id``. That
re-enables cross-user bleed via Engram's retrieval API (search and
``get_context`` both scope by ``project``). It also flattened the
``topic_key`` and ``observation_type`` to generic values so the new
observations don't link up with the historical chat-message topic.

These tests pin the corrected behaviour:

  * Two mirrors for two different ``user_id`` values must target
    DIFFERENT ``project`` keys in the Engram client call.
  * The ``observation_type`` for a chat message mirror must be
    ``\"chat_message\"`` so retrieval queries can filter by it; older
    rows used ``\"manual\"`` and became invisible to chat-only searches.
  * The ``title`` carries a deterministic topic key that includes the
    ``user_id`` and ``project_id`` so observation_topic upserts chain
    correctly.

We mock ``app.core.engram_client.EngramClient`` so the tests do not
need a live Engram instance.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.message_store import engram_mirror


def _make_message(*, message_id: int | None = 1, content: str = "hola"):
    """Build a minimal stand-in for a Message ORM row."""
    msg = MagicMock()
    msg.id = message_id
    msg.role = "user"
    msg.content = content
    msg.engram_observation_id = None
    return msg


class TestEngramIsolation:
    def test_two_users_target_distinct_projects(self, monkeypatch):
        monkeypatch.delenv("ENGRAM_PROJECT", raising=False)

        captured: list[dict] = []

        def fake_save(self, **kwargs):
            captured.append(kwargs)
            return {"id": 1}

        with patch("app.core.engram_client.EngramClient.save", new=fake_save), \
             patch("app.core.engram_client.EngramClient.create_session",
                   return_value=None):
            engram_mirror(_make_message(), user_id=1, project_id=10)
            engram_mirror(_make_message(message_id=2), user_id=2, project_id=20)

        assert len(captured) == 2
        # Per-user project scoping: each user_id resolves to a different
        # ``project`` string. The previous rework used a single
        # ``ENGRAM_PROJECT`` env for everyone, which re-enabled
        # cross-user bleed via Engram retrieval.
        project_a = captured[0]["project"]
        project_b = captured[1]["project"]
        assert project_a != project_b, (
            f"Expected per-user project scoping; both mirrors went to "
            f"{project_a!r}. Captured: {captured}"
        )
        assert "1" in project_a
        assert "2" in project_b

    def test_observation_type_is_chat_message(self, monkeypatch):
        """The PR #104 rework flattened ``observation_type`` to
        ``\"manual\"``; chat-history retrieval queries filter by
        ``chat_message`` and would not see the new mirrors."""
        monkeypatch.delenv("ENGRAM_PROJECT", raising=False)

        captured: list[dict] = []

        def fake_save(self, **kwargs):
            captured.append(kwargs)
            return {"id": 1}

        with patch("app.core.engram_client.EngramClient.save", new=fake_save), \
             patch("app.core.engram_client.EngramClient.create_session",
                   return_value=None):
            engram_mirror(_make_message(), user_id=1, project_id=10)

        assert captured, "expected engram_mirror to call save()"
        assert captured[0]["observation_type"] == "chat_message", (
            f"Expected observation_type='chat_message' so retrieval can "
            f"filter by chat history; got {captured[0]['observation_type']!r}"
        )

    def test_title_carries_deterministic_topic_key(self, monkeypatch):
        """The title is the topic key for Engram's observation_topic
        upsert; flatten the role + user + project + message id so the
        observation chains correctly across retries."""
        monkeypatch.delenv("ENGRAM_PROJECT", raising=False)

        captured: list[dict] = []

        def fake_save(self, **kwargs):
            captured.append(kwargs)
            return {"id": 1}

        with patch("app.core.engram_client.EngramClient.save", new=fake_save), \
             patch("app.core.engram_client.EngramClient.create_session",
                   return_value=None):
            engram_mirror(_make_message(message_id=42), user_id=1, project_id=10)

        title = captured[0]["title"]
        # user + project + role + id encoded so the topic key is unique
        # per (user, project, turn) and idempotent across retries.
        for piece in ("user", "1", "10", "42"):
            assert piece in title, (
                f"title {title!r} missing required topic-key piece {piece!r}"
            )

    def test_engram_error_does_not_propagate(self, monkeypatch):
        """REQ-6 / ADR-011: best-effort. A down Engram must not crash
        the chat request — log WARNING and return."""
        monkeypatch.delenv("ENGRAM_PROJECT", raising=False)

        from app.core.engram_client import EngramError

        def fake_save(self, **kwargs):
            raise EngramError("Engram is down")

        with patch("app.core.engram_client.EngramClient.save", new=fake_save), \
             patch("app.core.engram_client.EngramClient.create_session",
                   return_value=None):
            # MUST NOT raise.
            engram_mirror(_make_message(), user_id=1, project_id=10)