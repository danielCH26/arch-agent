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

    def test_estado_segun_la_aprobacion_del_adr(self):
        # Revisión: dependía de current_phase == "final", una fase que no existe
        # en este flujo; el ADR aprobado se descargaba como "Propuesto".
        approved = render_adr_markdown(
            _ctx(approved_at="2026-10-17T15:00:00+00:00"), llm_sections=None
        )
        assert "| Estado | Aceptado |" in approved
        assert "| Aprobado | 2026-10-17 |" in approved
        pending = render_adr_markdown(_ctx(), llm_sections=None)
        assert "| Estado | Propuesto (pendiente de aprobación) |" in pending
        assert "| Aprobado |" not in pending

    def test_no_hereda_las_preguntas_de_la_interfaz(self):
        ctx = _ctx(
            proposal_markdown=(
                "## Trade-offs y decisión\n\n- Recomendación: Monolito modular\n"
                "- Punto de decisión: ¿Aprueba los trade-offs?\n"
            )
        )
        md = render_adr_markdown(ctx, llm_sections=LLM_GUIDE)
        assert "Recomendación: Monolito modular" in md
        assert "Punto de decisión" not in md
        assert "¿Aprueba" not in md

    def test_marca_los_atributos_de_calidad_propuestos_por_el_agente(self):
        resumen = dict(_ctx().resumen)
        resumen["calidad"] = ["Seguridad", "Disponibilidad"]
        resumen["calidad_origen"] = {"Seguridad": "dicho", "Disponibilidad": "propuesto"}
        md = render_adr_markdown(_ctx(resumen=resumen), llm_sections=None)
        assert "- Seguridad\n" in md
        assert "- Disponibilidad _(propuesto por el agente" in md


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

    def test_acepta_titulos_sin_tildes_ni_mayusculas(self):
        # Revisión: "tecnologico" sin tilde descartaba toda la sección 7.
        text = (
            LLM_GUIDE.replace("Stack tecnológico recomendado", "Stack tecnologico recomendado")
            .replace("Plan de implementación", "PLAN DE IMPLEMENTACION")
        )
        assert clean_llm_sections(text) is not None


