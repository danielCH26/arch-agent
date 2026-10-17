"""Tests HU8 para la verificación de fuentes y la métrica del KR.

- ``GET /api/patterns/{id}``: destino de ``verify_url`` en cada cita.
- ``GET /api/proposals/justification-stats``: % de propuestas que citan
  patrones (KR ≥80%), solo con la última iteración viva de cada proyecto.
- ``GET /api/proposals/{id}``: expone ``justification``.
- ``POST /api/proposals/{id}/decide``: rechaza decidir desde otro proyecto.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

CURRENT_USER = {"user_id": 1, "username": "sofia"}

CITED = (
    "## Patrones\n- Patrón principal: Hexagonal [1]\n\n"
    "## Justificación del patrón principal\nAísla el dominio de la infraestructura.\n"
)
UNCITED = "## Patrones\n- Hexagonal\n"
CITATIONS = [
    {"index": 1, "pattern_id": 7, "pattern_name": "Hexagonal", "source_role": "primary"}
]


def _proposal(pid, content, citations=CITATIONS, project_id=5, iteration=1, lifecycle="proposed"):
    return SimpleNamespace(
        id=pid,
        project_id=project_id,
        iteration=iteration,
        session_id=1,
        content=content,
        citations=[dict(c) for c in citations],
        feedback=None,
        lifecycle=lifecycle,
        created_at=None,
    )


def _stats_db(proposals, project_ids=(5,)):
    """DB falsa: ``query(Project.id)`` devuelve los proyectos, ``query(Proposal)`` las filas."""
    from app.api import proposals as module

    proposal_query = MagicMock()
    proposal_query.filter.return_value.order_by.return_value.all.return_value = proposals
    project_query = MagicMock()
    project_query.filter.return_value.all.return_value = [
        SimpleNamespace(id=pid) for pid in project_ids
    ]

    db = MagicMock()
    db.query.side_effect = lambda model: (
        proposal_query if model is module.Proposal else project_query
    )
    return db, proposal_query


class TestRouteOrder:
    def test_stats_route_declared_before_proposal_id_route(self):
        from app.api.proposals import router

        paths = [route.path for route in router.routes]
        assert paths.index("/api/proposals/justification-stats") < paths.index(
            "/api/proposals/{proposal_id}"
        )

    def test_source_chunks_route_declared_before_pattern_id_route(self):
        from app.api.patterns import router

        paths = [route.path for route in router.routes]
        assert paths.index("/api/patterns/{pattern_id}/source-chunks") < paths.index(
            "/api/patterns/{pattern_id}"
        )


class TestJustificationStats:
    def test_rate_over_latest_proposal_of_each_project(self):
        from app.api import proposals as module

        # Ordenadas como las devuelve la consulta: proyecto, iteración desc.
        rows = [
            _proposal(1, CITED, project_id=1, iteration=2),
            _proposal(2, UNCITED, project_id=1, iteration=1),  # iteración vieja: no cuenta
            _proposal(3, CITED, project_id=2),
            _proposal(4, CITED, project_id=3),
            _proposal(5, CITED, project_id=4, lifecycle="approved"),
            _proposal(6, UNCITED, project_id=5),
        ]
        db, _ = _stats_db(rows, project_ids=(1, 2, 3, 4, 5))

        with patch.object(module, "SessionLocal", return_value=db):
            out = asyncio.run(module.get_justification_stats(None, CURRENT_USER))

        assert out.project_id is None
        assert out.proposals_total == 5
        assert out.proposals_citing == 4
        assert out.citation_rate == 0.8
        assert out.meets_target is True
        assert [item.proposal_id for item in out.items] == [1, 3, 4, 5, 6]
        db.close.assert_called_once()

    def test_without_project_and_without_proposals_returns_zeros(self):
        from app.api import proposals as module

        db, proposal_query = _stats_db([], project_ids=())
        with patch.object(module, "SessionLocal", return_value=db):
            out = asyncio.run(module.get_justification_stats(None, CURRENT_USER))

        assert out.project_id is None
        assert out.proposals_total == 0
        assert out.proposals_citing == 0
        assert out.citation_rate == 0.0
        assert out.meets_target is False
        assert out.items == []
        proposal_query.filter.assert_not_called()

    def test_project_filter_reports_project_id(self):
        from app.api import proposals as module

        db, _ = _stats_db([_proposal(1, CITED)])
        with patch.object(module, "SessionLocal", return_value=db), \
             patch.object(module, "_require_owned_project") as owned:
            out = asyncio.run(module.get_justification_stats(5, CURRENT_USER))

        owned.assert_called_once()
        assert out.project_id == 5
        assert out.citation_rate == 1.0

    def test_project_filter_checks_ownership(self):
        from app.api import proposals as module

        db = MagicMock()
        forbidden = HTTPException(status_code=403, detail="No tienes acceso a este proyecto")
        with patch.object(module, "SessionLocal", return_value=db), \
             patch.object(module, "_require_owned_project", side_effect=forbidden):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(module.get_justification_stats(5, CURRENT_USER))
        assert exc.value.status_code == 403
        db.close.assert_called_once()


class TestGetProposalExposesJustification:
    def test_includes_justification(self):
        from app.api import proposals as module

        db = MagicMock()
        db.get.return_value = _proposal(3, CITED)
        with patch.object(module, "SessionLocal", return_value=db), \
             patch.object(module, "_require_owned_project"):
            out = asyncio.run(module.get_proposal(3, CURRENT_USER))

        assert out.justification["cites_patterns"] is True
        assert out.justification["primary_pattern_name"] == "Hexagonal"
        # El análisis no toca las citas guardadas.
        assert out.citations == CITATIONS


class TestDecideChecksOpenProject:
    def test_decision_from_another_project_is_409(self):
        from app.api import proposals as module

        db = MagicMock()
        db.get.return_value = _proposal(3, CITED, project_id=5)
        body = module.DecideRequest(decision="reject", project_id=6)
        with patch.object(module, "SessionLocal", return_value=db), \
             patch.object(module, "_require_owned_project", return_value=SimpleNamespace(id=5)):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(module.decide_proposal(3, body, CURRENT_USER))

        assert exc.value.status_code == 409
        db.commit.assert_not_called()
        db.rollback.assert_called_once()


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
        db.close.assert_called_once()
