"""ADR de la fase Revisión: armado, limpieza de la respuesta del LLM y
recolección de datos (SQLite en memoria)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.adr_generator import (
    LLM_SECTIONS,
    AdrContext,
    AdrDecision,
    AdrNotReadyError,
    clean_llm_sections,
    collect_adr_context,
    generate_llm_sections,
    render_adr_markdown,
)


@compiles(JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(_type, _compiler, **_kw):  # pragma: no cover - solo DDL de test
    return "JSON"


LLM_GUIDE = "\n\n".join(f"### 7.{i} {name}\nContenido de {name}." for i, name in enumerate(LLM_SECTIONS, 1))

MERMAID = "flowchart TD\n  A[API] --> B[(DB)]"


def _ctx(**overrides) -> AdrContext:
    base = dict(
        project_name="Clínica",
        project_description="Agenda de citas para una clínica",
        current_phase="revision",
        resumen={
            "problema": "Las citas se agendan por teléfono",
            "usuarios": "Pacientes y recepcionistas",
            "funcionalidades": ["Agendar citas", "Recordatorios"],
            "restricciones": ["Presupuesto de 20000 USD"],
            "calidad": ["Disponibilidad 99.5%"],
        },
        preguntas_respuestas=[{"pregunta": "¿Qué problema resuelve?", "respuesta": "Citas"}],
        proposal_markdown="# Propuesta\n\n## Trade-offs y decisión\n\n| Opción | Pro |\n|---|---|\n| Monolito | Simple |",
        proposal_iteration=2,
        proposal_lifecycle="approved",
        proposal_feedback_history=["Usar PostgreSQL"],
        citations=[
            {
                "pattern_id": 7,
                "pattern_name": "Monolito modular",
                "similarity": 0.87,
                "fuentes": [{"titulo": "Modular Monolith", "url": "https://example.com/mm"}],
            }
        ],
        mermaid=MERMAID,
        diagram_approved=True,
        decisions=[
            AdrDecision("requerimientos", "approved", None, datetime(2026, 10, 1, 9, 0)),
            AdrDecision("propuesta", "rejected", "muy complejo | caro", datetime(2026, 10, 2, 9, 0)),
            AdrDecision("propuesta", "approved", None, datetime(2026, 10, 3, 9, 0)),
        ],
    )
    base.update(overrides)
    return AdrContext(**base)


class TestRenderAdr:
    def test_incluye_todas_las_secciones_y_los_datos_aprobados(self):
        md = render_adr_markdown(
            _ctx(), llm_sections=LLM_GUIDE, generated_at=datetime(2026, 10, 16, tzinfo=timezone.utc)
        )
        for heading in (
            "# ADR-001: Arquitectura de Clínica",
            "## 1. Contexto",
            "## 2. Requerimientos",
            "## 3. Decisión",
            "## 4. Diagrama de arquitectura",
            "## 5. Referencias",
            "## 6. Historial de decisiones",
            "## 7. Guía para empezar",
            "## Anexo A. Elicitación de requerimientos",
        ):
            assert heading in md
        assert "Las citas se agendan por teléfono" in md
        assert "- Agendar citas" in md
        assert "- Presupuesto de 20000 USD" in md
        assert "| Fecha | 2026-10-16 |" in md
        assert f"```mermaid\n{MERMAID}\n```" in md
        assert "Contenido de Primer sprint." in md
        assert "- Usar PostgreSQL" in md

    def test_baja_los_titulos_de_la_propuesta_sin_tocar_bloques_de_codigo(self):
        ctx = _ctx(proposal_markdown="# Propuesta\n\n```\n# comentario\n```")
        md = render_adr_markdown(ctx, llm_sections=LLM_GUIDE)
        assert "### Propuesta" in md
        assert "\n# Propuesta" not in md
        assert "# comentario" in md  # dentro del fence no se toca

    def test_referencias_incluyen_las_fuentes_curadas_como_links(self):
        md = render_adr_markdown(_ctx(), llm_sections=LLM_GUIDE)
        assert "1. **Monolito modular** (similitud 87%)" in md
        assert "[Modular Monolith](https://example.com/mm)" in md

    def test_historial_escapa_pipes_y_traduce_decisiones(self):
        md = render_adr_markdown(_ctx(), llm_sections=LLM_GUIDE)
        assert "| Propuesta | Rechazada | muy complejo \\| caro |" in md
        assert "| Requerimientos | Aprobada | — |" in md

    def test_sin_guia_del_llm_el_adr_sale_igual_con_un_aviso(self):
        md = render_adr_markdown(_ctx(), llm_sections=None)
        assert "## 7. Guía para empezar" in md
        assert "no se pudo redactar esta parte" in md
        assert "## 3. Decisión" in md

    def test_sin_diagrama_lo_indica(self):
        md = render_adr_markdown(_ctx(mermaid=None, diagram_approved=False), llm_sections=None)
        assert "Todavía no se generó un diagrama" in md
        assert "```mermaid" not in md

    def test_estado_segun_la_fase(self):
        assert "| Estado | Aceptado |" in render_adr_markdown(_ctx(current_phase="final"), llm_sections=None)
        assert "| Estado | Propuesto |" in render_adr_markdown(
            _ctx(diagram_approved=False), llm_sections=None
        )


class TestCleanLlmSections:
    def test_acepta_una_respuesta_completa(self):
        assert clean_llm_sections(LLM_GUIDE) == LLM_GUIDE

    def test_quita_el_fence_que_envuelve_todo(self):
        assert clean_llm_sections(f"```markdown\n{LLM_GUIDE}\n```") == LLM_GUIDE

    def test_baja_titulos_de_nivel_1_y_2(self):
        text = LLM_GUIDE.replace("### 7.1", "## 7.1", 1)
        cleaned = clean_llm_sections(text)
        assert cleaned is not None
        assert "\n## " not in f"\n{cleaned}"

    def test_rechaza_respuestas_incompletas_o_vacias(self):
        assert clean_llm_sections(LLM_GUIDE.replace("Primer sprint", "Otra cosa")) is None
        assert clean_llm_sections("") is None


class _FakeModel:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.configs = []

    async def ainvoke(self, messages, config=None):
        self.configs.append(config)
        if self.error:
            raise self.error
        return type("Msg", (), {"content": self.response})()


class TestGenerateLlmSections:
    def test_devuelve_la_guia_y_usa_su_propio_run_name(self):
        model = _FakeModel(response=LLM_GUIDE)
        assert asyncio.run(generate_llm_sections(model, _ctx())) == LLM_GUIDE
        assert model.configs[0]["run_name"] == "adr-guide"

    def test_error_del_llm_devuelve_none_sin_lanzar(self):
        model = _FakeModel(error=RuntimeError("429 rate limit"))
        assert asyncio.run(generate_llm_sections(model, _ctx())) is None

    def test_respuesta_incompleta_devuelve_none(self):
        assert asyncio.run(generate_llm_sections(_FakeModel(response="### 7.1 Algo"), _ctx())) is None


# --- Recolección con base real (SQLite) ---------------------------------------

_TABLES = ["users", "sessions", "projects", "messages", "approvals", "proposals"]


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    import app.models  # noqa: F401
    from app.core.database import Base

    for name in _TABLES:
        Base.metadata.tables[name].create(bind=engine, checkfirst=True)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed(db, *, approved: bool = True):
    from app.models.approval import Approval
    from app.models.message import Message
    from app.models.project import Project
    from app.models.proposal import Proposal
    from app.models.session import UserSession
    from app.models.user import User

    db.add(User(id=1, username="u1", email="u1@x", password_hash="x"))
    db.add(Project(id=5, user_id=1, name="Clínica", description="Citas", current_phase="revision"))
    db.add(
        UserSession(
            id=1,
            user_id=1,
            engram_state={
                "5": {
                    "requerimientos": {
                        "resumen": {"problema": "Citas por teléfono", "funcionalidades": ["Agendar"]},
                        "preguntas_respuestas": [{"pregunta": "¿Problema?", "respuesta": "Citas"}],
                    }
                }
            },
        )
    )
    db.flush()
    db.add(Proposal(session_id=1, project_id=5, iteration=1, content="# v1", citations=[], feedback=None, lifecycle="rejected"))
    db.add(
        Proposal(
            session_id=1,
            project_id=5,
            iteration=2,
            content="# v2 aprobada",
            citations=[{"pattern_name": "Monolito"}],
            feedback="más simple",
            lifecycle="approved" if approved else "proposed",
        )
    )
    db.add(Message(id=10, session_id=1, project_id=5, user_id=1, role="assistant",
                   content="```mermaid\nflowchart TD\n  A --> B\n```", attachments=[{"id": "att-1", "kind": "screenshot"}]))
    db.add(Message(id=11, session_id=1, project_id=5, user_id=1, role="assistant",
                   content="```mermaid\nflowchart TD\n  X --> Y\n```", attachments=[{"id": "att-2", "kind": "screenshot"}]))
    db.add(Approval(session_id=1, project_id=5, phase="diagram", decision="approved", attachment_id="att-1"))
    db.add(Approval(session_id=1, project_id=5, phase="propuesta", decision="approved"))
    db.commit()


class TestCollectAdrContext:
    def test_junta_elicitacion_propuesta_aprobada_y_diagrama_aprobado(self, db):
        _seed(db)
        ctx = collect_adr_context(db, user_id=1, project_id=5)

        assert ctx.project_name == "Clínica"
        assert ctx.resumen["problema"] == "Citas por teléfono"
        assert ctx.preguntas_respuestas[0]["respuesta"] == "Citas"
        assert ctx.proposal_markdown == "# v2 aprobada"
        assert ctx.proposal_iteration == 2
        assert ctx.proposal_feedback_history == ["más simple"]
        assert ctx.citations == [{"pattern_name": "Monolito"}]
        # El aprobado (A --> B), no el más reciente (X --> Y).
        assert ctx.mermaid == "flowchart TD\n  A --> B"
        assert ctx.diagram_approved is True
        assert [d.phase for d in ctx.decisions] == ["diagram", "propuesta"]

    def test_sin_propuesta_aprobada_no_hay_adr(self, db):
        _seed(db, approved=False)
        with pytest.raises(AdrNotReadyError):
            collect_adr_context(db, user_id=1, project_id=5)