class TestDomainConcernsAndLint:
    def test_las_preocupaciones_del_dominio_sin_respuesta_van_a_preguntas_abiertas(self):
        ctx = _ctx(
            project_name="Huellitas",
            project_description="App para reportar mascotas perdidas",
            resumen={"problema": "Encontrar mascotas perdidas", "funcionalidades": ["Publicar avisos"]},
        )
        md = render_adr_markdown(ctx, llm_sections=LLM_GUIDE)
        assert "**Preguntas abiertas obligatorias**" in md
        assert "**Ubicación y mapas:**" in md
        assert "**Respaldos de los datos:**" in md

    def test_una_preocupacion_preguntada_en_la_elicitacion_no_se_repite(self):
        from app.core.domain_concerns import DOMAIN_CONCERNS

        ubicacion = next(c for c in DOMAIN_CONCERNS if c.key == "ubicacion")
        ctx = _ctx(
            project_description="App para reportar mascotas perdidas",
            preguntas_respuestas=[{"pregunta": ubicacion.question, "respuesta": "No hace falta"}],
        )
        md = render_adr_markdown(ctx, llm_sections=LLM_GUIDE)
        assert "**Ubicación y mapas:**" not in md

    def test_sin_guia_las_preguntas_obligatorias_salen_igual(self):
        ctx = _ctx(project_description="App para reportar mascotas perdidas")
        md = render_adr_markdown(ctx, llm_sections=None)
        assert "### 7.8 Preguntas abiertas" in md
        assert "**Ubicación y mapas:**" in md

    def test_lint_avisa_cifras_y_tecnologias_que_no_salen_de_lo_decidido(self):
        from app.core.adr_generator import lint_adr_guide

        guide = LLM_GUIDE.replace(
            "Contenido de Stack tecnológico recomendado.",
            "| Capa | Tecnología | Por qué |\n|---|---|---|\n"
            "| Backend | Django | Lo pide la propuesta |\n"
            "| Servidor | Gunicorn | Producción |\n"
            "| Despliegue | Docker (supuesto) | Portabilidad |\n",
        ).replace(
            "Contenido de Riesgos y mitigaciones.",
            "Disponibilidad con SLA 99 %. Servidor de 2 vCPU / 4 GB por $150 al mes.",
        )
        ctx = _ctx(proposal_markdown="## Tecnologias\n- Django\n- PostgreSQL")
        warnings = lint_adr_guide(ctx, guide)
        joined = " ".join(warnings)
        assert "Gunicorn" in joined
        assert "Docker" not in joined  # marcado como supuesto
        assert "Django" not in joined
        assert "2 vcpu" in joined
        assert "4 gb" in joined
        assert "$150" in joined

    def test_lint_no_avisa_cifras_que_estan_en_los_requerimientos(self):
        from app.core.adr_generator import lint_adr_guide

        guide = LLM_GUIDE.replace("Contenido de Consecuencias.", "Presupuesto de 20000 USD respetado.")
        assert lint_adr_guide(_ctx(), guide) == []

    def test_el_adr_incluye_el_aviso_del_lint(self):
        guide = LLM_GUIDE.replace("Contenido de Consecuencias.", "Costo estimado de $900 al mes.")
        md = render_adr_markdown(_ctx(), llm_sections=guide)
        assert "> **Revisión automática:**" in md
        assert "$900" in md

    def test_extract_guide_section_recupera_la_guia_sin_lo_agregado(self):
        from app.core.adr_generator import extract_guide_section

        ctx = _ctx(project_description="App para reportar mascotas perdidas")
        md = render_adr_markdown(ctx, llm_sections=LLM_GUIDE)
        assert extract_guide_section(md) == LLM_GUIDE
        assert extract_guide_section(render_adr_markdown(ctx, llm_sections=None)) is None

    def test_el_prompt_de_la_guia_hereda_las_reglas_de_viabilidad(self):
        from app.core.adr_generator import ADR_SYSTEM_PROMPT

        assert "CI/CD" in ADR_SYSTEM_PROMPT
        assert "No inventes métricas" in ADR_SYSTEM_PROMPT
        assert "(supuesto)" in ADR_SYSTEM_PROMPT


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
        assert ctx.diagram_attachment_id == "att-1"
        assert [d.phase for d in ctx.decisions] == ["diagram", "propuesta"]

    def test_un_diagrama_aprobado_y_despues_rechazado_ya_no_cuenta(self, db):
        from app.models.approval import Approval

        _seed(db)
        db.add(Approval(session_id=1, project_id=5, phase="diagram", decision="rejected", attachment_id="att-1"))
        db.commit()

        ctx = collect_adr_context(db, user_id=1, project_id=5)

        assert ctx.diagram_approved is False
        # Sin aprobado vigente se usa el último generado.
        assert ctx.mermaid == "flowchart TD\n  X --> Y"
        assert ctx.diagram_attachment_id == "att-2"

    def test_sin_propuesta_aprobada_no_hay_adr(self, db):
        _seed(db, approved=False)
        with pytest.raises(AdrNotReadyError):
            collect_adr_context(db, user_id=1, project_id=5)


class TestResumenEjecutivo:
    def test_va_antes_del_contexto_con_problema_decision_recursos_y_riesgos(self):
        ctx = _ctx(
            proposal_markdown=(
                "## Patrones\n- Patrón principal: Monolito modular\n\n"
                "## Justificación del patrón principal\n- Riesgo o costo: escala como una sola unidad\n\n"
                "## Trade-offs y decisión\n- Recomendación: **Monolito modular** [1]\n"
            ),
        )
        md = render_adr_markdown(ctx, llm_sections=None)

        assert md.index("## Resumen ejecutivo") < md.index("## 1. Contexto")
        summary = md.split("## Resumen ejecutivo", 1)[1].split("## 1. Contexto", 1)[0]
        assert "**Qué problema resuelve:** Las citas se agendan por teléfono." in summary
        assert "construir el sistema como Monolito modular." in summary
        assert "[1]" not in summary and "**Monolito" not in summary
        assert "**Presupuesto:** Presupuesto de 20000 USD" in summary
        assert "**Equipo:** no definido" in summary
        assert "escala como una sola unidad" in summary

    def test_usa_los_riesgos_y_preguntas_de_la_guia(self):
        guide = LLM_GUIDE.replace(
            "Contenido de Riesgos y mitigaciones.",
            "| Riesgo | Impacto | Mitigación |\n|---|---|---|\n| Caída del proveedor | alto | Respaldo |",
        ).replace("Contenido de Preguntas abiertas.", "- ¿Quién opera el servidor?")
        md = render_adr_markdown(_ctx(), llm_sections=guide)
        summary = md.split("## Resumen ejecutivo", 1)[1].split("## 1. Contexto", 1)[0]
        assert "- Caída del proveedor" in summary
        assert "- ¿Quién opera el servidor?" in summary


