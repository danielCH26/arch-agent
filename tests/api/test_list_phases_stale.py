"""Tests for the HU11 (REQ-SA-26) ``stale`` marker on ``GET /phases``.

The marker is computed on read via a pure Python loop over already-fetched
``approval_rows``. These tests exercise the ``compute_stale`` helper directly
(algorithm contract) AND the route's serialization (Pydantic output shape).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.api import projects as projects_module
from app.core.phase_decisions import AVAILABLE_PHASES


def _row(phase: str, decision: str, seconds_ago: float) -> Any:
    """Build a minimal approval-row stand-in (object with phase / decision /
    created_at attributes). Mirrors the SQLAlchemy model API used by
    ``compute_stale``.
    """
    obj = MagicMock()
    obj.phase = phase
    obj.decision = decision
    obj.created_at = datetime.utcnow() - timedelta(seconds=seconds_ago)
    return obj


# ---------------------------------------------------------------------------
# Algorithm unit tests
# ---------------------------------------------------------------------------


class TestComputeStaleAlgorithm:
    """REQ-SA-26 / SCN-SA-26.1..3."""

    def test_no_rows_returns_all_false(self):
        stale = projects_module.compute_stale([], current_phase="final")
        for phase in AVAILABLE_PHASES:
            assert stale[phase] is False

    def test_current_and_future_phases_are_never_stale(self):
        # current_phase=requerimientos → no past phases, all False.
        rows = [_row("requerimientos", "modified", seconds_ago=5)]
        stale = projects_module.compute_stale(rows, current_phase="requerimientos")
        for phase in AVAILABLE_PHASES:
            assert stale[phase] is False

    def test_modify_on_past_propuesta_flags_refinamiento_and_revision_stale(self):
        # SCN-SA-26.1: current_phase=final, propuesta modified AFTER the
        # downstream approve rows. refinamiento + revision must be stale.
        # propuesta must NOT be stale (it's the modified phase itself).
        now = datetime.utcnow()
        rows = [
            # aprobados viejos
            _row("requerimientos", "approved", seconds_ago=1000),
            _row("propuesta", "approved", seconds_ago=900),
            _row("refinamiento", "approved", seconds_ago=800),
            _row("revision", "approved", seconds_ago=700),
            _row("final", "approved", seconds_ago=600),
            # HU11 modify sobre propuesta, MÁS RECIENTE que los approves downstream
            MagicMock(
                phase="propuesta",
                decision="modified",
                created_at=datetime.utcnow() - timedelta(seconds=10),
            ),
        ]
        stale = projects_module.compute_stale(rows, current_phase="final")
        assert stale["requerimientos"] is False  # never modified
        assert stale["propuesta"] is False  # it's the modified phase itself
        assert stale["refinamiento"] is True  # modify > their approve
        assert stale["revision"] is True  # modify > their approve
        assert stale["final"] is False  # current phase, never stale

    def test_modify_older_than_downstream_approve_does_not_stale(self):
        # If the modify is OLDER than the downstream approves, the downstream
        # approve is more recent → not stale.
        rows = [
            _row("propuesta", "approved", seconds_ago=1000),
            _row("propuesta", "modified", seconds_ago=900),  # older than refinement approve
            _row("refinamiento", "approved", seconds_ago=500),
            _row("revision", "approved", seconds_ago=400),
            _row("final", "approved", seconds_ago=300),
        ]
        stale = projects_module.compute_stale(rows, current_phase="final")
        assert stale["propuesta"] is False
        assert stale["refinamiento"] is False  # modify older than approve
        assert stale["revision"] is False  # modify older than approve

    def test_two_modifies_idempotent(self):
        # SCN-SA-26.2: two modifies on the same past phase set stale once.
        # Boolean, not count — second modify doesn't double-flip.
        rows = [
            _row("requerimientos", "approved", seconds_ago=1000),
            _row("propuesta", "approved", seconds_ago=900),
            _row("propuesta", "modified", seconds_ago=500),  # first modify
            _row("propuesta", "modified", seconds_ago=100),  # second modify
            _row("refinamiento", "approved", seconds_ago=800),
            _row("revision", "approved", seconds_ago=700),
            _row("final", "approved", seconds_ago=600),
        ]
        stale = projects_module.compute_stale(rows, current_phase="final")
        # The marker is True (boolean), not "count of modifies".
        assert stale["propuesta"] is False  # itself, not stale
        assert stale["refinamiento"] is True
        assert stale["revision"] is True

    def test_re_approve_after_modify_clears_stale(self):
        # SCN-SA-26.3: when the user re-approves the modified upstream
        # phase, the new approve row is the newest on that phase. The
        # algorithm picks the latest approve of any downstream; if no
        # downstream was approved AFTER the new approve, stale clears.
        rows = [
            _row("propuesta", "approved", seconds_ago=2000),  # old approve
            _row("propuesta", "modified", seconds_ago=1500),  # old modify
            _row("refinamiento", "approved", seconds_ago=800),
            _row("revision", "approved", seconds_ago=700),
            _row("final", "approved", seconds_ago=600),
            # NEW approve on propuesta (after the user re-approved it):
            _row("propuesta", "approved", seconds_ago=50),
        ]
        stale = projects_module.compute_stale(rows, current_phase="final")
        assert stale["propuesta"] is False
        assert stale["refinamiento"] is False  # new propuesta approve is newer
        assert stale["revision"] is False  # new propuesta approve is newer

    def test_unknown_current_phase_returns_all_false(self):
        # Defensive: an unknown / corrupted current_phase never marks stale.
        stale = projects_module.compute_stale(
            [_row("propuesta", "modified", seconds_ago=1)],
            current_phase="not_a_phase",
        )
        for phase in AVAILABLE_PHASES:
            assert stale[phase] is False


# ---------------------------------------------------------------------------
# Route serialization (PhaseStatusItem.stale default + value)
# ---------------------------------------------------------------------------


class TestListPhasesStaleWire:
    def test_phase_status_item_default_stale_is_false(self):
        item = projects_module.PhaseStatusItem(
            name="requerimientos",
            label="Requerimientos",
            status="active",
            ready=True,
            current_decision=None,
        )
        assert item.stale is False

    def test_phase_status_item_accepts_stale_true(self):
        item = projects_module.PhaseStatusItem(
            name="refinamiento",
            label="Refinamiento",
            status="approved",
            ready=False,
            current_decision=None,
            stale=True,
        )
        assert item.stale is True

    def test_compute_stale_is_module_level_helper(self):
        # Pure-function test: the algorithm must be importable from the
        # route module so tests can call it directly without spinning up
        # the full FastAPI app.
        assert callable(projects_module.compute_stale)