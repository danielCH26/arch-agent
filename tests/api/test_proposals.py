"""
Tests para /api/proposals/* — CRUD + approve/reject/modify.

Issue: #12 — F08

Usa mocking puro (sin DB real) siguiendo el patrón de test_auth.py.
"""

import os
import pytest
import pytest_asyncio

# Configurar entorno antes de cualquier import de app.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRES_MINUTES", "60")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-32-chars!!")


class TestListProposals:
    """Tests para GET /api/proposals?session_id=X"""

    @pytest.mark.asyncio
    async def test_list_proposals_success(self):
        """Lista propuestas de una sesión propia."""
        from unittest.mock import MagicMock, patch

        with patch("app.api.proposals.SessionLocal") as mock_session_local:
            mock_db = MagicMock()

            # Mock UserSession query
            mock_session = MagicMock()
            mock_session.id = 1
            mock_session.user_id = 1

            # Mock Proposal query
            mock_proposal = MagicMock()
            mock_proposal.id = 10
            mock_proposal.session_id = 1
            mock_proposal.phase = "architecture"
            mock_proposal.version = 1
            mock_proposal.content = {"title": "Test", "components": []}
            mock_proposal.status = "draft"
            mock_proposal.created_at = None

            # Setup mocks - first query returns session, second returns proposals
            mock_db.query.return_value.filter.return_value.first.return_value = mock_session
            mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
                mock_proposal
            ]
            mock_session_local.return_value = mock_db

            from app.api.proposals import list_proposals

            # Call with user_id=1, session_id=1
            result = await list_proposals(
                session_id=1,
                current_user={"user_id": 1},
            )

            assert len(result) == 1
            assert result[0].id == 10
            assert result[0].status == "draft"

    @pytest.mark.asyncio
    async def test_list_proposals_session_not_owned(self):
        """Sesión que no pertenece al usuario retorna 404 (no 403)."""
        from unittest.mock import MagicMock, patch
        from fastapi import HTTPException

        with patch("app.api.proposals.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_session_local.return_value = mock_db

            from app.api.proposals import list_proposals

            with pytest.raises(HTTPException) as exc_info:
                await list_proposals(
                    session_id=999,
                    current_user={"user_id": 1},
                )

            assert exc_info.value.status_code == 404


class TestGetProposal:
    """Tests para GET /api/proposals/{id}"""

    @pytest.mark.asyncio
    async def test_get_proposal_success(self):
        """Obtiene propuesta propia."""
        from unittest.mock import MagicMock, patch

        with patch("app.api.proposals.SessionLocal") as mock_session_local:
            mock_db = MagicMock()

            # Mock Proposal con join
            mock_proposal = MagicMock()
            mock_proposal.id = 10
            mock_proposal.session_id = 1
            mock_proposal.phase = "architecture"
            mock_proposal.version = 1
            mock_proposal.content = {"title": "Test"}
            mock_proposal.status = "draft"
            mock_proposal.created_at = None

            mock_db.query.return_value.join.return_value.filter.return_value.first.return_value = (
                mock_proposal
            )
            mock_session_local.return_value = mock_db

            from app.api.proposals import get_proposal

            result = await get_proposal(
                proposal_id=10,
                current_user={"user_id": 1},
            )

            assert result.id == 10
            assert result.status == "draft"

    @pytest.mark.asyncio
    async def test_get_proposal_not_owned(self):
        """Propuesta de otro usuario retorna 404 (R5: no 403 para evitar info leak)."""
        from unittest.mock import MagicMock, patch
        from fastapi import HTTPException

        with patch("app.api.proposals.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.query.return_value.join.return_value.filter.return_value.first.return_value = (
                None
            )
            mock_session_local.return_value = mock_db

            from app.api.proposals import get_proposal

            with pytest.raises(HTTPException) as exc_info:
                await get_proposal(
                    proposal_id=999,
                    current_user={"user_id": 1},
                )

            assert exc_info.value.status_code == 404


class TestApproveProposal:
    """Tests para POST /api/proposals/{id}/approve"""

    @pytest.mark.asyncio
    async def test_approve_proposal_success(self):
        """Aprueba propuesta exitosamente."""
        from unittest.mock import MagicMock, patch

        with patch("app.api.proposals.SessionLocal") as mock_session_local:
            mock_db = MagicMock()

            # Mock Proposal
            mock_proposal = MagicMock()
            mock_proposal.id = 10
            mock_proposal.session_id = 1
            mock_proposal.phase = "architecture"
            mock_proposal.version = 1
            mock_proposal.content = {"title": "Test"}
            mock_proposal.status = "draft"

            mock_db.query.return_value.join.return_value.filter.return_value.first.return_value = (
                mock_proposal
            )
            mock_session_local.return_value = mock_db

            # Need to mock _set_status and _record_approval
            with patch("app.api.proposals._set_status") as mock_set_status, patch(
                "app.api.proposals._record_approval"
            ) as mock_record:
                mock_approval = MagicMock()
                mock_approval.id = 1
                mock_approval.proposal_id = 10
                mock_approval.decision = "approved"
                mock_approval.feedback = None
                mock_approval.created_at = None
                mock_record.return_value = mock_approval

                from app.api.proposals import approve_proposal

                result = await approve_proposal(
                    proposal_id=10,
                    current_user={"user_id": 1},
                )

                assert result.decision == "approved"
                mock_set_status.assert_called_once_with(10, "approved")

    @pytest.mark.asyncio
    async def test_approve_already_approved(self):
        """Ya aprobada retorna 409 Conflict."""
        from unittest.mock import MagicMock, patch
        from fastapi import HTTPException

        with patch("app.api.proposals.SessionLocal") as mock_session_local:
            mock_db = MagicMock()

            mock_proposal = MagicMock()
            mock_proposal.status = "approved"  # Already approved

            mock_db.query.return_value.join.return_value.filter.return_value.first.return_value = (
                mock_proposal
            )
            mock_session_local.return_value = mock_db

            from app.api.proposals import approve_proposal

            with pytest.raises(HTTPException) as exc_info:
                await approve_proposal(
                    proposal_id=10,
                    current_user={"user_id": 1},
                )

            assert exc_info.value.status_code == 409


class TestRejectProposal:
    """Tests para POST /api/proposals/{id}/reject"""

    @pytest.mark.asyncio
    async def test_reject_proposal_success(self):
        """Rechaza propuesta con feedback."""
        from unittest.mock import MagicMock, patch

        with patch("app.api.proposals.SessionLocal") as mock_session_local:
            mock_db = MagicMock()

            mock_proposal = MagicMock()
            mock_proposal.id = 10
            mock_proposal.session_id = 1
            mock_proposal.phase = "architecture"
            mock_proposal.version = 1
            mock_proposal.content = {"title": "Test"}
            mock_proposal.status = "draft"

            mock_db.query.return_value.join.return_value.filter.return_value.first.return_value = (
                mock_proposal
            )
            mock_session_local.return_value = mock_db

            with patch("app.api.proposals._set_status") as mock_set_status, patch(
                "app.api.proposals._record_approval"
            ) as mock_record:
                mock_approval = MagicMock()
                mock_approval.id = 1
                mock_approval.proposal_id = 10
                mock_approval.decision = "rejected"
                mock_approval.feedback = "No me gusta"
                mock_approval.created_at = None
                mock_record.return_value = mock_approval

                from app.api.proposals import reject_proposal
                from app.api.proposals import FeedbackIn

                result = await reject_proposal(
                    proposal_id=10,
                    body=FeedbackIn(feedback="No me gusta"),
                    current_user={"user_id": 1},
                )

                assert result.decision == "rejected"
                assert result.feedback == "No me gusta"
                mock_set_status.assert_called_once_with(10, "rejected")

    @pytest.mark.asyncio
    async def test_reject_already_rejected(self):
        """Ya rechazada retorna 409 Conflict."""
        from unittest.mock import MagicMock, patch
        from fastapi import HTTPException

        with patch("app.api.proposals.SessionLocal") as mock_session_local:
            mock_db = MagicMock()

            mock_proposal = MagicMock()
            mock_proposal.status = "rejected"  # Already rejected

            mock_db.query.return_value.join.return_value.filter.return_value.first.return_value = (
                mock_proposal
            )
            mock_session_local.return_value = mock_db

            from app.api.proposals import reject_proposal
            from app.api.proposals import FeedbackIn

            with pytest.raises(HTTPException) as exc_info:
                await reject_proposal(
                    proposal_id=10,
                    body=FeedbackIn(feedback="feedback"),
                    current_user={"user_id": 1},
                )

            assert exc_info.value.status_code == 409


class TestModifyProposal:
    """Tests para POST /api/proposals/{id}/modify"""

    @pytest.mark.asyncio
    async def test_modify_proposal_success(self):
        """Pide modificación exitosamente."""
        from unittest.mock import MagicMock, patch

        with patch("app.api.proposals.SessionLocal") as mock_session_local:
            mock_db = MagicMock()

            mock_proposal = MagicMock()
            mock_proposal.id = 10
            mock_proposal.session_id = 1
            mock_proposal.phase = "architecture"
            mock_proposal.version = 1
            mock_proposal.content = {"title": "Test"}
            mock_proposal.status = "draft"

            mock_db.query.return_value.join.return_value.filter.return_value.first.return_value = (
                mock_proposal
            )
            mock_session_local.return_value = mock_db

            with patch("app.api.proposals._set_status") as mock_set_status, patch(
                "app.api.proposals._record_approval"
            ) as mock_record:
                mock_approval = MagicMock()
                mock_approval.id = 1
                mock_approval.proposal_id = 10
                mock_approval.decision = "modified"
                mock_approval.feedback = "Cambiar la base de datos"
                mock_approval.created_at = None
                mock_record.return_value = mock_approval

                from app.api.proposals import modify_proposal
                from app.api.proposals import FeedbackIn

                result = await modify_proposal(
                    proposal_id=10,
                    body=FeedbackIn(feedback="Cambiar la base de datos"),
                    current_user={"user_id": 1},
                )

                assert result.decision == "modified"
                assert result.feedback == "Cambiar la base de datos"
                # Status changes to draft for new version
                mock_set_status.assert_called_once_with(10, "draft")

    @pytest.mark.asyncio
    async def test_modify_proposal_not_owned(self):
        """Propuesta de otro usuario retorna 404."""
        from unittest.mock import MagicMock, patch
        from fastapi import HTTPException

        with patch("app.api.proposals.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.query.return_value.join.return_value.filter.return_value.first.return_value = (
                None
            )
            mock_session_local.return_value = mock_db

            from app.api.proposals import modify_proposal
            from app.api.proposals import FeedbackIn

            with pytest.raises(HTTPException) as exc_info:
                await modify_proposal(
                    proposal_id=999,
                    body=FeedbackIn(feedback="feedback"),
                    current_user={"user_id": 1},
                )

            assert exc_info.value.status_code == 404
