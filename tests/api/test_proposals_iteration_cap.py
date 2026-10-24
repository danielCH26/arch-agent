"""Los tres cortes de iteracion deben LEER el getter, no una constante.

PR #102 round 5 (pedido 2 de Laura): los tests de 409 usaban el valor por
defecto (iteration=10 contra PROPOSAL_MAX_ITER=5), asi que pasaban igual
aunque alguien volviera a escribir `>= PROPOSAL_MAX_ITER` con la constante
de modulo. Como ``proposals.py`` sigue re-exportando PROPOSAL_MAX_ITER (es
contrato de test_env.py), esa regresion era invisible para la suite.

Estos tests setean un valor que no es el default (2) y comprueban que el
numero que aparece en el detalle es ese, en los tres cortes:

  1. ``_raise_if_iteration_cap_reached``  (POST /generate)
  2. ``modify_proposal``                  (POST /modify)
  3. ``_persist_proposal_and_log``        (el corte del generador)
"""

from __future__ import annotations

import os
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch

import pytest

# Valor deliberadamente distinto del default (5) y de los valores que usan
# otros tests, para que una constante hardcodeada no alcance a pasarlo.
CAP = "2"


@pytest.fixture
def cap_en_entorno():
    """Setea PROPOSAL_MAX_ITER=2 y lo restaura al final."""
    original = os.environ.get("PROPOSAL_MAX_ITER")
    os.environ["PROPOSAL_MAX_ITER"] = CAP
    yield CAP
    if original is None:
        os.environ.pop("PROPOSAL_MAX_ITER", None)
    else:
        os.environ["PROPOSAL_MAX_ITER"] = original


def _proposal(iteration: int, lifecycle: str = "proposed"):
    p = MagicMock()
    p.id = 1
    p.project_id = 1
    p.iteration = iteration
    p.lifecycle = lifecycle
    p.proposal_markdown = "markdown"
    p.snapshot = None
    return p


class TestGenerateCortaEnElTope:
    """``_raise_if_iteration_cap_reached`` (usado por POST /generate)."""

    def test_el_detalle_trae_el_valor_de_la_env_var(self, cap_en_entorno):
        from app.api.proposals import _raise_if_iteration_cap_reached

        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            _proposal(iteration=int(CAP))
        )

        with pytest.raises(Exception) as exc:
            _raise_if_iteration_cap_reached(db, project_id=1)

        assert exc.value.status_code == 409
        assert f"({CAP})" in exc.value.detail

    def test_no_corta_si_la_iteracion_esta_por_debajo(self, cap_en_entorno):
        from app.api.proposals import _raise_if_iteration_cap_reached

        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            _proposal(iteration=int(CAP) - 1)
        )

        # No debe levantar: la env var esta en 2 y la iteracion es 1.
        _raise_if_iteration_cap_reached(db, project_id=1)


class TestModifyCortaEnElTope(IsolatedAsyncioTestCase):
    """``modify_proposal`` (POST /modify). El repo usa IsolatedAsyncioTestCase."""

    async def test_el_detalle_trae_el_valor_de_la_env_var(self):
        from app.api.proposals import ModifyRequest, modify_proposal

        original = os.environ.get("PROPOSAL_MAX_ITER")
        os.environ["PROPOSAL_MAX_ITER"] = CAP
        try:
            prior = _proposal(iteration=int(CAP))
            mock_db = MagicMock()
            mock_db.get.return_value = prior

            with patch("app.api.proposals.SessionLocal", return_value=mock_db):
                with self.assertRaises(Exception) as exc:
                    await modify_proposal(
                        proposal_id=1,
                        body=ModifyRequest(feedback="needs work"),
                        current_user={"user_id": 1, "username": "x"},
                    )

            self.assertEqual(exc.exception.status_code, 409)
            self.assertIn(f"({CAP})", exc.exception.detail)
        finally:
            if original is None:
                os.environ.pop("PROPOSAL_MAX_ITER", None)
            else:
                os.environ["PROPOSAL_MAX_ITER"] = original


class TestPersistCortaEnElTope:
    """``_persist_proposal_and_log`` (el corte del generador)."""

    def test_el_error_trae_el_valor_de_la_env_var(self, cap_en_entorno):
        from app.core.proposal_generator import (
            _persist_proposal_and_log,
            _ProposalDomainError,
        )

        mock_db = MagicMock()
        # El generador abre su propia SessionLocal (no usa el ``session`` que
        # recibe), asi que se parchea ahi. Y se pasa ``iteration`` explicito
        # para saltarse la query de max_iter y llegar directo al corte.
        with patch("app.core.proposal_generator.SessionLocal", return_value=mock_db):
            with pytest.raises(_ProposalDomainError) as exc:
                _persist_proposal_and_log(
                    session_id=1,
                    project_id=1,
                    iteration=int(CAP) + 1,  # 3 > 2
                    prior_iteration=int(CAP),
                    prior_proposal_id=None,
                    prior_content=None,
                    markdown="# Propuesta",
                    citations=[],
                    feedback=None,
                    prompt="p",
                )

        assert f"({CAP})" in str(exc.value)
        # No debe haber llegado a insertar.
        mock_db.add.assert_not_called()


class TestNoVuelveALaConstante:
    """Guard de regresión: nadie debe volver a la constante de módulo."""

    def test_proposals_no_usa_la_constante_en_los_cortes(self):
        import inspect

        import app.api.proposals as proposals

        source = inspect.getsource(proposals)
        # Los cortes tienen que leer el getter.
        assert "latest.iteration) >= max_iterations" in source
        assert "prior.iteration >= max_iterations" in source
        # Y no debe haber un corte contra PROPOSAL_MAX_ITER directamente.
        assert ">= PROPOSAL_MAX_ITER" not in source
        assert "> PROPOSAL_MAX_ITER" not in source

    def test_el_generador_no_usa_la_constante_en_el_corte(self):
        import inspect

        from app.core import proposal_generator

        source = inspect.getsource(proposal_generator)
        assert "if iteration > max_iterations:" in source
        assert "iteration > PROPOSAL_MAX_ITER" not in source