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
        "app.api.adr.generate_llm_sections",
        new=AsyncMock(return_value="### 7.1 Componentes y responsabilidades\nx"),
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
    ), patch("app.api.adr.generate_llm_sections", new=AsyncMock(return_value=guide)):
        created = http.post("/api/projects/5/adr").json()

    assert "| Estado | Propuesto (pendiente de aprobación) |" in created["markdown"]

    llm = AsyncMock(side_effect=AssertionError("no debe llamar al LLM al aprobar"))
    with patch("app.api.adr.collect_adr_context", side_effect=lambda *a, **k: _ctx()), patch(
        "app.api.adr.generate_llm_sections", new=llm
    ):
        approved = http.post("/api/projects/5/adr/approve").json()

    assert "| Estado | Aceptado |" in approved["markdown"]
    assert "| Aprobado |" in approved["markdown"]
    assert "### 7.6 Primer sprint" in approved["markdown"]
    assert approved["guide_complete"] is True
    stored = http.get("/api/projects/5/adr").json()
    assert stored["markdown"] == approved["markdown"]
