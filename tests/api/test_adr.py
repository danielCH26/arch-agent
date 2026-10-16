"""GET/POST /api/projects/{id}/adr (fase Revisión)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.adr_generator import AdrContext, AdrNotReadyError
from app.core.llm_loader import LLMConfigError


class _FakeSession:
    """Sesión mínima: guarda el engram_state del usuario en memoria."""

    store: dict = {}

    def __init__(self):
        self._row = None

    def query(self, _model):
        return self

    def filter(self, *_args):
        return self

    def first(self):
        if "row" not in _FakeSession.store:
            return None
        return _FakeSession.store["row"]

    def add(self, row):
        _FakeSession.store["row"] = row

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _client() -> TestClient:
    from app.api.adr import router
    from app.api.dependencies import get_current_user

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides = {get_current_user: lambda: {"user_id": "1", "username": "alice"}}
    return TestClient(app)


def _ctx() -> AdrContext:
    return AdrContext(
        project_name="Clínica",
        project_description="Citas",
        current_phase="revision",
        proposal_markdown="# Propuesta",
    )


def _patches(**overrides):
    defaults = {
        "app.api.adr._require_project": None,
        "app.api.adr.SessionLocal": _FakeSession,
        "app.api.adr.get_langfuse_handler": None,
    }
    defaults.update(overrides)
    return [
        patch(target, return_value=value) if target != "app.api.adr.SessionLocal" else patch(target, value)
        for target, value in defaults.items()
    ]


def setup_function():
    _FakeSession.store = {}


def _run(patches, fn):
    for p in patches:
        p.start()
    try:
        return fn()
    finally:
        for p in patches:
            p.stop()


def test_get_sin_adr_devuelve_markdown_null():
    response = _run(_patches(), lambda: _client().get("/api/projects/5/adr"))
    assert response.status_code == 200
    assert response.json() == {"markdown": None, "generated_at": None, "guide_complete": False}


def test_post_sin_propuesta_aprobada_es_409():
    patches = _patches() + [
        patch(
            "app.api.adr.collect_adr_context",
            side_effect=AdrNotReadyError("Todavía no hay una propuesta aprobada."),
        )
    ]
    response = _run(patches, lambda: _client().post("/api/projects/5/adr"))
    assert response.status_code == 409
    assert "propuesta aprobada" in response.json()["detail"]


def test_post_sin_llm_configurado_genera_el_adr_sin_guia_y_lo_guarda():
    patches = _patches() + [
        patch("app.api.adr.collect_adr_context", return_value=_ctx()),
        patch("app.api.adr.build_langchain_model", side_effect=LLMConfigError("sin modelo", reason="missing")),
    ]

    def flow():
        client = _client()
        created = client.post("/api/projects/5/adr")
        stored = client.get("/api/projects/5/adr")
        return created, stored

    created, stored = _run(patches, flow)
    assert created.status_code == 200
    body = created.json()
    assert body["guide_complete"] is False
    assert body["markdown"].startswith("# ADR-001: Arquitectura de Clínica")
    assert "no se pudo redactar esta parte" in body["markdown"]
    # Se guarda: el GET devuelve el mismo documento sin volver a generarlo.
    assert stored.json()["markdown"] == body["markdown"]


def test_post_con_guia_del_llm_marca_guide_complete():
    patches = _patches() + [
        patch("app.api.adr.collect_adr_context", return_value=_ctx()),
        patch("app.api.adr.build_langchain_model", return_value=object()),
        patch("app.api.adr.generate_llm_sections", new=AsyncMock(return_value="### 7.1 Componentes y responsabilidades\nx")),
    ]
    response = _run(patches, lambda: _client().post("/api/projects/5/adr"))
    assert response.status_code == 200
    assert response.json()["guide_complete"] is True
    assert "### 7.1 Componentes y responsabilidades" in response.json()["markdown"]
