"""Tests for ``ProposalGenerator.regenerate()`` (HU11 REQ-PA-HU11-1..3).

The method bypasses F08's hard ``lifecycle != "proposed"`` 409 at the
generator layer, computing ``iteration = max+1`` regardless of the prior
row's lifecycle. Reuses the existing ``_persist_proposal_and_log`` cap so
``PROPOSAL_MAX_ITER`` is unchanged.

Tests run without the database: every external dependency is stubbed at
the method level (mirrors the slice-1 contract used by
``tests/api/test_proposals.py``).
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest


def _run(coro):
    return asyncio.run(coro)


def _fake_project():
    """Real-attribute project object — the generator reads ``.name`` and
    ``.description`` as plain strings so a MagicMock would fail string ops."""
    project = MagicMock()
    project.name = "demo"
    project.description = "demo description"
    return project


def test_proposal_generator_has_regenerate_method():
    # REQ-PA-HU11-1: the new method exists and is an async generator.
    from app.core.proposal_generator import ProposalGenerator

    assert hasattr(ProposalGenerator, "regenerate")
    assert callable(ProposalGenerator.regenerate)


def test_regenerate_dispatches_to_load_latest_any_lifecycle(monkeypatch):
    """Lifecycle guard is intentionally NOT applied at the generator."""
    from app.core import proposal_generator as pg_module

    called = {"n": 0}
    calls: list[tuple[int, int]] = []

    def _fake_load(user_id, project_id):
        called["n"] += 1
        calls.append((user_id, project_id))
        # Simulate a previously-approved iteration — the generator must
        # NOT raise on lifecycle, so we return the prior content directly.
        return "# Componentes previos\n- API", 2

    monkeypatch.setattr(
        pg_module, "_load_latest_proposal_any_lifecycle", _fake_load
    )

    generator = pg_module.ProposalGenerator(user_id=1, project_id=42)

    # Stub out everything else the generator would touch (RAG, LLM, DB).
    monkeypatch.setattr(
        pg_module,
        "_load_project_and_session",
        lambda user_id, project_id: (_fake_project(), 1),
    )
    monkeypatch.setattr(
        pg_module, "_retrieve_patterns", lambda query, user_id: []
    )
    monkeypatch.setattr(pg_module, "_filter_citations", lambda docs: [])
    monkeypatch.setattr(
        pg_module,
        "build_langchain_model",
        lambda user_id: _FakeModel(),
    )
    monkeypatch.setattr(
        pg_module,
        "_persist_proposal_and_log",
        lambda **kwargs: (101, 7),
    )

    async def _fake_engram(**kwargs):
        return None

    monkeypatch.setattr(pg_module, "_engram_mirror", _fake_engram)

    events = _run(_drain(generator.regenerate(project_id=42, feedback="x")))

    # The new helper was invoked once (so the lifecycle bypass works) and
    # the stream emitted the canonical ``sources → token* → done`` shape.
    assert called["n"] == 1
    assert calls == [(1, 42)]
    names = [name for name, _ in events]
    assert names[0] == "sources"
    assert names[-1] == "done"
    done_payload = events[-1][1]
    # iteration = prior_iteration + 1
    assert done_payload["iteration"] == 3
    assert done_payload["proposal_id"] == 101


def test_regenerate_does_not_change_prior_lifecycle(monkeypatch):
    """REQ-PA-HU11-1.2: regenerating does not mutate the prior row."""
    from app.core import proposal_generator as pg_module

    captured: dict = {}

    def _fake_persist(**kwargs):
        # The contract under test: HU11 does NOT pass ``prior_proposal_id``
        # so the generator doesn't write a duplicate proposal_approvals row.
        captured["kwargs"] = kwargs
        return 201, 8

    monkeypatch.setattr(
        pg_module,
        "_load_project_and_session",
        lambda user_id, project_id: (_fake_project(), 1),
    )
    monkeypatch.setattr(
        pg_module,
        "_load_latest_proposal_any_lifecycle",
        lambda user_id, project_id: ("old", 1),
    )
    monkeypatch.setattr(pg_module, "_retrieve_patterns", lambda q, u: [])
    monkeypatch.setattr(pg_module, "_filter_citations", lambda docs: [])
    monkeypatch.setattr(
        pg_module, "build_langchain_model", lambda u: _FakeModel()
    )
    monkeypatch.setattr(pg_module, "_persist_proposal_and_log", _fake_persist)

    async def _noop(**kwargs):
        return None

    monkeypatch.setattr(pg_module, "_engram_mirror", _noop)

    generator = pg_module.ProposalGenerator(user_id=1, project_id=42)
    _run(_drain(generator.regenerate(project_id=42, feedback="x")))

    # Verify the contract: prior_proposal_id is None so we don't double-write.
    assert captured["kwargs"]["prior_proposal_id"] is None
    assert captured["kwargs"]["prior_content"] is None
    # iteration = prior_iteration + 1
    assert captured["kwargs"]["iteration"] == 2


def test_regenerate_respects_proposal_max_iter_cap(monkeypatch):
    """REQ-PA-HU11-1.3: cap is unchanged (delegated to _persist helper)."""
    from app.core import proposal_generator as pg_module

    def _fake_persist(**kwargs):
        raise pg_module._ProposalDomainError(
            "Has alcanzado el máximo de iteraciones (5)"
        )

    monkeypatch.setattr(
        pg_module,
        "_load_project_and_session",
        lambda user_id, project_id: (_fake_project(), 1),
    )
    monkeypatch.setattr(
        pg_module,
        "_load_latest_proposal_any_lifecycle",
        lambda user_id, project_id: ("x", 5),
    )
    monkeypatch.setattr(pg_module, "_retrieve_patterns", lambda q, u: [])
    monkeypatch.setattr(pg_module, "_filter_citations", lambda docs: [])
    monkeypatch.setattr(
        pg_module, "build_langchain_model", lambda u: _FakeModel()
    )
    monkeypatch.setattr(pg_module, "_persist_proposal_and_log", _fake_persist)

    async def _noop(**kwargs):
        return None

    monkeypatch.setattr(pg_module, "_engram_mirror", _noop)

    generator = pg_module.ProposalGenerator(user_id=1, project_id=42)
    events = _run(_drain(generator.regenerate(project_id=42, feedback="x")))
    names = [name for name, _ in events]
    assert names[-1] == "error"
    assert "máximo" in str(events[-1][1])


def test_regenerate_missing_project_id_yields_error():
    """Generator is robust when no project_id is supplied."""
    from app.core.proposal_generator import ProposalGenerator

    generator = ProposalGenerator(user_id=1)
    events = _run(_drain(generator.regenerate(feedback="x")))
    assert events[0][0] == "error"


def test_regenerate_missing_user_id_yields_error():
    from app.core.proposal_generator import ProposalGenerator

    generator = ProposalGenerator(project_id=1)
    events = _run(_drain(generator.regenerate(project_id=1, feedback="x")))
    assert events[0][0] == "error"


def test_regenerate_empty_feedback_yields_error():
    from app.core.proposal_generator import ProposalGenerator

    generator = ProposalGenerator(user_id=1, project_id=1)
    events = _run(_drain(generator.regenerate(project_id=1, feedback="   ")))
    assert events[0][0] == "error"


# --- helpers ----------------------------------------------------------------


class _FakeModel:
    """Async-iterable that emits a single chunk so the generator's token
    loop fires exactly once. Mirrors the langchain ``astream`` interface."""

    async def astream(self, prompt):
        yield _FakeChunk("## Componentes\n- API\n")


class _FakeChunk:
    def __init__(self, content: str) -> None:
        self.content = content


async def _drain(gen):
    out = []
    async for event, payload in gen:
        out.append((event, payload))
    return out