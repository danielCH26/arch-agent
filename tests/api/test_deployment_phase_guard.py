"""
La puerta del servidor para cerrar Refinamiento.

`has_approved_deployment` tiene que aplicar el MISMO criterio que el ADR sobre
qué despliegue cuenta. Si no, se abre este agujero:

  1. se aprueba la arquitectura v1 y después su despliegue;
  2. se aprueba una arquitectura v2;
  3. el servidor deja cerrar Refinamiento con el despliegue de v1;
  4. el ADR descarta ese despliegue por no corresponder a v2 y sale sin la
     sección de despliegue.

O sea: la puerta decía que sí y el documento quedaba incompleto.

Se prueba con dobles porque la función abre su propia sesión (la llaman desde
fuera de una transacción) y lo que importa es la REGLA, no el SQL.
"""

from types import SimpleNamespace

import pytest

from app.api import deployments
from app.api.deployments import ATTACHMENT_KIND, has_approved_deployment


def _att(att_id: str, arquitectura: str | None):
    att = {"id": att_id, "kind": ATTACHMENT_KIND}
    if arquitectura is not None:
        att["architecture_attachment_id"] = arquitectura
    return att


@pytest.fixture
def entorno(monkeypatch):
    """Deja configurar adjuntos, decisiones y la arquitectura vigente."""

    estado = {"adjuntos": [], "decisiones": {}, "arquitectura": None, "falla_adr": False}

    class _Sesion:
        def close(self):
            pass

    monkeypatch.setattr(deployments, "SessionLocal", lambda: _Sesion())
    monkeypatch.setattr(
        deployments,
        "_deployment_rows",
        lambda db, **kw: [(1, None, estado["adjuntos"])],
    )
    monkeypatch.setattr(
        deployments,
        "latest_diagram_decisions",
        lambda db, **kw: estado["decisiones"],
    )

    def _context(db, **kw):
        if estado["falla_adr"]:
            raise deployments.AdrNotReadyError("todavía no")
        return SimpleNamespace(diagram_attachment_id=estado["arquitectura"])

    monkeypatch.setattr(deployments, "collect_adr_context", _context)
    return estado


class TestLaPuertaMiraLaArquitecturaVigente:
    def test_un_despliegue_de_la_arquitectura_anterior_no_abre_la_puerta(self, entorno):
        """El caso de la revisión: despliegue de v1, arquitectura vigente v2."""
        entorno["adjuntos"] = [_att("dep-v1", "arq-v1")]
        entorno["decisiones"] = {"dep-v1": "approve"}
        entorno["arquitectura"] = "arq-v2"
        assert has_approved_deployment(user_id=1, project_id=1) is False

    def test_el_despliegue_de_la_arquitectura_vigente_si_abre_la_puerta(self, entorno):
        entorno["adjuntos"] = [_att("dep-v2", "arq-v2")]
        entorno["decisiones"] = {"dep-v2": "approve"}
        entorno["arquitectura"] = "arq-v2"
        assert has_approved_deployment(user_id=1, project_id=1) is True

    def test_basta_con_que_uno_corresponda(self, entorno):
        entorno["adjuntos"] = [_att("dep-v1", "arq-v1"), _att("dep-v2", "arq-v2")]
        entorno["decisiones"] = {"dep-v1": "approve", "dep-v2": "approve"}
        entorno["arquitectura"] = "arq-v2"
        assert has_approved_deployment(user_id=1, project_id=1) is True

    def test_un_despliegue_viejo_sin_el_dato_se_acepta(self, entorno):
        # Mismo criterio que `deployment_matches_architecture`: descartarlo
        # dejaría trabados los proyectos anteriores a que se guardara el dato.
        entorno["adjuntos"] = [_att("dep-viejo", None)]
        entorno["decisiones"] = {"dep-viejo": "approve"}
        entorno["arquitectura"] = "arq-v2"
        assert has_approved_deployment(user_id=1, project_id=1) is True

    def test_si_el_adr_no_esta_listo_se_cae_al_criterio_anterior(self, entorno):
        entorno["adjuntos"] = [_att("dep-v1", "arq-v1")]
        entorno["decisiones"] = {"dep-v1": "approve"}
        entorno["falla_adr"] = True
        assert has_approved_deployment(user_id=1, project_id=1) is True


class TestLoQueYaFuncionaba:
    def test_sin_despliegues_no_abre_la_puerta(self, entorno):
        assert has_approved_deployment(user_id=1, project_id=1) is False

    @pytest.mark.parametrize("decision", ["modify", "reject", None])
    def test_un_despliegue_no_aprobado_no_abre_la_puerta(self, entorno, decision):
        entorno["adjuntos"] = [_att("dep-1", "arq-1")]
        entorno["decisiones"] = {"dep-1": decision}
        entorno["arquitectura"] = "arq-1"
        assert has_approved_deployment(user_id=1, project_id=1) is False

    def test_una_decision_sobre_un_adjunto_que_ya_no_existe_se_ignora(self, entorno):
        entorno["adjuntos"] = [_att("dep-1", "arq-1")]
        entorno["decisiones"] = {"dep-1": "modify", "dep-borrado": "approve"}
        entorno["arquitectura"] = "arq-1"
        assert has_approved_deployment(user_id=1, project_id=1) is False

    def test_los_adjuntos_que_no_son_despliegues_se_ignoran(self, entorno):
        entorno["adjuntos"] = [{"id": "shot-1", "kind": "screenshot"}]
        entorno["decisiones"] = {"shot-1": "approve"}
        assert has_approved_deployment(user_id=1, project_id=1) is False
