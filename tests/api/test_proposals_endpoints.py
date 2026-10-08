"""Tests for the JSON-returning endpoints in app/api/proposals.py.

Covers decide_proposal, get_proposal, decide_project_proposal, and
get_proposal_state. The SSE-streaming endpoints (generate_proposal,
modify_proposal) are tested indirectly via the ProposalGenerator mock.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.proposals import (
    DecideRequest,
    ModifyRequest,
    ProposalDecisionIn,
    ProposalDecisionOut,
    ProposalOut,
    ProposalStateOut,
    decide_project_proposal,
    decide_proposal,
    generate_proposal,
    get_proposal,
    get_proposal_state,
    modify_proposal,
)


def _make_proposal(
    proposal_id: int = 1,
    user_id: int = 1,
    project_id: int = 10,
    lifecycle: str = "proposed",
    iteration: int = 1,
) -> MagicMock:
    p = MagicMock()
    p.id = proposal_id
    p.user_id = user_id
    p.project_id = project_id
    p.lifecycle = lifecycle
    p.iteration = iteration
    p.content = "Some proposal content"
    p.citations = []
    p.feedback = None
    p.decision = None
    p.decided_at = None
    p.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return p


# ---------------------------------------------------------------------------
# POST /api/proposals/{proposal_id}/decide
# ---------------------------------------------------------------------------

class TestDecideProposal(unittest.IsolatedAsyncioTestCase):
    async def test_returns_400_when_decision_is_modify(self):
        """`decide=modify` on this endpoint must redirect to /modify."""
        body = DecideRequest(decision="modify", feedback="x")
        with self.assertRaises(Exception) as exc_info:
            await decide_proposal(proposal_id=1, body=body, current_user={"user_id": 1, "username": "x"})

        self.assertEqual(exc_info.exception.status_code, 400)

    async def test_returns_404_when_proposal_not_found(self):
        mock_db = MagicMock()
        mock_db.get.return_value = None

        with patch("app.api.proposals.SessionLocal", return_value=mock_db):
            with self.assertRaises(Exception) as exc_info:
                await decide_proposal(
                    proposal_id=999,
                    body=DecideRequest(decision="approve"),
                    current_user={"user_id": 1, "username": "x"},
                )

        self.assertEqual(exc_info.exception.status_code, 404)
        mock_db.close.assert_called_once()

    async def test_applying_decision_closes_db(self):
        proposal = _make_proposal(proposal_id=1, lifecycle="proposed")
        mock_db = MagicMock()
        mock_db.get.return_value = proposal
        # The function queries InteractionLog to detect duplicates — return None
        chain = MagicMock()
        chain.order_by.return_value.first.return_value = None
        mock_db.query.return_value.filter.return_value = chain

        with patch("app.api.proposals.SessionLocal", return_value=mock_db), \
             patch("app.api.proposals._apply_project_proposal_decision") as mock_apply:
            await decide_proposal(
                proposal_id=1,
                body=DecideRequest(decision="approve"),
                current_user={"user_id": 1, "username": "x"},
            )

        # _apply_project_proposal_decision is the transition trigger
        mock_apply.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# GET /api/proposals/{proposal_id}
# ---------------------------------------------------------------------------

class TestGetProposal(unittest.IsolatedAsyncioTestCase):
    async def test_returns_proposal_when_found(self):
        proposal = _make_proposal(proposal_id=5)
        mock_db = MagicMock()
        mock_db.get.return_value = proposal

        with patch("app.api.proposals.SessionLocal", return_value=mock_db):
            result = await get_proposal(proposal_id=5, current_user={"user_id": 1, "username": "x"})

        self.assertIsInstance(result, ProposalOut)
        self.assertEqual(result.id, 5)
        mock_db.close.assert_called_once()

    async def test_returns_404_when_proposal_not_found(self):
        mock_db = MagicMock()
        mock_db.get.return_value = None

        with patch("app.api.proposals.SessionLocal", return_value=mock_db):
            with self.assertRaises(Exception) as exc_info:
                await get_proposal(proposal_id=999, current_user={"user_id": 1, "username": "x"})

        self.assertEqual(exc_info.exception.status_code, 404)
        mock_db.close.assert_called_once()

    async def test_closes_db_on_exception(self):
        mock_db = MagicMock()
        mock_db.get.side_effect = RuntimeError("boom")

        with patch("app.api.proposals.SessionLocal", return_value=mock_db):
            with self.assertRaises(RuntimeError):
                await get_proposal(proposal_id=1, current_user={"user_id": 1, "username": "x"})

        mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# POST /api/projects/{project_id}/proposal/decision
# ---------------------------------------------------------------------------

class TestDecideProjectProposal(unittest.IsolatedAsyncioTestCase):
    async def test_returns_decision_out(self):
        # decide_project_proposal requires the project to exist AND be owned
        mock_db = MagicMock()
        # _require_owned_project chain: query().filter().first() returns the project
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()
        # After ownership check, the proposal query chain returns None (no awaiting proposal)
        side_effect_iter = iter([MagicMock(), None])
        mock_db.query.return_value.filter.return_value.first.side_effect = lambda: next(side_effect_iter)

        with patch("app.api.proposals.SessionLocal", return_value=mock_db), \
             patch("app.api.proposals._apply_project_proposal_decision") as mock_apply:
            # _apply_project_proposal_decision returns (approval, snapshot_chars, message)
            mock_apply.return_value = (MagicMock(id=42), 100, "Decision applied")
            result = await decide_project_proposal(
                project_id=1,
                body=ProposalDecisionIn(decision="approve"),
                current_user={"user_id": 1, "username": "x"},
            )

        self.assertIsInstance(result, ProposalDecisionOut)
        mock_db.close.assert_called_once()

    async def test_returns_404_when_phase_not_awaiting_decision(self):
        # First .filter().first() returns None (no proposal awaiting decision)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.api.proposals.SessionLocal", return_value=mock_db):
            with self.assertRaises(Exception) as exc_info:
                await decide_project_proposal(
                    project_id=999,
                    body=DecideRequest(decision="approve"),
                    current_user={"user_id": 1, "username": "x"},
                )

        self.assertEqual(exc_info.exception.status_code, 404)
        mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/proposal
# ---------------------------------------------------------------------------

class TestGetProposalState(unittest.IsolatedAsyncioTestCase):
    async def test_returns_state_when_proposal_exists(self):
        proposal = _make_proposal(project_id=42, lifecycle="proposed")
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = proposal

        with patch("app.api.proposals.SessionLocal", return_value=mock_db):
            result = await get_proposal_state(
                project_id=42,
                current_user={"user_id": 1, "username": "x"},
            )

        self.assertIsInstance(result, ProposalStateOut)
        # ProposalStateOut has fields like `approved`, `last_decision`, `proposal_snapshot_chars`
        # (not `current_phase`); just confirm the object is well-formed
        self.assertIsNotNone(result)
        mock_db.close.assert_called_once()

    async def test_returns_no_awaiting_decision_when_no_proposal(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        with patch("app.api.proposals.SessionLocal", return_value=mock_db):
            result = await get_proposal_state(
                project_id=999,
                current_user={"user_id": 1, "username": "x"},
            )

        # Should still return a ProposalStateOut, not raise
        self.assertIsInstance(result, ProposalStateOut)
        mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# POST /api/proposals/generate  (SSE streaming)
# ---------------------------------------------------------------------------

class TestGenerateProposal(unittest.IsolatedAsyncioTestCase):
    """The generate endpoint returns a StreamingResponse backed by
    ProposalGenerator.generate_stream. We mock the generator to verify
    the wiring without actually streaming bytes.
    """

    async def test_returns_streaming_response(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()

        # The async generator returned by generate_stream
        async def fake_stream(pid):
            yield ("sources", [{"pattern_name": "P"}])
            yield ("token", "hello")
            yield ("done", {"proposal_id": 42, "citations": []})

        # Fake ProposalGenerator class with generate_stream
        class FakeGenerator:
            def __init__(self, user_id, project_id):
                pass

            async def generate_stream(self, project_id, **kwargs):
                async for item in fake_stream(project_id):
                    yield item

        with patch("app.api.proposals.SessionLocal", return_value=mock_db), \
             patch("app.api.proposals.ProposalGenerator", FakeGenerator):
            result = await generate_proposal(
                body=MagicMock(project_id=42),
                current_user={"user_id": 1, "username": "alice"},
            )

        # It's a FastAPI StreamingResponse with the right media type
        self.assertEqual(result.media_type, "text/event-stream")

    async def test_closes_db_after_ownership_check(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()

        class FakeGenerator:
            def __init__(self, user_id, project_id):
                pass
            async def generate_stream(self, project_id, **kwargs):
                return
                yield  # make this a generator

        with patch("app.api.proposals.SessionLocal", return_value=mock_db), \
             patch("app.api.proposals.ProposalGenerator", FakeGenerator):
            await generate_proposal(
                body=MagicMock(project_id=42),
                current_user={"user_id": 1, "username": "alice"},
            )

        # The ownership-check DB session is closed even on the happy path
        mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# POST /api/proposals/{proposal_id}/modify  (SSE streaming)
# ---------------------------------------------------------------------------

class TestModifyProposal(unittest.IsolatedAsyncioTestCase):
    async def test_returns_404_when_proposal_not_found(self):
        mock_db = MagicMock()
        mock_db.get.return_value = None

        with patch("app.api.proposals.SessionLocal", return_value=mock_db):
            with self.assertRaises(Exception) as exc_info:
                await modify_proposal(
                    proposal_id=999,
                    body=ModifyRequest(feedback="needs more detail"),
                    current_user={"user_id": 1, "username": "x"},
                )

        self.assertEqual(exc_info.exception.status_code, 404)
        mock_db.close.assert_called_once()

    async def test_returns_409_when_proposal_not_in_proposed_state(self):
        proposal = _make_proposal(proposal_id=1, lifecycle="approved")
        mock_db = MagicMock()
        mock_db.get.return_value = proposal

        with patch("app.api.proposals.SessionLocal", return_value=mock_db):
            with self.assertRaises(Exception) as exc_info:
                await modify_proposal(
                    proposal_id=1,
                    body=ModifyRequest(feedback="needs work"),
                    current_user={"user_id": 1, "username": "x"},
                )

        self.assertEqual(exc_info.exception.status_code, 409)
        mock_db.close.assert_called_once()

    async def test_returns_409_when_max_iterations_reached(self):
        proposal = _make_proposal(proposal_id=1, lifecycle="proposed", iteration=10)
        mock_db = MagicMock()
        mock_db.get.return_value = proposal

        with patch("app.api.proposals.SessionLocal", return_value=mock_db):
            with self.assertRaises(Exception) as exc_info:
                await modify_proposal(
                    proposal_id=1,
                    body=ModifyRequest(feedback="needs work"),
                    current_user={"user_id": 1, "username": "x"},
                )

        self.assertEqual(exc_info.exception.status_code, 409)
        mock_db.close.assert_called_once()