class TestCoherenciaFinal:
    """Pasada final: el documento se revisa contra sí mismo."""

    def _guide(self, **replacements):
        guide = LLM_GUIDE
        for old, new in replacements.items():
            guide = guide.replace(f"Contenido de {old}.", new)
        return guide

    def test_componentes_que_no_estan_en_el_diagrama(self):
        from app.core.adr_generator import lint_adr_guide

        guide = self._guide(**{
            "Componentes y responsabilidades": "| Componente | Responsabilidad | Se comunica con |\n|---|---|---|\n"
            "| API | Reglas | DB |\n| Servicio de notificaciones | Avisos | API |",
        })
        warnings = " ".join(lint_adr_guide(_ctx(), guide))
        assert "no aparecen en el diagrama: Servicio de notificaciones" in warnings

    def test_el_sprint_debe_atacar_los_riesgos_altos(self):
        from app.core.adr_generator import lint_adr_guide

        guide = self._guide(**{
            "Riesgos y mitigaciones": "| Riesgo | Impacto | Mitigación |\n|---|---|---|\n"
            "| La fuente de datos de sensores no existe | alto | Validar proveedor |\n"
            "| Curva de aprendizaje | medio | Pares |",
            "Primer sprint": "- Crear el repositorio\n- Pantalla de login",
        })
        warnings = " ".join(lint_adr_guide(_ctx(), guide))
        assert "riesgo de impacto alto «La fuente de datos de sensores no existe»" in warnings
        assert "Curva de aprendizaje" not in warnings

        ok_guide = guide.replace("- Pantalla de login", "- Validar el proveedor de sensores")
        assert "riesgo de impacto alto" not in " ".join(lint_adr_guide(_ctx(), ok_guide))

    def test_preguntas_repetidas_y_etiquetas_internas(self):
        from app.core.adr_generator import lint_adr_guide

        guide = self._guide(**{
            "Preguntas abiertas": "- ¿Qué proveedor de mapas?\n- **¿Qué proveedor de mapas?**",
            "Consecuencias": "Se eligió por la evidencia RAG [2].",
        })
        warnings = " ".join(lint_adr_guide(_ctx(), guide))
        assert "Preguntas repetidas en 7.8" in warnings
        assert "Etiquetas internas" in warnings and "rag" in warnings

    def test_una_preocupacion_que_la_guia_ya_trata_no_se_repite(self):
        guide = self._guide(**{"Riesgos y mitigaciones": "Respaldo diario automático de la base."})
        md = render_adr_markdown(_ctx(), llm_sections=guide)
        assert "**Respaldos de los datos:**" not in md

    def test_la_tabla_de_la_propuesta_no_muestra_etiquetas_internas(self):
        ctx = _ctx(proposal_markdown="| Opción | Fuente RAG |\n|---|---|\n| A | [1] |\n| B | Sin fuente RAG |")
        md = render_adr_markdown(ctx, llm_sections=None)
        assert "RAG" not in md.split("## 3. Decisión", 1)[1].split("## 4.", 1)[0]
        assert "Referencia (sección 5)" in md and "Criterio general" in md

    def test_riesgos_del_resumen_ordenados_por_impacto(self):
        guide = self._guide(**{
            "Riesgos y mitigaciones": "| Riesgo | Impacto | Mitigación |\n|---|---|---|\n"
            "| Diseño poco claro | bajo | Revisar |\n| Fuente de datos incierta | alto | Validar |",
        })
        md = render_adr_markdown(_ctx(), llm_sections=guide)
        summary = md.split("## Resumen ejecutivo", 1)[1].split("## 1. Contexto", 1)[0]
        assert summary.index("Fuente de datos incierta (impacto alto)") < summary.index("Diseño poco claro")


