"""GET/POST /api/projects/{id}/adr y POST /adr/approve (fase Revisión)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.adr_generator import AdrContext, AdrNotReadyError
from app.core.llm_loader import LLMConfigError


class _FakeSession:
    """Sesión mínima: guarda la fila de UserSession y el proyecto en memoria."""

    store: dict = {}

    def query(self, _model):
        return self

    def filter(self, *_args):
        return self

    def with_for_update(self, **_kwargs):
        _FakeSession.store["locked"] = _FakeSession.store.get("locked", 0) + 1
        return self

    def first(self):
        return _FakeSession.store.get("row")

    def get(self, _model, _id):
        return _FakeSession.store["project"]

    def add(self, row):
        _FakeSession.store["row"] = row

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _ctx() -> AdrContext:
    return AdrContext(
        project_name="Clínica",
        project_description="Citas",
        current_phase="revision",
        proposal_markdown="# Propuesta",
    )


@pytest.fixture()
def client():
    from app.api.adr import router
    from app.api.dependencies import get_current_user

    _FakeSession.store = {"project": SimpleNamespace(phase_ready=False, current_phase="revision")}
    record = MagicMock()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides = {get_current_user: lambda: {"user_id": "1", "username": "alice"}}
    with patch("app.api.adr._require_project", return_value=None), patch(
        "app.api.adr.SessionLocal", _FakeSession
    ), patch("app.api.adr.get_langfuse_handler", return_value=None), patch(
        "app.api.adr.record_approval_decision", record
    ), patch(
        "app.api.adr.build_langchain_model",
        side_effect=LLMConfigError("sin modelo", reason="missing"),
    ):
        yield TestClient(app), record


def test_get_sin_adr_devuelve_markdown_null(client):
    http, _ = client
    body = http.get("/api/projects/5/adr").json()
    assert body["markdown"] is None
    assert body["approved_at"] is None


def test_post_sin_propuesta_aprobada_es_409(client):
    http, _ = client
    with patch(
        "app.api.adr.collect_adr_context",
        side_effect=AdrNotReadyError("Todavía no hay una propuesta aprobada."),
    ):
        response = http.post("/api/projects/5/adr")
    assert response.status_code == 409
    assert "propuesta aprobada" in response.json()["detail"]


def test_post_sin_llm_genera_el_adr_sin_guia_y_lo_guarda(client):
    http, _ = client
    with patch("app.api.adr.collect_adr_context", return_value=_ctx()):
        created = http.post("/api/projects/5/adr")
    stored = http.get("/api/projects/5/adr")

    assert created.status_code == 200
    body = created.json()
    assert body["guide_complete"] is False
    assert body["markdown"].startswith("# ADR-001: Arquitectura de Clínica")
    assert "no se pudo redactar esta parte" in body["markdown"]
    assert stored.json()["markdown"] == body["markdown"]


def test_post_con_guia_del_llm_marca_guide_complete(client):
    http, _ = client
    with patch("app.api.adr.collect_adr_context", return_value=_ctx()), patch(
        "app.api.adr.build_langchain_model", return_value=object()
    ), patch(
        "app.api.adr.generate_guide",
        new=AsyncMock(return_value=("### 7.1 Componentes y responsabilidades\nx", False)),
    ):
        response = http.post("/api/projects/5/adr")
    assert response.status_code == 200
    assert response.json()["guide_complete"] is True


def test_solicitar_cambios_registra_modify_y_los_incluye_en_el_adr(client):
    http, record = client
    with patch("app.api.adr.collect_adr_context", side_effect=lambda *a, **k: _ctx()):
        http.post("/api/projects/5/adr")
        response = http.post("/api/projects/5/adr", json={"feedback": "Usar Redis para caché"})

    body = response.json()
    assert body["feedback_history"] == ["Usar Redis para caché"]
    assert "- Usar Redis para caché" in body["markdown"]
    record.assert_called_once()
    assert record.call_args.kwargs["decision"] == "modify"
    assert record.call_args.kwargs["phase"] == "revision"


def test_aprobar_sin_adr_es_409(client):
    http, _ = client
    response = http.post("/api/projects/5/adr/approve")
    assert response.status_code == 409


def test_aprobar_termina_el_proyecto_y_pedir_cambios_lo_reabre(client):
    http, record = client
    project = _FakeSession.store["project"]
    with patch("app.api.adr.collect_adr_context", side_effect=lambda *a, **k: _ctx()):
        http.post("/api/projects/5/adr")
        approved = http.post("/api/projects/5/adr/approve").json()

        assert approved["approved_at"] is not None
        assert project.phase_ready is True
        assert record.call_args.kwargs["decision"] == "approve"
        # Aprobar dos veces no registra otra decisión.
        http.post("/api/projects/5/adr/approve")
        assert record.call_count == 1

        reopened = http.post("/api/projects/5/adr", json={"feedback": "Agregar auditoría"}).json()
    assert reopened["approved_at"] is None
    assert project.phase_ready is False


def test_post_con_cambios_sin_propuesta_aprobada_no_guarda_nada(client):
    """Revisión: antes se registraba el modify y se hacía commit antes del 409."""
    http, record = client
    project = _FakeSession.store["project"]
    project.phase_ready = True
    with patch(
        "app.api.adr.collect_adr_context",
        side_effect=AdrNotReadyError("Todavía no hay una propuesta aprobada."),
    ):
        response = http.post("/api/projects/5/adr", json={"feedback": "Usar Redis"})

    assert response.status_code == 409
    record.assert_not_called()
    assert project.phase_ready is True


@pytest.mark.parametrize("phase", ["requerimientos", "propuesta", "refinamiento"])
def test_generar_y_aprobar_fuera_de_revision_es_409(client, phase):
    http, record = client
    project = _FakeSession.store["project"]
    project.current_phase = phase
    with patch("app.api.adr.collect_adr_context", side_effect=lambda *a, **k: _ctx()):
        generated = http.post("/api/projects/5/adr")
        approved = http.post("/api/projects/5/adr/approve")

    assert generated.status_code == 409
    assert approved.status_code == 409
    assert "Revisión" in approved.json()["detail"]
    record.assert_not_called()
    assert project.phase_ready is False


def test_aprobar_vuelve_a_armar_el_markdown_como_aceptado_sin_llamar_al_llm(client):
    http, _ = client
    guide = "\n\n".join(
        f"### 7.{i} {name}\nContenido." for i, name in enumerate(
            ("Componentes y responsabilidades", "Stack tecnológico recomendado", "Consecuencias",
             "Riesgos y mitigaciones", "Plan de implementación", "Primer sprint",
             "Estructura inicial del repositorio", "Preguntas abiertas"), 1)
    )
    with patch("app.api.adr.collect_adr_context", side_effect=lambda *a, **k: _ctx()), patch(
        "app.api.adr.build_langchain_model", return_value=object()
    ), patch("app.api.adr.generate_guide", new=AsyncMock(return_value=(guide, False))):
        created = http.post("/api/projects/5/adr").json()

    assert "| Estado | Propuesto (pendiente de aprobación) |" in created["markdown"]

    llm = AsyncMock(side_effect=AssertionError("no debe llamar al LLM al aprobar"))
    with patch("app.api.adr.collect_adr_context", side_effect=lambda *a, **k: _ctx()), patch(
        "app.api.adr.generate_guide", new=llm
    ):
        approved = http.post("/api/projects/5/adr/approve").json()

    assert "| Estado | Aceptado |" in approved["markdown"]
    assert "| Aprobado |" in approved["markdown"]
    assert "### 7.6 Primer sprint" in approved["markdown"]
    assert approved["guide_complete"] is True
    stored = http.get("/api/projects/5/adr").json()
    assert stored["markdown"] == approved["markdown"]


# --- Re-revisión: los bloqueantes 1 y 2 sobre la estructura actual del ADR ---
# (guía con redacción + revisión + corrección y cifras marcadas como supuesto)


def test_aprobar_conserva_la_guia_corregida_y_el_diagrama_con_clases(client):
    http, _ = client
    mermaid = "flowchart TD\n  A[Web]:::web --> B[API]:::svc\n  B --> C[(DB)]"

    def ctx_con_diagrama(*_a, **_k):
        ctx = _ctx()
        ctx.mermaid = mermaid
        ctx.diagram_approved = True
        return ctx

    guide = "\n\n".join(
        f"### 7.{i} {name}\nContenido." for i, name in enumerate(
            ("Componentes y responsabilidades", "Stack tecnológico recomendado", "Consecuencias",
             "Riesgos y mitigaciones", "Plan de implementación", "Primer sprint",
             "Estructura inicial del repositorio", "Preguntas abiertas"), 1)
    ).replace("### 7.3 Consecuencias\nContenido.", "### 7.3 Consecuencias\nCosto de $900 (supuesto) al mes.")
    with patch("app.api.adr.collect_adr_context", side_effect=ctx_con_diagrama), patch(
        "app.api.adr.build_langchain_model", return_value=object()
    ), patch("app.api.adr.generate_guide", new=AsyncMock(return_value=(guide, True))):
        created = http.post("/api/projects/5/adr").json()

    llm = AsyncMock(side_effect=AssertionError("no debe llamar al LLM al aprobar"))
    with patch("app.api.adr.collect_adr_context", side_effect=ctx_con_diagrama), patch(
        "app.api.adr.generate_guide", new=llm
    ):
        approved = http.post("/api/projects/5/adr/approve").json()

    # Bloqueante 1: el estado sale de approved_at, también con la guía corregida.
    assert "| Estado | Propuesto (pendiente de aprobación) |" in created["markdown"]
    assert "| Estado | Aceptado |" in approved["markdown"]
    assert "| Aprobado |" in approved["markdown"]
    # La guía que se aprueba es la guardada: no se vuelve a redactar ni a corregir.
    assert "Costo de $900 (supuesto) al mes." in approved["markdown"]
    assert approved["markdown"].count("(supuesto)") == created["markdown"].count("(supuesto)")
    # Bloqueante 2: las clases del diagrama llegan intactas al ADR.
    assert "A[Web]:::web --> B[API]:::svc" in approved["markdown"]
    assert "|::" not in approved["markdown"]


# --- Revisión: el modify se guarda con el ADR, causa del fallo y doble clic ----


def test_el_modify_se_registra_despues_del_llm_junto_con_el_adr(client):
    """Antes se confirmaba ANTES de llamar al LLM: si el guardado fallaba quedaba suelto."""
    http, record = client
    order: list[str] = []
    record.side_effect = lambda *a, **k: order.append("record")

    async def _guide(*_a, **_k):
        order.append("llm")
        return None, False

    with patch("app.api.adr.collect_adr_context", side_effect=lambda *a, **k: _ctx()), patch(
        "app.api.adr.build_langchain_model", return_value=object()
    ), patch("app.api.adr.generate_guide", new=_guide):
        body = http.post("/api/projects/5/adr", json={"feedback": "Agregar auditoría"}).json()

    assert order == ["llm", "record"]
    assert body["feedback_history"] == ["Agregar auditoría"]
    # El cambio pedido ya aparece en el historial de decisiones del ADR.
    assert "Agregar auditoría" in body["markdown"].split("## 6.")[1]


def test_si_falla_el_guardado_no_queda_el_modify(client):
    http, record = client
    with patch("app.api.adr.collect_adr_context", side_effect=lambda *a, **k: _ctx()), patch(
        "app.api.adr._save_adr", side_effect=RuntimeError("db caída")
    ):
        response = http.post("/api/projects/5/adr", json={"feedback": "Agregar auditoría"})
    assert response.status_code == 500
    # record_approval_decision se llamó dentro de la transacción que hizo rollback.
    assert record.call_count <= 1


def test_la_causa_del_fallo_de_la_guia_se_guarda_y_se_muestra(client):
    http, _ = client

    async def _guide(_model, _ctx_arg, *, callbacks=None, diagnostics=None):
        diagnostics["failure"] = "too_large"
        return None, False

    with patch("app.api.adr.collect_adr_context", side_effect=lambda *a, **k: _ctx()), patch(
        "app.api.adr.build_langchain_model", return_value=object()
    ), patch("app.api.adr.generate_guide", new=_guide):
        created = http.post("/api/projects/5/adr").json()
        approved = http.post("/api/projects/5/adr/approve").json()

    assert "límite de tokens" in created["markdown"]
    # Al aprobar se vuelve a armar sin LLM y conserva la causa.
    assert "límite de tokens" in approved["markdown"]


def test_aprobar_bloquea_la_fila_de_sesion(client):
    http, _ = client
    with patch("app.api.adr.collect_adr_context", side_effect=lambda *a, **k: _ctx()):
        http.post("/api/projects/5/adr")
        before = _FakeSession.store.get("locked", 0)
        http.post("/api/projects/5/adr/approve")
    assert _FakeSession.store.get("locked", 0) == before + 1
