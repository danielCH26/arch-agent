"""Tests HU8 para los endpoints de verificación de fuentes y métrica del KR.

- ``GET /api/patterns/{id}``: destino de ``verify_url`` en cada cita.
- ``GET /api/proposals/justification-stats``: % de propuestas que citan
  patrones (KR ≥80%).
- ``GET /api/proposals/{id}``: expone ``justification`` y ``cited``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

CURRENT_USER = {"user_id": 1, "username": "sofia"}

CITED = "## Patrones\n- **Hexagonal**: aísla el dominio [1]\n"
UNCITED = "## Patrones\n- **Monolito**: simple (sin patron del catalogo)\n"
CITATIONS = [{"index": 1, "pattern_id": 7, "pattern_name": "Hexagonal", "similarity": 0.9}]


def _proposal(pid, content, citations):
    return SimpleNamespace(
        id=pid,
        project_id=5,
        iteration=1,
        content=content,
        citations=[dict(c) for c in citations],
        feedback=None,
        lifecycle="proposed",
        created_at=None,
    )


class TestRouteOrder:
    def test_stats_route_declared_before_proposal_id_route(self):
        from app.api.proposals import router

        paths = [route.path for route in router.routes]
        assert paths.index("/api/proposals/justification-stats") < paths.index(
            "/api/proposals/{proposal_id}"
        )


class TestJustificationStats:
    def test_rate_over_user_proposals(self):
        from app.api import proposals as module

        rows = [_proposal(i, CITED, CITATIONS) for i in range(4)]
        rows.append(_proposal(9, UNCITED, CITATIONS))
        db = MagicMock()
        db.query.return_value.join.return_value.filter.return_value.all.return_value = rows

        with patch.object(module, "SessionLocal", return_value=db):
            out = asyncio.run(module.get_justification_stats(None, CURRENT_USER))

        assert out.proposals_total == 5
        assert out.proposals_citing_patterns == 4
        assert out.citation_rate == 0.8
        assert out.meets_target is True
        db.close.assert_called_once()

    def test_project_filter_checks_ownership(self):
        from app.api import proposals as module

        db = MagicMock()
        forbidden = HTTPException(status_code=403, detail="No tienes acceso a este proyecto")
        with patch.object(module, "SessionLocal", return_value=db), \
             patch.object(module, "_require_owned_project", side_effect=forbidden):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(module.get_justification_stats(5, CURRENT_USER))
        assert exc.value.status_code == 403


class TestGetProposalExposesJustification:
    def test_includes_justification_and_cited_flag(self):
        from app.api import proposals as module

        db = MagicMock()
        db.get.return_value = _proposal(3, CITED, CITATIONS)
        with patch.object(module, "SessionLocal", return_value=db), \
             patch.object(module, "_require_owned_project"):
            out = asyncio.run(module.get_proposal(3, CURRENT_USER))

        assert out.justification["cites_patterns"] is True
        assert out.justification["coverage"] == 1.0
        assert out.citations[0]["cited"] is True


class TestPatternDetail:
    def test_returns_pattern_with_chunks_and_sources(self):
        from app.api import patterns as module

        pattern = SimpleNamespace(
            id=7,
            pattern_name="Hexagonal",
            category="Estructural",
            description="Puertos y adaptadores",
            use_cases="Dominios ricos",
            tradeoffs={"ventajas": ["testeable"]},
            when_not_to_use="CRUD simple",
            decision_signals=[{"pregunta": "¿?", "señal_patron": "sí"}],
        )
        chunks = [
            SimpleNamespace(id=1, chunk_type="summary", chunk_text="resumen", chunk_metadata=None),
            SimpleNamespace(
                id=2,
                chunk_type="source_upload",
                chunk_text="extracto",
                chunk_metadata={"filename": "cockburn.pdf"},
            ),
        ]
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = pattern
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = chunks

        with patch.object(module, "SessionLocal", return_value=db):
            out = asyncio.run(module.get_pattern(7, CURRENT_USER))

        assert out.pattern_name == "Hexagonal"
        assert [c.source for c in out.chunks] == [module.CURATED_SOURCE_LABEL, "cockburn.pdf"]
        db.close.assert_called_once()

    def test_unknown_pattern_is_404(self):
        from app.api import patterns as module

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with patch.object(module, "SessionLocal", return_value=db):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(module.get_pattern(404, CURRENT_USER))
        assert exc.value.status_code == 404
