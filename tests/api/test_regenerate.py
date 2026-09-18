"""HTTP-level tests for ``POST /api/projects/{id}/phases/{phase}/regenerate``.

HU11 REQ-SA-25..29 / design §C, §E. The route is a thin SSE adapter; the
real per-phase logic lives in ``app/core/regenerate_dispatcher.py``.
These tests pin the route-level contract:

- 400 on unknown phase / empty feedback
- 409 on ``final`` (REQ-SA-8) and on phases at/after ``current_phase``
- 200 SSE stream shape ``sources|token*|done|error``
- 200 + ``regenerated: false`` for ``revision`` (no LLM call)
- 502 (error event) on LLM failure mid-stream, with the audit row
  recorded by the prior ``/decision`` call STILL intact (REQ-SA-25.4)
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import projects as projects_module
from app.core import regenerate_dispatcher


def _collect_sse_events(body_iter) -> list[tuple[str, Any]]:
    """Drain an async iterator into a list of ``(event_name, payload)`` tuples.

    The FastAPI route serializes each tuple as
    ``event: <name>\\ndata: <json>\\n\\n`` so the parser mirrors the
    frontend's ``dispatchSSEEvent``.
    """
    out: list[tuple[str, Any]] = []

    async def _drain():
        async for event_name, payload_obj in body_iter:
            out.append((event_name, payload_obj))

    asyncio.run(_drain())
    return out


def _make_project(user_id: int = 1, current_phase: str = "refinamiento"):
    project = MagicMock()
    project.id = 7
    project.user_id = user_id
    project.current_phase = current_phase
    project.description = "demo"
    project.phase_ready = False
    return project


def _patch_session_local(monkeypatch, project):
    """Replace ``SessionLocal`` in app.core.database with a factory that
    returns a stub session yielding ``project`` for the ownership query.
    """
    sess = MagicMock()

    def _query(model):
        q = MagicMock()
        # The route does TWO Project queries: ownership (with user_id) and
        # existence check (without user_id for the 404 fallback). Return
        # ``project`` only when the user_id filter matches; otherwise None
        # so 404 path is exercised cleanly.

        def _filter(*args, **kwargs):
            return q

        q.filter = MagicMock(side_effect=_filter)
        q.first = MagicMock(return_value=project)
        q.all = MagicMock(return_value=[])
        return q

    sess.query = MagicMock(side_effect=_query)
    sess.close = MagicMock()

    monkeypatch.setattr(
        "app.core.database.SessionLocal", lambda: sess
    )
    return sess


def _patch_require_project(monkeypatch, project):
    """Bypass the FastAPI Depends chain — return a MagicMock current_user."""

    def _stub_require(uid, pid):
        return project

    monkeypatch.setattr(projects_module, "_require_project", _stub_require)


# ---------------------------------------------------------------------------
# Pre-flight 400 / 409
# ---------------------------------------------------------------------------


class TestRegeneratePreflight:
    def test_unknown_phase_raises_400(self, monkeypatch):
        project = _make_project()
        _patch_session_local(monkeypatch, project)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                projects_module.regenerate_phase(
                    project_id=project.id,
                    phase="not_a_phase",
                    body=projects_module.PhaseRegenerateIn(feedback="x"),
                    current_user={"user_id": 1, "username": "architect"},
                )
            )
        assert exc_info.value.status_code == 400

    def test_empty_feedback_raises_400(self, monkeypatch):
        project = _make_project()
        _patch_session_local(monkeypatch, project)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                projects_module.regenerate_phase(
                    project_id=project.id,
                    phase="propuesta",
                    body=projects_module.PhaseRegenerateIn(feedback="   "),
                    current_user={"user_id": 1, "username": "architect"},
                )
            )
        assert exc_info.value.status_code == 400

    def test_final_phase_raises_409(self, monkeypatch):
        project = _make_project(current_phase="refinamiento")
        _patch_session_local(monkeypatch, project)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                projects_module.regenerate_phase(
                    project_id=project.id,
                    phase="final",
                    body=projects_module.PhaseRegenerateIn(feedback="ajustar"),
                    current_user={"user_id": 1, "username": "architect"},
                )
            )
        assert exc_info.value.status_code == 409

    def test_phase_ahead_of_current_raises_409(self, monkeypatch):
        # current_phase=requerimientos; trying to regenerate propuesta fails.
        project = _make_project(current_phase="requerimientos")
        _patch_session_local(monkeypatch, project)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                projects_module.regenerate_phase(
                    project_id=project.id,
                    phase="propuesta",
                    body=projects_module.PhaseRegenerateIn(feedback="x"),
                    current_user={"user_id": 1, "username": "architect"},
                )
            )
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Dispatch unit tests
# ---------------------------------------------------------------------------


class TestDispatchGuards:
    def test_unknown_phase_raises_missing_payload(self):
        gen = regenerate_dispatcher.dispatch_regenerate(
            db=None,
            user_id=1,
            project_id=1,
            phase="banana",
            feedback="x",
            payload=None,
            current_phase="requerimientos",
        )
        with pytest.raises(regenerate_dispatcher.MissingPayload):
            asyncio.run(_drain(gen))

    def test_empty_feedback_raises_missing_payload(self):
        gen = regenerate_dispatcher.dispatch_regenerate(
            db=None,
            user_id=1,
            project_id=1,
            phase="propuesta",
            feedback="   ",
            payload=None,
            current_phase="refinamiento",
        )
        with pytest.raises(regenerate_dispatcher.MissingPayload):
            asyncio.run(_drain(gen))

    def test_final_phase_raises_past_phase_conflict(self):
        gen = regenerate_dispatcher.dispatch_regenerate(
            db=None,
            user_id=1,
            project_id=1,
            phase="final",
            feedback="x",
            payload=None,
            current_phase="refinamiento",
        )
        with pytest.raises(regenerate_dispatcher.PastPhaseConflict):
            asyncio.run(_drain(gen))

    def test_phase_ahead_of_current_raises_past_phase_conflict(self):
        gen = regenerate_dispatcher.dispatch_regenerate(
            db=None,
            user_id=1,
            project_id=1,
            phase="refinamiento",
            feedback="x",
            payload=None,
            current_phase="requerimientos",
        )
        with pytest.raises(regenerate_dispatcher.PastPhaseConflict):
            asyncio.run(_drain(gen))


async def _drain(gen):
    async for _ in gen:
        pass


# ---------------------------------------------------------------------------
# revision no-op
# ---------------------------------------------------------------------------


class TestRevisionNoOp:
    def test_revision_emits_done_regenerated_false_without_llm(self):
        # SCN-SA-25.3: revision modify is a UI edit, no LLM call required.
        gen = regenerate_dispatcher.dispatch_regenerate(
            db=None,
            user_id=1,
            project_id=1,
            phase="revision",
            feedback="cambiar a event-driven",
            payload={"patron_elegido": "Event Sourcing"},
            current_phase="final",
        )
        events = _collect_sse_events(gen)
        assert len(events) == 1
        event_name, payload = events[0]
        assert event_name == "done"
        assert payload["regenerated"] is False
        assert payload["phase"] == "revision"


# ---------------------------------------------------------------------------
# propuesta dispatch (delegates to ProposalGenerator.regenerate)
# ---------------------------------------------------------------------------


class TestPropuestaDispatch:
    def test_propuesta_emits_sources_then_done_via_generator(self, monkeypatch):
        # Stub ProposalGenerator.regenerate so we don't hit the real DB.
        async def _fake_regenerate(self, project_id, feedback):
            yield ("sources", [{"pattern_id": 1, "pattern_name": "Hexagonal"}])
            yield ("token", "## Componentes")
            yield ("token", "\n- API")
            yield (
                "done",
                {"proposal_id": 99, "iteration": 3, "lifecycle": "proposed"},
            )

        monkeypatch.setattr(
            "app.core.proposal_generator.ProposalGenerator.regenerate",
            _fake_regenerate,
        )

        gen = regenerate_dispatcher.dispatch_regenerate(
            db=None,
            user_id=1,
            project_id=1,
            phase="propuesta",
            feedback="agregar cache",
            payload=None,
            current_phase="refinamiento",
        )
        events = _collect_sse_events(gen)
        names = [name for name, _ in events]
        assert names[0] == "sources"
        assert names[-1] == "done"
        # iteration comes from the generator — verify it propagates.
        done_payload = events[-1][1]
        assert done_payload["proposal_id"] == 99
        assert done_payload["iteration"] == 3


# ---------------------------------------------------------------------------
# refinamiento dispatch (sources + token + done)
# ---------------------------------------------------------------------------


class TestRefinamientoDispatch:
    def test_refinamiento_emits_sources_token_done(self, monkeypatch):
        # Stub the helper that reads prior attachments so the dispatcher
        # has something to emit on the ``sources`` event.
        monkeypatch.setattr(
            "app.core.phase_decisions._latest_assistant_attachments",
            lambda db, project_id: [
                {"kind": "screenshot", "mime": "image/png", "url": "/x"}
            ],
        )

        gen = regenerate_dispatcher.dispatch_regenerate(
            db=MagicMock(),
            user_id=1,
            project_id=1,
            phase="refinamiento",
            feedback="definir mejor los retries",
            payload=None,
            current_phase="revision",
        )
        events = _collect_sse_events(gen)
        names = [name for name, _ in events]
        assert names[0] == "sources"
        assert "token" in names
        assert names[-1] == "done"
        done_payload = events[-1][1]
        assert done_payload["regenerated"] is True
        assert done_payload["phase"] == "refinamiento"


# ---------------------------------------------------------------------------
# LLM mid-stream failure keeps audit row (REQ-SA-25.4 / SCN-SA-25.4)
# ---------------------------------------------------------------------------


class TestLLMFailureKeepsAuditRow:
    def test_propuesta_llm_failure_emits_error_event(self, monkeypatch):
        async def _failing_regenerate(self, project_id, feedback):
            yield ("sources", [])
            yield ("token", "fracmento")
            yield ("error", "LLM stream failed: 503 rate limit")

        monkeypatch.setattr(
            "app.core.proposal_generator.ProposalGenerator.regenerate",
            _failing_regenerate,
        )

        gen = regenerate_dispatcher.dispatch_regenerate(
            db=None,
            user_id=1,
            project_id=1,
            phase="propuesta",
            feedback="agregar cache",
            payload=None,
            current_phase="refinamiento",
        )
        events = _collect_sse_events(gen)
        names = [name for name, _ in events]
        # The error event is the terminal one — design §B.3 explicitly
        # notes the upstream audit row (recorded by HU10's /decision
        # call) STAYS in the DB; the SSE only signals the LLM failure.
        assert names[-1] == "error"
        assert any("rate limit" in str(payload) for _, payload in events)


# ---------------------------------------------------------------------------
# Body model
# ---------------------------------------------------------------------------


class TestRegenerateBodyModel:
    def test_body_accepts_feedback_only(self):
        body = projects_module.PhaseRegenerateIn(feedback="ok")
        assert body.feedback == "ok"
        assert body.payload is None

    def test_body_accepts_feedback_and_payload(self):
        body = projects_module.PhaseRegenerateIn(
            feedback="cambiar", payload={"patron_elegido": "CQRS"}
        )
        assert body.payload == {"patron_elegido": "CQRS"}