class TestDatosDelUsuario:
    def test_contexto_tecnico_y_datos_textuales_en_requerimientos_y_resumen(self):
        resumen = dict(_ctx().resumen)
        resumen["contexto_tecnico"] = {
            "plataforma": "App móvil",
            "habilidades_equipo": "React y Node",
            "fuentes_de_datos": "API del proveedor de buses en tiempo real",
        }
        resumen["datos_viabilidad"] = {"equipo": "4 devs, 3 front y 1 PM"}
        md = render_adr_markdown(_ctx(resumen=resumen), llm_sections=None)

        assert "### Contexto técnico" in md
        assert "**Fuente de los datos:** API del proveedor de buses en tiempo real" in md
        assert "**Equipo:** «4 devs, 3 front y 1 PM»" in md
        summary = md.split("## Resumen ejecutivo", 1)[1].split("## 1. Contexto", 1)[0]
        assert "**Equipo:** 4 devs, 3 front y 1 PM" in summary

    def test_el_prompt_de_la_guia_lleva_los_datos_del_usuario(self):
        from app.core.adr_generator import _adr_prompt

        resumen = dict(_ctx().resumen)
        resumen["datos_viabilidad"] = {"equipo": "4 devs, 3 front y 1 PM"}
        assert "3 front y 1 PM" in _adr_prompt(_ctx(resumen=resumen))


class TestCorreccionDeLaGuia:
    """Segunda pasada: el LLM corrige lo que encontró la revisión automática."""

    BAD = LLM_GUIDE.replace("Contenido de Consecuencias.", "Costo de $900 al mes.")

    class _Seq:
        def __init__(self, *responses):
            self.responses = list(responses)
            self.configs = []
            self.prompts = []

        async def ainvoke(self, messages, config=None):
            self.configs.append(config)
            self.prompts.append(messages[-1].content)
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return type("Msg", (), {"content": item})()

    def test_corrige_y_usa_la_version_con_menos_avisos(self):
        from app.core.adr_generator import generate_guide

        model = self._Seq(self.BAD, LLM_GUIDE)
        guide, repaired = asyncio.run(generate_guide(model, _ctx()))

        assert repaired is True
        assert guide == LLM_GUIDE
        assert model.configs[1]["run_name"] == "adr-guide-repair"
        assert "$900" in model.prompts[1]  # el aviso viaja en el pedido de corrección

    def test_si_la_correccion_no_mejora_se_queda_la_original(self):
        from app.core.adr_generator import generate_guide

        model = self._Seq(self.BAD, self.BAD)
        guide, repaired = asyncio.run(generate_guide(model, _ctx()))
        assert (guide, repaired) == (self.BAD, False)

    def test_si_la_correccion_falla_se_queda_la_original(self):
        from app.core.adr_generator import generate_guide

        model = self._Seq(self.BAD, RuntimeError("429"))
        guide, repaired = asyncio.run(generate_guide(model, _ctx()))
        assert (guide, repaired) == (self.BAD, False)

    def test_sin_avisos_no_hay_segunda_llamada(self):
        from app.core.adr_generator import generate_guide

        model = self._Seq(LLM_GUIDE)
        guide, repaired = asyncio.run(generate_guide(model, _ctx()))
        assert (guide, repaired) == (LLM_GUIDE, False)
        assert len(model.configs) == 1

    def test_se_puede_desactivar(self, monkeypatch):
        from app.core import adr_generator

        monkeypatch.setattr(adr_generator, "ADR_GUIDE_REPAIR", False)
        model = self._Seq(self.BAD)
        guide, repaired = asyncio.run(adr_generator.generate_guide(model, _ctx()))
        assert (guide, repaired) == (self.BAD, False)
        assert len(model.configs) == 1
